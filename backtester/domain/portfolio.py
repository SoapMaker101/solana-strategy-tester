# backtester/domain/portfolio.py

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional, Union, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from .strategy_trade_blueprint import StrategyTradeBlueprint

from .position import Position as PositionModel

# Type alias for annotations - pyright/basedpyright compatibility fix
# PositionModel is used for constructor calls to ensure correct type resolution
Position = PositionModel  # type: ignore[assignment]
from .execution_model import ExecutionProfileConfig
from .portfolio_events import PortfolioEvent as PortfolioEventModel, PortfolioEventType

# Type alias for annotations - pyright/basedpyright compatibility fix
PortfolioEvent = PortfolioEventModel  # type: ignore[assignment]
from .portfolio_reset import (
    PortfolioState,
    PortfolioResetContext,
    ResetReason,
    apply_portfolio_reset,
)

logger = logging.getLogger(__name__)


@dataclass
class FeeModel:
    """
    Модель комиссий и проскальзывания.
    Все значения в долях (0.1 = 10%).
    
    Поддерживает два режима:
    1. Legacy: slippage_pct применяется одинаково для всех событий
    2. Profiles: reason-based slippage через execution profiles
    """
    swap_fee_pct: float = 0.003       # 0.3%
    lp_fee_pct: float = 0.001         # 0.1%
    slippage_pct: Optional[float] = 0.10  # 10% slippage (legacy, используется если profiles=None)
    network_fee_sol: float = 0.0005   # фикс. комиссия сети в SOL
    profiles: Optional[Dict[str, ExecutionProfileConfig]] = None  # Execution profiles

    def effective_fee_pct(self, notional_sol: float) -> float:
        """
        DEPRECATED: Используется только для обратной совместимости.
        Новая логика применяет slippage к ценам через ExecutionModel.
        
        Считает суммарные издержки как долю от notional_sol.
        Round-trip: вход + выход.
        """
        # Используем slippage_pct для legacy режима
        slippage = self.slippage_pct if self.slippage_pct is not None else 0.10
        # Переменные компоненты (в процентах)
        pct_roundtrip = 2 * (self.swap_fee_pct + self.lp_fee_pct + slippage)
        # Фиксированная сеть в процентах
        network_pct = self.network_fee_sol / notional_sol if notional_sol > 0 else 0.0
        return pct_roundtrip + network_pct


@dataclass
class PortfolioConfig:
    """
    Конфигурация портфеля.
    """
    initial_balance_sol: float = 10.0
    allocation_mode: Literal["fixed", "dynamic"] = "dynamic"
    percent_per_trade: float = 0.1
    max_exposure: float = 0.5
    max_open_positions: int = 10

    fee_model: FeeModel = field(default_factory=FeeModel)
    execution_profile: str = "realistic"  # realistic | stress | custom

    backtest_start: Optional[datetime] = None
    backtest_end: Optional[datetime] = None

    # Profit reset конфигурация (reset по росту equity портфеля)
    profit_reset_enabled: Optional[bool] = None
    profit_reset_multiple: Optional[float] = None  # Множитель для profit reset (например, 2.0 = x2)

    # DEPRECATED: legacy alias для profit reset
    runner_reset_enabled: Optional[bool] = None
    runner_reset_multiple: Optional[float] = None
    
    # Capacity reset конфигурация (v1.6)
    capacity_reset_enabled: bool = True
    capacity_open_ratio_threshold: float = 1.0  # Порог заполненности портфеля (1.0 = 100%)
    capacity_window_type: Literal["time", "signals"] = "time"  # Тип окна: по времени или по количеству сигналов
    capacity_window_size: Union[int, str] = 7  # Размер окна: дни (int) или строка "7d" для time, количество сигналов для signals
    capacity_max_blocked_ratio: float = 0.4  # Максимальная доля отклоненных сигналов за окно (0.4 = 40%)
    capacity_max_avg_hold_days: float = 10.0  # Максимальное среднее время удержания открытых позиций (дни)
    
    # Capacity prune конфигурация (v1.7)
    capacity_reset_mode: Literal["close_all", "prune"] = "close_all"  # Режим capacity reset: close_all (старое поведение) или prune (частичное закрытие)
    prune_fraction: float = 0.5  # Доля кандидатов для закрытия при prune (0.5 = 50%)
    prune_min_hold_days: float = 1.0  # Минимальное время удержания для кандидата (дни)
    prune_max_mcap_usd: float = 20000.0  # Максимальный mcap для кандидата (USD)
    prune_max_current_pnl_pct: float = -0.30  # Максимальный текущий PnL для кандидата (-0.30 = -30%)
    
    # Capacity prune hardening (v1.7.1)
    prune_cooldown_signals: int = 0  # Cooldown по количеству сигналов (0 = отключен)
    prune_cooldown_days: Optional[float] = None  # Cooldown по времени в днях (None = отключен)
    prune_min_candidates: int = 3  # Минимальное количество кандидатов для выполнения prune
    prune_protect_min_max_xn: Optional[float] = 2.0  # Защита позиций с max_xn >= этого значения (None = отключено)
    
    # PortfolioReplay конфигурация
    max_hold_minutes: Optional[int] = None  # Максимальное время удержания позиции в минутах (режим B)
    
    def resolved_profit_reset_enabled(self) -> bool:
        """
        Возвращает значение profit_reset_enabled с fallback на runner_reset_enabled для обратной совместимости.
        
        Приоритет:
        1. profit_reset_enabled (если задан явно, не None)
        2. runner_reset_enabled (deprecated alias)
        """
        if self.profit_reset_enabled is not None:
            return bool(self.profit_reset_enabled)
        # Fallback на старое поле для обратной совместимости
        if self.runner_reset_enabled is None:
            return False
        return bool(self.runner_reset_enabled)
    
    def resolved_profit_reset_multiple(self) -> float:
        """
        Возвращает значение profit_reset_multiple с fallback на runner_reset_multiple для обратной совместимости.
        
        Приоритет:
        1. profit_reset_multiple (если задан явно, не None)
        2. runner_reset_multiple (deprecated alias)
        """
        if self.profit_reset_multiple is not None:
            return float(self.profit_reset_multiple)
        # Fallback на старое поле для обратной совместимости
        if self.runner_reset_multiple is None:
            return 1.0
        return float(self.runner_reset_multiple)


