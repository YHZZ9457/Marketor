from __future__ import annotations

import json

import pandas as pd
import pytest

from csi300_service.catalog import InstrumentCatalog
from csi300_service.custom_instruments import CustomInstrumentManager, normalize_imported_csv
from csi300_service.service import MarketService


def test_import_chinese_stock_csv_and_analyze(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    source = tmp_path / "示例股票.csv"
    pd.DataFrame({
        "交易日期": pd.date_range("2024-01-01", periods=40).strftime("%Y%m%d"),
        "开盘价": range(99, 139),
        "最高价": range(101, 141),
        "最低价": range(98, 138),
        "收盘价": range(100, 140),
        "成交额": range(1000, 1040),
    }).to_csv(source, index=False, encoding="utf-8-sig")

    instrument = CustomInstrumentManager().import_csv(
        source, symbol="my_stock", name="我的股票", asset_class="stock",
        market="CN", currency="CNY",
    )

    catalog = InstrumentCatalog()
    assert catalog.get("my_stock") == instrument
    service = MarketService("my_stock", catalog=catalog)
    assert service.latest()["close"] == 139
    assert service.metadata()["asset_class"] == "stock"
    assert service.metadata()["rows"] == 40


def test_import_fund_nav_and_replace_existing_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    source = tmp_path / "fund.csv"
    pd.DataFrame({
        "净值日期": pd.date_range("2025-01-01", periods=20),
        "单位净值": [1 + index / 100 for index in range(20)],
    }).to_csv(source, index=False)
    manager = CustomInstrumentManager()
    manager.import_csv(source, symbol="my_fund", name="自选基金", asset_class="fund")

    with pytest.raises(ValueError, match="已存在"):
        manager.import_csv(source, symbol="my_fund", name="自选基金", asset_class="fund")

    frame = pd.read_csv(source)
    frame["单位净值"] += 1
    frame.to_csv(source, index=False)
    manager.import_csv(source, symbol="my_fund", name="自选基金", asset_class="fund", replace=True)
    assert MarketService("my_fund").latest()["close"] == pytest.approx(2.19)


def test_csv_import_rejects_missing_columns_and_too_few_rows(tmp_path):
    missing = tmp_path / "missing.csv"
    missing.write_text("日期,成交额\n2024-01-01,100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="至少需要日期"):
        normalize_imported_csv(missing)

    short = tmp_path / "short.csv"
    short.write_text("date,close\n2024-01-01,100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="至少需要 15 条"):
        normalize_imported_csv(short)


def test_custom_catalog_file_is_separate_from_bundled_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    source = tmp_path / "index.csv"
    pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=15),
        "close": range(100, 115),
    }).to_csv(source, index=False)
    manager = CustomInstrumentManager()
    manager.import_csv(source, symbol="private_index", name="自定义指数", asset_class="index")

    payload = json.loads(manager.config_path.read_text(encoding="utf-8"))
    assert payload["instruments"][0]["source_priority"] == []
    assert InstrumentCatalog().get("private_index").market == "CUSTOM"
