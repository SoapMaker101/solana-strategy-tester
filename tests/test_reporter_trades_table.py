"""
Unit tests for Reporter.save_trades_table method
"""
import pytest
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from backtester.infrastructure.reporter import Reporter
from backtester.domain.models import StrategyOutput


@pytest.fixture
def reporter(tmp_path):
    """Создает Reporter с временной директорией"""
    return Reporter(output_dir=str(tmp_path))


def test_trades_table_has_required_columns(reporter):
    """Проверяет, что таблица содержит все необходимые колонки"""
    # Создаём результаты с валидной сделкой
    results = [
        {
            "signal_id": "test1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "source": "test_source",
            "narrative": "test narrative",
            "result": StrategyOutput(
                entry_time=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
                entry_price=100.0,
                exit_time=datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
                exit_price=110.0,
                pnl=0.1,  # 10%
                reason="tp",
                meta={
                    "total_supply_used": 1000000.0,
                    "entry_mcap_proxy": 100000000.0,
                }
            )
        }
    ]
    
    # Сохраняем таблицу
    reporter.save_trades_table("test_strategy", results)
    
    # Читаем CSV
    csv_path = reporter.output_dir / "test_strategy_trades.csv"
    df = pd.read_csv(csv_path)
    
    # Проверяем наличие обязательных колонок
    required_columns = [
        "signal_id", "contract_address", "signal_timestamp",
        "entry_time", "exit_time", "entry_price", "exit_price",
        "pnl_pct", "reason", "source", "narrative"
    ]
    
    for col in required_columns:
        assert col in df.columns, f"Column {col} missing from trades table"
    
    # Проверяем, что есть данные
    assert len(df) == 1
    assert df.iloc[0]["signal_id"] == "test1"
    assert df.iloc[0]["contract_address"] == "TOKEN1"
    assert df.iloc[0]["entry_price"] == 100.0
    assert df.iloc[0]["exit_price"] == 110.0
    assert df.iloc[0]["pnl_pct"] == 10.0  # 0.1 * 100 = 10.0%
    assert df.iloc[0]["reason"] == "tp"
    assert df.iloc[0]["source"] == "test_source"
    assert df.iloc[0]["narrative"] == "test narrative"


def test_trades_table_flattens_meta_scalars(reporter):
    """Проверяет, что скалярные значения из meta расплющиваются правильно"""
    results = [
        {
            "signal_id": "test1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "result": StrategyOutput(
                entry_time=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
                entry_price=100.0,
                exit_time=datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
                exit_price=110.0,
                pnl=0.1,
                reason="tp",
                meta={
                    "total_supply_used": 1000000.0,
                    "entry_mcap_proxy": 100000000.0,
                    "exit_mcap_proxy": 110000000.0,
                    "mcap_change_pct": 0.1,
                    "vol_sum_5m": 5000.0,
                    "vol_sum_15m": 15000.0,
                    "range_pct_5m": 0.05,
                    "volat_5m": 0.02,
                    "signal_to_entry_delay_minutes": 1.0,
                }
            )
        }
    ]
    
    reporter.save_trades_table("test_strategy", results)
    csv_path = reporter.output_dir / "test_strategy_trades.csv"
    df = pd.read_csv(csv_path)
    
    # Проверяем, что скалярные значения из meta появились как колонки с префиксом meta_
    assert "meta_total_supply_used" in df.columns
    assert "meta_entry_mcap_proxy" in df.columns
    assert "meta_exit_mcap_proxy" in df.columns
    assert "meta_mcap_change_pct" in df.columns
    assert "meta_vol_sum_5m" in df.columns
    assert "meta_vol_sum_15m" in df.columns
    
    # Проверяем значения
    row = df.iloc[0]
    assert row["meta_total_supply_used"] == 1000000.0
    assert row["meta_entry_mcap_proxy"] == 100000000.0
    assert row["meta_exit_mcap_proxy"] == 110000000.0
    assert row["meta_mcap_change_pct"] == 0.1
    assert row["meta_vol_sum_5m"] == 5000.0
    assert row["meta_vol_sum_15m"] == 15000.0


