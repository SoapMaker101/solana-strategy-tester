# backtester/decision/selection_rules.py
# Formalized selection criteria for strategy filtering

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SelectionCriteria:
    """
    Неизменяемые критерии отбора стратегий.
    
    Поддерживает два набора критериев:
    - RR/RRD критерии (survival_rate, variance, worst_window_pnl и т.д.)
    - Runner критерии (hit_rate_x2, hit_rate_x5, tail_contribution и т.д.)
    
    Критерии применяются условно в зависимости от типа стратегии.
    """
    # RR/RRD критерии
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
    
    # Runner критерии
    min_hit_rate_x2: Optional[float] = None
    """Минимальный hit_rate для уровня x2 (доля сделок, достигших x2)."""
    
    min_hit_rate_x5: Optional[float] = None
    """Минимальный hit_rate для уровня x5 (доля сделок, достигших x5)."""
    
    min_p90_hold_days: Optional[float] = None
    """Минимальный 90-й перцентиль времени удержания позиции в днях."""
    
    max_p90_hold_days: Optional[float] = None
    """Максимальный 90-й перцентиль времени удержания позиции в днях."""
    
    min_tail_contribution: Optional[float] = None
    """Минимальная доля PnL от top 5% сделок (tail contribution)."""
    
    max_drawdown_pct: Optional[float] = None
    """Максимальная допустимая просадка по equity curve портфеля (в процентах, отрицательное значение)."""


# Базовые критерии для RR/RRD (DEFAULT)
# ⚠️ ВАЖНО: Эти значения фиксируются как baseline и могут меняться вручную позже.
# Cursor НЕ ПОДБИРАЕТ эти значения.
DEFAULT_CRITERIA = SelectionCriteria(
    min_survival_rate=0.6,
    max_pnl_variance=0.3,
    min_worst_window_pnl=-0.15,
    min_median_window_pnl=0.0,
    min_windows=3,
    # Runner критерии не заданы по умолчанию
    min_hit_rate_x2=None,
    min_hit_rate_x5=None,
    min_p90_hold_days=None,
    max_p90_hold_days=None,
    min_tail_contribution=None,
    max_drawdown_pct=None,
)

# Runner критерии (baseline)
# ⚠️ ВАЖНО: Эти значения фиксируются как baseline для Runner стратегий.
DEFAULT_RUNNER_CRITERIA = SelectionCriteria(
    # RR/RRD критерии не используются для Runner
    min_survival_rate=0.0,
    max_pnl_variance=float('inf'),
    min_worst_window_pnl=-float('inf'),
    min_median_window_pnl=-float('inf'),
    min_windows=1,
    # Runner критерии
    min_hit_rate_x2=0.30,  # 30% сделок должны достичь x2
    min_hit_rate_x5=0.10,  # 10% сделок должны достичь x5
    min_p90_hold_days=None,  # Не ограничиваем минимальное время удержания
    max_p90_hold_days=None,  # Не ограничиваем максимальное время удержания (можно задать, например, 14 дней)
    min_tail_contribution=0.3,  # Минимум 30% PnL от top 5% сделок
    max_drawdown_pct=-0.5,  # Максимальная просадка не более 50%
)









