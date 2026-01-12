# backtester/domain/portfolio.py

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional, Union, TYPE_CHECKING
from enum import Enum
from uuid import uuid4

if TYPE_CHECKING:
    from .strategy_trade_blueprint import StrategyTradeBlueprint

from .position import Position as PositionModel

# Type alias for annotations - pyright/basedpyright compatibility fix
# PositionModel is used for constructor calls to ensure correct type resolution
Position = PositionModel  # type: ignore[assignment]
from .models import StrategyOutput
from .execution_model import ExecutionProfileConfig, ExecutionModel
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


class EventType(Enum):
    """Тип события в event-driven симуляции."""
    ENTRY = "entry"  # Открытие позиции
    EXIT = "exit"    # Закрытие позиции по стратегии


@dataclass
class TradeEvent:
    """Событие в event-driven симуляции портфеля."""
    event_type: EventType
    event_time: datetime
    trade_data: Dict[str, Any]  # Исходные данные сделки (signal_id, contract_address, result: StrategyOutput)
    
    def __lt__(self, other: TradeEvent) -> bool:
        """
        Сортировка событий: сначала по времени, затем EXIT перед ENTRY на одном timestamp.
        Это гарантирует, что закрытия обрабатываются перед открытиями на одном моменте времени.
        """
        if self.event_time != other.event_time:
            return self.event_time < other.event_time
        # На одном timestamp: EXIT перед ENTRY
        if self.event_type == EventType.EXIT and other.event_type == EventType.ENTRY:
            return True
        if self.event_type == EventType.ENTRY and other.event_type == EventType.EXIT:
            return False
        return False  # Одинаковые типы событий на одном времени


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
    allocation_mode: Literal["fixed", "dynamic", "fixed_then_dynamic_after_profit_reset"] = "dynamic"
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
    profit_reset_trigger_basis: Literal["equity_peak", "realized_balance"] = "equity_peak"  # Основа для триггера: equity_peak (legacy) или realized_balance (новый)

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
    
    # PortfolioReplay конфигурация (ЭТАП 2)
    use_replay_mode: bool = False  # Если True, использует PortfolioReplay вместо legacy PortfolioEngine
    max_hold_minutes: Optional[int] = None  # Максимальное время удержания позиции в минутах (используется ТОЛЬКО в Replay, режим B)
    
    def resolved_profit_reset_enabled(self) -> bool:
        """
        Возвращает значение profit_reset_enabled с fallback на runner_reset_enabled для обратной совместимости.
        
        ВАЛИДАЦИЯ: если profit_reset_multiple <= 1.0 или invalid, reset автоматически disabled.
        
        Приоритет:
        1. profit_reset_enabled (если задан явно, не None)
        2. runner_reset_enabled (deprecated alias)
        3. Проверка валидности profit_reset_multiple (если <= 1.0 или invalid, disabled)
        """
        # Проверяем явные флаги
        if self.profit_reset_enabled is not None:
            enabled = bool(self.profit_reset_enabled)
        elif self.runner_reset_enabled is not None:
            enabled = bool(self.runner_reset_enabled)
        else:
            enabled = False
        
        # Если явно disabled, возвращаем False
        if not enabled:
            return False
        
        # Дополнительная проверка: profit_reset_multiple должен быть валидным и > 1.0
        multiple = self.resolved_profit_reset_multiple()
        if multiple is None:
            # multiple <= 1.0 или invalid - автоматически disabled
            return False
        
        return True
    
    def resolved_profit_reset_multiple(self) -> Optional[float]:
        """
        Возвращает значение profit_reset_multiple с fallback на runner_reset_multiple для обратной совместимости.
        
        ВАЛИДАЦИЯ: profit_reset_multiple должен быть float > 1.0, иначе reset disabled.
        
        Приоритет:
        1. profit_reset_multiple (если задан явно, не None)
        2. runner_reset_multiple (deprecated alias)
        
        Returns:
            float > 1.0 если валидно, иначе None (reset disabled)
        """
        multiple = None
        if self.profit_reset_multiple is not None:
            multiple = self.profit_reset_multiple
        elif self.runner_reset_multiple is not None:
            multiple = self.runner_reset_multiple
        
        if multiple is None:
            return None
        
        # Жёсткая валидация: должен быть float > 1.0
        try:
            multiple_float = float(multiple)
            # Проверяем что это конечное число и > 1.0
            if not math.isfinite(multiple_float) or multiple_float <= 1.0:
                logger.warning(
                    f"profit_reset_multiple={multiple_float} <= 1.0 or not finite, "
                    f"profit reset disabled. Use value > 1.0 to enable."
                )
                return None
            return multiple_float
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Failed to parse profit_reset_multiple={multiple}: {e}, "
                f"profit reset disabled."
            )
            return None


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
    cycle_start_balance: float = 0.0  # Реализованный баланс (cash) в начале текущего цикла (для realized_balance trigger)
    
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
    Портфельный движок:
    - принимает StrategyOutput'ы
    - применяет размер позиции, лимиты, комиссии
    - считает баланс и equity кривую
    
    ПРОБЛЕМА CAPACITY CHOKE (v1.6):
    Портфель может перестать открывать новые сделки (capacity choke):
    - open_positions долго == max_open_positions
    - новые сигналы отклоняются (max_open_positions/max_exposure)
    - turnover маленький → прибыльный profit reset может не наступить, портфель "висит"
    
    РЕШЕНИЕ:
    - Profit reset (по equity threshold) - сохраняется, показал прибыльность
    - Capacity reset (новый механизм) - срабатывает при capacity pressure независимо от profit reset
    """

    def __init__(self, config: PortfolioConfig) -> None:
        self.config = config
        self.execution_model = ExecutionModel.from_config(config)

    def _dbg(self, event: str, **kv) -> None:
        """
        Диагностический helper для portfolio-level reset.
        Логирует только при включенном флаге PORTFOLIO_DEBUG_RESET=1.
        
        Args:
            event: Название события
            **kv: Ключ-значение пары для логирования
        """
        debug_enabled = os.getenv("PORTFOLIO_DEBUG_RESET") == "1"
        if not debug_enabled:
            return
        
        # Формируем строку с параметрами
        parts = [f"[RESETDBG] {event}"]
        for key, value in kv.items():
            if isinstance(value, Position):
                # Для позиций выводим ключевую информацию
                parts.append(f"{key}.signal_id={value.signal_id}")
                parts.append(f"{key}.status={value.status}")
                parts.append(f"{key}.id={id(value)}")
                parts.append(f"{key}.closed_by_reset={value.meta.get('closed_by_reset', False)}")
                parts.append(f"{key}.triggered_portfolio_reset={value.meta.get('triggered_portfolio_reset', False)}")
            elif isinstance(value, datetime):
                parts.append(f"{key}={value.isoformat()}")
            elif isinstance(value, list):
                # Для списков позиций выводим количество и signal_id
                if value and isinstance(value[0], Position):
                    parts.append(f"{key}.count={len(value)}")
                    parts.append(f"{key}.signal_ids=[{', '.join(p.signal_id for p in value)}]")
                elif not value:
                    parts.append(f"{key}=[]")
                else:
                    parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}={value}")
        
        message = " ".join(parts)
        logger.debug(message)
        print(message)

    def _dbg_meta(self, pos: Position, label: str) -> None:
        """
        Диагностический helper для отслеживания изменений meta позиции.
        Логирует только при включенном флаге PORTFOLIO_DEBUG_RESET=1.
        
        Args:
            pos: Позиция для диагностики
            label: Метка события/места в коде
        """
        debug_enabled = os.getenv("PORTFOLIO_DEBUG_RESET") == "1"
        if not debug_enabled:
            return
        
        meta_id = id(pos.meta) if pos.meta is not None else None
        meta_keys = list(pos.meta.keys()) if pos.meta is not None else []
        closed_by_reset = pos.meta.get("closed_by_reset", False) if pos.meta is not None else False
        triggered_portfolio_reset = pos.meta.get("triggered_portfolio_reset", False) if pos.meta is not None else False
        
        message = (
            f"[METADBG] {label} | "
            f"signal_id={pos.signal_id} | "
            f"status={pos.status} | "
            f"id(pos)={id(pos)} | "
            f"id(meta)={meta_id} | "
            f"meta_keys={sorted(meta_keys)} | "
            f"closed_by_reset={closed_by_reset} | "
            f"triggered_portfolio_reset={triggered_portfolio_reset}"
        )
        logger.debug(message)
        print(message)

    def _ensure_meta(self, pos: Position) -> Dict[str, Any]:
        """
        Гарантирует, что pos.meta существует и возвращает его.
        НЕ создает новый dict, если meta уже существует.
        
        Args:
            pos: Позиция для проверки/инициализации meta
            
        Returns:
            Существующий или новый dict для pos.meta
        """
        if pos.meta is None:
            pos.meta = {}
        return pos.meta
    
    def _forced_close_position(
        self,
        pos: Position,
        current_time: datetime,
        reset_reason: str,
        additional_meta: Optional[Dict[str, Any]] = None,
        portfolio_events: Optional[List[PortfolioEvent]] = None,
        override_reason: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Единый метод для принудительного закрытия позиции (forced close).
        
        Используется для:
        - Profit reset
        - Capacity reset (close-all)
        - Capacity prune
        
        Args:
            pos: Позиция для закрытия
            current_time: Время закрытия
            reset_reason: Причина закрытия ("profit", "capacity", "capacity_prune", "runner", "manual")
            additional_meta: Дополнительные поля для meta (опционально)
            
        Returns:
            Dict с ключами: exit_pnl_sol, fees_total, network_fee_exit, effective_exit_price
        """
        from .portfolio_reset import get_mark_price_for_position
        
        # Получаем mark price
        raw_exit_price = get_mark_price_for_position(pos, current_time)
        
        # Применяем slippage (используем reason="manual" для forced close)
        effective_exit_price = self.execution_model.apply_exit(raw_exit_price, reason="manual_close")
        
        # Вычисляем PnL на основе исполненных цен
        exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price) if pos.meta else pos.entry_price
        exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price if exec_entry_price > 0 else 0.0
        exit_pnl_sol = pos.size * exit_pnl_pct
        
        # Применяем fees к возвращаемому нотионалу
        notional_returned = pos.size + exit_pnl_sol
        notional_after_fees = self.execution_model.apply_fees(notional_returned)
        fees_total = notional_returned - notional_after_fees
        network_fee_exit = self.execution_model.network_fee()
        
        # Обновляем позицию
        pos.exit_time = current_time
        pos.exit_price = raw_exit_price  # Сохраняем raw цену
        if pos.meta:
            pos.meta.setdefault("exec_exit_price", effective_exit_price)
        pos.pnl_pct = exit_pnl_pct
        pos.status = "closed"
        
        # Устанавливаем meta поля
        meta_updates = {
            "pnl_sol": exit_pnl_sol,
            "fees_total_sol": fees_total,
            "closed_by_reset": True,
            "reset_reason": reset_reason,
            "close_reason": reset_reason,
        }
        
        # Добавляем дополнительные поля если есть
        if additional_meta:
            meta_updates.update(additional_meta)
        
        if pos.meta:
            pos.meta.update(meta_updates)
            pos.meta["network_fee_sol"] = pos.meta.get("network_fee_sol", 0.0) + network_fee_exit
        
        # Эмитим событие закрытия (v2.0.1) - каноническое POSITION_CLOSED
        if portfolio_events is not None:
            event_meta = {
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "exit_time": current_time.isoformat(),
                "fees_total_sol": fees_total,
                "reset_reason": reset_reason,
            }
            if additional_meta:
                event_meta.update(additional_meta)

            # ВАЖНО: override_reason имеет приоритет над reset_reason
            # Это гарантирует, что при принудительном закрытии reason не перезаписывается
            close_reason = override_reason if override_reason is not None else reset_reason

            strategy_name = pos.meta.get("strategy", "unknown") if pos.meta else "unknown"
            portfolio_events.append(
                PortfolioEvent.create_position_closed(
                    timestamp=current_time,
                    strategy=strategy_name,
                    signal_id=pos.signal_id,
                    contract_address=pos.contract_address,
                    position_id=pos.position_id,
                    reason=close_reason,  # Используем override_reason если задан
                    raw_price=raw_exit_price,
                    exec_price=effective_exit_price,
                    pnl_pct=exit_pnl_pct * 100.0,  # В процентах
                    pnl_sol=exit_pnl_sol,
                    meta=event_meta,
                )
            )
        
        return {
            "exit_pnl_sol": exit_pnl_sol,
            "fees_total": fees_total,
            "network_fee_exit": network_fee_exit,
            "effective_exit_price": effective_exit_price,
        }

    def _position_size(self, current_balance: float, state: Optional[PortfolioState] = None) -> float:
        """
        Вычисляет размер позиции на основе текущего баланса и режима аллокации.
        
        Args:
            current_balance: Текущий баланс (cash)
            state: Состояние портфеля (опционально, требуется для fixed_then_dynamic_after_profit_reset)
        """
        if self.config.allocation_mode == "fixed":
            base = self.config.initial_balance_sol
        elif self.config.allocation_mode == "dynamic":
            base = current_balance
        elif self.config.allocation_mode == "fixed_then_dynamic_after_profit_reset":
            # До первого profit reset: fixed (initial_balance)
            # После первого profit reset: dynamic (current_balance)
            if state is None:
                # Fallback для обратной совместимости: используем fixed
                base = self.config.initial_balance_sol
            elif state.portfolio_reset_profit_count == 0:
                # До первого reset: fixed
                base = self.config.initial_balance_sol
            else:
                # После первого reset: dynamic
                base = current_balance
        else:
            # Fallback для неизвестных режимов
            base = current_balance
        return max(0.0, base * self.config.percent_per_trade)
    
    def _check_capacity_reset(
        self,
        state: PortfolioState,
        current_time: datetime,
        capacity_tracking: Dict[str, Any],
    ) -> Optional[PortfolioResetContext]:
        """
        Проверяет, должен ли сработать capacity reset (close-all режим).
        
        Для режима prune используйте _maybe_apply_capacity_prune().
        
        Триггер capacity reset:
        1. open_positions / max_open_positions >= capacity_open_ratio_threshold
        2. blocked_by_capacity_in_window >= capacity_blocked_signals_threshold
        3. closed_in_window <= capacity_min_turnover_threshold
        
        Args:
            state: Состояние портфеля
            current_time: Текущее время
            capacity_tracking: Dict с метриками capacity (blocked_by_capacity_in_window, closed_in_window, window_start, window_end)
            
        Returns:
            PortfolioResetContext если reset должен сработать, иначе None
        """
        if not self.config.capacity_reset_enabled:
            return None
        
        # Для режима prune не возвращаем context (prune обрабатывается отдельно)
        if self.config.capacity_reset_mode == "prune":
            return None
        
        # Вычисляем open_ratio
        max_open = self.config.max_open_positions
        if max_open <= 0:
            return None
        
        open_ratio = len(state.open_positions) / max_open
        if open_ratio < self.config.capacity_open_ratio_threshold:
            return None  # Портфель не заполнен
        
        # Проверяем метрики окна
        blocked_window = capacity_tracking.get("blocked_by_capacity_in_window", 0)
        signals_in_window = capacity_tracking.get("signals_in_window", 0)
        avg_hold_days = capacity_tracking.get("avg_hold_time_open_positions", 0.0)
        
        # Проверяем max_blocked_ratio (доля отклоненных сигналов)
        if signals_in_window > 0:
            blocked_ratio = blocked_window / signals_in_window
            if blocked_ratio < self.config.capacity_max_blocked_ratio:
                return None  # Недостаточно отклоненных сигналов (низкая доля)
        else:
            return None  # Нет сигналов в окне
        
        # Проверяем max_avg_hold_days (среднее время удержания открытых позиций)
        if avg_hold_days < self.config.capacity_max_avg_hold_days:
            return None  # Среднее время удержания низкое (есть turnover), reset не нужен
        
        # Все условия выполнены - capacity reset должен сработать
        # Выбираем marker position (первая открытая позиция)
        if not state.open_positions:
            return None  # Нет открытых позиций (не должно происходить)
        
        marker_position = state.open_positions[0]
        # Исключаем marker из positions_to_force_close (архитектурный инвариант)
        # Marker будет закрыт отдельно в apply_portfolio_reset
        positions_to_force_close = [
            p for p in state.open_positions
            if p.signal_id != marker_position.signal_id
        ]
        
        context = PortfolioResetContext(
            reason=ResetReason.CAPACITY_PRUNE,
            reset_time=current_time,
            marker_position=marker_position,
            positions_to_force_close=positions_to_force_close,
            open_ratio=open_ratio,
            blocked_window=blocked_window,
            turnover_window=capacity_tracking.get("closed_in_window", 0),
            window_start=capacity_tracking.get("window_start"),
            window_end=capacity_tracking.get("window_end"),
        )
        
        return context
    
    def _compute_current_pnl_pct(
        self,
        pos: Position,
        current_time: datetime,
    ) -> float:
        """
        Вычисляет текущий PnL позиции (mark-to-market) без использования price_loader.
        
        Использует существующий механизм получения mark price через get_mark_price_for_position
        и применяет ExecutionModel для реалистичной цены с учетом slippage.
        
        Fallback: если mark price недоступен, использует pos.meta["last_seen_price"] (для тестов).
        
        Args:
            pos: Позиция для расчета PnL
            current_time: Текущее время
            
        Returns:
            Текущий PnL в процентах (например, -0.30 = -30%)
        """
        from .portfolio_reset import get_mark_price_for_position
        
        # Получаем mark price
        mark_price = get_mark_price_for_position(pos, current_time)
        
        # Fallback: если mark_price совпадает с entry_price (нет данных), проверяем last_seen_price
        if pos.meta and mark_price == pos.entry_price:
            last_seen_price = pos.meta.get("last_seen_price")
            if last_seen_price is not None and last_seen_price > 0:
                mark_price = last_seen_price
        
        # Применяем ExecutionModel для реалистичной цены выхода (slippage)
        effective_mark_exit_price = self.execution_model.apply_exit(mark_price, reason="manual_close")
        
        # Получаем цену входа (исполненную, с slippage)
        entry_price = pos.meta.get("exec_entry_price") if pos.meta else None
        if entry_price is None:
            entry_price = pos.entry_price
        
        if entry_price <= 0:
            return 0.0
        
        # Вычисляем текущий PnL
        current_pnl_pct = (effective_mark_exit_price - entry_price) / entry_price
        return current_pnl_pct
    
    def _select_capacity_prune_candidates(
        self,
        state: PortfolioState,
        current_time: datetime,
    ) -> List[Position]:
        """
        Выбирает кандидатов для capacity prune.
        
        Кандидат должен одновременно удовлетворять:
        1. hold_days >= prune_min_hold_days
        2. mcap_usd <= prune_max_mcap_usd (если есть в meta)
        3. current_pnl_pct <= prune_max_current_pnl_pct
        
        Args:
            state: Состояние портфеля
            current_time: Текущее время
            
        Returns:
            Список позиций-кандидатов для prune
        """
        candidates = []
        
        for pos in state.open_positions:
            if pos.status != "open" or pos.entry_time is None:
                continue
            
            # Проверка 1: hold_days >= prune_min_hold_days
            hold_seconds = (current_time - pos.entry_time).total_seconds()
            hold_days = hold_seconds / (24 * 3600)
            if hold_days < self.config.prune_min_hold_days:
                continue
            
            # Проверка 2: mcap_usd <= prune_max_mcap_usd (только если известно)
            # Если mcap_usd неизвестно (None) - не применяем фильтр (v1.9: robust к None)
            mcap_usd = None
            if pos.meta:
                # Пробуем разные варианты ключей
                mcap_usd = pos.meta.get("mcap_usd") or pos.meta.get("mcap_usd_at_entry")
                if mcap_usd is None:
                    # Используем entry_mcap_proxy как fallback
                    entry_mcap_proxy = pos.meta.get("entry_mcap_proxy")
                    if entry_mcap_proxy is not None:
                        mcap_usd = entry_mcap_proxy
            
            # Применяем mcap-фильтр только если значение известно
            if mcap_usd is not None and mcap_usd > self.config.prune_max_mcap_usd:
                continue
            
            # Проверка 3: current_pnl_pct <= prune_max_current_pnl_pct (только если известно)
            # _compute_current_pnl_pct всегда возвращает float, но проверяем для robustness
            current_pnl_pct = self._compute_current_pnl_pct(pos, current_time)
            if current_pnl_pct is not None and current_pnl_pct > self.config.prune_max_current_pnl_pct:
                continue
            
            # Проверка 4: protect tail - не закрываем позиции с max_xn >= protect_min_max_xn (hardening v1.7.1)
            if self.config.prune_protect_min_max_xn is not None:
                max_xn = None
                if pos.meta:
                    # Пробуем разные варианты ключей для max_xn
                    max_xn = pos.meta.get("max_xn") or pos.meta.get("max_xn_reached")
                    if max_xn is None:
                        # Fallback: вычисляем из levels_hit (Runner)
                        levels_hit = pos.meta.get("levels_hit", {})
                        if levels_hit:
                            try:
                                max_xn = max(float(k) for k in levels_hit.keys() if k.replace('.', '', 1).isdigit())
                            except (ValueError, TypeError):
                                pass
                
                if max_xn is not None and max_xn >= self.config.prune_protect_min_max_xn:
                    continue  # Позиция защищена от prune (tail potential)
            
            # Все условия выполнены - добавляем в кандидаты
            candidates.append(pos)
        
        return candidates
    
    def _maybe_apply_capacity_prune(
        self,
        state: PortfolioState,
        current_time: datetime,
        capacity_tracking: Dict[str, Any],
        signal_index: int,
        portfolio_events: Optional[List[PortfolioEvent]] = None,
    ) -> bool:
        """
        Применяет capacity prune, если условия выполнены.
        
        Capacity prune закрывает ~50% "плохих" позиций без сброса profit cycle.
        Это НЕ reset операция - не обновляет cycle_start_equity, equity_peak_in_cycle,
        portfolio_reset_count.
        
        Args:
            state: Состояние портфеля (изменяется in-place)
            current_time: Текущее время
            capacity_tracking: Dict с метриками capacity
            
        Returns:
            True если prune был применен, False иначе
        """
        if not self.config.capacity_reset_enabled:
            return False
        
        if self.config.capacity_reset_mode != "prune":
            return False  # Режим close_all обрабатывается через _check_capacity_reset
        
        # Проверка cooldown (hardening v1.7.1)
        if self.config.prune_cooldown_signals > 0:
            if state.capacity_prune_cooldown_until_signal_index is not None:
                if signal_index < state.capacity_prune_cooldown_until_signal_index:
                    return False  # Cooldown активен
        
        if self.config.prune_cooldown_days is not None:
            if state.capacity_prune_cooldown_until_time is not None:
                if current_time < state.capacity_prune_cooldown_until_time:
                    return False  # Cooldown активен
        
        # Проверяем условия capacity pressure (v1.9: используем события вместо capacity_tracking)
        max_open = self.config.max_open_positions
        if max_open <= 0:
            return False
        
        open_ratio = len(state.open_positions) / max_open
        if open_ratio < self.config.capacity_open_ratio_threshold:
            return False
        
        blocked_window = capacity_tracking.get("blocked_by_capacity_in_window", 0)
        signals_in_window = capacity_tracking.get("signals_in_window", 0)
        if signals_in_window == 0:
            return False
        blocked_ratio = blocked_window / signals_in_window
        if blocked_ratio < self.config.capacity_max_blocked_ratio:
            return False
        
        avg_hold_days = capacity_tracking.get("avg_hold_time_open_positions", 0.0)
        
        if avg_hold_days < self.config.capacity_max_avg_hold_days:
            return False
        
        # Все условия capacity pressure выполнены - выбираем кандидатов для prune
        candidates = self._select_capacity_prune_candidates(state, current_time)
        
        # Проверка min_candidates (hardening v1.7.1)
        min_candidates = max(1, self.config.prune_min_candidates)  # Минимум 1 для backward compatibility
        if len(candidates) < min_candidates:
            # Не делаем prune если кандидатов меньше минимума
            return False
        
        # Вычисляем score для каждого кандидата (более "плохие" = выше score)
        candidate_scores = []
        for pos in candidates:
            hold_seconds = (current_time - pos.entry_time).total_seconds() if pos.entry_time else 0
            hold_days = hold_seconds / (24 * 3600)
            
            mcap_usd = None
            if pos.meta:
                mcap_usd = pos.meta.get("mcap_usd") or pos.meta.get("mcap_usd_at_entry")
                if mcap_usd is None:
                    entry_mcap_proxy = pos.meta.get("entry_mcap_proxy")
                    if entry_mcap_proxy is not None:
                        mcap_usd = entry_mcap_proxy
            
            current_pnl_pct = self._compute_current_pnl_pct(pos, current_time)
            
            # Score: хуже pnl → выше score, дольше hold → выше score, меньше mcap → выше score
            score = (-current_pnl_pct) * 100 + hold_days * 1.0
            if mcap_usd is not None:
                score += (self.config.prune_max_mcap_usd - mcap_usd) / self.config.prune_max_mcap_usd
            
            candidate_scores.append((pos, score, hold_days, mcap_usd, current_pnl_pct))
        
        # Сортируем по score DESC (более плохие первыми)
        candidate_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Вычисляем количество позиций для закрытия
        prune_count = max(1, int(self.config.prune_fraction * len(candidates)))
        prune_count = min(prune_count, len(candidates))  # Не больше чем кандидатов
        
        # Берем top-K кандидатов
        positions_to_prune = [item[0] for item in candidate_scores[:prune_count]]
        
        # Trigger эмитится только если реально есть позиции для закрытия
        if len(positions_to_prune) == 0:
            return False

        if portfolio_events is not None and positions_to_prune:
            marker_position = positions_to_prune[0]
            portfolio_events.append(
                PortfolioEvent.create_portfolio_reset_triggered(
                    timestamp=current_time,
                    strategy=marker_position.meta.get("strategy", "unknown") if marker_position.meta else "unknown",
                    signal_id=marker_position.signal_id,
                    contract_address=marker_position.contract_address,
                    position_id=marker_position.position_id,
                    reason="capacity_prune",
                    meta={
                        "open_ratio": open_ratio,
                        "blocked_window": blocked_window,
                        "signals_in_window": signals_in_window,
                        "avg_hold_days": avg_hold_days,
                        "signal_index": signal_index,
                        "closed_positions_count": len(positions_to_prune),
                    },
                )
            )
        
        # Закрываем выбранные позиции через market close
        for pos in positions_to_prune:
            # Находим данные из candidate_scores (до закрытия позиции)
            candidate_data = None
            for item in candidate_scores:
                if item[0].signal_id == pos.signal_id:
                    candidate_data = item
                    break
            
            # Подготавливаем дополнительные meta поля для prune
            if candidate_data:
                _, score, hold_days, mcap_usd, current_pnl_pct_before_close = candidate_data
                current_pnl_pct = current_pnl_pct_before_close
            else:
                # Fallback если не нашли в candidate_scores
                hold_seconds = (current_time - pos.entry_time).total_seconds() if pos.entry_time else 0
                hold_days = hold_seconds / (24 * 3600)
                mcap_usd = None
                if pos.meta:
                    mcap_usd = pos.meta.get("mcap_usd") or pos.meta.get("mcap_usd_at_entry")
                    if mcap_usd is None:
                        entry_mcap_proxy = pos.meta.get("entry_mcap_proxy")
                        if entry_mcap_proxy is not None:
                            mcap_usd = entry_mcap_proxy
                # Используем exit_pnl_pct как fallback (будет вычислен в _forced_close_position)
                current_pnl_pct = None  # Будет установлен после закрытия
                score = 0.0
            
            # Используем единый метод для forced close
            close_result = self._forced_close_position(
                pos=pos,
                current_time=current_time,
                reset_reason="capacity_prune",
                additional_meta={
                    "capacity_prune": True,
                    "capacity_prune_trigger_time": current_time.isoformat(),
                    "capacity_prune_current_pnl_pct": current_pnl_pct if current_pnl_pct is not None else pos.pnl_pct,
                    "capacity_prune_mcap_usd": mcap_usd,
                    "capacity_prune_hold_days": hold_days,
                    "capacity_prune_score": score,
                },
                portfolio_events=portfolio_events,  # Передаем события (v1.9)
            )
            
            # Возвращаем капитал (size + pnl - fees - network_fee)
            notional_returned = pos.size + close_result["exit_pnl_sol"]
            notional_after_fees = notional_returned - close_result["fees_total"]
            state.balance += notional_after_fees
            state.balance -= close_result["network_fee_exit"]
            
            state.closed_positions.append(pos)
            state.peak_balance = max(state.peak_balance, state.balance)
            state.equity_curve.append({"timestamp": current_time, "balance": state.balance})
        
        # Удаляем закрытые позиции из open_positions
        state.open_positions = [
            p for p in state.open_positions
            if p.signal_id not in {pos.signal_id for pos in positions_to_prune}
        ]
        
        # Обновляем счетчики prune (НЕ reset счетчики!)
        state.portfolio_capacity_prune_count = getattr(state, 'portfolio_capacity_prune_count', 0) + 1
        state.last_capacity_prune_time = current_time
        
        # Устанавливаем cooldown (hardening v1.7.1)
        if self.config.prune_cooldown_signals > 0:
            state.capacity_prune_cooldown_until_signal_index = signal_index + self.config.prune_cooldown_signals
        
        if self.config.prune_cooldown_days is not None:
            from datetime import timedelta
            state.capacity_prune_cooldown_until_time = current_time + timedelta(days=self.config.prune_cooldown_days)
        
        # Сохраняем статистику для observability (hardening v1.7.1)
        # Примечание: blocked_window теперь считается из capacity_tracking
        prune_event = {
            "trigger_time": current_time.isoformat(),
            "signal_index": signal_index,
            "candidates_count": len(candidates),
            "pruned_count": len(positions_to_prune),
            "open_ratio": open_ratio,
            "blocked_window": blocked_window,
            "signals_in_window": signals_in_window,
            "avg_hold_days": avg_hold_days,
            "pruned_hold_days": [item[2] for item in candidate_scores[:len(positions_to_prune)]],  # hold_days закрытых
            "pruned_current_pnl_pct": [item[4] for item in candidate_scores[:len(positions_to_prune)]],  # current_pnl_pct закрытых
        }
        if not hasattr(state, 'capacity_prune_events'):
            state.capacity_prune_events = []
        state.capacity_prune_events.append(prune_event)
        
        logger.info(
            f"[CAPACITY_PRUNE] Triggered at {current_time.isoformat()}: "
            f"candidates={len(candidates)}, pruned={len(positions_to_prune)}, "
            f"open_ratio={open_ratio:.2f}, blocked_window={blocked_window}, "
            f"avg_hold_days={avg_hold_days:.2f}, cooldown_until_signal={state.capacity_prune_cooldown_until_signal_index}"
        )

        return True
    
    def _update_capacity_tracking(
        self,
        capacity_tracking: Dict[str, Any],
        current_time: datetime,
        state: PortfolioState,
        signal_blocked_by_capacity: bool,
        position_closed: bool,
    ) -> None:
        """
        Обновляет метрики capacity tracking.
        
        Args:
            capacity_tracking: Dict для хранения метрик (изменяется in-place)
            current_time: Текущее время
            signal_blocked_by_capacity: Был ли сигнал отклонен по capacity
            position_closed: Была ли закрыта позиция
        """
        # Инициализация если нужно
        if "window_start" not in capacity_tracking:
            capacity_tracking["window_start"] = current_time
            capacity_tracking["blocked_by_capacity_in_window"] = 0
            capacity_tracking["closed_in_window"] = 0
            capacity_tracking["signals_in_window"] = 0
        
        window_start = capacity_tracking["window_start"]
        
        # Определяем границы окна
        if self.config.capacity_window_type == "time":
            # Окно по времени
            window_size = self.config.capacity_window_size
            if isinstance(window_size, str) and window_size.endswith("d"):
                days = int(window_size[:-1])
            else:
                days = int(window_size)
            window_duration = timedelta(days=days)
            window_end = window_start + window_duration
        else:
            # Окно по количеству сигналов
            window_end = None  # Будет обновляться по количеству сигналов
        
        # Обновляем счетчики
        if signal_blocked_by_capacity:
            capacity_tracking["blocked_by_capacity_in_window"] = capacity_tracking.get("blocked_by_capacity_in_window", 0) + 1
        
        if position_closed:
            capacity_tracking["closed_in_window"] = capacity_tracking.get("closed_in_window", 0) + 1
        
        capacity_tracking["signals_in_window"] = capacity_tracking.get("signals_in_window", 0) + 1
        
        # Обновляем окно если нужно
        if self.config.capacity_window_type == "time":
            # Если текущее время вышло за окно, сдвигаем окно
            if window_end is not None and current_time > window_end:
                # Сбрасываем окно
                capacity_tracking["window_start"] = current_time
                capacity_tracking["blocked_by_capacity_in_window"] = 0
                capacity_tracking["closed_in_window"] = 0
                capacity_tracking["signals_in_window"] = 0
        else:
            # Окно по сигналам: если достигли лимита, сдвигаем окно
            window_size = int(self.config.capacity_window_size)
            if capacity_tracking["signals_in_window"] >= window_size:
                # Сбрасываем окно
                capacity_tracking["window_start"] = current_time
                capacity_tracking["blocked_by_capacity_in_window"] = 0
                capacity_tracking["closed_in_window"] = 0
                capacity_tracking["signals_in_window"] = 0
        
        # Обновляем avg_hold_time_open_positions
        if state.open_positions:
            total_hold_seconds = sum(
                (current_time - pos.entry_time).total_seconds()
                for pos in state.open_positions
                if pos.entry_time
            )
            avg_hold_seconds = total_hold_seconds / len(state.open_positions)
            avg_hold_days = avg_hold_seconds / (24 * 3600)
            capacity_tracking["avg_hold_time_open_positions"] = avg_hold_days
        else:
            capacity_tracking["avg_hold_time_open_positions"] = 0.0
        
        capacity_tracking["window_end"] = window_end if self.config.capacity_window_type == "time" else current_time
    
    def _select_profit_reset_marker(
        self,
        state: PortfolioState,
        closed_positions_candidates: List[Position],
        open_positions_candidates: List[Position],
    ) -> Optional[Position]:
        """
        Выбирает marker-позицию для profit reset детерминированно.
        
        Приоритет выбора:
        1. Позиция с максимальным effective_pnl_pct среди закрытых кандидатов
        2. Позиция с максимальным pnl_sol среди закрытых кандидатов
        3. Позиция с максимальным (exit_price / entry_price) среди закрытых кандидатов
        4. Позиция с максимальным effective_pnl_pct среди открытых кандидатов
        5. Самая ранняя позиция по entry_time
        
        Args:
            state: Состояние портфеля
            closed_positions_candidates: Список закрытых позиций-кандидатов
            open_positions_candidates: Список открытых позиций-кандидатов
            
        Returns:
            Выбранная marker-позиция или None, если кандидатов нет
        """
        # Сначала проверяем закрытые позиции
        if closed_positions_candidates:
            # Сортируем по приоритету: effective_pnl_pct -> pnl_sol -> exit_price/entry_price
            def get_marker_score(pos: Position) -> tuple:
                # Приоритет 1: effective_pnl_pct из meta
                effective_pnl = pos.meta.get("effective_pnl_pct") if pos.meta else None
                if effective_pnl is not None:
                    pnl_score = float(effective_pnl)
                else:
                    # Fallback: используем pnl_pct из позиции
                    pnl_score = float(pos.pnl_pct) if pos.pnl_pct is not None else 0.0
                
                # Приоритет 2: pnl_sol из meta
                pnl_sol = pos.meta.get("pnl_sol") if pos.meta else None
                if pnl_sol is not None:
                    sol_score = float(pnl_sol)
                else:
                    # Fallback: вычисляем из размера и pnl_pct
                    sol_score = pos.size * pnl_score if pnl_score > 0 else 0.0
                
                # Приоритет 3: exit_price / entry_price
                if pos.entry_price and pos.entry_price > 0 and pos.exit_price and pos.exit_price > 0:
                    ratio_score = pos.exit_price / pos.entry_price
                else:
                    ratio_score = 1.0
                
                # Возвращаем tuple для сортировки (по убыванию)
                return (-pnl_score, -sol_score, -ratio_score)
            
            # Сортируем и берем первую (с максимальным score)
            sorted_candidates = sorted(closed_positions_candidates, key=get_marker_score)
            return sorted_candidates[0]
        
        # Если закрытых нет, проверяем открытые
        if open_positions_candidates:
            # Для открытых позиций используем effective_pnl_pct или entry_time
            def get_open_marker_score(pos: Position) -> tuple:
                effective_pnl = pos.meta.get("effective_pnl_pct") if pos.meta else None
                if effective_pnl is not None:
                    pnl_score = float(effective_pnl)
                else:
                    pnl_score = float(pos.pnl_pct) if pos.pnl_pct is not None else 0.0
                
                # Если pnl одинаковый, берем самую раннюю
                entry_time = pos.entry_time if pos.entry_time else datetime.max.replace(tzinfo=timezone.utc)
                return (-pnl_score, entry_time)
            
            sorted_candidates = sorted(open_positions_candidates, key=get_open_marker_score)
            return sorted_candidates[0]
        
        return None

    def _apply_reset(
        self,
        state: PortfolioState,
        marker_position: Position,
        reset_time: datetime,
        positions_to_force_close: List[Position],
        reason: ResetReason,
        portfolio_events: Optional[List[PortfolioEvent]] = None,
    ) -> None:
        """
        Helper-метод для применения reset к PortfolioState.
        
        Это единственная точка в PortfolioEngine, где вызывается apply_portfolio_reset().
        
        Args:
            state: Состояние портфеля (изменяется in-place)
            marker_position: Позиция-маркер для reset
            reset_time: Время reset
            positions_to_force_close: Позиции для принудительного закрытия
            reason: Причина reset
            portfolio_events: Список событий для эмиссии (v1.9)
        """
        # GUARD B: profit reset не исполняется, если нет реальных открытых позиций
        # Если len(real_open_positions) == 0, reset не имеет смысла (нечего закрывать)
        real_open_positions = [
            p for p in positions_to_force_close
            if not (p.meta and p.meta.get("marker", False))
        ]
        if len(real_open_positions) == 0:
            # Нет реальных позиций для закрытия → пропускаем reset
            # НЕ создаем marker, НЕ эмитим portfolio_reset_triggered, НЕ списываем fees
            logger.warning(
                f"[PROFIT_RESET] Guard B: Reset skipped - no real open positions to close. "
                f"reset_time={reset_time}, reason={reason}"
            )
            return
        
        # ВАЖНО: Делаем snapshot open_positions ДО вызова apply_portfolio_reset
        # apply_portfolio_reset изменяет state.open_positions, поэтому нужно сохранить состояние заранее
        open_positions_snapshot = list(state.open_positions)
        
        # Сохраняем статус marker_position до reset (для эмиссии событий)
        marker_was_open = marker_position.status == "open"
        
        context = PortfolioResetContext(
            reason=reason,
            reset_time=reset_time,
            marker_position=marker_position,
            positions_to_force_close=positions_to_force_close,
        )
        apply_portfolio_reset(context, state, self.execution_model)
        
        # Эмитим события reset (v2.0.1) - канонический контракт
        # Порядок: сначала все POSITION_CLOSED, потом PORTFOLIO_RESET_TRIGGERED
        if portfolio_events is not None:
            # Маппинг ResetReason -> канонический reason
            reset_reason_str = {
                ResetReason.PROFIT_RESET: "profit_reset",
                ResetReason.CAPACITY_PRUNE: "capacity_prune",
                ResetReason.MANUAL: "manual_close",
            }.get(reason, "manual_close")
            
            # ВАЖНО: Находим marker_position в snapshot по meta["marker"]=True
            # Используем snapshot, так как state.open_positions уже изменен apply_portfolio_reset
            marker_from_state: Optional[Position] = None
            for p in open_positions_snapshot:
                if p.meta and p.meta.get("marker", False):
                    marker_from_state = p
                    break
            
            # Если marker не найден в snapshot, используем переданный marker_position
            if marker_from_state is None:
                marker_from_state = marker_position
            
            # ВАЖНО: Собираем ВСЕ открытые позиции из snapshot на момент reset_time
            # Используем snapshot, так как state.open_positions уже изменен apply_portfolio_reset
            # Убираем проверку exit_time > reset_time, так как reset_time может совпадать с exit_time
            # Для snapshot-логики берем просто p.status=="open" на момент snapshot и исключаем marker по meta
            real_open_positions_at_reset = [
                p for p in open_positions_snapshot 
                if p.status == "open" 
                and not (p.meta and p.meta.get("marker", False))  # Исключаем marker
            ]
            
            # Также добавляем positions_to_force_close, если они еще не в списке
            for pos in positions_to_force_close:
                if pos not in real_open_positions_at_reset and pos.status == "open" and not (pos.meta and pos.meta.get("marker", False)):
                    real_open_positions_at_reset.append(pos)
            
            # ВАЖНО: ВСЕГДА закрываем marker_position при profit reset (даже если есть реальные позиции)
            # Используем marker_was_open (сохраненный ДО apply_portfolio_reset), а не marker_from_state.status
            # так как к моменту эмиссии событий marker может уже быть закрыт/изменен
            all_open_positions_at_reset = list(real_open_positions_at_reset)
            if reset_reason_str == "profit_reset" and marker_from_state is not None and marker_was_open:
                # Закрываем marker_position с reason="profit_reset"
                # Убеждаемся, что marker не дублируется в списке
                if marker_from_state not in all_open_positions_at_reset:
                    all_open_positions_at_reset.append(marker_from_state)
            
            # 1. Эмитим POSITION_CLOSED для каждой закрытой позиции (N событий) - ПЕРВЫМИ
            # ЖЁСТКИЙ КОНТРАКТ: reason="profit_reset", timestamp=reset_time, position_id обязателен
            emitted_profit_reset_closures = 0
            for pos in all_open_positions_at_reset:
                strategy_name = pos.meta.get("strategy", "unknown") if pos.meta else "unknown"
                raw_exit_price = pos.exit_price if pos.exit_price is not None else pos.entry_price
                exec_exit_price = pos.meta.get("exec_exit_price", raw_exit_price) if pos.meta else raw_exit_price
                pnl_sol = pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0
                pnl_pct = pos.pnl_pct * 100.0 if pos.pnl_pct is not None else None  # В процентах
                
                close_meta = {
                    "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                    "exit_time": reset_time.isoformat(),
                    "fees_total_sol": pos.meta.get("fees_total_sol", 0.0) if pos.meta else 0.0,
                    "closed_by_reset": True,
                    "reset_reason": reset_reason_str,
                }
                
                # ЖЁСТКИЙ КОНТРАКТ: reason строго "profit_reset" (или другой reset_reason_str), timestamp строго reset_time
                event = PortfolioEvent.create_position_closed(
                    timestamp=reset_time,  # Строго reset_time, без +epsilon
                    strategy=strategy_name,
                    signal_id=pos.signal_id,
                    contract_address=pos.contract_address,
                    position_id=pos.position_id,  # Обязателен
                    reason=reset_reason_str,  # Строго reset_reason_str (не нормализуется)
                    raw_price=raw_exit_price,
                    exec_price=exec_exit_price,
                    pnl_pct=pnl_pct,
                    pnl_sol=pnl_sol,
                    meta=close_meta,
                )
                portfolio_events.append(event)
                if reset_reason_str == "profit_reset":
                    emitted_profit_reset_closures += 1
            
            # Debug-guard: проверка, что события были эмитчены
            # ВАЖНО: Для profit reset ВСЕГДА должно быть хотя бы одно POSITION_CLOSED (marker_position)
            if reset_reason_str == "profit_reset":
                # Проверяем, что marker_position был закрыт
                marker_closed = False
                marker_position_id = None
                if marker_from_state is not None:
                    marker_position_id = marker_from_state.position_id
                    for event in portfolio_events:
                        if (event.event_type == PortfolioEventType.POSITION_CLOSED 
                            and event.reason == "profit_reset"
                            and event.position_id == marker_position_id):
                            marker_closed = True
                            break
                
                # Assert: если reset сработал и marker был open, должен быть хотя бы один POSITION_CLOSED с reason="profit_reset"
                # Если marker_was_open=False, assert не должен падать (marker мог быть уже закрыт до reset)
                if marker_was_open:
                    assert emitted_profit_reset_closures > 0, \
                        f"[PROFIT_RESET] ERROR: Reset triggered with marker_was_open=True, but no POSITION_CLOSED events with reason='profit_reset' emitted! " \
                        f"emitted={emitted_profit_reset_closures}, reset_reason={reset_reason_str}"
                    
                    # Дополнительный guard: marker_position должен быть закрыт
                    if marker_from_state is not None:
                        assert marker_closed, \
                            f"[PROFIT_RESET] ERROR: Reset triggered with marker_was_open=True, but marker_position (id={marker_position_id}) was not closed! " \
                            f"marker_status={marker_from_state.status}, emitted_closures={emitted_profit_reset_closures}"
            
            # 2. Эмитим PORTFOLIO_RESET_TRIGGERED (1 событие) - ПОСЛЕ всех POSITION_CLOSED
            # Используем marker_from_state (найденный в state) или fallback на marker_position
            final_marker = marker_from_state if marker_from_state is not None else marker_position
            
            # Генерируем уникальный reset_id для каждого reset
            reset_id = uuid4().hex
            
            # closed_positions_count должен быть количеством реальных позиций (без marker)
            # positions_to_force_close уже содержит только реальные позиции (marker исключен)
            closed_positions_count = len(positions_to_force_close)
            
            # Создаем уникальный marker position_id для этого reset (если marker создается заново)
            # Если marker уже существует, используем его position_id
            marker_position_id = final_marker.position_id if final_marker is not None else marker_position.position_id
            
            # Добавляем reset_id в meta marker'а (для всех marker позиций)
            # Ищем все marker позиции в closed_positions и добавляем reset_id
            for pos in state.closed_positions:
                if pos.meta and pos.meta.get("marker", False) and pos.signal_id == "__profit_reset_marker__":
                    # Проверяем что это marker для текущего reset (по времени)
                    if pos.exit_time == reset_time:
                        pos.meta["reset_id"] = reset_id
            # Также добавляем в final_marker если он еще открыт
            if final_marker is not None and final_marker.meta is not None:
                final_marker.meta["reset_id"] = reset_id
                final_marker.meta["marker"] = True
            elif marker_position.meta is not None:
                marker_position.meta["reset_id"] = reset_id
                marker_position.meta["marker"] = True
            
            portfolio_events.append(
                PortfolioEvent.create_portfolio_reset_triggered(
                    timestamp=reset_time,  # Строго reset_time
                    reason=reset_reason_str,  # Строго reset_reason_str
                    closed_positions_count=closed_positions_count,  # Только реальные позиции (без marker)
                    position_id=marker_position_id,
                    signal_id=final_marker.signal_id if final_marker is not None else marker_position.signal_id,
                    contract_address=final_marker.contract_address if final_marker is not None else marker_position.contract_address,
                    strategy=final_marker.meta.get("strategy", "portfolio") if final_marker and final_marker.meta else (marker_position.meta.get("strategy", "portfolio") if marker_position.meta else "portfolio"),
                    meta={
                        "reset_id": reset_id,  # Уникальный ID для каждого reset
                        "reset_time": reset_time.isoformat(),
                        "cycle_start_equity": state.cycle_start_equity,
                        "equity_peak_in_cycle": state.equity_peak_in_cycle,
                        "cycle_start_balance": state.cycle_start_balance,  # Для realized_balance trigger
                        "current_balance": state.balance,
                    },
                )
            )
            
            # ВАЖНО: Удаляем marker_position из open_positions после эмиссии событий
            if marker_from_state is not None and marker_from_state in state.open_positions:
                state.open_positions.remove(marker_from_state)
                if marker_from_state not in state.closed_positions:
                    marker_from_state.status = "closed"
                    marker_from_state.exit_time = reset_time
                    state.closed_positions.append(marker_from_state)

    def _process_runner_partial_exits(
        self,
        pos: Position,
        current_time: datetime,
        balance: float,
        equity_curve: List[Dict[str, Any]],
        closed_positions: List[Position],
        portfolio_events: Optional[List[PortfolioEvent]] = None,
    ) -> Dict[str, Any]:
        """
        Обрабатывает частичные выходы для Runner стратегии.
        
        Args:
            pos: Позиция Runner
            current_time: Текущее время (время входа новой сделки)
            balance: Текущий баланс
            equity_curve: Кривая equity для обновления
            closed_positions: Список закрытых позиций
            
        Returns:
            Dict с обновленным balance
        """
        
        # Извлекаем данные о частичных выходах из meta
        levels_hit_raw = pos.meta.get("levels_hit", {})
        fractions_exited_raw = pos.meta.get("fractions_exited", {})
        
        if not levels_hit_raw or not fractions_exited_raw:
            # Нет частичных выходов, возвращаем как есть
            return {"balance": balance}
        
        # Парсим levels_hit (ключи - строки, значения - ISO строки времени)
        levels_hit: Dict[float, datetime] = {}
        for k_str, v_str in levels_hit_raw.items():
            try:
                xn = float(k_str)
                hit_time = datetime.fromisoformat(v_str) if isinstance(v_str, str) else v_str
                levels_hit[xn] = hit_time
            except (ValueError, TypeError):
                continue
        
        # Парсим fractions_exited (ключи - строки, значения - float)
        fractions_exited: Dict[float, float] = {}
        for k_str, v in fractions_exited_raw.items():
            try:
                xn = float(k_str)
                fraction = float(v)
                fractions_exited[xn] = fraction
            except (ValueError, TypeError):
                continue
        
        # Получаем оригинальный размер позиции (если не сохранен, используем текущий)
        original_size = pos.meta.get("original_size", pos.size)
        if "original_size" not in pos.meta:
            pos.meta["original_size"] = original_size
        
        # Сортируем уровни по времени достижения
        sorted_levels = sorted(levels_hit.items(), key=lambda x: x[1])
        
        # Обрабатываем каждый уровень, который был достигнут до current_time
        for xn, hit_time in sorted_levels:
            # Проверяем, был ли этот уровень уже обработан
            processed_key = f"partial_exit_processed_{xn}"
            if pos.meta.get(processed_key, False):
                continue  # Уже обработан
            
            # Проверяем, что уровень был достигнут до current_time
            if hit_time > current_time:
                continue  # Еще не достигнут
            
            # Получаем долю для закрытия
            fraction = fractions_exited.get(xn, 0.0)
            if fraction <= 0:
                continue
            
            # Вычисляем размер частичного выхода (от оригинального размера)
            exit_size = original_size * fraction
            
            # Проверяем, что есть что закрывать
            if exit_size > pos.size:
                exit_size = pos.size  # Закрываем только то, что осталось
            
            if exit_size <= 1e-9:
                continue  # Ничего не закрываем
            
            # Вычисляем цену выхода (entry_price * xn)
            exit_price_raw = pos.entry_price * xn
            
            # Применяем slippage к цене выхода (для TP используем reason="ladder_tp")
            effective_exit_price = self.execution_model.apply_exit(exit_price_raw, "ladder_tp")
            
            # Вычисляем PnL для этой части - используем exec_entry_price из meta для правильного расчета баланса
            exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
            exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price
            exit_pnl_sol = exit_size * exit_pnl_pct
            
            # Применяем fees к возвращаемому нотионалу
            notional_returned = exit_size + exit_pnl_sol
            notional_after_fees = self.execution_model.apply_fees(notional_returned)
            fees_partial = notional_returned - notional_after_fees
            
            # Network fee для частичного выхода
            network_fee_exit = self.execution_model.network_fee()
            
            # Возвращаем капитал в баланс
            balance += notional_after_fees
            balance -= network_fee_exit
            
            # Уменьшаем размер позиции (remaining_size)
            pos.size -= exit_size
            
            # Сохраняем remaining_size в meta для использования в reporter
            pos.meta["remaining_size"] = pos.size
            
            # ВАЖНО: Математический pnl_pct для meta (без учета slippage/fees)
            # Тест ожидает: pnl_pct_contrib = f * (xn - 1.0) * 100.0
            pnl_pct_meta = fraction * (xn - 1.0) * 100.0
            
            # Сохраняем информацию о частичном выходе в meta
            if "partial_exits" not in pos.meta:
                pos.meta["partial_exits"] = []
            
            # Эмитим событие POSITION_PARTIAL_EXIT (только один раз!)
            if portfolio_events is not None:
                strategy_name = pos.meta.get("strategy", "unknown") if pos.meta else "unknown"
                pnl_pct_contrib = exit_pnl_pct * 100.0  # В процентах для события (с учетом slippage)
                event = PortfolioEvent.create_position_partial_exit(
                    timestamp=hit_time,
                    strategy=strategy_name,
                    signal_id=pos.signal_id,
                    contract_address=pos.contract_address,
                    position_id=pos.position_id,
                    level_xn=xn,
                    fraction=fraction,
                    raw_price=exit_price_raw,
                    exec_price=effective_exit_price,
                    pnl_pct_contrib=pnl_pct_contrib,
                    pnl_sol_contrib=exit_pnl_sol,
                    meta={
                        "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                        "exit_time": hit_time.isoformat(),
                        "exit_size": exit_size,
                        "fees_sol": fees_partial,
                        "network_fee_sol": network_fee_exit,
                        "reason": "ladder_tp",  # Сохраняем reason в meta
                    },
                )
                portfolio_events.append(event)
                
                # Сохраняем event_id в meta для связи
                # ВАЖНО: pnl_pct в meta должен быть математическим (f * (xn - 1.0) * 100.0)
                pos.meta["partial_exits"].append({
                    "xn": xn,
                    "hit_time": hit_time.isoformat(),
                    "exit_size": exit_size,
                    "exit_price": effective_exit_price,
                    "pnl_pct": pnl_pct_meta,  # Математический вклад: f * (xn - 1.0) * 100.0
                    "pnl_sol": exit_pnl_sol,
                    "fees_sol": fees_partial,
                    "network_fee_sol": network_fee_exit,
                    "event_id": event.event_id,
                })
            else:
                # Если portfolio_events не передан, все равно сохраняем в meta
                pos.meta["partial_exits"].append({
                    "xn": xn,
                    "hit_time": hit_time.isoformat(),
                    "exit_size": exit_size,
                    "exit_price": effective_exit_price,
                    "pnl_pct": pnl_pct_meta,  # Математический вклад: f * (xn - 1.0) * 100.0
                    "pnl_sol": exit_pnl_sol,
                    "fees_sol": fees_partial,
                    "network_fee_sol": network_fee_exit,
                })
            
            # Обновляем общие fees
            # ВАЖНО: fees_total_sol будет пересчитан в конце из всех executions (TASK 3)
            # Здесь только накапливаем для промежуточных расчетов
            if "fees_total_sol" in pos.meta:
                pos.meta["fees_total_sol"] += fees_partial + network_fee_exit
            else:
                # Начальное значение: network_fee при входе (если есть) + fees_partial + network_fee_exit
                network_fee_entry = pos.meta.get("network_fee_sol", 0.0)
                pos.meta["fees_total_sol"] = network_fee_entry + fees_partial + network_fee_exit
            
            if "network_fee_sol" in pos.meta:
                pos.meta["network_fee_sol"] += network_fee_exit
            else:
                # Начальное значение: network_fee при входе (если есть) + network_fee_exit
                network_fee_entry = pos.meta.get("network_fee_sol", 0.0)
                pos.meta["network_fee_sol"] = network_fee_entry + network_fee_exit
            
            # Помечаем уровень как обработанный
            pos.meta[processed_key] = True
            
            # Обновляем equity curve
            equity_curve.append({"timestamp": hit_time, "balance": balance})
        
        # Если после обработки частичных выходов остался остаток, закрываем его по time_stop
        # Остаток закрывается только если current_time >= exit_time (time_stop наступил)
        if pos.size > 1e-9 and pos.exit_time is not None and current_time >= pos.exit_time:
            # Проверяем, не был ли остаток уже закрыт
            remainder_closed_key = "remainder_closed"
            if pos.meta.get(remainder_closed_key, False):
                # Остаток уже закрыт
                pass
            elif pos.exit_price is not None:
                # Применяем slippage для time_stop - используем raw exit_price для расчета slippage
                effective_exit_price = self.execution_model.apply_exit(pos.exit_price, "time_stop")
                
                # Вычисляем PnL для остатка - используем exec_entry_price из meta для правильного расчета баланса
                exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
                exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price
                exit_pnl_sol = pos.size * exit_pnl_pct
                
                # Применяем fees
                notional_returned = pos.size + exit_pnl_sol
                notional_after_fees = self.execution_model.apply_fees(notional_returned)
                fees_remainder = notional_returned - notional_after_fees
                network_fee_exit = self.execution_model.network_fee()
                
                # Возвращаем капитал
                balance += notional_after_fees
                balance -= network_fee_exit
                
                # Variant C: Сохраняем информацию о закрытии остатка в meta для использования в _process_position_exit
                # НЕ создаём POSITION_PARTIAL_EXIT event для remainder - только POSITION_CLOSED будет создан позже
                if "partial_exits" not in pos.meta:
                    pos.meta["partial_exits"] = []
                pos.meta["partial_exits"].append({
                    "xn": pos.exit_price / pos.entry_price if pos.entry_price > 0 else 1.0,
                    "hit_time": pos.exit_time.isoformat() if pos.exit_time else "",
                    "exit_size": pos.size,
                    "exit_price": effective_exit_price,
                    "pnl_pct": exit_pnl_pct,
                    "pnl_sol": exit_pnl_sol,
                    "fees_sol": fees_remainder,
                    "network_fee_sol": network_fee_exit,
                    "is_remainder": True,
                })
                # Сохраняем данные remainder в meta для использования в _process_position_exit при создании POSITION_CLOSED
                pos.meta["remainder_exit_data"] = {
                    "raw_price": pos.exit_price,
                    "exec_price": effective_exit_price,
                    "pnl_sol": exit_pnl_sol,
                    "pnl_pct": exit_pnl_pct,
                    "fees_sol": fees_remainder,
                    "network_fee_sol": network_fee_exit,
                    "exit_size": pos.size,
                }
                # НЕ создаём POSITION_PARTIAL_EXIT event для remainder - это будет сделано через POSITION_CLOSED в _process_position_exit
                
                # Обновляем fees
                pos.meta["fees_total_sol"] = pos.meta.get("fees_total_sol", 0.0) + fees_remainder + network_fee_exit
                if "network_fee_sol" in pos.meta:
                    pos.meta["network_fee_sol"] += network_fee_exit
                else:
                    pos.meta["network_fee_sol"] = network_fee_exit
                
                # Помечаем остаток как закрытый
                pos.meta[remainder_closed_key] = True
                pos.size = 0.0
                pos.meta["remaining_size"] = 0.0
        
        # Если позиция полностью закрыта после partial exits
        # НЕ добавляем в closed_positions здесь - это будет сделано в _process_position_exit
        # Просто обновляем статус и PnL
        if pos.size <= 1e-9:
            pos.status = "closed"
            # Обновляем общий PnL позиции
            total_pnl_sol = sum(exit.get("pnl_sol", 0.0) for exit in pos.meta.get("partial_exits", []))
            pos.meta["pnl_sol"] = total_pnl_sol
            
            # TASK 3: Пересчитываем fees_total_sol из executions (один источник истины)
            # Суммируем fees из всех partial_exits (включая network_fee для каждого exit)
            fees_from_partial_exits = sum(
                exit.get("fees_sol", 0.0) + exit.get("network_fee_sol", 0.0)
                for exit in pos.meta.get("partial_exits", [])
            )
            # Добавляем network_fee при входе (если есть, и если он еще не учтен)
            # network_fee_sol в meta может содержать только entry fee, или entry + exit fees
            # Проверяем: если network_fee_sol == sum(network_fee_exit из partial_exits), значит entry fee не учтен
            network_fee_exits_total = sum(
                exit.get("network_fee_sol", 0.0)
                for exit in pos.meta.get("partial_exits", [])
            )
            network_fee_entry = pos.meta.get("network_fee_sol", 0.0) - network_fee_exits_total
            if network_fee_entry < 0:
                network_fee_entry = 0.0  # Защита от отрицательных значений
            
            fees_total_sol = fees_from_partial_exits + network_fee_entry
            pos.meta["fees_total_sol"] = fees_total_sol
            
            # TASK 4: Пересчитываем realized_multiple / pnl_pct_total по ledger (executions)
            # Считаем proceeds по executions:
            # - Для partial exit: proceeds += abs(qty_delta) * xn
            # - Для final exit (time_stop): proceeds += abs(qty_delta) * (exec_price / exec_entry_price)
            original_size = pos.meta.get("original_size", pos.size)
            exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
            proceeds_total = 0.0
            
            for exit in pos.meta.get("partial_exits", []):
                exit_size = exit.get("exit_size", 0.0)
                if exit.get("is_remainder", False):
                    # Final exit (time_stop) - используем exec_price / exec_entry_price
                    exit_price = exit.get("exit_price", 0.0)
                    if exec_entry_price > 0:
                        xn = exit_price / exec_entry_price
                    else:
                        xn = 1.0
                else:
                    # Partial exit - используем xn из уровня
                    xn = exit.get("xn", 1.0)
                
                proceeds_total += exit_size * xn
            
            # Если нет partial_exits, используем fallback на fractions_exited
            if proceeds_total == 0.0:
                fractions = pos.meta.get("fractions_exited", {})
                realized_multiple = sum(float(xn) * float(frac) for xn, frac in fractions.items()) if fractions else pos.meta.get("realized_multiple", 1.0)
            else:
                # realized_multiple = proceeds_total / initial_size_sol
                if original_size > 0:
                    realized_multiple = proceeds_total / original_size
                else:
                    realized_multiple = 1.0
            
            pos.meta["realized_multiple"] = realized_multiple
            pos.pnl_pct = float(realized_multiple) - 1.0
            
            # Пересчитываем pnl_sol по формуле: pnl_sol = initial_size * (realized_multiple - 1) - fees_total_sol
            if original_size > 0:
                pnl_sol_recalculated = original_size * (realized_multiple - 1.0) - fees_total_sol
                # Используем пересчитанное значение, если оно отличается от суммы partial_exits
                # (это может быть из-за округлений или других факторов)
                pos.meta["pnl_sol"] = pnl_sol_recalculated
            
            pos.meta["close_reason"] = "time_stop" if pos.meta.get("time_stop_triggered") else "ladder_tp"
            # ВАЖНО: Помечаем, что событие POSITION_CLOSED должно быть создано в _process_position_exit
            # Это гарантирует, что событие будет создано даже если позиция уже закрыта
            pos.meta["_needs_close_event"] = True
            # НЕ добавляем в closed_positions - это будет сделано в _process_position_exit
        
        return {"balance": balance}

    def _process_position_exit(
        self,
        pos: Position,
        current_time: datetime,
        state: PortfolioState,
        positions_by_signal_id: Dict[str, Position],
        portfolio_events: Optional[List[PortfolioEvent]] = None,
        override_reason: Optional[str] = None,
    ) -> None:
        """
        Обрабатывает закрытие позиции по EXIT событию.
        
        Args:
            pos: Позиция для закрытия
            current_time: Текущее время (время EXIT события)
            state: Состояние портфеля
            positions_by_signal_id: Mapping позиций по signal_id
            override_reason: Принудительный reason для POSITION_CLOSED (если задан, имеет приоритет)
        """
        # ВАЖНО: Если позиция уже закрыта reset'ом, не перезаписываем reason
        # Но проверяем, было ли событие создано
        if pos.meta and pos.meta.get("closed_by_reset", False) and override_reason is None:
            # Позиция уже закрыта reset'ом, событие должно быть эмитчено в _apply_reset
            # Проверяем, что событие было создано (если нет, создаем его)
            if portfolio_events is not None and not pos.meta.get("close_event_id"):
                # Событие не было создано, создаем его сейчас
                close_reason = pos.meta.get("reset_reason", "manual_close")
                pnl_sol = pos.meta.get("pnl_sol", 0.0)
                fees_total = pos.meta.get("fees_total_sol", 0.0)
                raw_exit_price = pos.exit_price
                exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price)
                
                close_event = PortfolioEvent.create_position_closed(
                    timestamp=current_time,
                    strategy=pos.meta.get("strategy", "unknown"),
                    signal_id=pos.signal_id,
                    contract_address=pos.contract_address,
                    position_id=pos.position_id,
                    reason=close_reason,
                    raw_price=raw_exit_price,
                    exec_price=exec_exit_price,
                    pnl_pct=pos.pnl_pct * 100.0 if pos.pnl_pct else None,
                    pnl_sol=pnl_sol,
                    meta={
                        "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                        "exit_time": current_time.isoformat(),
                        "fees_total_sol": fees_total,
                    },
                )
                portfolio_events.append(close_event)
                pos.meta["close_event_id"] = close_event.event_id
            # Не обрабатываем повторно
            return
        
        # Проверяем, является ли позиция Runner с частичными выходами
        is_runner = pos.meta.get("runner_ladder", False)
        
        if is_runner and pos.exit_time is not None:
            # Guard: для runner_ladder=True partial exits эмитятся ТОЛЬКО из ladder-разметки
            # Проверяем, не были ли partial exits уже обработаны
            partial_exits_processed_key = "runner_partial_exits_processed"
            if pos.meta.get(partial_exits_processed_key, False):
                # Partial exits уже обработаны, пропускаем
                pass
            elif current_time >= pos.exit_time or any(
                hit_time <= current_time 
                for hit_time in (
                    datetime.fromisoformat(v) if isinstance(v, str) else v
                    for v in pos.meta.get("levels_hit", {}).values()
                )
            ):
                # Обрабатываем частичные выходы Runner (только один раз!)
                partial_exits_processed = self._process_runner_partial_exits(
                    pos=pos,
                    current_time=current_time,
                    balance=state.balance,
                    equity_curve=state.equity_curve,
                    closed_positions=state.closed_positions,
                    portfolio_events=portfolio_events,
                )
                state.balance = partial_exits_processed["balance"]
                state.peak_balance = max(state.peak_balance, state.balance)
                # Помечаем, что partial exits обработаны
                pos.meta[partial_exits_processed_key] = True
            
            # Если позиция полностью закрыта после partial exits (size <= 0), удаляем из open
            # Проверяем, не добавлена ли уже в closed_positions
            # ВАЖНО: Проверяем, не было ли событие уже создано
            if pos.size <= 1e-9:
                pos.status = "closed"
                
                # Эмитим событие POSITION_CLOSED для runner ladder позиции
                # Проверяем, не было ли событие уже создано (из _process_runner_partial_exits)
                if portfolio_events is not None and not pos.meta.get("close_event_id"):
                    # TASK B: Правильный reason для POSITION_CLOSED
                    # Если time_stop_triggered=True → "time_stop"
                    # Иначе если закрыли после ladder TP → "ladder_tp"
                    # override_reason имеет приоритет
                    if override_reason is not None:
                        close_reason = override_reason
                    elif pos.meta and pos.meta.get("time_stop_triggered", False):
                        # Финальный выход по time_stop
                        close_reason = "time_stop"
                    elif pos.meta and pos.meta.get("close_reason"):
                        # Используем close_reason из meta (установлен в _process_runner_partial_exits)
                        close_reason = pos.meta.get("close_reason")
                    else:
                        # Fallback на ladder_reason
                        close_reason = pos.meta.get("ladder_reason", "ladder_tp") if pos.meta else "ladder_tp"
                    
                    pnl_sol = pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0
                    fees_total = pos.meta.get("fees_total_sol", 0.0) if pos.meta else 0.0
                    
                    # Variant C: Если есть remainder_exit_data, используем его для правильных цен и PnL
                    remainder_data = pos.meta.get("remainder_exit_data") if pos.meta else None
                    if remainder_data:
                        # Используем данные remainder для финального закрытия
                        raw_exit_price = remainder_data.get("raw_price", pos.exit_price)
                        exec_exit_price = remainder_data.get("exec_price", pos.meta.get("exec_exit_price", pos.exit_price) if pos.meta else pos.exit_price)
                        # PnL уже пересчитан в pos.meta["pnl_sol"] из всех partial_exits, включая remainder
                    else:
                        # Обычный случай (позиция закрыта полностью на уровнях)
                        raw_exit_price = pos.exit_price
                        exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price) if pos.meta else pos.exit_price
                    
                    # Каноническое событие POSITION_CLOSED с position_id
                    close_event = PortfolioEvent.create_position_closed(
                        timestamp=current_time,
                        strategy=pos.meta.get("strategy", "unknown") if pos.meta else "unknown",
                        signal_id=pos.signal_id,
                        contract_address=pos.contract_address,
                        position_id=pos.position_id,
                        reason=close_reason,  # Используем правильный reason
                        raw_price=raw_exit_price,
                        exec_price=exec_exit_price,
                        pnl_pct=pos.pnl_pct * 100.0 if pos.pnl_pct else None,  # В процентах
                        pnl_sol=pnl_sol,
                        meta={
                            "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                            "exit_time": current_time.isoformat(),
                            "fees_total_sol": fees_total,
                            "runner_ladder": True,
                        },
                    )
                    portfolio_events.append(close_event)
                    # Сохраняем event_id для использования в reporter
                    if pos.meta:
                        pos.meta["close_event_id"] = close_event.event_id
                
                # Добавляем в closed_positions только если еще не добавлена
                if pos not in state.closed_positions:
                    state.closed_positions.append(pos)
                state.open_positions = [p for p in state.open_positions if p.signal_id != pos.signal_id]
                if pos.signal_id in positions_by_signal_id:
                    del positions_by_signal_id[pos.signal_id]
                # POSITION_CLOSED уже был эмитчен выше (строка 1479), не дублируем
                return
        
        # Обычная обработка для Runner (полное закрытие)
        if pos.exit_time is not None and current_time >= pos.exit_time:
            # Закрываем позицию нормально
            network_fee_exit = self.execution_model.network_fee()
            trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
            
            # Применяем fees к возвращаемому нотионалу
            notional_returned = pos.size + trade_pnl_sol
            notional_after_fees = self.execution_model.apply_fees(notional_returned)
            fees_total = notional_returned - notional_after_fees
            
            state.balance += notional_after_fees  # Возвращаем размер + PnL минус fees
            state.balance -= network_fee_exit  # Network fee при выходе
            m = self._ensure_meta(pos)
            m.update({
                "pnl_sol": trade_pnl_sol,
                "fees_total_sol": fees_total,
            })
            # Обновляем общий network_fee_sol (вход + выход)
            m["network_fee_sol"] = m.get("network_fee_sol", 0.0) + network_fee_exit
            
            pos.status = "closed"
            # Добавляем в closed_positions только если еще не добавлена
            if pos not in state.closed_positions:
                state.closed_positions.append(pos)
            state.open_positions = [p for p in state.open_positions if p.signal_id != pos.signal_id]
            if pos.signal_id in positions_by_signal_id:
                del positions_by_signal_id[pos.signal_id]

            # Эмитим событие POSITION_CLOSED (v2.0.1) - каноническое
            if portfolio_events is not None:
                # ВАЖНО: override_reason имеет приоритет над всеми другими источниками reason
                if override_reason is not None:
                    canonical_reason = override_reason
                else:
                    close_reason_raw = pos.meta.get("close_reason", pos.meta.get("ladder_reason", "tp")) if pos.meta else "tp"
                    # Маппинг legacy close_reason -> канонический reason
                    close_reason_map = {
                        "tp": "ladder_tp",
                        "sl": "stop_loss",
                        "timeout": "time_stop",
                        "time_stop": "time_stop",
                        "stop_loss": "stop_loss",
                        "ladder_tp": "ladder_tp",
                    }
                    canonical_reason = close_reason_map.get(close_reason_raw, close_reason_raw)
                
                pnl_sol = pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0
                fees_total = pos.meta.get("fees_total_sol", 0.0) if pos.meta else 0.0
                raw_exit_price = pos.exit_price
                exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price) if pos.meta else pos.exit_price
                
                # Каноническое событие POSITION_CLOSED (v2.0.1)
                close_event = PortfolioEvent.create_position_closed(
                    timestamp=current_time,
                    strategy=pos.meta.get("strategy", "unknown") if pos.meta else "unknown",
                    signal_id=pos.signal_id,
                    contract_address=pos.contract_address,
                    position_id=pos.position_id,
                    reason=canonical_reason,  # Используем override_reason если задан
                    raw_price=raw_exit_price,
                    exec_price=exec_exit_price,
                    pnl_pct=pos.pnl_pct * 100.0 if pos.pnl_pct else None,  # В процентах
                    pnl_sol=pnl_sol,
                    meta={
                        "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                        "exit_time": current_time.isoformat(),
                        "fees_total_sol": fees_total,
                    },
                )
                portfolio_events.append(close_event)
                # Сохраняем event_id для использования в reporter (final_exit.event_id)
                if pos.meta:
                    pos.meta["close_event_id"] = close_event.event_id

            state.peak_balance = max(state.peak_balance, state.balance)
            if pos.exit_time:
                state.equity_curve.append(
                    {"timestamp": pos.exit_time, "balance": state.balance}
                )
            
            # Обновляем equity_peak_in_cycle после закрытия позиции
            if self.config.resolved_profit_reset_enabled():
                state.update_equity_peak()

    def _try_open_position(
        self,
        trade_data: Dict[str, Any],
        current_time: datetime,
        state: PortfolioState,
        capacity_tracking: Dict[str, Any],
        positions_by_signal_id: Dict[str, Position],
        portfolio_events: List[PortfolioEvent],
    ) -> Optional[Position]:
        """
        Пытается открыть позицию для ENTRY события.
        
        Args:
            trade_data: Данные сделки (signal_id, contract_address, result: StrategyOutput)
            current_time: Текущее время (время ENTRY события)
            state: Состояние портфеля
            capacity_tracking: Dict для capacity tracking
            positions_by_signal_id: Mapping позиций по signal_id
            
        Returns:
            Position если позиция успешно открыта, иначе None
        """
        out: StrategyOutput = trade_data["result"]
        strategy_name = trade_data.get("strategy", "unknown")
        
        # Проверка лимитов портфеля
        blocked_by_capacity = False
        
        # Проверяем meta флаг blocked_by_capacity (для тестов и явной маркировки)
        if out.meta and out.meta.get("blocked_by_capacity") is True:
            blocked_by_capacity = True
            # Обновляем capacity tracking: сигнал явно помечен как blocked
            self._update_capacity_tracking(
                capacity_tracking=capacity_tracking,
                current_time=current_time,
                state=state,
                signal_blocked_by_capacity=True,
                position_closed=False,
            )
            return None
        
        # лимит по количеству позиций
        # Исключаем marker_position из проверки лимитов
        real_open_positions = [p for p in state.open_positions if not (p.meta and p.meta.get("marker", False))]
        if len(real_open_positions) >= self.config.max_open_positions:
            blocked_by_capacity = True
            # Обновляем capacity tracking: сигнал отклонен по capacity
            self._update_capacity_tracking(
                capacity_tracking=capacity_tracking,
                current_time=current_time,
                state=state,
                signal_blocked_by_capacity=True,
                position_closed=False,
            )
            return None

        # текущая экспозиция (учитываем, что баланс уже уменьшен на открытые позиции)
        total_open_notional = sum(p.size for p in state.open_positions)
        # Доступный баланс = текущий баланс (уже уменьшенный на открытые позиции)
        available_balance = state.balance
        
        # В fixed mode total_capital должен быть равен initial_balance_sol,
        # так как размер позиции рассчитывается от начального баланса.
        # В dynamic mode total_capital = available_balance + total_open_notional.
        # В fixed_then_dynamic_after_profit_reset: до reset как fixed, после reset как dynamic.
        if self.config.allocation_mode == "fixed":
            total_capital = self.config.initial_balance_sol
        elif self.config.allocation_mode == "fixed_then_dynamic_after_profit_reset":
            if state.portfolio_reset_profit_count == 0:
                total_capital = self.config.initial_balance_sol
            else:
                total_capital = available_balance + total_open_notional
        else:
            total_capital = available_balance + total_open_notional
        
        # Рассчитываем максимально допустимый размер новой позиции с учетом max_exposure
        if self.config.max_exposure >= 1.0:
            # Нет ограничения на экспозицию
            max_allowed_notional = float('inf')
        else:
            numerator = self.config.max_exposure * total_capital - total_open_notional
            if numerator <= 0:
                # Уже превышен лимит экспозиции
                max_allowed_notional = 0.0
            else:
                max_allowed_notional = numerator / (1.0 - self.config.max_exposure)

        # Размер позиции рассчитываем от доступного баланса
        desired_size = self._position_size(available_balance, state=state)
        
        # Проверяем, что желаемый размер не превышает лимит экспозиции
        if desired_size > max_allowed_notional:
            blocked_by_capacity = True
            # Обновляем capacity tracking: сигнал отклонен по capacity (exposure)
            self._update_capacity_tracking(
                capacity_tracking=capacity_tracking,
                current_time=current_time,
                state=state,
                signal_blocked_by_capacity=True,
                position_closed=False,
            )
            return None
        
        size = desired_size
        if size <= 0:
            blocked_by_capacity = True
            # Обновляем capacity tracking: сигнал отклонен (size <= 0)
            self._update_capacity_tracking(
                capacity_tracking=capacity_tracking,
                current_time=current_time,
                state=state,
                signal_blocked_by_capacity=True,
                position_closed=False,
            )
            return None
        
        # Обновляем capacity tracking: сигнал принят (не был отклонен)
        if not blocked_by_capacity:
            self._update_capacity_tracking(
                capacity_tracking=capacity_tracking,
                current_time=current_time,
                state=state,
                signal_blocked_by_capacity=False,
                position_closed=False,
            )

        # Применяем ExecutionModel: slippage к ценам и fees к нотионалу
        raw_entry_price = out.entry_price or 0.0
        raw_exit_price = out.exit_price or 0.0
        
        if raw_entry_price <= 0 or raw_exit_price <= 0:
            return None
        
        # Применяем slippage к ценам
        effective_entry_price = self.execution_model.apply_entry(raw_entry_price, "entry")
        effective_exit_price = self.execution_model.apply_exit(raw_exit_price, out.reason)
        
        # Пересчитываем PnL на основе эффективных цен (slippage уже учтен)
        raw_pnl_pct = out.pnl
        effective_pnl_pct = (effective_exit_price - effective_entry_price) / effective_entry_price
        
        # Network fee вычитается отдельно из баланса
        network_fee = self.execution_model.network_fee()
        
        # Создаем Position с эффективными ценами
        # Проверяем, является ли стратегия Runner
        is_runner = out.meta.get("runner_ladder", False)

        # Итоговый PnL (Runner uses realized_multiple, not exit_price)
        net_pnl_pct = out.pnl if is_runner else effective_pnl_pct

        # Вычитаем размер позиции и network fee из баланса при открытии
        state.balance -= size  # Платим полный размер позиции
        state.balance -= network_fee  # Network fee при входе
        
        pos_meta = {
            "strategy": strategy_name,
            "raw_pnl_pct": raw_pnl_pct,
            "raw_entry_price": raw_entry_price,
            "raw_exit_price": raw_exit_price,
            "effective_pnl_pct": effective_pnl_pct,
            "slippage_entry_pct": (effective_entry_price - raw_entry_price) / raw_entry_price if raw_entry_price > 0 else 0.0,
            "slippage_exit_pct": (raw_exit_price - effective_exit_price) / raw_exit_price if raw_exit_price > 0 else 0.0,
            "network_fee_sol": network_fee,  # Только вход, выход добавится при закрытии
            "execution_profile": self.config.execution_profile,
            # Исполненные цены (с slippage) для расчета PnL и баланса
            "exec_entry_price": effective_entry_price,
            "exec_exit_price": effective_exit_price,
            "close_reason": out.reason,
        }
        
        # Для Runner сохраняем данные о частичных выходах и original_size
        if is_runner:
            pos_meta["runner_ladder"] = True
            pos_meta["original_size"] = size  # Сохраняем оригинальный размер для расчета частичных выходов
            pos_meta["levels_hit"] = out.meta.get("levels_hit", {})
            pos_meta["fractions_exited"] = out.meta.get("fractions_exited", {})
            pos_meta["time_stop_triggered"] = out.meta.get("time_stop_triggered", False)
            pos_meta["realized_multiple"] = out.meta.get("realized_multiple", 1.0)
        
        # Сохраняем mcap_usd для capacity prune (используем entry_mcap_proxy из StrategyOutput.meta)
        if out.meta:
            entry_mcap_proxy = out.meta.get("entry_mcap_proxy")
            if entry_mcap_proxy is not None:
                pos_meta["mcap_usd"] = entry_mcap_proxy
                pos_meta["mcap_usd_at_entry"] = entry_mcap_proxy
        
        # PositionModel.entry_price и PositionModel.exit_price содержат RAW цены (для reset проверки)
        # Исполненные цены (с slippage) хранятся в meta["exec_entry_price"] и meta["exec_exit_price"]
        pos = PositionModel(
            signal_id=trade_data["signal_id"],
            contract_address=trade_data["contract_address"],
            entry_time=current_time,
            entry_price=raw_entry_price,  # RAW цена (для reset проверки)
            size=size,
            exit_time=out.exit_time,
            exit_price=raw_exit_price,  # RAW цена (для reset проверки)
            pnl_pct=net_pnl_pct,  # PnL рассчитывается по исполненным ценам (effective_pnl_pct)
            status="open",
            meta=pos_meta,
        )
        
        # Эмитим событие POSITION_OPENED с position_id
        event = PortfolioEvent.create_position_opened(
            timestamp=current_time,
            strategy=strategy_name,
            signal_id=trade_data["signal_id"],
            contract_address=trade_data["contract_address"],
            position_id=pos.position_id,
            meta={
                "size": size,
                "entry_price": raw_entry_price,
                "exec_entry_price": effective_entry_price,
                "open_positions": len(state.open_positions) + 1,
            },
        )
        portfolio_events.append(event)
        pos.meta["open_event_id"] = event.event_id
        
        return pos

    def simulate(
        self,
        all_results: List[Dict[str, Any]],
        strategy_name: str,
        blueprints: Optional[List['StrategyTradeBlueprint']] = None,
    ) -> PortfolioResult:
        """
        Основной метод симуляции по одной стратегии.

        all_results: список dict'ов: {
            "signal_id": ...,
            "contract_address": ...,
            "strategy": str,
            "timestamp": datetime (время сигнала),
            "result": StrategyOutput
        }
        
        blueprints: опциональный список StrategyTradeBlueprint для Replay режима (ЭТАП 2)
        """
        # Проверка use_replay_mode (ЭТАП 2)
        if self.config.use_replay_mode:
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
        
        # Legacy path (без изменений)
        # 1. Отфильтровать по стратегии (Runner-only: только исполненные сделки)
        trades: List[Dict[str, Any]] = []
        total_results = len(all_results)
        filtered_by_strategy = 0
        filtered_by_entry = 0
        filtered_by_window = 0
        
        for r in all_results:
            if r.get("strategy") != strategy_name:
                filtered_by_strategy += 1
                continue
            out_result = r.get("result")  # type: ignore
            if not isinstance(out_result, StrategyOutput):
                continue
            
            if out_result.entry_time is None or out_result.exit_time is None:
                filtered_by_entry += 1
                continue
            
            # Фильтрация по окну по entry_time (только для executed trades с entry_time)
            # Для attempts без entry_time используем timestamp сигнала
            trade_timestamp = out_result.entry_time if out_result.entry_time is not None else r.get("timestamp")
            if trade_timestamp:
                if self.config.backtest_start and trade_timestamp < self.config.backtest_start:
                    filtered_by_window += 1
                    continue
                if self.config.backtest_end and trade_timestamp > self.config.backtest_end:
                    filtered_by_window += 1
                    continue
            
            # Дополнительная проверка: если exit_time выходит за backtest_end, 
            # обрезаем exit_time до backtest_end (но это требует доступа к ценам, пока пропускаем)

            # NOTE: здесь можно дополнительно обрезать exit_time > backtest_end,
            # но это потребует доступа к ценам. Пока выходим, как есть.
            trades.append(r)
        
        print(f"  [portfolio] Portfolio filtering for {strategy_name}:")
        print(f"     Total results: {total_results}")
        print(f"     Filtered by strategy: {filtered_by_strategy}")
        print(f"     Filtered by entry/exit: {filtered_by_entry}")
        print(f"     Filtered by window: {filtered_by_window}")
        print(f"     Valid trades: {len(trades)}")

        if not trades:
            # Нет сделок для симуляции
            initial = self.config.initial_balance_sol
            empty_stats = PortfolioStats(
                final_balance_sol=initial,
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                trades_executed=0,
                trades_skipped_by_risk=0,
                cycle_start_balance=initial,
            )
            # Используем текущее время для equity curve, если нет сделок
            return PortfolioResult(  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
                equity_curve=[{"timestamp": datetime.now(timezone.utc), "balance": initial}],  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
                positions=[],  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
                stats=empty_stats,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            )

        # 2. Построение событий (event-driven подход)
        events: List[TradeEvent] = []
        for trade in trades:
            trade_output: StrategyOutput = trade["result"]
            trade_entry_time: Optional[datetime] = trade_output.entry_time
            trade_exit_time: Optional[datetime] = trade_output.exit_time
            if trade_entry_time is None or trade_exit_time is None:
                continue

            events.append(TradeEvent(
                event_type=EventType.ENTRY,
                event_time=trade_entry_time,
                trade_data=trade,
            ))

            events.append(TradeEvent(
                event_type=EventType.EXIT,
                event_time=trade_exit_time,
                trade_data=trade,
            ))
        
        # Сортируем события по времени (EXIT перед ENTRY на одном timestamp)
        events.sort()

        # Инициализация состояния портфеля
        initial_balance = self.config.initial_balance_sol
        state = PortfolioState(
            balance=initial_balance,
            peak_balance=initial_balance,
            open_positions=[],
            closed_positions=[],
            equity_curve=[],
            cycle_start_equity=initial_balance,  # Начало цикла = начальный баланс
            equity_peak_in_cycle=initial_balance,  # Пик equity в текущем цикле
            cycle_start_balance=initial_balance,  # Реализованный баланс в начале цикла
        )

        # Создаем marker_position для profit reset (если включен)
        marker_position: Optional[Position] = None
        if self.config.resolved_profit_reset_enabled():
            # Определяем base_time для marker_position (время первого трейда или текущее время)
            base_time = None
            if events:
                base_time = events[0].event_time
            if base_time is None:
                base_time = datetime.now(timezone.utc)
            
            # Создаем marker_position
            # ВАЖНО: marker_position.status должен быть "open" сразу после создания
            # marker_position.position_id обязателен (генерируется автоматически в Position.__init__)
            marker_position = Position(
                signal_id="__profit_reset_marker__",
                contract_address="__profit_reset_marker__",
                entry_time=base_time,
                entry_price=1.0,
                size=0.0,  # Не влияет на баланс
                status="open",  # ВАЖНО: статус должен быть "open" для корректной работы reset логики
                meta={
                    "marker": True,  # Исключаем из лимитов
                    "strategy": strategy_name,
                },
            )
            # Гарантируем, что status действительно "open" (на случай, если Position использует другие значения)
            marker_position.status = "open"
            # Добавляем marker_position в open_positions (но он не учитывается в лимитах через meta["marker"])
            state.open_positions.append(marker_position)

        # стартовая точка equity-кривой
        if events:
            first_time = events[0].event_time
            state.equity_curve.append({"timestamp": first_time, "balance": state.balance})

        skipped_by_risk = 0
        skipped_by_reset = 0
        trades_executed = 0  # Счетчик открытых позиций (инкрементируется только при ENTRY)
        
        # Инициализация capacity tracking
        capacity_tracking: Dict[str, Any] = {}
        
        # Инициализация списка событий портфеля (v1.9)
        portfolio_events: List[PortfolioEvent] = []
        
        # Mapping для быстрого поиска позиций по signal_id
        positions_by_signal_id: Dict[str, Position] = {}
        
        # Signal index для cooldown tracking (hardening v1.7.1)
        signal_index = 0

        # 3. Event-driven обработка: группируем события по времени и обрабатываем
        i = 0
        while i < len(events):
            # Группируем события на текущем timestamp
            current_time = events[i].event_time
            events_at_time: List[TradeEvent] = []
            while i < len(events) and events[i].event_time == current_time:
                events_at_time.append(events[i])
                i += 1
            
            # Обновляем equity_peak_in_cycle перед обработкой событий на текущем timestamp
            if self.config.resolved_profit_reset_enabled():
                state.update_equity_peak()
            
            # ВАЖНО: Проверяем profit reset ДО обработки EXIT событий ТОЛЬКО для equity_peak
            # Для realized_balance проверка происходит ПОСЛЕ EXIT событий (чтобы cash balance был обновлен)
            profit_reset_triggered_before_exit = False
            if (self.config.resolved_profit_reset_enabled() 
                and self.config.profit_reset_trigger_basis == "equity_peak"):
                # ВАЛИДАЦИЯ: проверяем что profit_reset_multiple валиден
                multiple = self.config.resolved_profit_reset_multiple()
                if multiple is None:
                    # multiple <= 1.0 или invalid - reset disabled, skip
                    profit_reset_triggered_before_exit = False
                else:
                    # GUARD A: baseline <= 0 → profit reset невозможен
                    # Profit reset — это политика фиксации прибыли, в минусе она не имеет смысла
                    if state.cycle_start_equity <= 0:
                        # cycle_start_equity <= 0 → threshold <= 0, условие становится "always true"
                        # Пропускаем reset чтобы избежать бесконечной петли
                        profit_reset_triggered_before_exit = False
                    # ANTI-SPAM GUARD (Guard C): нельзя повторно триггерить reset на том же timestamp
                    elif (state.last_portfolio_reset_time is not None 
                          and state.last_portfolio_reset_time == current_time):
                        # Уже был reset на этом timestamp - skip
                        profit_reset_triggered_before_exit = False
                    else:
                        reset_threshold = state.cycle_start_equity * multiple
                        if state.equity_peak_in_cycle >= reset_threshold:
                            # Собираем открытые позиции ДО обработки EXIT событий (исключаем marker)
                            open_positions_before_exit = [
                                p for p in state.open_positions 
                                if p.status == "open" and not (p.meta and p.meta.get("marker", False))
                            ]
                            
                            # GUARD B: profit reset не исполняется, если нет реальных открытых позиций
                            if len(open_positions_before_exit) == 0:
                                # Нет реальных позиций для закрытия → пропускаем reset
                                profit_reset_triggered_before_exit = False
                            else:
                                # Используем marker_position, созданный при старте, или выбираем из открытых
                                reset_marker_position = marker_position
                                if reset_marker_position is None:
                                    # Fallback: выбираем marker из открытых позиций
                                    closed_candidates = state.closed_positions
                                    open_candidates = open_positions_before_exit
                                    reset_marker_position = self._select_profit_reset_marker(
                                        state=state,
                                        closed_positions_candidates=closed_candidates,
                                        open_positions_candidates=open_candidates,
                                    )
                                
                                # Если marker_position не найден, создаем временный
                                if reset_marker_position is None:
                                    reset_marker_position = Position(
                                        signal_id="__profit_reset_marker__",
                                        contract_address="__profit_reset_marker__",
                                        entry_time=current_time,
                                        entry_price=1.0,
                                        size=0.0,
                                        status="open",
                                        meta={"marker": True, "strategy": strategy_name},
                                    )
                                    state.open_positions.append(reset_marker_position)
                                
                                # Исключаем marker из списка forced-close, если он открыт
                                if reset_marker_position.status == "open" and reset_marker_position in open_positions_before_exit:
                                    other_positions_to_force_close = [p for p in open_positions_before_exit if p.signal_id != reset_marker_position.signal_id]
                                else:
                                    other_positions_to_force_close = open_positions_before_exit
                                
                                self._apply_reset(
                                    state=state,
                                    marker_position=reset_marker_position,
                                    reset_time=current_time,
                                    positions_to_force_close=other_positions_to_force_close,
                                    reason=ResetReason.PROFIT_RESET,
                                    portfolio_events=portfolio_events,
                                )
                                profit_reset_triggered_before_exit = True
            
            # Сначала обрабатываем все EXIT события на текущем timestamp
            exit_events = [e for e in events_at_time if e.event_type == EventType.EXIT]
            for event in exit_events:
                trade_data = event.trade_data
                signal_id = trade_data["signal_id"]
                
                # Находим позицию в open_positions
                pos = positions_by_signal_id.get(signal_id)
                if pos is None or pos.status != "open":
                    continue  # Позиция уже закрыта или не найдена
                
                # Обрабатываем закрытие позиции
                self._process_position_exit(
                    pos=pos,
                    current_time=current_time,
                    state=state,
                    positions_by_signal_id=positions_by_signal_id,
                    portfolio_events=portfolio_events,
                )
            
            # Затем обрабатываем все ENTRY события на текущем timestamp
            entry_events = [e for e in events_at_time if e.event_type == EventType.ENTRY]
            for event in entry_events:
                trade_data = event.trade_data
                entry_output: StrategyOutput = trade_data["result"]
                entry_time: Optional[datetime] = entry_output.entry_time  # Может быть None для no_candles/corrupt
                signal_id = trade_data["signal_id"]
                contract_address = trade_data["contract_address"]
                strategy_name = trade_data.get("strategy", "unknown")
                
                if entry_time is None:
                    skipped_by_risk += 1
                    continue
                
                # Попытка открыть позицию
                pos = self._try_open_position(
                    trade_data=trade_data,
                    current_time=entry_time,
                    state=state,
                    capacity_tracking=capacity_tracking,
                    positions_by_signal_id=positions_by_signal_id,
                    portfolio_events=portfolio_events,  # Передаем список событий для эмиссии
                )
                
                if pos is None:
                    skipped_by_risk += 1
                    continue
                
                # Позиция успешно открыта
                state.open_positions.append(pos)
                positions_by_signal_id[pos.signal_id] = pos
                trades_executed += 1  # Инкрементируем счетчик только при открытии позиции
                signal_index += 1  # Инкрементируем signal_index для cooldown tracking (hardening v1.7.1)
                state.equity_curve.append({"timestamp": entry_time, "balance": state.balance})
                # Событие POSITION_OPENED уже эмитировано в _try_open_position
            
            # После обработки всех событий на текущем timestamp: проверяем profit reset ПЕРЕД capacity
            # Порядок приоритетов: profit reset > capacity (hardening v1.7.1)
            # НО: profit reset уже мог быть обработан ДО EXIT событий (profit_reset_triggered_before_exit) для equity_peak
            # Для realized_balance проверка происходит ПОСЛЕ EXIT событий (чтобы cash balance был обновлен)
            profit_reset_triggered = profit_reset_triggered_before_exit
            if not profit_reset_triggered_before_exit and self.config.resolved_profit_reset_enabled():
                # ВАЛИДАЦИЯ: проверяем что profit_reset_multiple валиден
                multiple = self.config.resolved_profit_reset_multiple()
                if multiple is None:
                    # multiple <= 1.0 или invalid - reset disabled
                    should_trigger = False
                else:
                    should_trigger = False
                    reset_threshold = 0.0
                    
                    # GUARD A: baseline <= 0 → profit reset невозможен
                    # Profit reset — это политика фиксации прибыли, в минусе она не имеет смысла
                    baseline = 0.0
                    if self.config.profit_reset_trigger_basis == "equity_peak":
                        baseline = state.cycle_start_equity
                    elif self.config.profit_reset_trigger_basis == "realized_balance":
                        baseline = state.cycle_start_balance
                    
                    if baseline <= 0:
                        # baseline <= 0 → threshold <= 0, условие становится "always true"
                        # Пропускаем reset чтобы избежать бесконечной петли
                        should_trigger = False
                    # ANTI-SPAM GUARD (Guard C): нельзя повторно триггерить reset на том же timestamp
                    elif (state.last_portfolio_reset_time is not None 
                          and state.last_portfolio_reset_time == current_time):
                        # Уже был reset на этом timestamp - skip
                        should_trigger = False
                    elif self.config.profit_reset_trigger_basis == "equity_peak":
                        # Legacy режим: проверка по equity_peak
                        state.update_equity_peak()
                        reset_threshold = state.cycle_start_equity * multiple
                        should_trigger = state.equity_peak_in_cycle >= reset_threshold
                    elif self.config.profit_reset_trigger_basis == "realized_balance":
                        # Новый режим: проверка по realized balance (cash) ПОСЛЕ exits
                        reset_threshold = state.cycle_start_balance * multiple
                        should_trigger = state.balance >= reset_threshold
                    
                
                if should_trigger:
                    # Формируем список позиций для принудительного закрытия
                    # ВАЖНО: собираем ВСЕ открытые позиции (status == "open" и exit_time is None или exit_time > current_time)
                    # Исключаем marker_position из реальных позиций
                    positions_to_force_close = [
                        p for p in state.open_positions 
                        if p.status == "open" 
                        and (p.exit_time is None or p.exit_time > current_time)
                        and not (p.meta and p.meta.get("marker", False))  # Исключаем marker
                    ]
                    
                    # GUARD B: profit reset не исполняется, если нет реальных открытых позиций
                    if len(positions_to_force_close) == 0:
                        # Нет реальных позиций для закрытия → пропускаем reset
                        should_trigger = False
                    else:
                        # ВАЖНО: Создаем новый marker для каждого reset (уникальный position_id)
                        # Не переиспользуем старый marker, чтобы каждый reset имел уникальный marker
                        reset_marker_position = Position(
                            signal_id="__profit_reset_marker__",
                            contract_address="__profit_reset_marker__",
                            entry_time=current_time,
                            entry_price=1.0,
                            size=0.0,
                            status="open",
                            meta={"marker": True, "strategy": strategy_name},
                        )
                        state.open_positions.append(reset_marker_position)
                        
                        self._apply_reset(
                            state=state,
                            marker_position=reset_marker_position,
                            reset_time=current_time,
                            positions_to_force_close=positions_to_force_close,
                            reason=ResetReason.PROFIT_RESET,
                            portfolio_events=portfolio_events,
                        )
                        
                        if reset_marker_position is not None:
                            self._dbg_meta(reset_marker_position, "AFTER_profit_reset_at_timestamp")
                        profit_reset_triggered = True  # Profit reset сработал
            
            # Проверка capacity reset/prune (только если profit reset не сработал)
            # Важно: profit reset имеет приоритет, capacity проверяется только если profit reset не сработал
            if self.config.capacity_reset_enabled and not profit_reset_triggered:
                if self.config.capacity_reset_mode == "prune":
                    # Режим prune: применяем частичное закрытие
                    prune_applied = self._maybe_apply_capacity_prune(
                        state=state,
                        current_time=current_time,
                        capacity_tracking=capacity_tracking,
                        signal_index=signal_index,
                        portfolio_events=portfolio_events,  # Передаем события (v1.9)
                    )
                    if prune_applied:
                        # Обновляем positions_by_signal_id после prune
                        # (позиции уже удалены из open_positions в _maybe_apply_capacity_prune)
                        pruned_signal_ids = {
                            pos.signal_id for pos in state.closed_positions
                            if pos.meta and pos.meta.get("capacity_prune", False)
                            and pos.meta.get("capacity_prune_trigger_time") == current_time.isoformat()
                        }
                        for signal_id in pruned_signal_ids:
                            if signal_id in positions_by_signal_id:
                                del positions_by_signal_id[signal_id]
                else:
                    # Режим close_all: применяем полный reset
                    capacity_reset_context = self._check_capacity_reset(
                        state=state,
                        current_time=current_time,
                        capacity_tracking=capacity_tracking,
                    )
                    if capacity_reset_context is not None:
                        # Применяем capacity reset
                        self._apply_reset(
                            state=state,
                            marker_position=capacity_reset_context.marker_position,
                            reset_time=capacity_reset_context.reset_time,
                            positions_to_force_close=capacity_reset_context.positions_to_force_close,
                            reason=ResetReason.CAPACITY_PRUNE,
                            portfolio_events=portfolio_events,
                        )
                        # Обновляем positions_by_signal_id после reset
                        for pos in capacity_reset_context.positions_to_force_close:
                            if pos.signal_id in positions_by_signal_id:
                                del positions_by_signal_id[pos.signal_id]
                        if capacity_reset_context.marker_position.signal_id in positions_by_signal_id:
                            del positions_by_signal_id[capacity_reset_context.marker_position.signal_id]
                        
                        logger.info(
                            f"[CAPACITY_RESET] Triggered at {current_time.isoformat()}: "
                            f"open_ratio={capacity_reset_context.open_ratio:.2f}, "
                            f"blocked_window={capacity_reset_context.blocked_window}, "
                            f"turnover_window={capacity_reset_context.turnover_window}"
                        )
        
        # 4. Закрываем все оставшиеся открытые позиции (финальная обработка)
        # Это нужно для позиций, у которых exit_time находится после последнего события
        # Сортируем позиции по exit_time для корректной обработки reset
        remaining_positions = sorted(
            [p for p in state.open_positions if p.exit_time is not None and p.status == "open"], 
            key=lambda p: p.exit_time if p.exit_time else datetime.max
        )
        
        # Обрабатываем оставшиеся позиции
        for pos in remaining_positions:
            if pos.status != "open":
                continue  # Позиция уже закрыта
            
            # Используем exit_time как current_time для финального закрытия
            final_exit_time = pos.exit_time if pos.exit_time else datetime.now(timezone.utc)
            
            # Обрабатываем закрытие позиции
            self._process_position_exit(
                pos=pos,
                current_time=final_exit_time,
                state=state,
                positions_by_signal_id=positions_by_signal_id,
                portfolio_events=portfolio_events,
            )
            
            # Обновляем equity_peak_in_cycle после закрытия позиции
            if self.config.resolved_profit_reset_enabled():
                state.update_equity_peak()
                
                # Проверка portfolio-level reset по equity (profit reset)
                # ВАЛИДАЦИЯ: проверяем что profit_reset_multiple валиден
                multiple = self.config.resolved_profit_reset_multiple()
                if multiple is None:
                    # multiple <= 1.0 или invalid - reset disabled, skip
                    pass
                else:
                    # GUARD A: baseline <= 0 → profit reset невозможен
                    if state.cycle_start_equity <= 0:
                        # cycle_start_equity <= 0 → threshold <= 0, условие становится "always true"
                        # Пропускаем reset чтобы избежать бесконечной петли
                        pass
                    # ANTI-SPAM GUARD (Guard C): нельзя повторно триггерить reset на том же timestamp
                    elif (state.last_portfolio_reset_time is not None 
                          and state.last_portfolio_reset_time == current_time):
                        # Уже был reset на этом timestamp - skip
                        pass
                    else:
                        reset_threshold = state.cycle_start_equity * multiple
                        if state.equity_peak_in_cycle >= reset_threshold:
                            # Формируем список позиций для принудительного закрытия (кроме той, которую уже закрываем)
                            # Исключаем marker_position из реальных позиций
                            positions_to_force_close = [
                                p for p in state.open_positions 
                                if p.signal_id != pos.signal_id 
                                and p.status == "open" 
                                and not p.meta.get("closed_by_reset")
                                and not (p.meta and p.meta.get("marker", False))  # Исключаем marker
                            ]
                            
                            # GUARD B: profit reset не исполняется, если нет реальных открытых позиций
                            if len(positions_to_force_close) == 0:
                                # Нет реальных позиций для закрытия → пропускаем reset
                                pass
                            else:
                                # Используем marker_position, созданный при старте, или выбираем из закрытых
                                reset_marker_position = marker_position
                                if reset_marker_position is None:
                                    # Fallback: выбираем marker из закрытых позиций
                                    closed_candidates = state.closed_positions + [pos]
                                    open_candidates = positions_to_force_close
                                    reset_marker_position = self._select_profit_reset_marker(
                                        state=state,
                                        closed_positions_candidates=closed_candidates,
                                        open_positions_candidates=open_candidates,
                                    )
                                
                                # Если marker_position не найден, создаем временный
                                if reset_marker_position is None:
                                    reset_marker_position = Position(
                                        signal_id="__profit_reset_marker__",
                                        contract_address="__profit_reset_marker__",
                                        entry_time=final_exit_time,
                                        entry_price=1.0,
                                        size=0.0,
                                        status="open",
                                        meta={"marker": True, "strategy": strategy_name},
                                    )
                                    state.open_positions.append(reset_marker_position)
                                
                                reset_time_portfolio = final_exit_time
                                self._apply_reset(
                                    state=state,
                                    marker_position=reset_marker_position,
                                    reset_time=reset_time_portfolio,
                                    positions_to_force_close=positions_to_force_close,
                                    reason=ResetReason.PROFIT_RESET,
                                    portfolio_events=portfolio_events,
                                )
                                if reset_marker_position is not None:
                                    self._dbg_meta(reset_marker_position, "AFTER_process_portfolio_level_reset_final_close")

        # 5. Сортируем equity curve по времени для корректного расчета drawdown
        state.equity_curve.sort(key=lambda x: x["timestamp"] if x.get("timestamp") else datetime.min)
        
        # 6. Статистика
        final_balance = state.balance
        total_return_pct = (final_balance - self.config.initial_balance_sol) / self.config.initial_balance_sol

        max_drawdown_pct = 0.0
        if state.equity_curve:
            peak = state.equity_curve[0]["balance"]
            max_dd = 0.0
            for point in state.equity_curve:
                bal = point["balance"]
                if bal > peak:
                    peak = bal
                dd = (bal - peak) / peak if peak > 0 else 0.0
                if dd < max_dd:
                    max_dd = dd
            max_drawdown_pct = max_dd

        # Обновляем equity_peak_in_cycle для финального значения
        state.update_equity_peak()
        
        # Сохраняем prune events для observability (hardening v1.7.1)
        capacity_prune_events = getattr(state, 'capacity_prune_events', [])
        
        # Пересчет счетчиков из событий (v2.0)
        if portfolio_events:
            reset_events = [
                e for e in portfolio_events
                if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
            ]
            profit_reset_events = [e for e in reset_events if e.reason == "profit_reset"]
            capacity_reset_events = [e for e in reset_events if e.reason == "capacity_prune"]
            state.portfolio_reset_profit_count = len(profit_reset_events)
            state.portfolio_reset_capacity_count = len(capacity_reset_events)
            state.portfolio_reset_count = state.portfolio_reset_profit_count + state.portfolio_reset_capacity_count
            if reset_events:
                state.last_portfolio_reset_time = max(e.timestamp for e in reset_events)

            prune_close_events = [
                e for e in portfolio_events
                if e.event_type == PortfolioEventType.POSITION_CLOSED and e.reason == "capacity_prune"
            ]
            if prune_close_events:
                state.portfolio_capacity_prune_count = len(prune_close_events)
                state.last_capacity_prune_time = max(e.timestamp for e in prune_close_events)
        
        stats = PortfolioStats(
            final_balance_sol=final_balance,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            trades_executed=trades_executed,  # Используем счетчик открытых позиций, а не len(closed_positions)
            trades_skipped_by_risk=skipped_by_risk,
            trades_skipped_by_reset=skipped_by_reset,
            portfolio_reset_count=state.portfolio_reset_count,
            last_portfolio_reset_time=state.last_portfolio_reset_time,
            portfolio_reset_profit_count=getattr(state, 'portfolio_reset_profit_count', 0),
            portfolio_reset_capacity_count=getattr(state, 'portfolio_reset_capacity_count', 0),
            cycle_start_equity=state.cycle_start_equity,
            equity_peak_in_cycle=state.equity_peak_in_cycle,
            cycle_start_balance=getattr(state, 'cycle_start_balance', state.balance),
            portfolio_capacity_prune_count=getattr(state, 'portfolio_capacity_prune_count', 0),
            last_capacity_prune_time=getattr(state, 'last_capacity_prune_time', None),
            capacity_prune_events=capacity_prune_events,
            portfolio_events=portfolio_events,  # Добавляем события портфеля (v1.9)
        )

        # Все позиции помечаем closed для консистентности
        for pos in state.closed_positions:
            pos.status = "closed"
        
        # ВАЖНО: Гарантируем, что для всех закрытых позиций есть событие POSITION_CLOSED
        # Это исправляет проблему missing_events_chain (P1)
        if portfolio_events is not None:
            closed_position_ids = {pos.position_id for pos in state.closed_positions}
            close_event_ids = {
                e.position_id for e in portfolio_events 
                if e.event_type == PortfolioEventType.POSITION_CLOSED
            }
            missing_close_events = closed_position_ids - close_event_ids
            
            # Self-check debug-лог (без изменения поведения)
            if missing_close_events:
                logger.debug(
                    f"[PORTFOLIO_SELF_CHECK] Found {len(missing_close_events)} closed positions "
                    f"without POSITION_CLOSED events: {list(missing_close_events)[:5]}"
                )
            else:
                logger.debug(
                    f"[PORTFOLIO_SELF_CHECK] All {len(closed_position_ids)} closed positions "
                    f"have POSITION_CLOSED events ({len(close_event_ids)} events found)"
                )
            
            # Для каждой позиции без события создаем его
            for pos in state.closed_positions:
                if pos.position_id in missing_close_events:
                    # Определяем reason для события
                    close_reason = "time_stop"  # По умолчанию
                    if pos.meta:
                        if pos.meta.get("closed_by_reset", False):
                            close_reason = pos.meta.get("reset_reason", "manual_close")
                        elif pos.meta.get("close_reason"):
                            close_reason = pos.meta.get("close_reason")
                        elif pos.meta.get("time_stop_triggered", False):
                            close_reason = "time_stop"
                        elif pos.meta.get("runner_ladder", False):
                            close_reason = "ladder_tp"
                    
                    # Используем exit_time или текущее время
                    exit_time = pos.exit_time if pos.exit_time else datetime.now(timezone.utc)
                    
                    pnl_sol = pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0
                    fees_total = pos.meta.get("fees_total_sol", 0.0) if pos.meta else 0.0
                    raw_exit_price = pos.exit_price if pos.exit_price else pos.entry_price
                    exec_exit_price = pos.meta.get("exec_exit_price", raw_exit_price) if pos.meta else raw_exit_price
                    
                    close_event = PortfolioEvent.create_position_closed(
                        timestamp=exit_time,
                        strategy=pos.meta.get("strategy", "unknown") if pos.meta else "unknown",
                        signal_id=pos.signal_id,
                        contract_address=pos.contract_address,
                        position_id=pos.position_id,
                        reason=close_reason,
                        raw_price=raw_exit_price,
                        exec_price=exec_exit_price,
                        pnl_pct=pos.pnl_pct * 100.0 if pos.pnl_pct else None,
                        pnl_sol=pnl_sol,
                        meta={
                            "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                            "exit_time": exit_time.isoformat(),
                            "fees_total_sol": fees_total,
                        },
                    )
                    portfolio_events.append(close_event)
                    if pos.meta:
                        pos.meta["close_event_id"] = close_event.event_id

        # Логируем момент возврата результата
        reset_positions = [p for p in state.closed_positions if p.meta.get("closed_by_reset", False)]
        self._dbg(
            "result_return",
            positions_count=len(state.closed_positions),
            reset_positions_count=len(reset_positions),
            reset_positions_signal_ids=[p.signal_id for p in reset_positions],
            portfolio_reset_count=state.portfolio_reset_count,
            cycle_start_equity=state.cycle_start_equity,
            equity_peak_in_cycle=state.equity_peak_in_cycle,
        )
        
        # Финальная проверка всех позиций перед возвратом
        for pos in state.closed_positions:
            self._dbg_meta(pos, f"FINAL_CHECK_before_return_signal_id={pos.signal_id}")

        return PortfolioResult(  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            equity_curve=state.equity_curve,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            positions=state.closed_positions,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            stats=stats,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
        )
