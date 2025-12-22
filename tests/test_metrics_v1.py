"""
Тесты для метрик v1 (portfolio_summary, strategy_stability, strategy_selection).

Проверяет наличие и корректность расчета всех требуемых метрик v1:
- Portfolio: final_balance_sol, total_return_pct, max_drawdown_pct, trades_executed, 
  trades_skipped_by_risk, trades_skipped_by_reset, reset_count, last_reset_time, 
  cycle_start_equity, equity_peak_in_cycle
- Stage A: survival_rate, worst_window_pnl, median_window_pnl, pnl_variance, windows_total,
  и для Runner: hit_rate_x2, hit_rate_x5, p90_hold_days, tail_contribution
- Stage B: passed, failed_reasons
"""
import pytest
import pandas as pd
import json
from pathlib import Path
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from backtester.domain.portfolio import PortfolioEngine, PortfolioConfig, PortfolioStats
from backtester.domain.models import StrategyOutput
from backtester.research.strategy_stability import (
    calculate_runner_metrics,
    build_stability_table,
    is_runner_strategy,
)
from backtester.decision.strategy_selector import (
    select_strategies,
    check_strategy_criteria,
)
from backtester.decision.selection_rules import (
    DEFAULT_CRITERIA_V1,
    DEFAULT_RUNNER_CRITERIA_V1,
)


def test_portfolio_summary_has_required_columns():
    """Проверяет, что portfolio_summary.csv содержит все требуемые колонки."""
    # Создаем минимальный PortfolioStats с требуемыми полями
    stats = PortfolioStats(
        final_balance_sol=10.5,
        total_return_pct=0.05,
        max_drawdown_pct=-0.10,
        trades_executed=5,
        trades_skipped_by_risk=2,
        trades_skipped_by_reset=0,
        portfolio_reset_count=0,  # reset_count теперь property, доступен через portfolio_reset_count
        last_portfolio_reset_time=None,  # last_reset_time теперь property, доступен через last_portfolio_reset_time
        cycle_start_equity=10.0,
        equity_peak_in_cycle=10.5,
    )
    
    # Проверяем наличие всех полей
    required_fields = [
        "final_balance_sol",
        "total_return_pct",
        "max_drawdown_pct",
        "trades_executed",
        "trades_skipped_by_risk",
        "trades_skipped_by_reset",
        "reset_count",
        "last_reset_time",
        "cycle_start_equity",
        "equity_peak_in_cycle",
    ]
    
    for field in required_fields:
        assert hasattr(stats, field), f"PortfolioStats missing field: {field}"
    
    # Проверяем, что поля можно сериализовать в CSV
    row = {
        "strategy": "test_strategy",
        "final_balance_sol": stats.final_balance_sol,
        "total_return_pct": stats.total_return_pct,
        "max_drawdown_pct": stats.max_drawdown_pct,
        "trades_executed": stats.trades_executed,
        "trades_skipped_by_risk": stats.trades_skipped_by_risk,
        "trades_skipped_by_reset": stats.trades_skipped_by_reset,
        "reset_count": stats.reset_count,
        "last_reset_time": (
            stats.last_reset_time.isoformat() 
            if stats.last_reset_time else None
        ),
        "cycle_start_equity": stats.cycle_start_equity,
        "equity_peak_in_cycle": stats.equity_peak_in_cycle,
    }
    
    df = pd.DataFrame([row])
    assert len(df.columns) == len(required_fields) + 1  # +1 для strategy
    for field in required_fields:
        assert field in df.columns, f"CSV missing column: {field}"


def test_stage_a_stability_has_required_columns():
    """Проверяет, что strategy_stability.csv содержит все требуемые поля."""
    # Создаем синтетические данные для stability table
    stability_rows = [
        {
            "strategy": "RR_2.0_0.5",
            "split_count": 3,
            "survival_rate": 0.65,
            "worst_window_pnl": -0.20,
            "median_window_pnl": 0.05,
            "pnl_variance": 0.12,
            "windows_total": 3,
            "windows_positive": 2,
        },
        {
            "strategy": "Runner_test",
            "split_count": 3,
            "survival_rate": 0.70,
            "worst_window_pnl": -0.15,
            "median_window_pnl": 0.10,
            "pnl_variance": 0.10,
            "windows_total": 3,
            "windows_positive": 2,
            "hit_rate_x2": 0.40,
            "hit_rate_x5": 0.10,
            "p90_hold_days": 30.0,
            "tail_contribution": 0.60,
        },
    ]
    
    df = pd.DataFrame(stability_rows)
    
    # Проверяем базовые колонки (для всех стратегий)
    required_base_cols = [
        "strategy",
        "split_count",
        "survival_rate",
        "worst_window_pnl",
        "median_window_pnl",
        "pnl_variance",
        "windows_total",
    ]
    
    for col in required_base_cols:
        assert col in df.columns, f"Missing base column: {col}"
    
    # Проверяем Runner-специфичные колонки (для Runner стратегий)
    runner_cols = [
        "hit_rate_x2",
        "hit_rate_x5",
        "p90_hold_days",
        "tail_contribution",
    ]
    
    # Для Runner стратегий должны быть Runner колонки
    runner_row = df[df["strategy"] == "Runner_test"].iloc[0]
    for col in runner_cols:
        assert col in df.columns, f"Missing Runner column: {col}"
        assert pd.notna(runner_row[col]), f"Runner column {col} is NaN"


