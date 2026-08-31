from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import pandas as pd

from .catalog import Instrument, InstrumentCatalog, custom_catalog_path
from .data import load_data


ASSET_CLASSES = {"index", "stock", "fund"}
COLUMN_ALIASES = {
    "date": ("date", "datetime", "trade_date", "日期", "交易日期", "净值日期"),
    "open": ("open", "开盘", "开盘价"),
    "high": ("high", "最高", "最高价"),
    "low": ("low", "最低", "最低价"),
    "close": (
        "close", "adj close", "adj_close", "收盘", "收盘价", "单位净值",
        "累计净值", "nav", "net_value", "净值",
    ),
    "amount": ("amount", "turnover", "成交额", "成交金额"),
}


def normalize_symbol(value: str) -> str:
    symbol = re.sub(r"[^a-z0-9._-]+", "_", value.strip().lower()).strip("_.-")
    if not symbol:
        raise ValueError("标的代码只能包含字母、数字、点、横线或下划线")
    return symbol


def _read_csv(path: Path) -> pd.DataFrame:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            errors.append(str(exc))
    raise ValueError(f"无法识别 CSV 编码：{errors[-1] if errors else path.name}")


def normalize_imported_csv(path: str | Path) -> pd.DataFrame:
    """Normalize common Chinese/English market CSV columns into the service schema."""
    source = Path(path)
    frame = _read_csv(source)
    lookup = {str(column).strip().lower(): column for column in frame.columns}
    selected: dict[str, Any] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        match = next((lookup[alias.lower()] for alias in aliases if alias.lower() in lookup), None)
        if match is not None:
            selected[canonical] = frame[match]
    missing = {"date", "close"} - set(selected)
    if missing:
        raise ValueError("CSV 至少需要日期和收盘价/净值列；支持 date/日期 与 close/收盘价/单位净值")

    output = pd.DataFrame(selected)
    date_text = output["date"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    output["date"] = pd.to_datetime(date_text, errors="coerce")
    for column in ["open", "high", "low", "close", "amount"]:
        if column in output:
            values = output[column].astype(str).str.replace(",", "", regex=False).str.strip()
            output[column] = pd.to_numeric(values, errors="coerce")
    output = output.dropna(subset=["date", "close"]).sort_values("date")
    output = output.drop_duplicates("date", keep="last").reset_index(drop=True)
    if output.empty:
        raise ValueError("CSV 中没有可用的日期和价格记录")
    if (output["close"] <= 0).any():
        raise ValueError("收盘价/净值必须全部大于 0")
    if len(output) < 15:
        raise ValueError("至少需要 15 条有效记录才能计算基础指标")
    output["daily_return"] = output["close"].pct_change()
    output["return"] = output["daily_return"]
    output["net_value"] = output["close"] / float(output.iloc[0]["close"])
    return output


class CustomInstrumentManager:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else custom_catalog_path()
        self.data_dir = self.config_path.parent / "data"

    def import_csv(
        self,
        source_path: str | Path,
        *,
        symbol: str,
        name: str,
        asset_class: str,
        market: str = "CUSTOM",
        currency: str = "CNY",
        replace: bool = False,
    ) -> Instrument:
        symbol = normalize_symbol(symbol)
        name = name.strip()
        asset_class = asset_class.strip().lower()
        if not name:
            raise ValueError("标的名称不能为空")
        if asset_class not in ASSET_CLASSES:
            raise ValueError("标的类型必须是 index、stock 或 fund")
        try:
            existing = InstrumentCatalog(custom_config_path=self.config_path).get(symbol)
        except KeyError:
            existing = None
        if existing is not None and not replace:
            raise ValueError(f"标的代码 {symbol!r} 已存在")
        if existing is not None and self.config_path.parent.resolve() not in existing.data_path.resolve().parents:
            raise ValueError("不能覆盖内置标的，请使用其他代码")

        frame = normalize_imported_csv(source_path)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data_file = f"{symbol}.csv"
        destination = self.data_dir / data_file
        self._write_csv(frame, destination)

        payload = self._read_payload()
        record = {
            "symbol": symbol,
            "name": name,
            "asset_class": asset_class,
            "currency": currency.strip().upper() or "CNY",
            "market": market.strip().upper() or "CUSTOM",
            "source_priority": [],
            "amount_unit": "N/A",
            "data_file": f"data/{data_file}",
        }
        records = [item for item in payload["instruments"] if str(item.get("symbol", "")).lower() != symbol]
        records.append(record)
        self._write_payload({"instruments": records})
        return InstrumentCatalog(custom_config_path=self.config_path).get(symbol)

    def _read_payload(self) -> dict[str, list[dict[str, Any]]]:
        if not self.config_path.exists():
            return {"instruments": []}
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        return {"instruments": list(payload.get("instruments", []))}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.config_path.parent,
                suffix=".tmp", delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temp_name, self.config_path)
        finally:
            if temp_name and Path(temp_name).exists():
                Path(temp_name).unlink()

    @staticmethod
    def _write_csv(frame: pd.DataFrame, destination: Path) -> None:
        output = frame.copy()
        output["date"] = output["date"].dt.strftime("%Y-%m-%d")
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=destination.parent,
                suffix=".tmp", delete=False,
            ) as handle:
                temp_name = handle.name
                output.to_csv(handle, index=False)
            os.replace(temp_name, destination)
        finally:
            if temp_name and Path(temp_name).exists():
                Path(temp_name).unlink()
        load_data(destination)  # Verify the persisted file through the production loader.
