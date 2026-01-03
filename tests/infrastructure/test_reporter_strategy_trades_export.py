"""
Тесты для экспорта strategy_trades.csv (Этап 1)
"""
import pytest
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta
from tempfile import TemporaryDirectory

from backtester.infrastructure.reporter import Reporter
from backtester.domain.strategy_trade_blueprint import (
    StrategyTradeBlueprint,
    PartialExitBlueprint,
    FinalExitBlueprint,
)


def test_strategy_trades_csv_export_columns():
    """
    Тест экспорта strategy_trades.csv.
    
    Сценарий согласно PIPE изменений.md:
    - создать StrategyTradeBlueprint вручную
    - сохранить CSV через reporter
    - проверить:
      - файл существует
      - header совпадает
      - partial_exits_json парсится
      - final_exit_json парсится или пустой
    """
    with TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        # Создаем StrategyTradeBlueprint вручную
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Создаем partial_exits с разными timestamp (проверяем сортировку)
        partial_exits = [
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=5),  # Второй по времени
                xn=5.0,
                fraction=0.4
            ),
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=2),  # Первый по времени
                xn=2.0,
                fraction=0.3
            ),
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=10),  # Третий по времени
                xn=10.0,
                fraction=0.3
            ),
        ]
        
        # Создаем final_exit
        final_exit = FinalExitBlueprint(
            timestamp=base_time + timedelta(minutes=15),
            reason="all_levels_hit"
        )
        
        blueprint = StrategyTradeBlueprint(
            signal_id="test_signal_1",
            strategy_id="test_strategy",
            contract_address="TESTTOKEN",
            entry_time=base_time,
            entry_price_raw=100.0,
            entry_mcap_proxy=100_000_000.0,
            partial_exits=partial_exits,
            final_exit=final_exit,
            realized_multiple=5.6,  # 0.3*2.0 + 0.4*5.0 + 0.3*10.0
            max_xn_reached=10.0,
            reason="all_levels_hit"
        )
        
        # Сохраняем CSV
        reporter.save_strategy_trades([blueprint])
        
        # Проверяем, что файл существует
        csv_path = Path(tmpdir) / "strategy_trades.csv"
        assert csv_path.exists(), "strategy_trades.csv file should exist"
        
        # Проверяем header
        expected_columns = [
            "signal_id",
            "strategy_id",
            "contract_address",
            "entry_time",
            "entry_price_raw",
            "entry_mcap_proxy",
            "partial_exits_json",
            "final_exit_json",
            "realized_multiple",
            "max_xn_reached",
            "reason",
        ]
        
        # Читаем CSV через pandas для проверки header
        df = pd.read_csv(csv_path)
        
        # Проверяем, что все колонки присутствуют
        assert list(df.columns) == expected_columns, \
            f"CSV columns mismatch. Expected: {expected_columns}, got: {list(df.columns)}"
        
        # Проверяем, что есть одна строка данных
        assert len(df) == 1, f"Expected 1 row, got {len(df)}"
        
        row = df.iloc[0]
        
        # Проверяем базовые поля
        assert row["signal_id"] == "test_signal_1"
        assert row["strategy_id"] == "test_strategy"
        assert row["contract_address"] == "TESTTOKEN"
        assert row["entry_price_raw"] == pytest.approx(100.0)
        assert row["entry_mcap_proxy"] == pytest.approx(100_000_000.0)
        assert row["realized_multiple"] == pytest.approx(5.6)
        assert row["max_xn_reached"] == pytest.approx(10.0)
        assert row["reason"] == "all_levels_hit"
        
        # Проверяем entry_time (ISO формат)
        assert row["entry_time"] == base_time.isoformat()
        
        # Проверка 1: partial_exits_json парсится
        partial_exits_json_str = row["partial_exits_json"]
        assert isinstance(partial_exits_json_str, str), "partial_exits_json should be a string"
        
        try:
            partial_exits_parsed = json.loads(partial_exits_json_str)
        except json.JSONDecodeError as e:
            pytest.fail(f"Failed to parse partial_exits_json as JSON: {e}")
        
        # Проверяем структуру partial_exits
        assert isinstance(partial_exits_parsed, list), "partial_exits_json should be a list"
        assert len(partial_exits_parsed) == 3, "Should have 3 partial exits"
        
        # Проверяем, что partial_exits отсортированы по времени (должны быть в порядке 2x, 5x, 10x)
        # Это проверяет что to_row() правильно сортирует
        assert partial_exits_parsed[0]["xn"] == pytest.approx(2.0)
        assert partial_exits_parsed[0]["fraction"] == pytest.approx(0.3)
        assert partial_exits_parsed[1]["xn"] == pytest.approx(5.0)
        assert partial_exits_parsed[1]["fraction"] == pytest.approx(0.4)
        assert partial_exits_parsed[2]["xn"] == pytest.approx(10.0)
        assert partial_exits_parsed[2]["fraction"] == pytest.approx(0.3)
        
        # Проверяем, что timestamps идут в порядке возрастания
        timestamps = [exit_data["timestamp"] for exit_data in partial_exits_parsed]
        assert timestamps == sorted(timestamps), "partial_exits should be sorted by timestamp"
        
        # Проверяем формат timestamp (ISO)
        for exit_data in partial_exits_parsed:
            assert "timestamp" in exit_data
            assert "xn" in exit_data
            assert "fraction" in exit_data
            # Проверяем, что timestamp можно распарсить
            datetime.fromisoformat(exit_data["timestamp"])
        
        # Проверка 2: final_exit_json парсится (не пустой)
        final_exit_json_str = row["final_exit_json"]
        assert isinstance(final_exit_json_str, str), "final_exit_json should be a string"
        assert final_exit_json_str != "", "final_exit_json should not be empty when final_exit is present"
        
        try:
            final_exit_parsed = json.loads(final_exit_json_str)
        except json.JSONDecodeError as e:
            pytest.fail(f"Failed to parse final_exit_json as JSON: {e}")
        
        # Проверяем структуру final_exit
        assert isinstance(final_exit_parsed, dict), "final_exit_json should be a dict"
        assert "timestamp" in final_exit_parsed
        assert "reason" in final_exit_parsed
        assert final_exit_parsed["reason"] == "all_levels_hit"
        # Проверяем, что timestamp можно распарсить
        datetime.fromisoformat(final_exit_parsed["timestamp"])