def test_trades_table_jsonifies_nested_meta(reporter):
    """Проверяет, что вложенные dict и list в meta преобразуются в JSON строки"""
    nested_dict = {"key1": "value1", "key2": 123}
    nested_list = [1, 2, 3, "test"]
    
    results = [
        {
            "signal_id": "test1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "result": StrategyOutput(
                entry_time=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
                entry_price=100.0,
                exit_time=datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
                exit_price=110.0,
                pnl=0.1,
                reason="tp",
                meta={
                    "scalar_value": 42.0,
                    "nested_dict": nested_dict,
                    "nested_list": nested_list,
                    "another_dict": {"a": 1, "b": "test"},
                }
            )
        }
    ]
    
    reporter.save_trades_table("test_strategy", results)
    csv_path = reporter.output_dir / "test_strategy_trades.csv"
    df = pd.read_csv(csv_path)
    
    # Проверяем скалярное значение
    assert "meta_scalar_value" in df.columns
    assert df.iloc[0]["meta_scalar_value"] == 42.0
    
    # Проверяем, что вложенные структуры - это JSON строки
    assert "meta_nested_dict" in df.columns
    assert "meta_nested_list" in df.columns
    assert "meta_another_dict" in df.columns
    
    nested_dict_str = df.iloc[0]["meta_nested_dict"]
    nested_list_str = df.iloc[0]["meta_nested_list"]
    another_dict_str = df.iloc[0]["meta_another_dict"]
    
    # Проверяем, что это строки
    assert isinstance(nested_dict_str, str)
    assert isinstance(nested_list_str, str)
    assert isinstance(another_dict_str, str)
    
    # Проверяем, что это валидный JSON, и содержимое правильное
    parsed_dict = json.loads(nested_dict_str)
    assert parsed_dict == nested_dict
    
    parsed_list = json.loads(nested_list_str)
    assert parsed_list == nested_list
    
    parsed_another = json.loads(another_dict_str)
    assert parsed_another == {"a": 1, "b": "test"}


def test_trades_table_filters_no_entry_and_error(reporter):
    """Проверяет, что результаты с reason='no_entry' и 'error' не попадают в таблицу"""
    results = [
        {
            "signal_id": "valid_trade",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "result": StrategyOutput(
                entry_time=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
                entry_price=100.0,
                exit_time=datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
                exit_price=110.0,
                pnl=0.1,
                reason="tp",
                meta={}
            )
        },
        {
            "signal_id": "no_entry",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={}
            )
        },
        {
            "signal_id": "error",
            "contract_address": "TOKEN3",
            "strategy": "test_strategy",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="error",
                meta={"exception": "Some error"}
            )
        },
    ]
    
    reporter.save_trades_table("test_strategy", results)
    csv_path = reporter.output_dir / "test_strategy_trades.csv"
    df = pd.read_csv(csv_path)
    
    # Должна быть только одна строка (valid_trade)
    assert len(df) == 1
    assert df.iloc[0]["signal_id"] == "valid_trade"
    assert "no_entry" not in df["signal_id"].values
    assert "error" not in df["signal_id"].values


def test_trades_table_handles_empty_results(reporter):
    """Проверяет обработку пустого списка результатов"""
    results = []
    
    reporter.save_trades_table("test_strategy", results)
    
    # Файл должен существовать
    csv_path = reporter.output_dir / "test_strategy_trades.csv"
    assert csv_path.exists()
    
    # Должен содержать только заголовки
    df = pd.read_csv(csv_path)
    assert len(df) == 0
    
    # Проверяем наличие базовых колонок
    required_columns = [
        "signal_id", "contract_address", "signal_timestamp",
        "entry_time", "exit_time", "entry_price", "exit_price",
        "pnl_pct", "reason", "source", "narrative"
    ]
    for col in required_columns:
        assert col in df.columns


















