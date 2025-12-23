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
    
    max_tail_contribution: Optional[float] = None
    """Максимальная допустимая доля PnL от сделок с realized_multiple >= 5x (tail contribution)."""
    
    # Runner критерии v2 (новые метрики для частичных закрытий)
    min_hit_rate_x4: Optional[float] = None
    """Минимальный hit_rate для уровня x4 (tail threshold, доля сделок, достигших x4)."""
    
    min_tail_pnl_share: Optional[float] = None
    """Минимальная доля прибыли от tail-ног (0..1, из realized_tail_pnl_sol / realized_total_pnl_sol)."""
    
    min_non_tail_pnl_share: Optional[float] = None
    """Минимальная доля прибыли от non-tail ног (может быть <0, leak)."""


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
    max_tail_contribution=None,
    max_drawdown_pct=None,
)

# Критерии v1 для Stage A (split_count 3/4/5)
# Пороги из ТЗ: survival_rate >= 0.60, worst_window_pnl >= -0.25, 
# pnl_variance <= 0.15, median_window_pnl >= 0.00
DEFAULT_CRITERIA_V1 = SelectionCriteria(
    min_survival_rate=0.60,
    max_pnl_variance=0.15,
    min_worst_window_pnl=-0.25,
    min_median_window_pnl=0.00,
    min_windows=3,
    # Runner критерии не заданы по умолчанию
    min_hit_rate_x2=None,
    min_hit_rate_x5=None,
    min_p90_hold_days=None,
    max_p90_hold_days=None,
    min_tail_contribution=None,
    max_tail_contribution=None,
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
    max_tail_contribution=None,
    max_drawdown_pct=-0.5,  # Максимальная просадка не более 50%
)

# Runner критерии v1 (для fixed/1%/exposure=0.95/100 pos/no reset)
# Пороги из ТЗ: hit_rate_x2 >= 0.35, hit_rate_x5 >= 0.08, 
# tail_contribution <= 0.80, p90_hold_days <= 35
DEFAULT_RUNNER_CRITERIA_V1 = SelectionCriteria(
    # RR/RRD критерии не используются для Runner
    min_survival_rate=0.0,
    max_pnl_variance=float('inf'),
    min_worst_window_pnl=-float('inf'),
    min_median_window_pnl=-float('inf'),
    min_windows=1,
    # Runner критерии v1
    min_hit_rate_x2=0.35,  # 35% сделок должны достичь x2
    min_hit_rate_x5=0.08,  # 8% сделок должны достичь x5
    min_p90_hold_days=None,  # Не ограничиваем минимальное время удержания
    max_p90_hold_days=35.0,  # Максимум 35 дней (90-й перцентиль)
    min_tail_contribution=None,  # Не ограничиваем минимум
    max_tail_contribution=0.80,  # Максимум 80% PnL от сделок с realized_multiple >= 5x
    max_drawdown_pct=-0.60,  # Максимальная просадка не более 60%
)

# Runner критерии v2 (для частичных закрытий, использует hit_rate_x4 и tail_pnl_share)
# Использует новые метрики: hit_rate_x4 (tail threshold x4), tail_pnl_share (0..1), non_tail_pnl_share
DEFAULT_RUNNER_CRITERIA_V2 = SelectionCriteria(
    # RR/RRD критерии не используются для Runner
    min_survival_rate=0.0,
    max_pnl_variance=float('inf'),
    min_worst_window_pnl=-float('inf'),
    min_median_window_pnl=-float('inf'),
    min_windows=1,
    # Runner критерии v2 - V1 поля явно отключены
    min_hit_rate_x2=None,  # Не используется в v2 (используем hit_rate_x4)
    min_hit_rate_x5=None,  # Не используется в v2 (используем hit_rate_x4)
    min_hit_rate_x4=0.10,  # Минимум 10% сделок должны достичь x4 (tail threshold)
    min_p90_hold_days=None,  # Не используется в v2
    max_p90_hold_days=None,  # Не используется в v2
    min_tail_contribution=None,  # Не используется в v2 (используем tail_pnl_share)
    max_tail_contribution=None,  # Не используется в v2 (используем tail_pnl_share)
    min_tail_pnl_share=0.3,  # Минимум 30% прибыли от tail-ног (x4+)
    min_non_tail_pnl_share=-0.2,  # Минимум -20% (допускаем leak, но не слишком большой)
    max_drawdown_pct=-0.60,  # Максимальная просадка не более 60%
)