def test_strategy_trades_csv_export_empty_final_exit():
    """
    Тест экспорта с пустым final_exit (проверяем, что final_exit_json = "").
    """
    with TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        blueprint = StrategyTradeBlueprint(
            signal_id="test_signal_2",
            strategy_id="test_strategy",
            contract_address="TESTTOKEN",
            entry_time=base_time,
            entry_price_raw=100.0,
            entry_mcap_proxy=None,
            partial_exits=[],
            final_exit=None,  # Пустой final_exit
            realized_multiple=1.0,
            max_xn_reached=0.0,
            reason="no_entry"
        )
        
        # Сохраняем CSV
        reporter.save_strategy_trades([blueprint])
        
        csv_path = Path(tmpdir) / "strategy_trades.csv"
        df = pd.read_csv(csv_path)
        
        row = df.iloc[0]
        
        # Проверяем, что final_exit_json пустой
        final_exit_json_str = row["final_exit_json"]
        assert final_exit_json_str == "", "final_exit_json should be empty string when final_exit is None"
        
        # Проверяем, что partial_exits_json пустой список (JSON)
        partial_exits_json_str = row["partial_exits_json"]
        partial_exits_parsed = json.loads(partial_exits_json_str)
        assert partial_exits_parsed == [], "partial_exits_json should be empty list when no partial_exits"


def test_strategy_trades_csv_export_empty_list():
    """
    Тест экспорта с пустым списком blueprints (файл должен быть создан с header).
    """
    with TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        # Сохраняем пустой список
        reporter.save_strategy_trades([])
        
        csv_path = Path(tmpdir) / "strategy_trades.csv"
        assert csv_path.exists(), "strategy_trades.csv should exist even with empty list"
        
        df = pd.read_csv(csv_path)
        
        # Проверяем header
        expected_columns = [
            "signal_id",
            "strategy_id",
            "contract_address",
            "entry_time",
            "entry_price_raw",
            "entry_mcap_proxy",
            "partial_exits_json",
            "final_exit_json",
            "realized_multiple",
            "max_xn_reached",
            "reason",
        ]
        
        assert list(df.columns) == expected_columns, \
            f"CSV columns mismatch. Expected: {expected_columns}, got: {list(df.columns)}"
        
        # Проверяем, что нет строк данных
        assert len(df) == 0, "Should have no rows when blueprints list is empty"

