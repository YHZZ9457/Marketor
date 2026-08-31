from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from .catalog import InstrumentCatalog
from .data_sources import (
    AKShareEastMoneyDataSource,
    AKShareGlobalEastMoneyDataSource,
    AKShareGlobalSinaDataSource,
    AKShareHKIndexSinaDataSource,
    AKShareIndexZHHistDataSource,
    AKShareTencentDataSource,
    AKShareUSIndexSinaDataSource,
    BaoStockDataSource,
    CsvDataSource,
    HiThinkDataSource,
    MarketDataSource,
    TushareDataSource,
    hithink_api_key,
)
from .service import MarketService
from .validation import validate_market_data


class DataUpdateError(RuntimeError):
    pass


class OverlapMismatchError(DataUpdateError):
    pass


def source_meta_path(instrument: Any) -> Path:
    """Sidecar metadata file recorded next to each instrument CSV."""
    return Path(str(instrument.data_path) + ".meta.json")


def read_source_meta(symbol: str = "csi300", catalog: InstrumentCatalog | None = None) -> dict[str, Any] | None:
    """Return the last recorded online-update metadata for an instrument."""
    instrument = (catalog or InstrumentCatalog()).get(symbol)
    path = source_meta_path(instrument)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class UpdateResult:
    online_success: bool
    updated: bool
    symbol: str
    local_latest: str
    remote_latest: str | None
    fetched_start: str
    fetched_end: str
    overlap_records: int
    new_records: int
    latest: dict[str, Any]
    signal: dict[str, Any]
    data_source: str = "Local CSV"
    online_status: str = "local"
    attempts: list[str] = field(default_factory=list)
    warning: str | None = None
    amount_unit: str = "CNY_THOUSAND"
    meta_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketDataUpdater:
    def __init__(
        self,
        symbol: str = "csi300",
        *,
        catalog: InstrumentCatalog | None = None,
        remote_source: MarketDataSource | None = None,
        source_mode: str | None = None,
        overlap_trading_days: int = 10,
        close_tolerance: float = 0.01,
    ):
        self.catalog = catalog or InstrumentCatalog()
        self.instrument = self.catalog.get(symbol)
        self.local_source = CsvDataSource(self.instrument.data_path)
        self.provider_code = self.instrument.provider_code
        self.baostock_code = self.instrument.baostock_code
        self.tencent_code = self.instrument.tencent_code
        self.eastmoney_code = self.instrument.eastmoney_code
        self.zh_index_code = self.instrument.zh_index_code
        self.global_name = self.instrument.global_name
        self.sina_code = self.instrument.sina_code
        self.market = self.instrument.market.upper()
        self.remote_source = remote_source
        self.source_mode = (source_mode or os.getenv("DATA_SOURCE", "auto")).strip().lower()
        if self.source_mode not in {"auto", "hithink", "baostock", "tencent", "eastmoney", "sina", "tushare", "local"}:
            raise ValueError("DATA_SOURCE 必须是 auto、hithink、baostock、tencent、eastmoney、sina、tushare 或 local")
        self.overlap_trading_days = max(1, overlap_trading_days)
        self.close_tolerance = close_tolerance

    def bootstrap(
        self,
        *,
        start_date: str = "2005-01-01",
        today: date | None = None,
        force: bool = False,
    ) -> UpdateResult:
        """Create a new instrument CSV from one explicitly selected online source."""
        path = Path(self.instrument.data_path)
        if path.exists() and not force:
            raise DataUpdateError(f"本地行情文件已存在：{path.name}")
        mode = self.instrument.source_priority[0] if self.source_mode == "auto" else self.source_mode
        if self.remote_source is not None:
            source_name, source = type(self.remote_source).__name__, self.remote_source
        else:
            source_name, source = self._create_source(mode)
        end = pd.Timestamp(today or date.today())
        frame = source.get_daily(start_date, end.strftime("%Y-%m-%d")).copy()
        if "return" in frame.columns and "daily_return" not in frame.columns:
            frame["daily_return"] = frame["return"]
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        validate_market_data(frame)
        frame["return"] = frame.get("daily_return", frame["close"].pct_change())
        frame["net_value"] = frame["close"] / float(frame.iloc[0]["close"])
        self._atomic_save(frame, path)
        meta_path = self._write_meta(
            source=source_name,
            latest_date=frame.iloc[-1]["date"].strftime("%Y-%m-%d"),
            fetched_start=pd.Timestamp(start_date).strftime("%Y-%m-%d"),
            fetched_end=end.strftime("%Y-%m-%d"),
            overlap_records=0,
            new_records=len(frame),
            online_status="normal",
        )
        snapshot, signal = self._local_snapshot()
        return UpdateResult(
            online_success=True,
            updated=True,
            symbol=self.instrument.symbol,
            local_latest=frame.iloc[0]["date"].strftime("%Y-%m-%d"),
            remote_latest=frame.iloc[-1]["date"].strftime("%Y-%m-%d"),
            fetched_start=pd.Timestamp(start_date).strftime("%Y-%m-%d"),
            fetched_end=end.strftime("%Y-%m-%d"),
            overlap_records=0,
            new_records=len(frame),
            latest=snapshot,
            signal=signal,
            data_source=source_name,
            online_status="normal",
            attempts=[f"{source_name}: bootstrap success"],
            amount_unit=self.instrument.amount_unit,
            meta_path=str(meta_path),
        )

    def run(self, *, allow_fallback: bool = True, today: date | None = None) -> UpdateResult:
        local = self.local_source.get_daily()
        local_latest = local.iloc[-1]["date"]
        overlap_index = max(0, len(local) - self.overlap_trading_days - 1)
        fetched_start = local.iloc[overlap_index]["date"]
        fetched_end = pd.Timestamp(today or date.today())
        if self.source_mode == "local" and self.remote_source is None:
            return self._fallback_result(local_latest, fetched_start, fetched_end, [], warning=None)

        candidates: list[tuple[str, MarketDataSource]] = []
        creation_errors: list[str] = []
        if self.remote_source is not None:
            candidates.append((type(self.remote_source).__name__, self.remote_source))
        else:
            modes = [self.source_mode] if self.source_mode != "auto" else list(self.instrument.source_priority)
            load_dotenv()
            if self.source_mode == "auto" and self.market == "CN" and hithink_api_key() and "hithink" not in modes:
                modes.insert(0, "hithink")
            for mode in modes:
                if mode == "tushare" and not os.getenv("TUSHARE_TOKEN"):
                    continue
                try:
                    candidates.append(self._create_source(mode))
                except Exception as exc:
                    creation_errors.append(f"{mode}: {exc}")

        attempts = list(creation_errors)
        last_error: Exception | None = None
        for source_name, source in candidates:
            try:
                result = self._update(source, source_name, local, local_latest, fetched_start, fetched_end)
                result.attempts = [*attempts, f"{source_name}: success"]
                return result
            except Exception as exc:
                last_error = exc
                attempts.append(f"{source_name}: {exc}")

        if not allow_fallback:
            raise last_error or DataUpdateError("没有可用的在线数据源")
        details = "；".join(attempts) or "没有可用的在线数据源"
        return self._fallback_result(
            local_latest,
            fetched_start,
            fetched_end,
            attempts,
            warning=f"在线更新失败，继续使用本地数据：{details}",
        )

    def _create_source(self, mode: str) -> tuple[str, MarketDataSource]:
        if mode == "hithink":
            if not self.provider_code:
                raise DataUpdateError("该标的未配置同花顺代码")
            if self.market != "CN":
                raise DataUpdateError("同花顺数据源当前仅用于中国市场")
            scale = 0.001 if self.instrument.amount_unit == "CNY_THOUSAND" else 1.0
            return "同花顺官方 API", HiThinkDataSource(
                self.provider_code, asset_type="index" if self.instrument.asset_class == "index" else "stock",
                amount_scale=scale,
            )
        if mode == "baostock":
            if not self.baostock_code:
                raise DataUpdateError("该标的未配置 BaoStock 代码")
            return "BaoStock", BaoStockDataSource(self.baostock_code)
        if mode == "tencent":
            if not self.tencent_code:
                raise DataUpdateError("该标的未配置腾讯代码")
            return "AKShare/Tencent", AKShareTencentDataSource(
                self.tencent_code, amount_unit=self.instrument.amount_unit
            )
        if mode == "eastmoney":
            if self.global_name:
                return "AKShare/Global EastMoney", AKShareGlobalEastMoneyDataSource(self.global_name)
            if self.zh_index_code:
                return "AKShare/EastMoney", AKShareIndexZHHistDataSource(
                    self.zh_index_code,
                    eastmoney_code=self.eastmoney_code,
                    amount_unit=self.instrument.amount_unit,
                )
            if not self.eastmoney_code:
                raise DataUpdateError("该标的未配置东方财富代码")
            return "AKShare/EastMoney", AKShareEastMoneyDataSource(
                self.eastmoney_code, amount_unit=self.instrument.amount_unit
            )
        if mode == "sina":
            if not self.sina_code:
                raise DataUpdateError("该标的未配置新浪指数代码")
            if self.market == "US":
                return "AKShare/US Sina", AKShareUSIndexSinaDataSource(self.sina_code)
            if self.market == "HK":
                return "AKShare/HK Sina", AKShareHKIndexSinaDataSource(self.sina_code)
            return "AKShare/Global Sina", AKShareGlobalSinaDataSource(self.sina_code)
        if mode == "tushare":
            if not self.provider_code:
                raise DataUpdateError("该标的未配置 Tushare 代码")
            return "Tushare", TushareDataSource(self.provider_code)
        raise DataUpdateError(f"不支持的数据源：{mode}")

    def _update(
        self,
        source: MarketDataSource,
        source_name: str,
        local: pd.DataFrame,
        local_latest: pd.Timestamp,
        fetched_start: pd.Timestamp,
        fetched_end: pd.Timestamp,
    ) -> UpdateResult:
        validate_market_data(local)
        remote = source.get_daily(fetched_start.strftime("%Y-%m-%d"), fetched_end.strftime("%Y-%m-%d")).copy()
        if "return" in remote.columns and "daily_return" not in remote.columns:
            remote["daily_return"] = pd.to_numeric(remote["return"], errors="coerce")
        remote["date"] = pd.to_datetime(remote["date"], errors="raise")
        validate_market_data(remote)

        overlap = local[["date", "close"]].merge(
            remote.loc[remote["date"] <= local_latest, ["date", "close"]],
            on="date",
            suffixes=("_local", "_remote"),
        )
        required_overlap = min(self.overlap_trading_days, len(local))
        if len(overlap) < required_overlap:
            raise DataUpdateError(f"重叠交易日不足：需要 {required_overlap}，实际 {len(overlap)}")
        differences = (overlap["close_local"] - overlap["close_remote"]).abs()
        if (differences > self.close_tolerance).any():
            bad = overlap.loc[differences.idxmax()]
            raise OverlapMismatchError(
                f"重叠区间收盘价不一致：{bad['date']:%Y-%m-%d}，"
                f"本地 {bad['close_local']:.4f}，{source_name} {bad['close_remote']:.4f}"
            )

        additions = remote[remote["date"] > local_latest].copy()
        if not additions.empty:
            if "return" not in additions.columns:
                additions["return"] = additions.get("daily_return")
            if "net_value" in local.columns:
                last_net = local.iloc[-1].get("net_value")
                last_close = local.iloc[-1]["close"]
                if pd.notna(last_net):
                    additions["net_value"] = float(last_net) * additions["close"] / float(last_close)
            combined = pd.concat([local, additions], ignore_index=True, sort=False)
            combined = combined.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
            validate_market_data(combined)
            self._atomic_save(combined, self.instrument.data_path)

        meta_path = self._write_meta(
            source=source_name,
            latest_date=remote.iloc[-1]["date"].strftime("%Y-%m-%d"),
            fetched_start=fetched_start.strftime("%Y-%m-%d"),
            fetched_end=fetched_end.strftime("%Y-%m-%d"),
            overlap_records=len(overlap),
            new_records=len(additions),
            online_status="normal",
        )
        snapshot, signal = self._local_snapshot()
        return UpdateResult(
            online_success=True,
            updated=not additions.empty,
            symbol=self.instrument.symbol,
            local_latest=local_latest.strftime("%Y-%m-%d"),
            remote_latest=remote.iloc[-1]["date"].strftime("%Y-%m-%d"),
            fetched_start=fetched_start.strftime("%Y-%m-%d"),
            fetched_end=fetched_end.strftime("%Y-%m-%d"),
            overlap_records=len(overlap),
            new_records=len(additions),
            latest=snapshot,
            signal=signal,
            data_source=source_name,
            online_status="normal",
            amount_unit=self.instrument.amount_unit,
            meta_path=str(meta_path),
        )

    def _write_meta(
        self,
        *,
        source: str,
        latest_date: str,
        fetched_start: str,
        fetched_end: str,
        overlap_records: int,
        new_records: int,
        online_status: str,
        warning: str | None = None,
    ) -> Path:
        """Record which source served the latest update, next to the CSV."""
        payload: dict[str, Any] = {
            "name": self.instrument.name,
            "symbol": self.instrument.symbol,
            "zh_index_code": self.zh_index_code,
            "source": source,
            "source_priority": list(self.instrument.source_priority),
            "download_time": datetime.now().isoformat(timespec="seconds"),
            "latest_date": latest_date,
            "fetched_start": fetched_start,
            "fetched_end": fetched_end,
            "overlap_records": overlap_records,
            "new_records": new_records,
            "online_status": online_status,
            "amount_unit": self.instrument.amount_unit,
        }
        if warning is not None:
            payload["warning"] = warning
        path = source_meta_path(self.instrument)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _fallback_result(
        self,
        local_latest: pd.Timestamp,
        fetched_start: pd.Timestamp,
        fetched_end: pd.Timestamp,
        attempts: list[str],
        warning: str | None,
    ) -> UpdateResult:
        snapshot, signal = self._local_snapshot()
        return UpdateResult(
            online_success=False,
            updated=False,
            symbol=self.instrument.symbol,
            local_latest=local_latest.strftime("%Y-%m-%d"),
            remote_latest=None,
            fetched_start=fetched_start.strftime("%Y-%m-%d"),
            fetched_end=fetched_end.strftime("%Y-%m-%d"),
            overlap_records=0,
            new_records=0,
            latest=snapshot,
            signal=signal,
            data_source="Local CSV",
            online_status="failed" if warning else "local",
            attempts=attempts,
            warning=warning,
            amount_unit=self.instrument.amount_unit,
        )

    def _local_snapshot(self) -> tuple[dict[str, Any], dict[str, Any]]:
        service = MarketService(self.instrument.symbol, catalog=self.catalog)
        return service.latest(), service.signal()

    @staticmethod
    def _atomic_save(frame: pd.DataFrame, path: Path) -> None:
        output = frame.copy()
        if "daily_return" not in output.columns and "return" in output.columns:
            output["daily_return"] = output["return"]
        if "return" not in output.columns and "daily_return" in output.columns:
            output["return"] = output["daily_return"]
        preferred = ["date", "open", "high", "low", "close", "amount", "daily_return", "return", "net_value"]
        output = output[[column for column in preferred if column in output.columns]]
        output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
        path = Path(path)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=".tmp", dir=path.parent, delete=False) as handle:
                temp_name = handle.name
                output.to_csv(handle, index=False)
            os.replace(temp_name, path)
        finally:
            if temp_name and Path(temp_name).exists():
                Path(temp_name).unlink()
