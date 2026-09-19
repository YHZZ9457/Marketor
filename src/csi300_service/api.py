from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .catalog import InstrumentCatalog
from .comparison import MarketComparisonService
from .events import EventBacktester
from .service import MarketService
from .statistics import statistics_methods

app = FastAPI(title="Market Analysis Service", version="0.21.1")
catalog = InstrumentCatalog()
web_dir = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=web_dir), name="static")


@lru_cache(maxsize=64)
def _service(symbol: str) -> MarketService:
    try:
        return MarketService(symbol, catalog=catalog)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/")
def root():
    return FileResponse(web_dir / "index.html")


@app.get("/api")
def api_index():
    return {
        "service": "Market Analysis Service",
        "default_symbol": "csi300",
        "endpoints": ["/instruments", "/comparison", "/events", "/latest", "/indicators", "/history", "/signal", "/strategies/ma-dynamic-v1", "/holding-returns", "/statistics/methods", "/docs"],
    }


@app.get("/instruments")
def instruments():
    """List the configured catalog; instruments without a local CSV are marked
    ``data_available: false`` instead of failing the whole endpoint."""
    rows = []
    for item in catalog.list():
        try:
            meta = _service(item.symbol).metadata()
            meta["data_available"] = True
        except HTTPException:
            meta = item.to_dict()
            meta["data_available"] = False
        rows.append(meta)
    return rows


@app.get("/statistics/methods")
def methods():
    return statistics_methods()


@app.get("/comparison")
def comparison():
    return MarketComparisonService(catalog).snapshots()


@app.get("/events")
def events(symbol: str = "csi300", metric: str = "bias250", threshold: float = -0.10, direction: str = "below", cooldown: int = Query(60, ge=0, le=1250)):
    return EventBacktester(_service(symbol)).run(metric, threshold, direction, cooldown)


@app.get("/latest")
def latest(symbol: str = "csi300"):
    return _service(symbol).latest()


@app.get("/indicators")
def indicators(days: int = Query(30, ge=1, le=1000), symbol: str = "csi300"):
    return _service(symbol).indicators(days)


@app.get("/history")
def history(start: str | None = None, end: str | None = None, limit: int = Query(5000, ge=1, le=10000), symbol: str = "csi300"):
    return _service(symbol).history(start, end, limit)


@app.get("/signal")
def signal(symbol: str = "csi300", equity: float = Query(10000, ge=0, allow_inf_nan=False)):
    return _service(symbol).signal(equity)


@app.get("/holding-returns")
def holding_returns(symbol: str = "csi300", method: str = "summary", days: str = "1,7,30,365,730,1095,1825"):
    try:
        periods = [int(value.strip()) for value in days.split(",") if value.strip()]
        return _service(symbol).holding_returns(periods, method)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/strategies/ma-dynamic-v1")
def ma_dynamic(symbol: str = "csi300", start: str | None = None,
               end: str | None = None, include_ledger: bool = False):
    try:
        return _service(symbol).ma_dynamic(start, end, include_ledger)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
