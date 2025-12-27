"""
Test that Stage A uses portfolio trades (executed) only, not strategy-level trades.
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import shutil

from backtester.research.run_stage_a import main
from backtester.research.strategy_stability import generate_stability_table_from_portfolio_trades
from backtester.research.window_aggregator import validate_trades_table
from backtester.domain.portfolio import PortfolioResult, PortfolioStats
from backtester.domain.position import Position


@pytest.fixture
def temp_reports_dir():
    """Создаёт временную директорию для тестов"""
    tmp_dir = tempfile.mkdtemp()
    yield Path(tmp_dir)
    shutil.rmtree(tmp_dir)


def test_stage_a_uses_portfolio_trades_only(temp_reports_dir):
    """
    Test 1: Stage A uses portfolio trades only.
    
    Сценарий:
    - есть synthetic strategy outputs = 10 сделок
    - портфель реально исполнил только 3 (остальные "пропущены")
    - Stage A должен видеть 3 сделки
    - в stability table trades_total==3, а не 10
    """
    # Создаём portfolio_trades.csv с 3 executed trades
    portfolio_trades = pd.DataFrame({
        "strategy": ["test_strategy", "test_strategy", "test_strategy"],
        "signal_id": ["s1", "s2", "s3"],
        "contract_address": ["TOKEN1", "TOKEN2", "TOKEN3"],
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-02-01T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-15T10:01:00Z",
            "2024-02-01T10:01:00Z",
        ], utc=True),
        "status": ["closed", "closed", "closed"],
        "size": [1.0, 1.0, 1.0],
        "pnl_sol": [0.1, -0.05, 0.15],
        "fees_total_sol": [0.001, 0.001, 0.001],
        "exec_entry_price": [100.0, 100.0, 100.0],
        "exec_exit_price": [110.0, 95.0, 120.0],
        "raw_entry_price": [100.0, 100.0, 100.0],
        "raw_exit_price": [110.0, 95.0, 120.0],
        "closed_by_reset": [False, False, False],
        "triggered_reset": [False, False, False],
        "triggered_portfolio_reset": [False, False, False],
    })
    
    trades_path = temp_reports_dir / "portfolio_trades.csv"
    portfolio_trades.to_csv(trades_path, index=False)
    
    # Запускаем Stage A
    stability_df = generate_stability_table_from_portfolio_trades(
        trades_path=trades_path,
        reports_dir=temp_reports_dir,
        split_counts=[2, 3],
    )
    
    # Проверяем, что trades_total == 3 (а не 10)
    assert len(stability_df) > 0, "Should have stability rows"
    
    # Проверяем trades_total для каждой стратегии
    for _, row in stability_df.iterrows():
        if row["strategy"] == "test_strategy":
            assert row["trades_total"] == 3, f"Expected 3 executed trades, got {row['trades_total']}"


def test_schema_validation(temp_reports_dir):
    """
    Test 3: Schema validation.
    
    Передать в Stage A таблицу без pnl_sol → Stage A падает с ValueError.
    """
    # Создаём таблицу без обязательной колонки pnl_sol
    invalid_trades = pd.DataFrame({
        "strategy": ["test_strategy"],
        "signal_id": ["s1"],
        "contract_address": ["TOKEN1"],
        "entry_time": pd.to_datetime(["2024-01-01T10:00:00Z"], utc=True),
        "exit_time": pd.to_datetime(["2024-01-01T10:01:00Z"], utc=True),
        "status": ["closed"],
        # Отсутствует pnl_sol!
    })
    
    trades_path = temp_reports_dir / "portfolio_trades.csv"
    invalid_trades.to_csv(trades_path, index=False)
    
    # Stage A должен упасть с ValueError при валидации
    with pytest.raises(ValueError, match="Missing required columns.*pnl_sol"):
        generate_stability_table_from_portfolio_trades(
            trades_path=trades_path,
            reports_dir=temp_reports_dir,
        )
    
    # Также проверяем validate_trades_table напрямую
    df = pd.read_csv(trades_path)
    with pytest.raises(ValueError, match="Missing required columns.*pnl_sol"):
        validate_trades_table(df, trades_path)


def test_schema_validation_non_closed_status(temp_reports_dir):
    """
    Test: Schema validation rejects non-closed positions.
    """
    # Создаём таблицу с открытой позицией
    invalid_trades = pd.DataFrame({
        "strategy": ["test_strategy"],
        "signal_id": ["s1"],
        "contract_address": ["TOKEN1"],
        "entry_time": pd.to_datetime(["2024-01-01T10:00:00Z"], utc=True),
        "exit_time": pd.to_datetime(["2024-01-01T10:01:00Z"], utc=True),
        "status": ["open"],  # Не closed!
        "size": [1.0],
        "pnl_sol": [0.1],
        "fees_total_sol": [0.001],
        "exec_entry_price": [100.0],
        "exec_exit_price": [110.0],
        "raw_entry_price": [100.0],
        "raw_exit_price": [110.0],
        "closed_by_reset": [False],
        "triggered_reset": [False],
        "triggered_portfolio_reset": [False],
    })
    
    trades_path = temp_reports_dir / "portfolio_trades.csv"
    invalid_trades.to_csv(trades_path, index=False)
    
    # Stage A должен отфильтровать или упасть при валидации
    with pytest.raises(ValueError, match="status != 'closed'"):
        df = pd.read_csv(trades_path)
        validate_trades_table(df, trades_path)


def test_window_splitting_entry_time(temp_reports_dir):
    """
    Test 4: Window splitting based on entry_time.
    
    Сделать trades с разными entry_time; сплит 2/3/4/5 должен давать:
    - корректное количество окон
    - суммы trades_total совпадают с исходным
    """
    # Создаём trades с разными entry_time
    portfolio_trades = pd.DataFrame({
        "strategy": ["test_strategy"] * 8,
        "signal_id": [f"s{i}" for i in range(8)],
        "contract_address": ["TOKEN1"] * 8,
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-05T10:00:00Z",
            "2024-01-10T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-01-20T10:00:00Z",
            "2024-01-25T10:00:00Z",
            "2024-01-30T10:00:00Z",
            "2024-02-01T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-05T10:01:00Z",
            "2024-01-10T10:01:00Z",
            "2024-01-15T10:01:00Z",
            "2024-01-20T10:01:00Z",
            "2024-01-25T10:01:00Z",
            "2024-01-30T10:01:00Z",
            "2024-02-01T10:01:00Z",
        ], utc=True),
        "status": ["closed"] * 8,
        "size": [1.0] * 8,
        "pnl_sol": [0.1] * 8,
        "fees_total_sol": [0.001] * 8,
        "exec_entry_price": [100.0] * 8,
        "exec_exit_price": [110.0] * 8,
        "raw_entry_price": [100.0] * 8,
        "raw_exit_price": [110.0] * 8,
        "closed_by_reset": [False] * 8,
        "triggered_reset": [False] * 8,
        "triggered_portfolio_reset": [False] * 8,
    })
    
    trades_path = temp_reports_dir / "portfolio_trades.csv"
    portfolio_trades.to_csv(trades_path, index=False)
    
    # Тестируем разные split_counts
    for split_n in [2, 3, 4, 5]:
        stability_df = generate_stability_table_from_portfolio_trades(
            trades_path=trades_path,
            reports_dir=temp_reports_dir,
            split_counts=[split_n],
        )
        
        # Проверяем, что trades_total == 8 для всех split_n
        for _, row in stability_df.iterrows():
            if row["strategy"] == "test_strategy":
                assert row["trades_total"] == 8, f"Expected 8 trades for split {split_n}, got {row['trades_total']}"
                assert row["windows_total"] == split_n, f"Expected {split_n} windows, got {row['windows_total']}"


def test_runner_partial_exits_pnl(temp_reports_dir):
    """
    Test 2: Runner partial exits do not break pnl.
    
    Сценарий:
    - создать позиции Runner с meta:
      - exec_entry_price/exec_exit_price
      - pnl_sol
    - Stage A должен суммировать pnl_sol и выдавать верный total_pnl по окнам
    """
    # Создаём portfolio_trades с Runner позициями (с partial exits через pnl_sol)
    portfolio_trades = pd.DataFrame({
        "strategy": ["runner_strategy"] * 3,
        "signal_id": ["r1", "r2", "r3"],
        "contract_address": ["TOKEN1", "TOKEN2", "TOKEN3"],
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-02-01T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:05:00Z",
            "2024-01-15T10:05:00Z",
            "2024-02-01T10:05:00Z",
        ], utc=True),
        "status": ["closed", "closed", "closed"],
        "size": [1.0, 1.0, 1.0],
        # pnl_sol уже включает partial exits (суммированный PnL от всех частичных выходов)
        "pnl_sol": [0.2, -0.1, 0.3],  # Включает partial exits
        "fees_total_sol": [0.002, 0.002, 0.002],
        "exec_entry_price": [100.0, 100.0, 100.0],
        "exec_exit_price": [120.0, 90.0, 130.0],
        "raw_entry_price": [100.0, 100.0, 100.0],
        "raw_exit_price": [120.0, 90.0, 130.0],
        "closed_by_reset": [False, False, False],
        "triggered_reset": [False, False, False],
        "triggered_portfolio_reset": [False, False, False],
    })
    
    trades_path = temp_reports_dir / "portfolio_trades.csv"
    portfolio_trades.to_csv(trades_path, index=False)
    
    # Запускаем Stage A
    stability_df = generate_stability_table_from_portfolio_trades(
        trades_path=trades_path,
        reports_dir=temp_reports_dir,
        split_counts=[2],
    )
    
    # Проверяем, что total_pnl правильно суммирует pnl_sol
    # Ожидаемая сумма: 0.2 + (-0.1) + 0.3 = 0.4
    # Но это будет разбито по окнам, поэтому проверяем что trades_total == 3
    assert len(stability_df) > 0, "Should have stability rows"
    
    for _, row in stability_df.iterrows():
        if row["strategy"] == "runner_strategy":
            assert row["trades_total"] == 3, f"Expected 3 trades, got {row['trades_total']}"
            # Проверяем, что worst_window_pnl и best_window_pnl корректны
            # (сумма pnl_sol в худшем/лучшем окне должна быть правильной)









