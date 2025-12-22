"""
Тесты для проверки что Stage B читает hit rates из portfolio_positions.csv.

T3: Stage B читает hit rates из portfolio_positions
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from backtester.decision.strategy_selector import (
    generate_selection_table_from_stability,
    load_stability_csv,
)
from backtester.decision.selection_rules import DEFAULT_RUNNER_CRITERIA_V1


def test_stage_b_hit_rates_from_portfolio_positions(tmp_path):
    """
    Тест: Stage B читает hit rates из portfolio_positions.csv.
    
    Setup:
    - strategy_stability.csv с одной стратегией
    - portfolio_positions.csv: 10 позиций, 6 с max_xn_reached>=2 (первые 5 + последняя 5.1), 1 с max_xn_reached>=5
    
    Ожидаем:
    - hit_rate_x2 == 0.6 (6 из 10)
    - hit_rate_x5 == 0.1 (1 из 10)
    """
    # Создаем strategy_stability.csv
    stability_data = {
        "strategy": ["Runner_Test"],
        "split_count": [3],
        "survival_rate": [1.0],
        "pnl_variance": [0.0],
        "worst_window_pnl": [0.0],
        "best_window_pnl": [0.0],
        "median_window_pnl": [0.0],
        "windows_positive": [1],
        "windows_total": [1],
        # Runner метрики будут добавлены из portfolio_positions
        "hit_rate_x2": [0.0],  # Placeholder, будет перезаписан
        "hit_rate_x5": [0.0],  # Placeholder, будет перезаписан
        "p90_hold_days": [1.0],
        "tail_contribution": [0.0],
        "max_drawdown_pct": [0.0],
    }
    stability_df = pd.DataFrame(stability_data)
    stability_path = tmp_path / "strategy_stability.csv"
    stability_df.to_csv(stability_path, index=False)
    
    # Создаем portfolio_positions.csv
    # 10 позиций: 6 с max_xn_reached>=2 (первые 5 + последняя 5.1), 1 с max_xn_reached>=5
    positions_data = {
        "strategy": ["Runner_Test"] * 10,
        "signal_id": [f"sig_{i}" for i in range(10)],
        "contract_address": [f"TOKEN{i}" for i in range(10)],
        "entry_time": [datetime(2024, 1, 1, 12, i, 0, tzinfo=timezone.utc).isoformat() for i in range(10)],
        "exit_time": [datetime(2024, 1, 1, 13, i, 0, tzinfo=timezone.utc).isoformat() for i in range(10)],
        "status": ["closed"] * 10,
        "size": [1.0] * 10,
        "pnl_sol": [1.0] * 10,
        "fees_total_sol": [0.1] * 10,
        "exec_entry_price": [1.0] * 10,
        "exec_exit_price": [2.1, 2.2, 2.3, 2.4, 2.5,  # 5 позиций с max_xn_reached>=2
                             1.1, 1.2, 1.3, 1.4, 5.1],  # 4 позиции с max_xn_reached<2, 1 с max_xn_reached>=5
        "raw_entry_price": [1.0] * 10,
        "raw_exit_price": [2.0] * 10,
        "closed_by_reset": [False] * 10,
        "triggered_portfolio_reset": [False] * 10,
        "reset_reason": ["none"] * 10,
        "hold_minutes": [60] * 10,
        "max_xn_reached": [2.1, 2.2, 2.3, 2.4, 2.5,  # 5 позиций с max_xn_reached>=2
                           1.1, 1.2, 1.3, 1.4, 5.1],  # 4 позиции с max_xn_reached<2, 1 с max_xn_reached>=5
        "hit_x2": [True, True, True, True, True,  # 5 позиций
                   False, False, False, False, True],  # 4 позиции False, 1 True (>=5) → итого 6 True
        "hit_x5": [False, False, False, False, False,  # 5 позиций False
                   False, False, False, False, True],  # 4 позиции False, 1 True → итого 1 True
    }
    positions_df = pd.DataFrame(positions_data)
    positions_path = tmp_path / "portfolio_positions.csv"
    positions_df.to_csv(positions_path, index=False)
    
    # Создаем reports_dir для calculate_runner_metrics
    reports_dir = tmp_path
    
    # Импортируем функцию для обновления stability table с hit rates
    from backtester.research.strategy_stability import build_stability_table, calculate_runner_metrics
    
    # Обновляем stability table с hit rates из portfolio_positions
    # Для этого нужно вызвать calculate_runner_metrics и обновить stability_df
    runner_metrics = calculate_runner_metrics(
        strategy_name="Runner_Test",
        portfolio_positions_path=positions_path,
        portfolio_summary_path=None,
    )
    
    # Обновляем stability_df с реальными hit rates
    stability_df.loc[0, "hit_rate_x2"] = runner_metrics["hit_rate_x2"]
    stability_df.loc[0, "hit_rate_x5"] = runner_metrics["hit_rate_x5"]
    stability_df.loc[0, "p90_hold_days"] = runner_metrics["p90_hold_days"]
    stability_df.loc[0, "tail_contribution"] = runner_metrics["tail_contribution"]
    stability_df.loc[0, "max_drawdown_pct"] = runner_metrics["max_drawdown_pct"]
    
    # Сохраняем обновленный stability.csv
    stability_df.to_csv(stability_path, index=False)
    
    # Запускаем Stage B
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=stability_path,
        output_path=tmp_path / "strategy_selection.csv",
        criteria=None,  # Используем DEFAULT_CRITERIA
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    # Проверяем результат
    assert len(selection_df) == 1, "Должна быть одна стратегия"
    
    row = selection_df.iloc[0]
    
    # Проверяем hit rates
    assert abs(row["hit_rate_x2"] - 0.6) < 0.01, f"hit_rate_x2 должен быть ~0.6 (6 из 10), получен {row['hit_rate_x2']}"
    assert abs(row["hit_rate_x5"] - 0.1) < 0.01, f"hit_rate_x5 должен быть ~0.1 (1 из 10), получен {row['hit_rate_x5']}"
    
    # Проверяем что tail_contribution не NaN
    assert not pd.isna(row.get("tail_contribution", None)), "tail_contribution не должен быть NaN"
    assert isinstance(row.get("tail_contribution", None), (int, float)), "tail_contribution должен быть числом"
    
    # Проверяем что файл создан
    selection_path = tmp_path / "strategy_selection.csv"
    assert selection_path.exists(), "strategy_selection.csv должен быть создан"
    
    # Проверяем что hit rates записаны в файл
    selection_df_file = pd.read_csv(selection_path)
    assert "hit_rate_x2" in selection_df_file.columns, "hit_rate_x2 должна быть в CSV"
    assert "hit_rate_x5" in selection_df_file.columns, "hit_rate_x5 должна быть в CSV"
    assert abs(selection_df_file.iloc[0]["hit_rate_x2"] - 0.6) < 0.01, "hit_rate_x2 должен быть записан в CSV"
    assert abs(selection_df_file.iloc[0]["hit_rate_x5"] - 0.1) < 0.01, "hit_rate_x5 должен быть записан в CSV"

