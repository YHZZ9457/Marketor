from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import sys


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    data_path: Path
    asset_class: str = "index"
    currency: str = "CNY"
    provider_code: str | None = None
    baostock_code: str | None = None
    tencent_code: str | None = None
    eastmoney_code: str | None = None
    zh_index_code: str | None = None
    global_name: str | None = None
    sina_code: str | None = None
    market: str = "CN"
    source_priority: tuple[str, ...] = ("eastmoney", "tencent", "baostock", "tushare")
    amount_unit: str = "CNY_THOUSAND"
    online_source: str | None = None
    adjustment: str | None = None

    @property
    def has_data(self) -> bool:
        return self.data_path.exists()

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["data_path"] = str(self.data_path)
        return result


def default_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS")) / "data"
        target = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Marketor" / "data"
        target.mkdir(parents=True, exist_ok=True)
        for source in bundled.iterdir():
            destination = target / source.name
            if source.name == "instruments.json" or not destination.exists():
                shutil.copy2(source, destination)
        return target
    return Path(__file__).resolve().parents[2] / "data"


def user_storage_dir() -> Path:
    """Writable storage for user-defined instruments in source and packaged builds."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Marketor"


def custom_catalog_path() -> Path:
    return user_storage_dir() / "custom" / "instruments.json"


class InstrumentCatalog:
    """File-backed instrument registry.

    Adding a market only requires a CSV plus an entry in instruments.json; service,
    API and CLI code do not need to change.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        custom_config_path: str | Path | None = None,
    ):
        self.config_path = Path(config_path) if config_path else default_data_dir() / "instruments.json"
        self._items: dict[str, Instrument] = {}
        self._load_config(self.config_path)
        if config_path is None:
            custom_path = Path(custom_config_path) if custom_config_path else custom_catalog_path()
            if custom_path.exists():
                self._load_config(custom_path)
        if not self._items:
            raise ValueError("Instrument catalog is empty")

    def _load_config(self, config_path: Path) -> None:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        base_dir = config_path.parent.resolve()
        for item in payload.get("instruments", []):
            symbol = str(item["symbol"]).strip().lower()
            if not symbol or symbol in self._items:
                raise ValueError(f"Invalid or duplicate instrument symbol: {symbol!r}")
            data_path = (base_dir / item["data_file"]).resolve()
            if base_dir not in data_path.parents:
                raise ValueError(f"Instrument data_file must stay inside {base_dir}")
            self._items[symbol] = Instrument(
                symbol=symbol,
                name=item["name"],
                data_path=data_path,
                asset_class=item.get("asset_class", "index"),
                currency=item.get("currency", "CNY"),
                provider_code=item.get("provider_code"),
                baostock_code=item.get("baostock_code"),
                tencent_code=item.get("tencent_code"),
                eastmoney_code=item.get("eastmoney_code"),
                zh_index_code=item.get("zh_index_code"),
                global_name=item.get("global_name"),
                sina_code=item.get("sina_code"),
                market=item.get("market", "CN"),
                source_priority=tuple(item.get("source_priority", ("eastmoney", "tencent", "baostock", "tushare"))),
                amount_unit=item.get("amount_unit", "CNY_THOUSAND"),
                online_source=item.get("online_source"),
                adjustment=item.get("adjustment"),
            )

    def get(self, symbol: str = "csi300") -> Instrument:
        key = symbol.strip().lower()
        try:
            return self._items[key]
        except KeyError as exc:
            available = ", ".join(sorted(self._items))
            raise KeyError(f"Unknown instrument {symbol!r}; available: {available}") from exc

    def list(self, *, include_unavailable: bool = True) -> list[Instrument]:
        items = list(self._items.values())
        if include_unavailable:
            return items
        return [item for item in items if item.has_data]