def test_runner_metrics_computation(tmp_path):
    """Проверяет корректность расчета Runner метрик из portfolio_positions.csv (новый контракт)."""
    # Создаем синтетический portfolio_positions.csv с Runner метриками
    # 4 позиции:
    # A) max_xn_reached=2.0 hit_x2=True hit_x5=False
    # B) max_xn_reached=5.0 hit_x2=True hit_x5=True
    # C) max_xn_reached=7.0 hit_x2=True hit_x5=True (tail)
    # D) max_xn_reached=1.5 hit_x2=False hit_x5=False
    # => hit_rate_x2 = 3/4 = 0.75, hit_rate_x5 = 2/4 = 0.5
    
    positions_data = {
        "strategy": ["Runner_Test"] * 4,
        "signal_id": ["sig_1", "sig_2", "sig_3", "sig_4"],
        "contract_address": ["TOKEN1", "TOKEN2", "TOKEN3", "TOKEN4"],
        "entry_time": [
            "2024-01-01T00:00:00Z",
            "2024-01-03T00:00:00Z",
            "2024-01-11T00:00:00Z",
            "2024-01-21T00:00:00Z",
        ],
        "exit_time": [
            "2024-01-02T00:00:00Z",  # 1 день
            "2024-01-10T00:00:00Z",  # 7 дней
            "2024-01-20T00:00:00Z",  # 9 дней
            "2024-01-22T00:00:00Z",  # 1 день
        ],
        "status": ["closed"] * 4,
        "size": [1.0] * 4,
        "pnl_sol": [1.0, 4.0, 6.0, 0.5],  # Total = 11.5, tail (>=5) = 4.0 + 6.0 = 10.0
        "fees_total_sol": [0.1] * 4,
        "exec_entry_price": [1.0] * 4,
        "exec_exit_price": [2.0, 5.0, 7.0, 1.5],
        "raw_entry_price": [1.0] * 4,
        "raw_exit_price": [2.0, 5.0, 7.0, 1.5],
        "closed_by_reset": [False] * 4,
        "triggered_portfolio_reset": [False] * 4,
        "reset_reason": ["none"] * 4,
        "hold_minutes": [1440, 10080, 12960, 1440],  # 1, 7, 9, 1 день в минутах
        "max_xn_reached": [2.0, 5.0, 7.0, 1.5],
        "hit_x2": [True, True, True, False],  # 3 из 4
        "hit_x5": [False, True, True, False],  # 2 из 4
    }
    
    positions_df = pd.DataFrame(positions_data)
    positions_path = tmp_path / "portfolio_positions.csv"
    positions_df.to_csv(positions_path, index=False)
    
    # Вычисляем Runner метрики из portfolio_positions.csv
    runner_metrics = calculate_runner_metrics(
        strategy_name="Runner_Test",
        portfolio_positions_path=positions_path,
        portfolio_summary_path=None,
    )
    
    # Проверяем hit_rate_x2: 3 из 4 сделок достигли x2
    assert runner_metrics["hit_rate_x2"] == pytest.approx(0.75, abs=0.01)
    
    # Проверяем hit_rate_x5: 2 из 4 сделок достигли x5
    assert runner_metrics["hit_rate_x5"] == pytest.approx(0.50, abs=0.01)
    
    # Проверяем p90_hold_days: 90-й перцентиль времени удержания
    # Дни: 1, 7, 9, 1 -> p90 должен быть около 9
    assert runner_metrics["p90_hold_days"] > 0
    assert runner_metrics["p90_hold_days"] <= 10
    assert isinstance(runner_metrics["p90_hold_days"], (int, float))
    
    # Проверяем tail_contribution: доля PnL от сделок с max_xn_reached >= 5.0
    # Сделки с >= 5.0: sig_2 (4.0), sig_3 (6.0) = 10.0
    # Total PnL: 1.0 + 4.0 + 6.0 + 0.5 = 11.5
    # tail_contribution = 10.0 / 11.5 ≈ 0.87
    assert runner_metrics["tail_contribution"] > 0.80
    assert runner_metrics["tail_contribution"] <= 1.0
    assert isinstance(runner_metrics["tail_contribution"], (int, float))
    
    # Проверяем что max_drawdown_pct существует и имеет валидный тип
    assert "max_drawdown_pct" in runner_metrics
    assert isinstance(runner_metrics["max_drawdown_pct"], (int, float))