@dataclass
class PortfolioStats:
    final_balance_sol: float
    total_return_pct: float
    max_drawdown_pct: float
    trades_executed: int
    trades_skipped_by_risk: int
    trades_skipped_by_reset: int = 0  # Сделки, пропущенные из-за reset guard
    
    # Portfolio-level reset tracking (по equity threshold и capacity)
    portfolio_reset_count: int = 0  # Количество срабатываний portfolio-level reset (profit + capacity)
    last_portfolio_reset_time: Optional[datetime] = None  # Время последнего portfolio-level reset
    
    # Разделение счетчиков portfolio reset (опционально, для детализации)
    portfolio_reset_profit_count: int = 0  # Количество profit reset (по equity threshold)
    portfolio_reset_capacity_count: int = 0  # Количество capacity reset
    
    def __post_init__(self):
        """Инициализация счетчиков reset."""
        # Если счетчики не были явно установлены, инициализируем их
        if not hasattr(self, 'portfolio_reset_profit_count'):
            self.portfolio_reset_profit_count = 0
        if not hasattr(self, 'portfolio_reset_capacity_count'):
            self.portfolio_reset_capacity_count = 0
    
    # Обратная совместимость: reset_count означает portfolio-level reset
    @property
    def reset_count(self) -> int:
        """Обратная совместимость: reset_count = portfolio_reset_count"""
        return self.portfolio_reset_count
    
    @property
    def last_reset_time(self) -> Optional[datetime]:
        """Обратная совместимость: last_reset_time = last_portfolio_reset_time"""
        return self.last_portfolio_reset_time
    
    cycle_start_equity: float = 0.0  # Equity в начале текущего цикла
    equity_peak_in_cycle: float = 0.0  # Пик equity в текущем цикле
    
    # Capacity prune tracking (v1.7)
    portfolio_capacity_prune_count: int = 0  # Количество срабатываний capacity prune
    last_capacity_prune_time: Optional[datetime] = None  # Время последнего capacity prune
    
    # Capacity prune observability (v1.7.1)
    capacity_prune_events: List[Dict[str, Any]] = field(default_factory=list)  # Список событий prune для статистики
    
    # Portfolio events (v1.9) - источник истины для всех решений портфеля
    portfolio_events: List['PortfolioEvent'] = field(default_factory=list)  # Канонический список событий портфеля


@dataclass
class PortfolioResult:
    equity_curve: List[Dict[str, Any]]
    positions: List[Position]
    stats: PortfolioStats


class PortfolioEngine:
    """
    Обертка над PortfolioReplay для обратной совместимости.
    
    Теперь PortfolioEngine является тонкой оберткой, которая делегирует всю работу
    PortfolioReplay. Все legacy методы удалены.
    """

    def __init__(self, config: PortfolioConfig) -> None:
        self.config = config

    def simulate(
        self,
        all_results: List[Dict[str, Any]],
        strategy_name: str,
        blueprints: Optional[List['StrategyTradeBlueprint']] = None,
    ) -> PortfolioResult:
        """
        Основной метод симуляции по одной стратегии.

        all_results: список dict'ов (используется только для обратной совместимости API, не обрабатывается)
        
        blueprints: список StrategyTradeBlueprint для Replay
        """
        from .portfolio_replay import PortfolioReplay
        
        # Фильтруем blueprints по strategy_name
        filtered_blueprints = []
        if blueprints is not None:
            filtered_blueprints = [
                bp for bp in blueprints
                if bp.strategy_id == strategy_name
            ]
        
        # Вызываем PortfolioReplay.replay()
        return PortfolioReplay.replay(
            blueprints=filtered_blueprints,
            portfolio_config=self.config,
            market_data=None,  # TODO: передать market_data если будет доступно
        )
