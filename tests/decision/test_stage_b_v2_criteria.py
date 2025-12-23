# tests/decision/test_stage_b_v2_criteria.py
"""
Тесты для проверки критериев V2 в Stage B.

Проверяет, что Stage B v2 использует tail_pnl_share вместо tail_contribution.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile

from backtester.decision.strategy_selector import (
    select_strategies,
    is_runner_strategy,
)
from backtester.decision.selection_rules import DEFAULT_RUNNER_CRITERIA_V2


def test_stage_b_v2_uses_tail_pnl_share():
    """
    Тест: критерии V2 используют tail_pnl_share.
    
    Дано:
    - Strategy_A: hit_rate_x4=0.2, tail_pnl_share=0.7 → проходит
    - Strategy_B: hit_rate_x4=0.2, tail_pnl_share=0.1 → не проходит
    
    Проверяем:
    - Passed/Rejected корректны
    - В причинах reject фигурирует tail_pnl_share, а не tail_contribution
    """
    # Создаем stability CSV с 2 стратегиями
    stability_data = [
        {
            "strategy": "Runner_A",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            "hit_rate_x4": 0.2,
            "tail_pnl_share": 0.7,  # Выше минимума 0.3
            "non_tail_pnl_share": 0.3,
            "max_drawdown_pct": -0.3,
        },
        {
            "strategy": "Runner_B",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            "hit_rate_x4": 0.2,
            "tail_pnl_share": 0.1,  # Ниже минимума 0.3
            "non_tail_pnl_share": 0.9,
            "max_drawdown_pct": -0.3,
        },
    ]
    
    stability_df = pd.DataFrame(stability_data)
    
    # Применяем критерии V2
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,  # Используем V2 для всех (но проверяем только Runner)
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    # Проверяем результаты
    strategy_a = selection_df[selection_df["strategy"] == "Runner_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Runner_B"].iloc[0]
    
    # Strategy_A должна пройти (tail_pnl_share=0.7 >= 0.3)
    assert strategy_a["passed"] == True, "Strategy_A должна пройти"
    
    # Strategy_B должна быть отклонена (tail_pnl_share=0.1 < 0.3)
    assert strategy_b["passed"] == False, "Strategy_B должна быть отклонена"
    
    # Проверяем, что в причинах отклонения фигурирует tail_pnl_share
    failed_reasons = strategy_b["failed_reasons"]
    assert isinstance(failed_reasons, list), "failed_reasons должен быть списком"
    assert len(failed_reasons) > 0, "Должна быть хотя бы одна причина отклонения"
    
    # Проверяем, что причина содержит tail_pnl_share
    tail_pnl_share_reason = any("tail_pnl_share" in reason for reason in failed_reasons)
    assert tail_pnl_share_reason, f"В причинах отклонения должен быть tail_pnl_share, получены: {failed_reasons}"
    
    # Проверяем, что НЕ используется tail_contribution в причинах
    tail_contribution_reason = any("tail_contribution" in reason for reason in failed_reasons)
    assert not tail_contribution_reason, f"В причинах отклонения НЕ должен быть tail_contribution, получены: {failed_reasons}"


def test_stage_b_v2_hit_rate_x4_check():
    """
    Тест: критерии V2 проверяют hit_rate_x4.
    
    Дано:
    - Strategy_A: hit_rate_x4=0.15 (выше минимума 0.10) → проходит
    - Strategy_B: hit_rate_x4=0.05 (ниже минимума 0.10) → не проходит
    """
    stability_data = [
        {
            "strategy": "Runner_A",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            "hit_rate_x4": 0.15,  # Выше минимума 0.10
            "tail_pnl_share": 0.5,
            "non_tail_pnl_share": 0.5,
            "max_drawdown_pct": -0.3,
        },
        {
            "strategy": "Runner_B",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            "hit_rate_x4": 0.05,  # Ниже минимума 0.10
            "tail_pnl_share": 0.5,
            "non_tail_pnl_share": 0.5,
            "max_drawdown_pct": -0.3,
        },
    ]
    
    stability_df = pd.DataFrame(stability_data)
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Runner_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Runner_B"].iloc[0]
    
    assert strategy_a["passed"] == True, "Strategy_A должна пройти"
    assert strategy_b["passed"] == False, "Strategy_B должна быть отклонена"
    
    # Проверяем, что причина отклонения содержит hit_rate_x4
    failed_reasons = strategy_b["failed_reasons"]
    hit_rate_x4_reason = any("hit_rate_x4" in reason for reason in failed_reasons)
    assert hit_rate_x4_reason, f"В причинах отклонения должен быть hit_rate_x4, получены: {failed_reasons}"


def test_stage_b_v2_non_tail_pnl_share_check():
    """
    Тест: критерии V2 проверяют non_tail_pnl_share.
    
    Дано:
    - Strategy_A: non_tail_pnl_share=-0.1 (выше минимума -0.2) → проходит
    - Strategy_B: non_tail_pnl_share=-0.3 (ниже минимума -0.2) → не проходит
    """
    stability_data = [
        {
            "strategy": "Runner_A",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            "hit_rate_x4": 0.2,
            "tail_pnl_share": 0.5,
            "non_tail_pnl_share": -0.1,  # Выше минимума -0.2
            "max_drawdown_pct": -0.3,
        },
        {
            "strategy": "Runner_B",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            "hit_rate_x4": 0.2,
            "tail_pnl_share": 0.5,
            "non_tail_pnl_share": -0.3,  # Ниже минимума -0.2 (больше leak)
            "max_drawdown_pct": -0.3,
        },
    ]
    
    stability_df = pd.DataFrame(stability_data)
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Runner_A"].iloc[0]
    strategy_b = selection_df[selection_df["strategy"] == "Runner_B"].iloc[0]
    
    assert strategy_a["passed"] == True, "Strategy_A должна пройти"
    assert strategy_b["passed"] == False, "Strategy_B должна быть отклонена"
    
    # Проверяем, что причина отклонения содержит non_tail_pnl_share
    failed_reasons = strategy_b["failed_reasons"]
    non_tail_reason = any("non_tail_pnl_share" in reason for reason in failed_reasons)
    assert non_tail_reason, f"В причинах отклонения должен быть non_tail_pnl_share, получены: {failed_reasons}"


def test_stage_b_v2_does_not_require_v1_fields():
    """
    Тест: V2 не требует hit_rate_x2/x5/p90_hold_days/tail_contribution.
    
    Дано:
    - Strategy_A: валидные V2 метрики, но нет V1 полей (hit_rate_x2, hit_rate_x5, p90_hold_days, tail_contribution)
    
    Ожидаем:
    - Strategy_A проходит по V2 метрикам
    - В failed_reasons НЕ содержится hit_rate_x2/hit_rate_x5/p90_hold_days/tail_contribution
    """
    stability_data = [
        {
            "strategy": "Runner_A",
            "split_count": 3,
            "survival_rate": 1.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_total": 3,
            "windows_positive": 3,
            # V2 метрики - валидные
            "hit_rate_x4": 0.15,  # Выше минимума 0.10
            "tail_pnl_share": 0.5,  # Выше минимума 0.3
            "non_tail_pnl_share": 0.5,  # Выше минимума -0.2
            "max_drawdown_pct": -0.3,  # Выше минимума -0.6
            # V1 поля отсутствуют (не должны требоваться)
            # hit_rate_x2 - отсутствует
            # hit_rate_x5 - отсутствует
            # p90_hold_days - отсутствует
            # tail_contribution - отсутствует
        },
    ]
    
    stability_df = pd.DataFrame(stability_data)
    
    selection_df = select_strategies(
        stability_df=stability_df,
        criteria=DEFAULT_RUNNER_CRITERIA_V2,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V2,
    )
    
    strategy_a = selection_df[selection_df["strategy"] == "Runner_A"].iloc[0]
    
    # Strategy_A должна пройти (все V2 метрики валидны)
    assert strategy_a["passed"] == True, f"Strategy_A должна пройти, но failed_reasons: {strategy_a['failed_reasons']}"
    
    # Проверяем, что в причинах отклонения НЕТ V1 полей
    failed_reasons = strategy_a.get("failed_reasons", [])
    if isinstance(failed_reasons, list) and len(failed_reasons) > 0:
        v1_fields_in_reasons = any(
            field in reason 
            for reason in failed_reasons 
            for field in ["hit_rate_x2", "hit_rate_x5", "p90_hold_days", "tail_contribution"]
        )
        assert not v1_fields_in_reasons, \
            f"В причинах отклонения НЕ должно быть V1 полей, получены: {failed_reasons}"

