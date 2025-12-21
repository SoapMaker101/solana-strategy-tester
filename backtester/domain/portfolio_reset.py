"""
Модуль для portfolio-level reset операций.

Reset - это доменное событие, которое происходит при достижении пороговых значений equity.
Это не побочный эффект, а явная операция с четкими инвариантами.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from .position import Position


class ResetReason(Enum):
    """Причина срабатывания reset."""
    EQUITY_THRESHOLD = "equity_threshold"  # Portfolio equity достигло порога (profit reset)
    CAPACITY_PRESSURE = "capacity_pressure"  # Capacity reset: портфель забит, мало закрытий, много отклонений
    RUNNER_XN = "runner_xn"  # Runner позиция достигла XN уровня
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
    
    # Runner reset tracking
    runner_reset_count: int = 0
    last_runner_reset_time: Optional[datetime] = None
    
    # Portfolio-level reset tracking
    portfolio_reset_count: int = 0
    last_portfolio_reset_time: Optional[datetime] = None
    portfolio_reset_profit_count: int = 0  # Количество profit reset
    portfolio_reset_capacity_count: int = 0  # Количество capacity reset
    
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
    
    # Reset blocking (для runner reset по XN)
    reset_until: Optional[datetime] = None
    
    # Capacity tracking метрики (v1.6)
    blocked_by_capacity_in_window: int = 0  # Количество отклоненных сигналов по capacity за окно
    closed_in_window: int = 0  # Количество закрытых позиций за окно
    avg_hold_time_open_positions: float = 0.0  # Среднее время удержания открытых позиций (дни)
    
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
    if pos.meta and pos.meta.get("raw_exit_price") is not None:
        raw_exit = pos.meta.get("raw_exit_price")
        if raw_exit > 0:
            return raw_exit
    
    # Fallback: используем entry_price (но помечаем в meta)
    if pos.meta:
        pos.meta["reset_exit_price_fallback"] = True
    return pos.entry_price


def apply_portfolio_reset(
    context: PortfolioResetContext,
    state: PortfolioState,
    execution_model: Any,  # ExecutionModel, избегаем циклического импорта
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
       - triggered_reset = True (для runner XN reset)
    
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
        effective_exit_price = execution_model.apply_exit(raw_exit_price, "manual")
        
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
            ResetReason.EQUITY_THRESHOLD: "profit",
            ResetReason.CAPACITY_PRESSURE: "capacity",
            ResetReason.RUNNER_XN: "runner",
            ResetReason.MANUAL: "manual",
        }.get(context.reason, context.reason.value)
        
        pos.meta.update({
            "pnl_sol": exit_pnl_sol,
            "fees_total_sol": fees_total,
            "closed_by_reset": True,
            "reset_reason": reset_reason_str,
        })
        pos.meta["network_fee_sol"] = pos.meta.get("network_fee_sol", 0.0) + network_fee_exit
        
        state.closed_positions.append(pos)
        state.peak_balance = max(state.peak_balance, state.balance)
        state.equity_curve.append({"timestamp": context.reset_time, "balance": state.balance})
    
    # Удаляем закрытые позиции из open_positions
    state.open_positions = [
        p for p in state.open_positions 
        if p.signal_id not in {pos.signal_id for pos in context.positions_to_force_close}
    ]
    
    # 2. Помечаем marker_position флагами reset
    # ВАЖНО: marker_position может быть еще открыта или уже закрыта
    # НО она обязательно должна попасть в closed_positions в итоге
    marker = context.marker_position
    
    # Устанавливаем флаги в зависимости от причины
    if context.reason == ResetReason.EQUITY_THRESHOLD:
        # Portfolio-level profit reset: marker помечается флагами
        marker.meta.setdefault("closed_by_reset", True)
        marker.meta.setdefault("triggered_portfolio_reset", True)
        marker.meta.setdefault("reset_reason", "profit")
    elif context.reason == ResetReason.CAPACITY_PRESSURE:
        # Portfolio-level capacity reset: marker закрывается отдельно через market close
        # (marker не в positions_to_force_close из-за архитектурного инварианта)
        
        # Закрываем marker через market close (как и остальные позиции)
        raw_exit_price = get_mark_price_for_position(marker, context.reset_time)
        effective_exit_price = execution_model.apply_exit(raw_exit_price, "manual")
        
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
        
        # Обновляем позицию
        marker.exit_time = context.reset_time
        marker.exit_price = raw_exit_price  # Сохраняем raw цену
        marker.meta.setdefault("exec_exit_price", effective_exit_price)
        marker.pnl_pct = exit_pnl_pct
        marker.status = "closed"
        
        # Устанавливаем флаги для marker (канонические значения)
        marker.meta.update({
            "pnl_sol": exit_pnl_sol,
            "fees_total_sol": fees_total,
            "closed_by_reset": True,
            "triggered_portfolio_reset": True,
            "reset_reason": "capacity",  # Каноническое значение для capacity reset
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
    elif context.reason == ResetReason.RUNNER_XN:
        # Runner XN reset: триггерная позиция НЕ имеет closed_by_reset (она закрывается нормально с прибылью)
        # Только остальные позиции force-close и получают closed_by_reset=True
        marker.meta.setdefault("triggered_reset", True)
        marker.meta.setdefault("reset_reason", "runner")
        # НЕ ставим closed_by_reset для триггерной позиции при runner reset
    
    # 3. Обновляем reset tracking переменные в зависимости от типа reset
    if context.reason == ResetReason.RUNNER_XN:
        # Runner reset по XN
        state.runner_reset_count += 1
        if state.last_runner_reset_time is None or context.reset_time > state.last_runner_reset_time:
            state.last_runner_reset_time = context.reset_time
        state.reset_until = context.reset_time
    elif context.reason == ResetReason.EQUITY_THRESHOLD:
        # Portfolio-level profit reset
        state.portfolio_reset_count += 1
        state.portfolio_reset_profit_count = getattr(state, 'portfolio_reset_profit_count', 0) + 1
        if state.last_portfolio_reset_time is None or context.reset_time > state.last_portfolio_reset_time:
            state.last_portfolio_reset_time = context.reset_time
        # Portfolio reset обновляет cycle tracking
        state.cycle_start_equity = state.balance
        state.equity_peak_in_cycle = state.cycle_start_equity
    elif context.reason == ResetReason.CAPACITY_PRESSURE:
        # Portfolio-level capacity reset
        state.portfolio_reset_count += 1
        state.portfolio_reset_capacity_count = getattr(state, 'portfolio_reset_capacity_count', 0) + 1
        if state.last_portfolio_reset_time is None or context.reset_time > state.last_portfolio_reset_time:
            state.last_portfolio_reset_time = context.reset_time
        # Portfolio reset обновляет cycle tracking
        state.cycle_start_equity = state.balance
        state.equity_peak_in_cycle = state.cycle_start_equity

