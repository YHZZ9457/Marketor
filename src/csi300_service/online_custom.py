from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .catalog import Instrument, InstrumentCatalog
from .custom_instruments import CustomInstrumentManager
from .data_sources import (
    AKShareCNStockEastMoneyDataSource,
    AKShareCNStockTencentDataSource,
    AKShareIndexZHHistDataSource,
    AKShareOpenFundDataSource,
    AKShareTencentDataSource,
    BaoStockDataSource,
    HiThinkDataSource,
    YahooChartDataSource,
    hithink_api_key,
    normalize_hithink_code,
)


ONLINE_TYPE_LABELS = {
    "cn_stock": "国内股票 / 场内 ETF",
    "cn_index": "国内指数",
    "cn_fund": "开放式基金",
    "yahoo": "全球股票 / ETF / 指数",
}


@dataclass(frozen=True)
class OnlineImportResult:
    instrument: Instrument
    provider: str
    attempts: tuple[str, ...]
    rows: int
    first_date: str
    last_date: str


def normalize_cn_provider_code(value: str) -> tuple[str, str, str]:
    raw = value.strip().lower().replace(".", "")
    explicit_market = raw[:2] if raw[:2] in {"sh", "sz", "bj"} else None
    plain = raw[2:] if explicit_market else raw
    if len(plain) != 6 or not plain.isdigit():
        raise ValueError("国内代码应为 6 位数字，例如 600519、000300 或 510300")
    market = explicit_market or ("sh" if plain[0] in "569" else "bj" if plain[0] in "48" else "sz")
    return plain, f"{market}.{plain}", f"{market}{plain}"


class OnlineMarketGateway:
    """Fetch canonical daily data from tested no-token providers with fallbacks."""

    def fetch(
        self,
        online_type: str,
        provider_code: str,
        start_date: str,
        end_date: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, str], str, tuple[str, ...]]:
        end_date = end_date or date.today().isoformat()
        attempts: list[str] = []
        if online_type == "cn_stock":
            plain, baostock_code, tencent_code = normalize_cn_provider_code(provider_code)
            candidates: tuple[tuple[str, Any], ...] = (
                ("BaoStock（前复权）", BaoStockDataSource(baostock_code, adjustflag="2")),
                ("腾讯（前复权）", AKShareCNStockTencentDataSource(tencent_code)),
                ("东方财富（前复权）", AKShareCNStockEastMoneyDataSource(plain)),
            )
            if hithink_api_key():
                asset_type = "etf" if plain[0] in "15" else "stock"
                candidates = (("同花顺官方 API", HiThinkDataSource(normalize_hithink_code(provider_code), asset_type=asset_type)), *candidates)
            frame, provider = self._first_available(candidates, start_date, end_date, attempts)
            name = self._baostock_name(baostock_code) or plain
            return frame, {"name": name, "currency": "CNY", "market": "CN", "asset_class": "stock", "adjustment": "qfq"}, provider, tuple(attempts)
        if online_type == "cn_index":
            plain, baostock_code, tencent_code = normalize_cn_provider_code(provider_code)
            candidates: tuple[tuple[str, Any], ...] = (
                ("BaoStock（指数原始点位）", BaoStockDataSource(baostock_code, adjustflag="3")),
                ("腾讯指数", AKShareTencentDataSource(tencent_code, amount_unit="LOTS")),
                ("东方财富指数", AKShareIndexZHHistDataSource(plain, eastmoney_code=tencent_code)),
            )
            if hithink_api_key():
                candidates = (("同花顺官方 API", HiThinkDataSource(normalize_hithink_code(provider_code), asset_type="index")), *candidates)
            frame, provider = self._first_available(candidates, start_date, end_date, attempts)
            name = self._baostock_name(baostock_code) or plain
            return frame, {"name": name, "currency": "CNY", "market": "CN", "asset_class": "index", "adjustment": "none"}, provider, tuple(attempts)
        if online_type == "cn_fund":
            code = provider_code.strip()
            if len(code) != 6 or not code.isdigit():
                raise ValueError("基金代码应为 6 位数字，例如 000001")
            source = AKShareOpenFundDataSource(code)
            try:
                frame = source.get_daily(start_date, end_date)
                attempts.append("东方财富基金：成功")
            except Exception as exc:
                attempts.append(f"东方财富基金：{exc}")
                raise RuntimeError("；".join(attempts)) from exc
            return frame, {"name": self._fund_name(code) or code, "currency": "CNY", "market": "CN", "asset_class": "fund", "adjustment": "nav"}, "东方财富基金", tuple(attempts)
        if online_type == "yahoo":
            code = provider_code.strip()
            if not code:
                raise ValueError("全球行情代码不能为空，例如 AAPL、SPY、^GSPC 或 0700.HK")
            source = YahooChartDataSource(code)
            try:
                frame = source.get_daily(start_date, end_date)
                attempts.append("Yahoo Finance：成功")
            except Exception as exc:
                attempts.append(f"Yahoo Finance：{exc}")
                raise RuntimeError("；".join(attempts)) from exc
            metadata = source.metadata
            return frame, {
                "name": str(metadata.get("longName") or metadata.get("shortName") or code),
                "currency": str(metadata.get("currency") or "USD"),
                "market": str(metadata.get("exchangeName") or "GLOBAL").upper(),
                "asset_class": "index" if code.startswith("^") else "stock",
                "adjustment": "adjusted",
            }, "Yahoo Finance", tuple(attempts)
        raise ValueError(f"不支持的联网类型：{online_type}")

    @staticmethod
    def _first_available(
        candidates: tuple[tuple[str, Any], ...],
        start_date: str,
        end_date: str,
        attempts: list[str],
    ) -> tuple[pd.DataFrame, str]:
        last_error: Exception | None = None
        for name, source in candidates:
            try:
                frame = source.get_daily(start_date, end_date)
                attempts.append(f"{name}：成功")
                return frame, name
            except Exception as exc:
                last_error = exc
                attempts.append(f"{name}：{exc}")
        raise RuntimeError("；".join(attempts)) from last_error

    @staticmethod
    def _baostock_name(code: str) -> str | None:
        try:
            import baostock as bs
            login = bs.login()
            if str(login.error_code) != "0":
                return None
            try:
                result = bs.query_stock_basic(code=code)
                if str(result.error_code) == "0" and result.next():
                    row = dict(zip(result.fields, result.get_row_data()))
                    return str(row.get("code_name") or "").strip() or None
            finally:
                bs.logout()
        except Exception:
            return None
        return None

    @staticmethod
    def _fund_name(code: str) -> str | None:
        try:
            import akshare as ak
            frame = ak.fund_name_em()
            codes = frame["基金代码"].astype(str).str.zfill(6)
            matches = frame.loc[codes == code]
            if not matches.empty:
                return str(matches.iloc[0]["基金简称"])
        except Exception:
            return None
        return None


