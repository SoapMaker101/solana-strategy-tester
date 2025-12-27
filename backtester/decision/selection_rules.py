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
# ⚠️ LEGACY: Это baseline критерии, но не canonical V3. См. DEFAULT_RUNNER_CRITERIA_V3.
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

# Runner критерии v2 (BC-совместимость для тестов) - LEGACY FALLBACK
# Использует V3 метрики: hit_rate_x4, tail_pnl_share, non_tail_pnl_share
# Пороги из тестов: hit_rate_x4 >= 0.10, tail_pnl_share >= 0.30,
# non_tail_pnl_share >= -0.20, max_drawdown_pct >= -0.60
# ⚠️ ВАЖНО: Это LEGACY BC-константа для обратной совместимости со старыми тестами.
# ⚠️ НЕ ИСПОЛЬЗУЙТЕ для новых разработок - используйте DEFAULT_RUNNER_CRITERIA_V3 (canonical).
# Проверки hit_rate_x4/tail_pnl_share/non_tail_pnl_share должны быть добавлены в check_strategy_criteria.
# Пока используем существующие поля SelectionCriteria с похожими значениями.
DEFAULT_RUNNER_CRITERIA_V2 = SelectionCriteria(
    # RR/RRD критерии не используются для Runner
    min_survival_rate=0.0,
    max_pnl_variance=float('inf'),
    min_worst_window_pnl=-float('inf'),
    min_median_window_pnl=-float('inf'),
    min_windows=1,
    # Runner критерии v2 (BC: используем существующие поля для совместимости)
    # Фактические проверки hit_rate_x4/tail_pnl_share/non_tail_pnl_share требуют расширения SelectionCriteria
    min_hit_rate_x2=None,  # V2 использует hit_rate_x4 (не поддерживается в текущем SelectionCriteria)
    min_hit_rate_x5=None,  # V2 не требует x5
    min_p90_hold_days=None,
    max_p90_hold_days=None,
    min_tail_contribution=0.30,  # BC: min_tail_pnl_share >= 0.30 (используем tail_contribution как прокси)
    max_tail_contribution=None,
    max_drawdown_pct=-0.60,  # Максимальная просадка не более 60%
)

# Runner критерии v3 (CANONICAL - используйте это для новых разработок)
# ⭐ КАНОНИЧЕСКИЕ критерии для Stage B (v1.9+).
# Использует V3 метрики: hit_rate_x4, tail_pnl_share, non_tail_pnl_share
# Пороги (canonical): 
#   - min_hit_rate_x4 = 0.15 (15% сделок должны достичь x4)
#   - min_tail_pnl_share = 0.80 (минимум 80% PnL от tail сделок)
#   - min_total_realized_pnl_sol = 0.0 (не теряем деньги)
#   - max_drawdown_pct = -0.72 (максимальная просадка не более 72%)
#   - max_p90_hold_days = None (не ограничиваем время удержания)
#
# ⚠️ ВАЖНО: 
# - Это CANONICAL критерии для Stage B по умолчанию
# - V2 - legacy fallback только для старых тестов
# - V1 - legacy для специфичных конфигураций (fixed/1%/exposure=0.95/100 pos/no reset)
# 
# Примечание: SelectionCriteria пока не поддерживает hit_rate_x4/tail_pnl_share напрямую,
# поэтому проверки выполняются в check_strategy_criteria через специальную логику V2/V3.
# Это будет обновлено в будущих версиях.
DEFAULT_RUNNER_CRITERIA_V3 = DEFAULT_RUNNER_CRITERIA_V2  # TODO: создать отдельную константу с canonical значениями
# ⚠️ TEMPORARY: V3 пока использует V2 как алиас, но логика в check_strategy_criteria различает их
# Canonical значения V3 (для справки):
#   - hit_rate_x4 >= 0.15
#   - tail_pnl_share >= 0.80
#   - non_tail_pnl_share >= -0.20 (fallback)
#   - max_drawdown_pct >= -0.72
#   - min_total_realized_pnl_sol >= 0.0 (проверяется отдельно)

# ⭐ CANONICAL DEFAULT для Stage B (v1.9+)
# По умолчанию Stage B должен использовать V3 логику (canonical).
# V2 - legacy fallback только для старых тестов.
# Примечание: В текущей реализации V3 использует V2 как алиас, но логика в check_strategy_criteria
# различает их через разные пороги (TODO: явно разделить V2 и V3 логику с canonical порогами 0.15/0.80).











