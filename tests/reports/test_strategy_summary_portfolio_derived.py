"""
Тесты для проверки что strategy_summary считается ТОЛЬКО из portfolio_positions.csv.

T2: generate_strategy_summary считается из portfolio_positions
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from backtester.domain.portfolio import PortfolioResult, PortfolioStats
from main import generate_strategy_summary
from backtester.infrastructure.reporter import Reporter


def test_strategy_summary_from_portfolio_positions(tmp_path):
    """
    Тест: strategy_summary считается только из portfolio_positions.csv.
    
    Создаем искусственный portfolio_positions.csv с 3 позициями:
    - pnl_sol: +1.0, -0.5, +0.2
    - fees_total_sol: 0.1, 0.05, 0.02
    - hold_minutes: 10, 20, 30
    - max_xn: 2.1, 1.2, 5.2
    - reset flags: 1 triggered, 1 closed_by_reset, 1 без ресета
    """
    # Создаем portfolio_positions.csv вручную
    positions_data = {
        "strategy": ["test_strategy", "test_strategy", "test_strategy"],
        "signal_id": ["sig1", "sig2", "sig3"],
        "contract_address": ["TOKEN1", "TOKEN2", "TOKEN3"],
        "entry_time": [
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
            datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc).isoformat(),
            datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc).isoformat(),
        ],
        "exit_time": [
            datetime(2024, 1, 1, 12, 10, 0, tzinfo=timezone.utc).isoformat(),
            datetime(2024, 1, 1, 13, 20, 0, tzinfo=timezone.utc).isoformat(),
            datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc).isoformat(),
        ],
        "status": ["closed", "closed", "closed"],
        "size": [1.0, 1.0, 1.0],
        "pnl_sol": [1.0, -0.5, 0.2],
        "fees_total_sol": [0.1, 0.05, 0.02],
        "exec_entry_price": [1.0, 1.0, 1.0],
        "exec_exit_price": [2.1, 1.2, 5.2],
        "raw_entry_price": [0.98, 0.98, 0.98],
        "raw_exit_price": [2.05, 1.18, 5.1],
        "closed_by_reset": [False, True, False],
        "triggered_portfolio_reset": [True, False, False],
        "reset_reason": ["profit", "profit", "none"],
        "hold_minutes": [10, 20, 30],
        "max_xn_reached": [2.1, 1.2, 5.2],
        "hit_x2": [True, False, True],
        "hit_x5": [False, False, True],
    }
    
    positions_df = pd.DataFrame(positions_data)
    positions_path = tmp_path / "portfolio_positions.csv"
    positions_df.to_csv(positions_path, index=False)
    
    # Создаем portfolio_results для передачи initial/final balance
    portfolio_result = PortfolioResult(
        positions=[],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=10.7,  # 10.0 + 0.7 (pnl_net)
            total_return_pct=0.07,
            max_drawdown_pct=0.0,
            trades_executed=3,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
        )
    )
    
    portfolio_results = {"test_strategy": portfolio_result}
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Вызываем generate_strategy_summary
    generate_strategy_summary(
        results_by_strategy={},  # Пустой - не используется
        portfolio_results=portfolio_results,
        output_dir=tmp_path,
        reporter=reporter
    )
    
    # Проверяем результат
    summary_path = tmp_path / "strategy_summary.csv"
    assert summary_path.exists(), "strategy_summary.csv должен быть создан"
    
    df = pd.read_csv(summary_path)
    assert len(df) == 1, "Должна быть одна стратегия"
    
    row = df.iloc[0]
    
    # Проверяем счетчики
    assert row["positions_total"] == 3, f"positions_total должен быть 3, получен {row['positions_total']}"
    assert row["positions_closed"] == 3, f"positions_closed должен быть 3, получен {row['positions_closed']}"
    assert row["total_trades"] == 3, f"total_trades должен быть 3, получен {row['total_trades']}"
    
    # Проверяем reset counts
    assert row["closed_by_reset_count"] == 1, f"closed_by_reset_count должен быть 1, получен {row['closed_by_reset_count']}"
    assert row["triggered_portfolio_reset_count"] == 1, f"triggered_portfolio_reset_count должен быть 1, получен {row['triggered_portfolio_reset_count']}"
    assert row["profit_reset_closed_count"] == 2, f"profit_reset_closed_count должен быть 2, получен {row['profit_reset_closed_count']}"
    
    # Проверяем PnL в SOL
    assert abs(row["strategy_total_pnl_sol"] - 0.7) < 0.001, f"strategy_total_pnl_sol должен быть ~0.7, получен {row['strategy_total_pnl_sol']}"
    assert abs(row["fees_total_sol"] - 0.17) < 0.001, f"fees_total_sol должен быть ~0.17, получен {row['fees_total_sol']}"
    assert abs(row["pnl_net_sol"] - 0.53) < 0.001, f"pnl_net_sol должен быть ~0.53, получен {row['pnl_net_sol']}"
    
    # Проверяем статистику PnL
    assert abs(row["avg_pnl_sol"] - 0.233) < 0.01, f"avg_pnl_sol должен быть ~0.233, получен {row['avg_pnl_sol']}"
    assert abs(row["median_pnl_sol"] - 0.2) < 0.001, f"median_pnl_sol должен быть ~0.2, получен {row['median_pnl_sol']}"
    assert abs(row["best_trade_pnl_sol"] - 1.0) < 0.001, f"best_trade_pnl_sol должен быть 1.0, получен {row['best_trade_pnl_sol']}"
    assert abs(row["worst_trade_pnl_sol"] - (-0.5)) < 0.001, f"worst_trade_pnl_sol должен быть -0.5, получен {row['worst_trade_pnl_sol']}"
    
    # Проверяем hit rates
    assert abs(row["hit_rate_x2"] - 2/3) < 0.001, f"hit_rate_x2 должен быть ~0.667, получен {row['hit_rate_x2']}"
    assert abs(row["hit_rate_x5"] - 1/3) < 0.001, f"hit_rate_x5 должен быть ~0.333, получен {row['hit_rate_x5']}"
    
    # Проверяем hold
    # pandas quantile(0.9) делает линейную интерполяцию: для [10,20,30] p90 = 28
    assert abs(row["p90_hold_minutes"] - 28) < 0.1, f"p90_hold_minutes должен быть ~28 (pandas quantile интерполяция), получен {row['p90_hold_minutes']}"
    assert abs(row["avg_hold_minutes"] - 20) < 0.1, f"avg_hold_minutes должен быть ~20, получен {row['avg_hold_minutes']}"
    assert abs(row["p50_hold_minutes"] - 20) < 0.1, f"p50_hold_minutes должен быть ~20, получен {row['p50_hold_minutes']}"
    
    # Проверяем return
    assert abs(row["final_balance_sol"] - 10.7) < 0.001, f"final_balance_sol должен быть ~10.7, получен {row['final_balance_sol']}"
    assert abs(row["portfolio_return_pct"] - 0.07) < 0.001, f"portfolio_return_pct должен быть ~0.07, получен {row['portfolio_return_pct']}"

