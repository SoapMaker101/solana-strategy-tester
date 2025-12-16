# backtester/decision/selection_rules.py
# Formalized selection criteria for strategy filtering

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionCriteria:
    """
    Неизменяемые критерии отбора стратегий.
    
    Все критерии применяются ко всем стратегиям одинаково.
    Не зависят от данных.
    Легко читаются и проверяются.
    """
    min_survival_rate: float
    """Минимальный survival_rate (доля окон с положительным pnl)."""
    
    max_pnl_variance: float
    """Максимальная допустимая дисперсия pnl по окнам."""
    
    min_worst_window_pnl: float
    """Минимальный worst_window_pnl (наихудший результат в окне)."""
    
    min_median_window_pnl: float
    """Минимальный median_window_pnl (медианный результат)."""
    
    min_windows: int
    """Минимальное количество окон для анализа (windows_total)."""


# Базовые критерии (DEFAULT)
# ⚠️ ВАЖНО: Эти значения фиксируются как baseline и могут меняться вручную позже.
# Cursor НЕ ПОДБИРАЕТ эти значения.
DEFAULT_CRITERIA = SelectionCriteria(
    min_survival_rate=0.6,
    max_pnl_variance=0.10,
    min_worst_window_pnl=-0.20,
    min_median_window_pnl=0.0,
    min_windows=3,
)



