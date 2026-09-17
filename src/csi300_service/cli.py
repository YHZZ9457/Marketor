from __future__ import annotations

import json
import sys
import typer
from .catalog import InstrumentCatalog
from .comparison import MarketComparisonService
from .events import EventBacktester
from .service import MarketService
from .statistics import statistics_methods
from .updater import MarketDataUpdater

app = typer.Typer(help="多标的历史数据、指标、统计和加减仓辅助信号")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _print(obj):
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2))


@app.command()
def latest(symbol: str = typer.Option("csi300", help="标的代码")):
    """显示最新指标。"""
    _print(MarketService(symbol).latest())


@app.command()
def signal(symbol: str = typer.Option("csi300", help="标的代码")):
    """显示当前加仓/减仓辅助信号。"""
    _print(MarketService(symbol).signal())


@app.command()
def indicators(days: int = 30, symbol: str = typer.Option("csi300", help="标的代码")):
    """显示最近 N 个交易日指标。"""
    _print(MarketService(symbol).indicators(days))


@app.command()
def history(start: str = "", end: str = "", limit: int = 200, symbol: str = typer.Option("csi300", help="标的代码")):
    """查询历史行情。"""
    _print(MarketService(symbol).history(start or None, end or None, limit))


@app.command("holding-returns")
def holding_returns(
    symbol: str = typer.Option("csi300", help="标的代码"),
    method: str = typer.Option("summary", help="统计方法"),
    days: str = typer.Option("1,7,30,365,730,1095,1825", help="逗号分隔的自然日持有期"),
):
    """计算默认持有期的历史收益统计。"""
    periods = [int(value.strip()) for value in days.split(",") if value.strip()]
    _print(MarketService(symbol).holding_returns(periods, method))


@app.command()
def instruments():
    """列出已配置的行情标的。"""
    catalog = InstrumentCatalog()
    _print([MarketService(item.symbol, catalog=catalog).metadata() for item in catalog.list()])


@app.command("statistics-methods")
def list_statistics_methods():
    """列出可用持有收益统计方法。"""
    _print(statistics_methods())


@app.command()
def compare():
    """按相对便宜程度输出全部本地指数排名与历史分位。"""
    _print(MarketComparisonService().snapshots())


@app.command()
def events(
    symbol: str = typer.Option("csi300", help="标的代码"),
    metric: str = typer.Option("bias250", help="事件指标"),
    threshold: float = typer.Option(-0.10, help="触发阈值"),
    direction: str = typer.Option("below", help="below 或 above"),
    cooldown: int = typer.Option(60, help="独立事件冷却交易日"),
):
    """列出独立信号事件及其后1/3/5年收益。"""
    _print(EventBacktester(MarketService(symbol)).run(metric, threshold, direction, cooldown))


@app.command()
def update(
    symbol: str = typer.Option("csi300", help="标的代码"),
    source: str | None = typer.Option(None, help="数据源：auto、hithink、baostock、tencent、eastmoney、sina、tushare、local"),
    strict: bool = typer.Option(False, help="在线更新失败时返回错误，而不是回退本地数据"),
):
    """按所选数据源增量更新行情；失败时默认继续使用本地 CSV。"""
    try:
        result = MarketDataUpdater(symbol, source_mode=source).run(allow_fallback=not strict)
    except Exception as exc:
        typer.echo(f"更新失败：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    latest = result.latest
    signal = result.signal
    output = {
        "online_success": result.online_success,
        "data_source": result.data_source,
        "online_status": result.online_status,
        "attempts": result.attempts,
        "warning": result.warning,
        "local_latest_before_update": result.local_latest,
        "remote_latest": result.remote_latest,
        "download_range": f"{result.fetched_start} → {result.fetched_end}",
        "overlap_records": result.overlap_records,
        "new_records": result.new_records,
        "database_latest": latest.get("date"),
        "close": latest.get("close"),
        "ma180": latest.get("ma180"),
        "bias180": latest.get("bias180"),
        "ma250": latest.get("ma250"),
        "bias250": latest.get("bias250"),
        "ma500": latest.get("ma500"),
        "bias500": latest.get("bias500"),
        "ma1250": latest.get("ma1250"),
        "bias1250": latest.get("bias1250"),
        "rsi14": latest.get("rsi14"),
        "v1_buy_fraction_pct": signal["accumulation"]["score"],
        "v1_sell_fraction_pct": signal["reduction"]["score"],
        "amount_unit": result.amount_unit,
    }
    _print(output)


@app.command()
def status(symbol: str = typer.Option("csi300", help="标的代码")):
    """显示本地最后可用指标，不访问在线数据源。"""
    service = MarketService(symbol)
    _print({"latest": service.latest(), "signal": service.signal()})


@app.command("source-meta")
def source_meta(symbol: str = typer.Option("csi300", help="标的代码")):
    """显示最近一次在线更新的数据来源记录（CSV 旁的 .meta.json）。"""
    from .updater import read_source_meta

    meta = read_source_meta(symbol)
    if meta is None:
        typer.echo("暂无来源记录（该标的尚未成功在线更新过）")
    else:
        _print(meta)


@app.command(hidden=True)
def bootstrap(
    symbol: str = typer.Option(..., help="待初始化的标的代码"),
    source: str = typer.Option("eastmoney", help="初始化数据源：eastmoney、sina、tencent、baostock 或 tushare"),
    start: str = typer.Option("2005-01-01", help="历史起始日期"),
    force: bool = typer.Option(False, help="覆盖已经存在的本地行情文件"),
):
    """为目录中尚无 CSV 的标的初始化历史行情。"""
    result = MarketDataUpdater(symbol, source_mode=source).bootstrap(start_date=start, force=force)
    _print(result.to_dict())


@app.command("ma-dynamic")
def ma_dynamic(symbol: str = typer.Option("csi300", help="标的代码"),
               start: str | None = None, end: str | None = None,
               ledger: bool = False):
    """沪深300 MA动态策略 V1；--ledger 输出逐日交易账本。"""
    try:
        result = MarketService(symbol).ma_dynamic(start, end, ledger)
    except (ValueError, KeyError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _print(result)
    if result["status"] != "ok":
        raise typer.Exit(code=1)
