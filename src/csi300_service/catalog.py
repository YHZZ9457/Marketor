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
    source_priority: tuple[str, ...] = ("eastmoney", "tencent", "baostock", "tushare")
    amount_unit: str = "CNY_THOUSAND"

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


class InstrumentCatalog:
    """File-backed instrument registry.

    Adding a market only requires a CSV plus an entry in instruments.json; service,
    API and CLI code do not need to change.
    """

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else default_data_dir() / "instruments.json"
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        base_dir = self.config_path.parent.resolve()
        self._items: dict[str, Instrument] = {}
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
                source_priority=tuple(item.get("source_priority", ("eastmoney", "tencent", "baostock", "tushare"))),
                amount_unit=item.get("amount_unit", "CNY_THOUSAND"),
            )
        if not self._items:
            raise ValueError("Instrument catalog is empty")

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
