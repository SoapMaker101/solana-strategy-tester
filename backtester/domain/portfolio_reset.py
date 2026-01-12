"""
Модуль для portfolio-level reset операций.

Reset - это доменное событие, которое происходит при достижении пороговых значений equity.
Это не побочный эффект, а явная операция с четкими инвариантами.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from .position import Position
from .execution_model import ExecutionModel

logger = logging.getLogger(__name__)


class ResetReason(Enum):
    """Причина срабатывания reset."""
    PROFIT_RESET = "profit_reset"  # Portfolio equity достигло порога (profit reset)
    CAPACITY_PRUNE = "capacity_prune"  # Capacity prune: частичное/полное закрытие плохих позиций
    MANUAL = "manual"  # Ручной reset (для расширения в будущем)


@dataclass
class PortfolioResetContext:
    """
    Контекст для выполнения portfolio reset.
    
    Инкапсулирует всю информацию, необходимую для reset операции:
    - Причина reset
    - Время reset
    - Marker position (позиция, логически вызвавшая reset)
    - Позиции для принудительного закрытия
    - Опциональные debug поля для capacity reset
    """
    reason: ResetReason
    reset_time: datetime
    marker_position: Position  # Обязательно должна существовать
    positions_to_force_close: List[Position]  # Позиции для принудительного закрытия (market close)
    # Опциональные debug поля для capacity reset
    open_ratio: Optional[float] = None
    blocked_window: Optional[int] = None
    turnover_window: Optional[int] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    
    def __post_init__(self):
        """Валидация контекста."""
        if self.marker_position is None:
            raise ValueError("marker_position не может быть None")
        
        # Проверяем, что marker не в списке для force-close (архитектурный инвариант)
        marker_id = self.marker_position.signal_id
        if any(p.signal_id == marker_id for p in self.positions_to_force_close):
            raise ValueError(
                f"marker_position (signal_id={marker_id}) не должна быть в positions_to_force_close"
            )


@dataclass
class PortfolioState:
    """
    Состояние портфеля в процессе симуляции.
    
    Инкапсулирует все изменяемое состояние, которое передается между методами.
    Это делает код более читаемым и тестируемым.
    """
    balance: float
    peak_balance: float
    open_positions: List[Position]
    closed_positions: List[Position]
    equity_curve: List[Dict[str, Any]]
    
    # Portfolio-level reset tracking
    portfolio_reset_count: int = 0
    last_portfolio_reset_time: Optional[datetime] = None
    portfolio_reset_profit_count: int = 0  # Количество profit reset
    portfolio_reset_capacity_count: int = 0  # Количество capacity reset
    
    # Capacity prune tracking (v1.7)
    portfolio_capacity_prune_count: int = 0  # Количество срабатываний capacity prune
    last_capacity_prune_time: Optional[datetime] = None  # Время последнего capacity prune
    
    # Обратная совместимость
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
    
    # Capacity tracking метрики (v1.6)
    blocked_by_capacity_in_window: int = 0  # Количество отклоненных сигналов по capacity за окно
    closed_in_window: int = 0  # Количество закрытых позиций за окно
    avg_hold_time_open_positions: float = 0.0  # Среднее время удержания открытых позиций (дни)
    
    # Capacity prune cooldown tracking (v1.7.1)
    capacity_prune_cooldown_until_signal_index: Optional[int] = None  # Cooldown до signal index
    capacity_prune_cooldown_until_time: Optional[datetime] = None  # Cooldown до времени (опционально)
    
    # Capacity prune observability (v1.7.1)
    capacity_prune_events: List[Dict[str, Any]] = field(default_factory=list)  # Список событий prune для статистики
    
    def current_equity(self) -> float:
        """Текущая equity (balance + открытые позиции)."""
        return self.balance + sum(p.size for p in self.open_positions)
    
    def update_equity_peak(self) -> None:
        """Обновляет equity_peak_in_cycle до текущей equity."""
        current = self.current_equity()
        if current > self.equity_peak_in_cycle:
            self.equity_peak_in_cycle = current


def get_mark_price_for_position(pos: Position, reset_time: datetime) -> float:
    """
    Получает текущую цену для позиции на момент reset.
    
    Использует последнюю доступную цену:
    1. Если есть exit_price в позиции (из StrategyOutput) - используем его
    2. Если есть raw_exit_price в meta - используем его
    3. Иначе fallback на entry_price (должно быть видно в meta: reset_exit_price_fallback=True)
    
    Args:
        pos: Позиция для получения цены
        reset_time: Время reset (для будущего расширения с price_loader)
        
    Returns:
        Текущая цена для закрытия позиции
    """
    # Приоритет 1: exit_price из позиции (если есть)
    if pos.exit_price is not None and pos.exit_price > 0:
        return pos.exit_price
    
    # Приоритет 2: raw_exit_price из meta
    if pos.meta:
        raw_exit = pos.meta.get("raw_exit_price")
        if raw_exit is not None and raw_exit > 0:
            return float(raw_exit)
    
    # Fallback: используем entry_price (но помечаем в meta)
    if pos.meta:
        pos.meta["reset_exit_price_fallback"] = True
    return pos.entry_price


def apply_portfolio_reset(
    context: PortfolioResetContext,
    state: PortfolioState,
    execution_model: ExecutionModel,  # ExecutionModel from execution_model.py
) -> None:
    """
    Применяет portfolio reset согласно контексту.
    
    Это ЕДИНСТВЕННАЯ точка, где:
    - изменяется reset_count
    - изменяются cycle_start_equity и equity_peak_in_cycle
    - устанавливаются reset-флаги на позициях
    
    Инварианты:
    1. marker_position ОБЯЗАТЕЛЬНО помечается флагами:
       - closed_by_reset = True (для portfolio-level reset)
       - triggered_portfolio_reset = True (для portfolio-level reset)
    
    2. Все позиции из positions_to_force_close закрываются market close
       (используется текущая цена через execution_model, не pnl=0)
       и помечаются closed_by_reset = True
    
    3. reset_count увеличивается на 1
    
    4. cycle_start_equity обновляется на текущий balance
    
    5. equity_peak_in_cycle сбрасывается на cycle_start_equity
    
    Args:
        context: Контекст reset операции
        state: Состояние портфеля (изменяется in-place)
        execution_model: ExecutionModel для расчета fees и slippage
    """
    # 1. Force-close позиции из positions_to_force_close (market close)
    for pos in context.positions_to_force_close:
        # Получаем текущую цену для закрытия
        raw_exit_price = get_mark_price_for_position(pos, context.reset_time)
        
        # Применяем slippage к цене выхода (используем reason="manual" для reset)
        effective_exit_price = execution_model.apply_exit(raw_exit_price, "manual_close")
        
        # Вычисляем PnL на основе исполненных цен (market close)
        exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
        exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price if exec_entry_price > 0 else 0.0
        exit_pnl_sol = pos.size * exit_pnl_pct
        
        # Применяем fees к возвращаемому нотионалу
        notional_returned = pos.size + exit_pnl_sol
        notional_after_fees = execution_model.apply_fees(notional_returned)
        fees_total = notional_returned - notional_after_fees
        network_fee_exit = execution_model.network_fee()
        
        # Возвращаем капитал
        state.balance += notional_after_fees
        state.balance -= network_fee_exit
        
        # Обновляем позицию
        pos.exit_time = context.reset_time
        pos.exit_price = raw_exit_price  # Сохраняем raw цену
        # Сохраняем exec цены в meta
        pos.meta.setdefault("exec_exit_price", effective_exit_price)
        pos.pnl_pct = exit_pnl_pct
        pos.status = "closed"
        
        # ВАЖНО: используем setdefault/update, никогда не присваиваем meta = ...
        # Маппинг ResetReason -> каноническое значение для meta/CSV
        reset_reason_str = {
            ResetReason.PROFIT_RESET: "profit_reset",
            ResetReason.CAPACITY_PRUNE: "capacity_prune",
            ResetReason.MANUAL: "manual_close",
        }.get(context.reason, context.reason.value)
        
        pos.meta.update({
            "pnl_sol": exit_pnl_sol,
            "fees_total_sol": fees_total,
            "closed_by_reset": True,
            "reset_reason": reset_reason_str,
            "close_reason": reset_reason_str,
        })
        pos.meta["network_fee_sol"] = pos.meta.get("network_fee_sol", 0.0) + network_fee_exit
        
        state.closed_positions.append(pos)
        state.peak_balance = max(state.peak_balance, state.balance)
        state.equity_curve.append({"timestamp": context.reset_time, "balance": state.balance})
    
    # Удаляем закрытые позиции из open_positions (после цикла)
    if context.positions_to_force_close:
        closed_signal_ids = {pos.signal_id for pos in context.positions_to_force_close}
        state.open_positions = [
            p for p in state.open_positions 
            if p.signal_id not in closed_signal_ids
        ]
    
    # 2. Помечаем marker_position флагами reset
    # ВАЖНО: marker_position может быть еще открыта или уже закрыта
    # НО она обязательно должна попасть в closed_positions в итоге
    marker = context.marker_position
    
    # Убеждаемся, что meta существует
    if marker.meta is None:
        marker.meta = {}
    
    # MARKER ECONOMICS: marker НЕ должен влиять на баланс (size=0.0)
    # Marker — служебный объект только для ledger/traceability
    # Вариант A (предпочтительно): marker вообще не создаёт executions и не списывает fees
    # Для marker: fees_total = 0, network_fee_exit = 0, pnl_sol = 0
    is_marker = marker.meta.get("marker", False) or marker.signal_id == "__profit_reset_marker__"
    
    if is_marker:
        # Marker: нулевая экономика (не влияет на баланс)
        exit_pnl_pct = 0.0
        exit_pnl_sol = 0.0
        fees_total = 0.0
        network_fee_exit = 0.0
        notional_after_fees = 0.0
        raw_exit_price = marker.entry_price if marker.entry_price > 0 else 1.0
        effective_exit_price = raw_exit_price
        # НЕ изменяем balance для marker
    else:
        # Реальная позиция: нормальная обработка
        raw_exit_price = get_mark_price_for_position(marker, context.reset_time)
        effective_exit_price = execution_model.apply_exit(raw_exit_price, "manual_close")

        # Вычисляем PnL на основе исполненных цен (market close)
        exec_entry_price = marker.meta.get("exec_entry_price", marker.entry_price)
        exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price if exec_entry_price > 0 else 0.0
        exit_pnl_sol = marker.size * exit_pnl_pct

        # Применяем fees к возвращаемому нотионалу
        notional_returned = marker.size + exit_pnl_sol
        notional_after_fees = execution_model.apply_fees(notional_returned)
        fees_total = notional_returned - notional_after_fees
        network_fee_exit = execution_model.network_fee()

        # Возвращаем капитал
        state.balance += notional_after_fees
        state.balance -= network_fee_exit

    # Обновляем позицию (marker или реальная)
    marker.exit_time = context.reset_time
    marker.exit_price = raw_exit_price
    marker.meta.setdefault("exec_exit_price", effective_exit_price)
    marker.pnl_pct = exit_pnl_pct
    marker.status = "closed"

    reset_reason_str = "profit_reset" if context.reason == ResetReason.PROFIT_RESET else "capacity_prune"
    marker.meta.update({
        "pnl_sol": exit_pnl_sol,
        "fees_total_sol": fees_total,
        "closed_by_reset": True,
        "triggered_portfolio_reset": True,
        "reset_reason": reset_reason_str,
        "close_reason": reset_reason_str,
    })
    marker.meta["network_fee_sol"] = marker.meta.get("network_fee_sol", 0.0) + network_fee_exit

    # Добавляем marker в closed_positions
    state.closed_positions.append(marker)
    state.peak_balance = max(state.peak_balance, state.balance)
    state.equity_curve.append({"timestamp": context.reset_time, "balance": state.balance})

    # Удаляем marker из open_positions
    state.open_positions = [
        p for p in state.open_positions
        if p.signal_id != marker.signal_id
    ]
    
    # 3. Обновляем reset tracking переменные в зависимости от типа reset
    if context.reason == ResetReason.PROFIT_RESET:
        # Portfolio-level profit reset
        state.portfolio_reset_count += 1
        state.portfolio_reset_profit_count = getattr(state, 'portfolio_reset_profit_count', 0) + 1
        if state.last_portfolio_reset_time is None or context.reset_time > state.last_portfolio_reset_time:
            state.last_portfolio_reset_time = context.reset_time
        state.cycle_start_equity = state.balance
        state.equity_peak_in_cycle = state.cycle_start_equity
        state.cycle_start_balance = state.balance  # Обновляем cycle_start_balance для realized_balance trigger
    elif context.reason == ResetReason.CAPACITY_PRUNE:
        # Portfolio-level capacity reset (close-all or prune)
        state.portfolio_reset_count += 1
        state.portfolio_reset_capacity_count = getattr(state, 'portfolio_reset_capacity_count', 0) + 1
        if state.last_portfolio_reset_time is None or context.reset_time > state.last_portfolio_reset_time:
            state.last_portfolio_reset_time = context.reset_time
        state.cycle_start_equity = state.balance
        state.equity_peak_in_cycle = state.cycle_start_equity
        state.cycle_start_balance = state.balance  # Обновляем cycle_start_balance для consistency
