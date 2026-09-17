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
    strategies: tuple[str, ...] = ("ma_dynamic_v1",)
    total_return_code: str | None = None
    total_return_file: str | None = None

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


def _catalog_path(base_dir: Path, value: str, field: str) -> Path:
    """Join a catalog filename without dereferencing legitimate Windows links."""
    relative = Path(str(value))
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError(f"Instrument {field} must stay inside {base_dir}")
    return base_dir / relative


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
        default_strategies = tuple(payload.get("default_strategies", ["ma_dynamic_v1"]))
        for item in payload.get("instruments", []):
            symbol = str(item["symbol"]).strip().lower()
            if not symbol or symbol in self._items:
                raise ValueError(f"Invalid or duplicate instrument symbol: {symbol!r}")
            data_path = _catalog_path(base_dir, item["data_file"], "data_file")
            total_return_file = item.get("total_return_file")
            if total_return_file:
                _catalog_path(base_dir, total_return_file, "total_return_file")
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
                strategies=tuple(item.get("strategies", default_strategies)),
                total_return_code=item.get("total_return_code"),
                total_return_file=total_return_file,
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