class OnlineCustomInstrumentManager:
    def __init__(
        self,
        custom_manager: CustomInstrumentManager | None = None,
        gateway: OnlineMarketGateway | None = None,
    ):
        self.custom_manager = custom_manager or CustomInstrumentManager()
        self.gateway = gateway or OnlineMarketGateway()

    def add(
        self,
        *,
        online_type: str,
        provider_code: str,
        symbol: str,
        start_date: str,
        name: str = "",
        replace: bool = False,
    ) -> OnlineImportResult:
        frame, metadata, provider, attempts = self.gateway.fetch(
            online_type, provider_code, start_date,
        )
        instrument = self.custom_manager.import_frame(
            frame,
            symbol=symbol,
            name=name.strip() or metadata["name"],
            asset_class=metadata["asset_class"],
            market=metadata["market"],
            currency=metadata["currency"],
            replace=replace,
            online_source=online_type,
            provider_code=provider_code.strip(),
            adjustment=metadata.get("adjustment"),
        )
        return self._result(instrument, frame, provider, attempts)

    def refresh(self, symbol: str, *, catalog: InstrumentCatalog | None = None) -> OnlineImportResult:
        catalog = catalog or InstrumentCatalog()
        instrument = catalog.get(symbol)
        if not instrument.online_source or not instrument.provider_code:
            raise ValueError("该标的没有联网更新配置")
        existing = pd.read_csv(instrument.data_path, usecols=["date"])
        start_date = pd.to_datetime(existing["date"], errors="raise").min().strftime("%Y-%m-%d")
        frame, metadata, provider, attempts = self.gateway.fetch(
            instrument.online_source, instrument.provider_code, start_date,
        )
        updated = self.custom_manager.import_frame(
            frame,
            symbol=instrument.symbol,
            name=instrument.name,
            asset_class=instrument.asset_class,
            market=instrument.market,
            currency=instrument.currency,
            replace=True,
            online_source=instrument.online_source,
            provider_code=instrument.provider_code,
            adjustment=instrument.adjustment or metadata.get("adjustment"),
        )
        return self._result(updated, frame, provider, attempts)

    @staticmethod
    def _result(
        instrument: Instrument,
        frame: pd.DataFrame,
        provider: str,
        attempts: tuple[str, ...],
    ) -> OnlineImportResult:
        dates = pd.to_datetime(frame["date"])
        return OnlineImportResult(
            instrument=instrument,
            provider=provider,
            attempts=attempts,
            rows=len(frame),
            first_date=dates.min().strftime("%Y-%m-%d"),
            last_date=dates.max().strftime("%Y-%m-%d"),
        )
