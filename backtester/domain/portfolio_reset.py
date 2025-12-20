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
    EQUITY_THRESHOLD = "equity_threshold"  # Portfolio equity достигло порога
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
    """
    reason: ResetReason
    reset_time: datetime
    marker_position: Position  # Обязательно должна существовать
    positions_to_force_close: List[Position]  # Позиции для принудительного закрытия (pnl=0)
    
    def __post_init__(self):
        """Валидация контекста."""
        if self.marker_position is None:
            raise ValueError("marker_position не может быть None")
        
        # Проверяем, что marker не в списке для force-close
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
    
    def current_equity(self) -> float:
        """Текущая equity (balance + открытые позиции)."""
        return self.balance + sum(p.size for p in self.open_positions)
    
    def update_equity_peak(self) -> None:
        """Обновляет equity_peak_in_cycle до текущей equity."""
        current = self.current_equity()
        if current > self.equity_peak_in_cycle:
            self.equity_peak_in_cycle = current


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
       - closed_by_reset = True
       - triggered_portfolio_reset = True (для portfolio-level)
       - triggered_reset = True (для runner XN reset)
    
    2. Все позиции из positions_to_force_close принудительно закрываются (pnl=0)
       и помечаются closed_by_reset = True
    
    3. reset_count увеличивается на 1
    
    4. cycle_start_equity обновляется на текущий balance
    
    5. equity_peak_in_cycle сбрасывается на cycle_start_equity
    
    Args:
        context: Контекст reset операции
        state: Состояние портфеля (изменяется in-place)
        execution_model: ExecutionModel для расчета fees
    """
    # 1. Force-close позиции из positions_to_force_close
    for pos in context.positions_to_force_close:
        # Используем exec_entry_price для правильного расчета баланса
        effective_exit_price = pos.meta.get("exec_entry_price", pos.entry_price)
        exit_pnl_pct = 0.0  # PnL = 0 для принудительного закрытия
        exit_pnl_sol = 0.0
        
        # Применяем fees к возвращаемому нотионалу (только размер позиции)
        notional_returned = pos.size
        notional_after_fees = execution_model.apply_fees(notional_returned)
        fees_total = notional_returned - notional_after_fees
        network_fee_exit = execution_model.network_fee()
        
        # Возвращаем капитал
        state.balance += notional_after_fees
        state.balance -= network_fee_exit
        
        # Обновляем позицию
        pos.exit_time = context.reset_time
        # Сохраняем exec цена в meta
        pos.meta.setdefault("exec_exit_price", effective_exit_price)
        pos.pnl_pct = exit_pnl_pct
        pos.status = "closed"
        
        # ВАЖНО: используем setdefault/update, никогда не присваиваем meta = ...
        pos.meta.update({
            "pnl_sol": exit_pnl_sol,
            "fees_total_sol": fees_total,
            "closed_by_reset": True,
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
        # Portfolio-level reset: marker помечается флагами, даже если нет forced-close позиций
        marker.meta.setdefault("closed_by_reset", True)
        marker.meta.setdefault("triggered_portfolio_reset", True)
    elif context.reason == ResetReason.RUNNER_XN:
        # Runner XN reset: триггерная позиция НЕ имеет closed_by_reset (она закрывается нормально с прибылью)
        # Только остальные позиции force-close и получают closed_by_reset=True
        marker.meta.setdefault("triggered_reset", True)
        # НЕ ставим closed_by_reset для триггерной позиции при runner reset
    
    # 3. Обновляем reset tracking переменные в зависимости от типа reset
    if context.reason == ResetReason.RUNNER_XN:
        # Runner reset по XN
        state.runner_reset_count += 1
        if state.last_runner_reset_time is None or context.reset_time > state.last_runner_reset_time:
            state.last_runner_reset_time = context.reset_time
        state.reset_until = context.reset_time
    elif context.reason == ResetReason.EQUITY_THRESHOLD:
        # Portfolio-level reset по equity
        state.portfolio_reset_count += 1
        if state.last_portfolio_reset_time is None or context.reset_time > state.last_portfolio_reset_time:
            state.last_portfolio_reset_time = context.reset_time
        # Portfolio reset обновляет cycle tracking
        state.cycle_start_equity = state.balance
        state.equity_peak_in_cycle = state.cycle_start_equity

