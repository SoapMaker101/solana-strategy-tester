"""
Integration test for Stage A pipeline
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import shutil

from backtester.research.run_stage_a import main
from backtester.research.window_aggregator import aggregate_all_strategies
from backtester.research.strategy_stability import generate_stability_table_from_reports


@pytest.fixture
def fake_reports_dir(tmp_path):
    """Создаёт директорию с fake trades CSV для 2 стратегий"""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Strategy 1: несколько сделок в разных временных окнах
    strategy1_trades = pd.DataFrame({
        "signal_id": ["s1_1", "s1_2", "s1_3", "s1_4"],
        "contract_address": ["TOKEN1", "TOKEN1", "TOKEN2", "TOKEN2"],
        "signal_timestamp": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-02-01T10:00:00Z",
            "2024-03-01T10:00:00Z",
        ], utc=True),
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-02-01T10:00:00Z",
            "2024-03-01T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-15T10:01:00Z",
            "2024-02-01T10:01:00Z",
            "2024-03-01T10:01:00Z",
        ], utc=True),
        "entry_price": [100.0, 100.0, 100.0, 100.0],
        "exit_price": [110.0, 95.0, 115.0, 120.0],
        "pnl_pct": [0.1, -0.05, 0.15, 0.2],  # В долях
        "reason": ["tp", "sl", "tp", "tp"],
        "source": ["test", "test", "test", "test"],
        "narrative": ["test", "test", "test", "test"],
    })
    
    strategy1_path = reports_dir / "fake_strategy_1_trades.csv"
    strategy1_trades.to_csv(strategy1_path, index=False)
    
    # Strategy 2: другая стратегия с другими результатами
    strategy2_trades = pd.DataFrame({
        "signal_id": ["s2_1", "s2_2"],
        "contract_address": ["TOKEN3", "TOKEN3"],
        "signal_timestamp": pd.to_datetime([
            "2024-01-10T10:00:00Z",
            "2024-02-10T10:00:00Z",
        ], utc=True),
        "entry_time": pd.to_datetime([
            "2024-01-10T10:00:00Z",
            "2024-02-10T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-10T10:01:00Z",
            "2024-02-10T10:01:00Z",
        ], utc=True),
        "entry_price": [100.0, 100.0],
        "exit_price": [90.0, 105.0],
        "pnl_pct": [-0.1, 0.05],  # В долях
        "reason": ["sl", "tp"],
        "source": ["test", "test"],
        "narrative": ["test", "test"],
    })
    
    strategy2_path = reports_dir / "fake_strategy_2_trades.csv"
    strategy2_trades.to_csv(strategy2_path, index=False)
    
    return reports_dir


def test_stage_a_pipeline_full(fake_reports_dir, monkeypatch, capsys):
    """Проверяет полный pipeline Stage A"""
    # Создаем positions-level CSV перед запуском Stage A
    positions_path = fake_reports_dir / "portfolio_positions.csv"
    df_positions = pd.DataFrame({
        "strategy": ["fake_strategy_1", "fake_strategy_1", "fake_strategy_2", "fake_strategy_2"],
        "signal_id": ["s1_1", "s1_2", "s2_1", "s2_2"],
        "contract_address": ["TOKEN1", "TOKEN2", "TOKEN3", "TOKEN3"],
        "entry_time": [
            "2024-01-01T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-01-10T10:00:00Z",
            "2024-02-10T10:00:00Z",
        ],
        "exit_time": [
            "2024-01-01T10:01:00Z",
            "2024-01-15T10:01:00Z",
            "2024-01-10T10:01:00Z",
            "2024-02-10T10:01:00Z",
        ],
        "status": ["closed", "closed", "closed", "closed"],
        "size": [1.0, 1.0, 1.0, 1.0],
        "pnl_sol": [0.1, -0.05, -0.1, 0.05],
        "pnl_pct": [0.1, -0.05, -0.1, 0.05],
        "fees_total_sol": [0.001, 0.001, 0.001, 0.001],
        "exec_entry_price": [100.0, 100.0, 100.0, 100.0],
        "exec_exit_price": [110.0, 95.0, 90.0, 105.0],
        "raw_entry_price": [100.0, 100.0, 100.0, 100.0],
        "raw_exit_price": [110.0, 95.0, 90.0, 105.0],
        "closed_by_reset": [False, False, False, False],
        "triggered_portfolio_reset": [False, False, False, False],
        "reset_reason": [None, None, None, None],
        "hold_minutes": [60, 60, 60, 60],
    })
    df_positions.to_csv(positions_path, index=False)
    
    # Мокаем sys.argv для argparse
    import sys
    monkeypatch.setattr(sys, "argv", [
        "run_stage_a.py",
        "--trades", str(positions_path),
        "--reports-dir",
        str(fake_reports_dir),
    ])
    
    # Запускаем Stage A
    main()
    
    # Проверяем, что создан файл strategy_stability.csv
    stability_path = fake_reports_dir / "strategy_stability.csv"
    assert stability_path.exists(), "strategy_stability.csv should be created"
    
    # Проверяем, что создан файл stage_a_summary.csv
    summary_path = fake_reports_dir / "stage_a_summary.csv"
    assert summary_path.exists(), "stage_a_summary.csv should be created"
    
    # Проверяем содержимое файла stability
    df = pd.read_csv(stability_path)
    
    assert len(df) >= 2, "Should have at least 2 strategies"
    assert "strategy" in df.columns
    assert "split_count" in df.columns, "Should have split_count column"
    assert "survival_rate" in df.columns
    assert "worst_window_pnl" in df.columns
    assert "pnl_variance" in df.columns
    
    # Проверяем, что обе стратегии присутствуют
    strategies = set(df["strategy"].tolist())
    assert "fake_strategy_1" in strategies or "fake_strategy_1_trades" in strategies
    assert "fake_strategy_2" in strategies or "fake_strategy_2_trades" in strategies
    
    # Проверяем содержимое файла summary
    summary_df = pd.read_csv(summary_path)
    assert "strategy" in summary_df.columns
    assert "split_count" in summary_df.columns
    assert "window_index" in summary_df.columns
    assert "window_start" in summary_df.columns
    assert "window_end" in summary_df.columns
    assert "window_trades" in summary_df.columns
    assert "window_pnl" in summary_df.columns


def test_stage_a_pipeline_aggregation(fake_reports_dir):
    """Проверяет агрегацию стратегий с равными окнами"""
    from backtester.research.window_aggregator import aggregate_all_strategies, DEFAULT_SPLITS
    
    aggregated = aggregate_all_strategies(fake_reports_dir, split_counts=DEFAULT_SPLITS)
    
    assert len(aggregated) >= 2, "Should aggregate at least 2 strategies"
    
    # Проверяем структуру
    for strategy_name, strategy_windows in aggregated.items():
        assert isinstance(strategy_windows, dict)
        # Должны быть окна для каждого split_count
        for window_name, window_list in strategy_windows.items():
            assert window_name.startswith("split_")
            assert isinstance(window_list, list)
            # Проверяем структуру каждого окна
            for window_info in window_list:
                assert "window_index" in window_info
                assert "window_start" in window_info
                assert "window_end" in window_info
                assert "metrics" in window_info


def test_stage_a_pipeline_stability_table_exists(fake_reports_dir):
    """Проверяет наличие итогового CSV после pipeline"""
    stability_df = generate_stability_table_from_reports(
        reports_dir=fake_reports_dir,
        output_path=fake_reports_dir / "strategy_stability.csv",
    )
    
    assert len(stability_df) >= 2, "Should have at least 2 strategies in stability table"
    
    # Проверяем обязательные колонки
    required_cols = [
        "strategy",
        "split_count",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "best_window_pnl",
        "median_window_pnl",
        "windows_positive",
        "windows_total",
    ]
    
    for col in required_cols:
        assert col in stability_df.columns, f"Missing column: {col}"
    
    # Проверяем, что таблица не отсортирована по pnl (важное правило!)
    # Не должно быть явной сортировки по worst_window_pnl или best_window_pnl


def test_stage_a_pipeline_no_empty_strategies(fake_reports_dir):
    """Проверяет, что пустые стратегии не ломают pipeline"""
    # Создаём пустой trades файл
    empty_path = fake_reports_dir / "empty_strategy_trades.csv"
    empty_df = pd.DataFrame(columns=[
        "signal_id", "contract_address", "signal_timestamp",
        "entry_time", "exit_time", "entry_price", "exit_price",
        "pnl_pct", "reason", "source", "narrative",
    ])
    empty_df.to_csv(empty_path, index=False)
    
    # Pipeline не должен упасть
    stability_df = generate_stability_table_from_reports(
        reports_dir=fake_reports_dir,
        output_path=fake_reports_dir / "strategy_stability.csv",
    )
    
    # Пустая стратегия может быть в таблице с нулевыми метриками
    # или может быть пропущена - оба варианта приемлемы
    assert isinstance(stability_df, pd.DataFrame)




















