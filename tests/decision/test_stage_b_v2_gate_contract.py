"""
Guard tests for Decision V2 gate contract.

These tests ensure that V2 criteria are applied only when V2 columns are present,
and that V2 logic correctly rejects strategies with tail_pnl_share < 0.30.
"""
import pytest
import pandas as pd

from backtester.decision.strategy_selector import select_strategies
from backtester.decision.selection_rules import DEFAULT_CRITERIA_V1, DEFAULT_RUNNER_CRITERIA_V2


def test_v2_gate_applies_when_v2_columns_present():
    """Guard: Если есть hit_rate_x4, tail_pnl_share, non_tail_pnl_share → V2 применяется."""
    stability_df = pd.DataFrame({
        "strategy": ["Strategy_A", "Strategy_B"],
        "survival_rate": [1.0, 1.0],
        "pnl_variance": [0.0, 0.0],
        "worst_window_pnl": [0.0, 0.0],
        "median_window_pnl": [0.0, 0.0],
        "windows_total": [3, 3],
        "hit_rate_x4": [0.2, 0.2],  # V2 column
        "tail_pnl_share": [0.7, 0.1],  # V2 column: Strategy_B < 0.30
        "non_tail_pnl_share": [0.3, 0.9],  # V2 column
        "max_drawdown_pct": [-0.3, -0.3],
    })
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Strategy_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Strategy_B"].iloc[0]
    
    # Strategy_A должна пройти (tail_pnl_share=0.7 >= 0.30)
    assert strategy_a["passed"] == True
    
    # Strategy_B должна быть отклонена (tail_pnl_share=0.1 < 0.30)
    assert strategy_b["passed"] == False
    failed_reasons = strategy_b["failed_reasons"]
    assert isinstance(failed_reasons, list)
    assert any("tail_pnl_share" in reason for reason in failed_reasons)


def test_v2_gate_not_applied_when_v2_columns_missing():
    """Guard: Если колонок V2 нет → V2 НЕ применяется."""
    stability_df = pd.DataFrame({
        "strategy": ["Strategy_A", "Strategy_B"],
        "survival_rate": [1.0, 0.5],  # Strategy_B fails V1
        "pnl_variance": [0.0, 0.0],
        "worst_window_pnl": [0.0, 0.0],
        "median_window_pnl": [0.0, 0.0],
        "windows_total": [3, 3],
        # Нет V2 колонок: hit_rate_x4, tail_pnl_share, non_tail_pnl_share
    })
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_CRITERIA_V1,  # V1 criteria
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,  # V2 criteria, но не применятся
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Strategy_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Strategy_B"].iloc[0]
    
    # Strategy_A должна пройти (survival_rate=1.0 >= 0.60)
    assert strategy_a["passed"] == True
    
    # Strategy_B должна быть отклонена по V1 (survival_rate=0.5 < 0.60)
    assert strategy_b["passed"] == False
    failed_reasons = strategy_b["failed_reasons"]
    assert isinstance(failed_reasons, list)
    # Должна быть причина по V1, не по V2
    assert any("survival_rate" in reason for reason in failed_reasons)


def test_v2_gate_hit_rate_x4_check():
    """Guard: V2 проверяет hit_rate_x4 >= 0.10."""
    stability_df = pd.DataFrame({
        "strategy": ["Strategy_A", "Strategy_B"],
        "survival_rate": [1.0, 1.0],
        "pnl_variance": [0.0, 0.0],
        "worst_window_pnl": [0.0, 0.0],
        "median_window_pnl": [0.0, 0.0],
        "windows_total": [3, 3],
        "hit_rate_x4": [0.15, 0.05],  # Strategy_B < 0.10
        "tail_pnl_share": [0.5, 0.5],
        "non_tail_pnl_share": [0.5, 0.5],
        "max_drawdown_pct": [-0.3, -0.3],
    })
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Strategy_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Strategy_B"].iloc[0]
    
    # Strategy_A должна пройти (hit_rate_x4=0.15 >= 0.10)
    assert strategy_a["passed"] == True
    
    # Strategy_B должна быть отклонена (hit_rate_x4=0.05 < 0.10)
    assert strategy_b["passed"] == False
    failed_reasons = strategy_b["failed_reasons"]
    assert isinstance(failed_reasons, list)
    assert any("hit_rate_x4" in reason for reason in failed_reasons)


def test_v2_gate_non_tail_pnl_share_check():
    """Guard: V2 проверяет non_tail_pnl_share >= -0.20."""
    stability_df = pd.DataFrame({
        "strategy": ["Strategy_A", "Strategy_B"],
        "survival_rate": [1.0, 1.0],
        "pnl_variance": [0.0, 0.0],
        "worst_window_pnl": [0.0, 0.0],
        "median_window_pnl": [0.0, 0.0],
        "windows_total": [3, 3],
        "hit_rate_x4": [0.2, 0.2],
        "tail_pnl_share": [0.5, 0.5],
        "non_tail_pnl_share": [-0.1, -0.3],  # Strategy_B < -0.20
        "max_drawdown_pct": [-0.3, -0.3],
    })
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Strategy_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Strategy_B"].iloc[0]
    
    # Strategy_A должна пройти (non_tail_pnl_share=-0.1 >= -0.20)
    assert strategy_a["passed"] == True
    
    # Strategy_B должна быть отклонена (non_tail_pnl_share=-0.3 < -0.20)
    assert strategy_b["passed"] == False
    failed_reasons = strategy_b["failed_reasons"]
    assert isinstance(failed_reasons, list)
    assert any("non_tail_pnl_share" in reason for reason in failed_reasons)