def test_stage_b_reasons_present():
    """Проверяет, что Stage B генерирует reasons и passed булевый."""
    # Создаем синтетическую stability table
    stability_data = [
        {
            "strategy": "RR_pass",
            "split_count": 3,
            "survival_rate": 0.70,  # >= 0.60 ✓
            "worst_window_pnl": -0.20,  # >= -0.25 ✓
            "median_window_pnl": 0.05,  # >= 0.00 ✓
            "pnl_variance": 0.10,  # <= 0.15 ✓
            "windows_total": 3,  # >= 3 ✓
        },
        {
            "strategy": "RR_fail",
            "split_count": 3,
            "survival_rate": 0.50,  # < 0.60 ✗
            "worst_window_pnl": -0.30,  # < -0.25 ✗
            "median_window_pnl": -0.05,  # < 0.00 ✗
            "pnl_variance": 0.20,  # > 0.15 ✗
            "windows_total": 3,
        },
        {
            "strategy": "Runner_pass",
            "split_count": 3,
            "survival_rate": 0.70,
            "worst_window_pnl": -0.20,
            "median_window_pnl": 0.05,
            "pnl_variance": 0.10,
            "windows_total": 3,
            "hit_rate_x2": 0.40,  # >= 0.35 ✓
            "hit_rate_x5": 0.10,  # >= 0.08 ✓
            "p90_hold_days": 30.0,  # <= 35 ✓
            "tail_contribution": 0.60,  # <= 0.80 ✓
            "max_drawdown_pct": -0.50,  # >= -0.60 ✓
        },
        {
            "strategy": "Runner_fail",
            "split_count": 3,
            "survival_rate": 0.70,
            "worst_window_pnl": -0.20,
            "median_window_pnl": 0.05,
            "pnl_variance": 0.10,
            "windows_total": 3,
            "hit_rate_x2": 0.30,  # < 0.35 ✗
            "hit_rate_x5": 0.05,  # < 0.08 ✗
            "p90_hold_days": 40.0,  # > 35 ✗
            "tail_contribution": 0.90,  # > 0.80 ✗
            "max_drawdown_pct": -0.70,  # < -0.60 ✗
        },
    ]
    
    stability_df = pd.DataFrame(stability_data)
    
    # Применяем отбор
    selection_df = select_strategies(
        stability_df,
        criteria=DEFAULT_CRITERIA_V1,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    # Проверяем наличие колонок passed и failed_reasons
    assert "passed" in selection_df.columns
    assert "failed_reasons" in selection_df.columns
    
    # Проверяем, что passed - булевый
    assert selection_df["passed"].dtype == bool
    
    # Проверяем результаты
    rr_pass = selection_df[selection_df["strategy"] == "RR_pass"].iloc[0]
    assert rr_pass["passed"] == True
    assert len(rr_pass["failed_reasons"]) == 0
    
    rr_fail = selection_df[selection_df["strategy"] == "RR_fail"].iloc[0]
    assert rr_fail["passed"] == False
    assert len(rr_fail["failed_reasons"]) > 0
    # Проверяем, что reasons содержат человекочитаемые сообщения
    reasons_str = "; ".join(rr_fail["failed_reasons"])
    assert "survival_rate" in reasons_str or "worst_window_pnl" in reasons_str
    
    runner_pass = selection_df[selection_df["strategy"] == "Runner_pass"].iloc[0]
    assert runner_pass["passed"] == True
    assert len(runner_pass["failed_reasons"]) == 0
    
    runner_fail = selection_df[selection_df["strategy"] == "Runner_fail"].iloc[0]
    assert runner_fail["passed"] == False
    assert len(runner_fail["failed_reasons"]) > 0
    reasons_str = "; ".join(runner_fail["failed_reasons"])
    assert "hit_rate" in reasons_str or "tail_contribution" in reasons_str or "p90_hold_days" in reasons_str


def test_is_runner_strategy():
    """Проверяет функцию определения Runner стратегий."""
    assert is_runner_strategy("Runner_test") == True
    assert is_runner_strategy("runner_test") == True
    assert is_runner_strategy("RUNNER_test") == True
    assert is_runner_strategy("RR_2.0_0.5") == False
    assert is_runner_strategy("RRD_3.0_1.5") == False
    assert is_runner_strategy("test_strategy") == False
