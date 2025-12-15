"""
Unit tests for selection_rules module
"""
import pytest
from dataclasses import FrozenInstanceError

from backtester.decision.selection_rules import SelectionCriteria, DEFAULT_CRITERIA


def test_criteria_immutable():
    """Проверяет, что критерии неизменяемы (frozen=True)"""
    criteria = SelectionCriteria(
        min_survival_rate=0.5,
        max_pnl_variance=0.05,
        min_worst_window_pnl=-0.1,
        min_median_window_pnl=0.0,
        min_windows=2,
    )
    
    # Попытка изменить поле должна вызвать FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        criteria.min_survival_rate = 0.6


def test_default_criteria_values():
    """Проверяет значения DEFAULT_CRITERIA"""
    assert DEFAULT_CRITERIA.min_survival_rate == 0.6
    assert DEFAULT_CRITERIA.max_pnl_variance == 0.10
    assert DEFAULT_CRITERIA.min_worst_window_pnl == -0.20
    assert DEFAULT_CRITERIA.min_median_window_pnl == 0.0
    assert DEFAULT_CRITERIA.min_windows == 3


def test_criteria_creation():
    """Проверяет создание критериев с разными значениями"""
    criteria = SelectionCriteria(
        min_survival_rate=0.8,
        max_pnl_variance=0.05,
        min_worst_window_pnl=-0.15,
        min_median_window_pnl=0.05,
        min_windows=5,
    )
    
    assert criteria.min_survival_rate == 0.8
    assert criteria.max_pnl_variance == 0.05
    assert criteria.min_worst_window_pnl == -0.15
    assert criteria.min_median_window_pnl == 0.05
    assert criteria.min_windows == 5


def test_criteria_equality():
    """Проверяет сравнение критериев"""
    criteria1 = SelectionCriteria(
        min_survival_rate=0.5,
        max_pnl_variance=0.05,
        min_worst_window_pnl=-0.1,
        min_median_window_pnl=0.0,
        min_windows=2,
    )
    
    criteria2 = SelectionCriteria(
        min_survival_rate=0.5,
        max_pnl_variance=0.05,
        min_worst_window_pnl=-0.1,
        min_median_window_pnl=0.0,
        min_windows=2,
    )
    
    criteria3 = SelectionCriteria(
        min_survival_rate=0.6,  # Другое значение
        max_pnl_variance=0.05,
        min_worst_window_pnl=-0.1,
        min_median_window_pnl=0.0,
        min_windows=2,
    )
    
    assert criteria1 == criteria2
    assert criteria1 != criteria3


