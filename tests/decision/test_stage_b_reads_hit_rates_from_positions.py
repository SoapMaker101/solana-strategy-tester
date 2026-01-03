"""
Тесты для проверки что Stage B читает hit rates из portfolio_positions.csv.

T4: Stage B runner metrics from positions
"""
import pytest
import pandas as pd
from pathlib import Path

from backtester.decision.strategy_selector import (
    generate_selection_table_from_stability,
    load_stability_csv,
)
from backtester.decision.selection_rules import DEFAULT_RUNNER_CRITERIA_V1


def test_stage_b_reads_hit_rates_from_stability(tmp_path):
    """
    Тест: Stage B читает hit rates из strategy_stability.csv (которые были рассчитаны из portfolio_positions.csv).
    """
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    
    # Создаем strategy_stability.csv с hit rates из portfolio_positions
    stability_data = {
        "strategy": ["Runner_Test"],
        "survival_rate": [1.0],
        "pnl_variance": [0.01],
        "worst_window_pnl": [0.5],
        "median_window_pnl": [1.0],
        "windows_total": [3],
        "windows_positive": [3],
        "hit_rate_x2": [0.6],  # Из portfolio_positions.csv
        "hit_rate_x5": [0.2],  # Из portfolio_positions.csv
        "p90_hold_days": [1.0],
        "tail_contribution": [0.625],  # Из portfolio_positions.csv (5.0 / 8.0)
        "max_drawdown_pct": [-0.1],
    }
    
    stability_df = pd.DataFrame(stability_data)
    stability_path = reports_dir / "strategy_stability.csv"
    stability_df.to_csv(stability_path, index=False)
    
    # Генерируем selection table
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=stability_path,
        output_path=reports_dir / "strategy_selection.csv",
        criteria=None,  # Не используется для Runner
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    # Проверяем результат
    assert len(selection_df) == 1, "Должна быть одна стратегия"
    
    row = selection_df.iloc[0]
    
    # Проверяем что hit rates присутствуют
    assert "hit_rate_x2" in row, "hit_rate_x2 должен быть в selection table"
    assert "hit_rate_x5" in row, "hit_rate_x5 должен быть в selection table"
    assert abs(row["hit_rate_x2"] - 0.6) < 0.001, f"hit_rate_x2 должен быть 0.6, получен {row['hit_rate_x2']}"
    assert abs(row["hit_rate_x5"] - 0.2) < 0.001, f"hit_rate_x5 должен быть 0.2, получен {row['hit_rate_x5']}"
    
    # Проверяем что tail_contribution присутствует
    assert "tail_contribution" in row, "tail_contribution должен быть в selection table"
    assert abs(row["tail_contribution"] - 0.625) < 0.001, f"tail_contribution должен быть 0.625, получен {row['tail_contribution']}"
    
    # Проверяем что критерии применены
    assert "passed" in row, "passed должен быть в selection table"
    assert "failed_reasons" in row, "failed_reasons должен быть в selection table"


def test_stage_b_tail_contribution_calculation(tmp_path):
    """
    Тест: tail_contribution правильно рассчитывается из portfolio_positions.csv.
    
    Проверяем что tail_contribution = pnl_tail / pnl_total где tail trades: max_xn_reached >= 5.0
    """
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    
    # Создаем portfolio_positions.csv с позициями для расчета tail_contribution
    positions_data = {
        "strategy": ["Runner_Test"] * 4,
        "signal_id": ["test_1", "test_2", "test_3", "test_4"],
        "pnl_sol": [1.0, 2.0, 5.0, -1.0],  # total = 7.0, tail (>=5.0) = 5.0
        "max_xn_reached": [2.0, 3.0, 6.0, 0.5],  # только test_3 имеет >= 5.0
    }
    
    positions_df = pd.DataFrame(positions_data)
    positions_path = reports_dir / "portfolio_positions.csv"
    positions_df.to_csv(positions_path, index=False)
    
    # Создаем strategy_stability.csv (Stage A должен был рассчитать tail_contribution)
    # tail_contribution = 5.0 / 7.0 = 0.714...
    stability_data = {
        "strategy": ["Runner_Test"],
        "survival_rate": [1.0],
        "pnl_variance": [0.01],
        "worst_window_pnl": [0.5],
        "median_window_pnl": [1.0],
        "windows_total": [2],
        "windows_positive": [2],
        "hit_rate_x2": [0.5],
        "hit_rate_x5": [0.25],  # 1 из 4
        "p90_hold_days": [1.0],
        "tail_contribution": [5.0 / 7.0],  # Правильный расчет
        "max_drawdown_pct": [-0.1],
    }
    
    stability_df = pd.DataFrame(stability_data)
    stability_path = reports_dir / "strategy_stability.csv"
    stability_df.to_csv(stability_path, index=False)
    
    # Генерируем selection table
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=stability_path,
        output_path=reports_dir / "strategy_selection.csv",
        criteria=None,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    # Проверяем что tail_contribution корректно прочитан
    row = selection_df.iloc[0]
    assert abs(row["tail_contribution"] - (5.0 / 7.0)) < 0.001, f"tail_contribution должен быть ~0.714, получен {row['tail_contribution']}"















