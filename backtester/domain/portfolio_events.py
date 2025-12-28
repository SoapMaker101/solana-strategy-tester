# backtester/domain/portfolio_events.py
# Portfolio Event System (v2.0) - Runner-only canonical events

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4


class PortfolioEventType(Enum):
    """
    Canonical event types for Runner-only pipeline.
    """
    
    # Attempt events
    ATTEMPT_RECEIVED = "attempt_received"  # Сигнал получен, начинаем обработку
    ATTEMPT_ACCEPTED_OPEN = "attempt_accepted_open"  # Портфель принял и открыл позицию
    ATTEMPT_REJECTED_CAPACITY = "attempt_rejected_capacity"  # Отклонено: нет места (max_open_positions)
    ATTEMPT_REJECTED_RISK = "attempt_rejected_risk"  # Отклонено: риск-правила (max_exposure, allocation, etc.)
    ATTEMPT_REJECTED_STRATEGY_NO_ENTRY = "attempt_rejected_strategy_no_entry"  # Стратегия вернула no_entry
    ATTEMPT_REJECTED_NO_CANDLES = "attempt_rejected_no_candles"  # Нет свечей для входа
    ATTEMPT_REJECTED_CORRUPT_CANDLES = "attempt_rejected_corrupt_candles"  # Битые свечи
    ATTEMPT_REJECTED_INVALID_INPUT = "attempt_rejected_invalid_input"  # Некорректный вход (нет entry_price и т.д.)
    
    # Executed events (position lifecycle)
    POSITION_OPENED = "position_opened"  # Позиция открыта
    POSITION_PARTIAL_EXIT = "position_partial_exit"  # Частичное закрытие позиции (для ladder)
    EXECUTED_CLOSE = "executed_close"  # Обычное закрытие позиции (tp/sl/timeout)
    POSITION_CLOSED = "position_closed"  # Позиция закрыта (канонический тип закрытия)
    CLOSED_BY_CAPACITY_PRUNE = "closed_by_capacity_prune"  # Закрыто prune'ом
    CLOSED_BY_PROFIT_RESET = "closed_by_profit_reset"  # Закрыто profit reset
    CLOSED_BY_CAPACITY_CLOSE_ALL = "closed_by_capacity_close_all"  # Закрыто legacy close-all
    
    # Portfolio maintenance events
    PORTFOLIO_RESET_TRIGGERED = "portfolio_reset_triggered"  # Portfolio reset триггер сработал (общий тип)
    PORTFOLIO_CYCLE_START_UPDATED = "portfolio_cycle_start_updated"  # Обновлен cycle_start_equity
    CAPACITY_PRESSURE_TRIGGERED = "capacity_pressure_triggered"  # Capacity pressure сработал (debug marker)
    CAPACITY_PRUNE_TRIGGERED = "capacity_prune_triggered"  # Prune триггер сработал
    CAPACITY_CLOSE_ALL_TRIGGERED = "capacity_close_all_triggered"  # Close-all триггер сработал
    PROFIT_RESET_TRIGGERED = "profit_reset_triggered"  # Profit reset триггер сработал


@dataclass(frozen=True, kw_only=True)
class PortfolioEvent:
    """
    Canonical portfolio event (v2.0).

    Position events always include position_id, strategy, signal_id, timestamp, contract_address.
    Reset events also reference marker position_id for audit traceability.
    """

    timestamp: datetime
    strategy: str
    signal_id: str
    contract_address: str
    event_type: PortfolioEventType
    position_id: str
    reason: Optional[str] = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "strategy": self.strategy,
            "signal_id": self.signal_id,
            "contract_address": self.contract_address,
            "position_id": self.position_id,
            "event_type": self.event_type.value,
            "position_id": self.position_id,
            "reason": self.reason,
            "meta": self.meta,
        }

    @classmethod
    def create_position_opened(
        cls,
        *,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.POSITION_OPENED,
            meta=meta or {},
        )

    @classmethod
    def create_position_partial_exit(
        cls,
        *,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.POSITION_PARTIAL_EXIT,
            reason=reason,
            meta=meta or {},
        )

    @classmethod
    def create_position_closed(
        cls,
        *,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.POSITION_CLOSED,
            reason=reason,
            meta=meta or {},
        )

    @classmethod
    def create_portfolio_reset_triggered(
        cls,
        *,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.PORTFOLIO_RESET_TRIGGERED,
            reason=reason,
            meta=meta or {},
        )
    
    @classmethod
    def create_capacity_prune_triggered(
        cls,
        timestamp: datetime,
        candidates_count: int,
        closed_count: int,
        blocked_ratio: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие CAPACITY_PRUNE_TRIGGERED."""
        event_meta = meta or {}
        event_meta.update({
            "candidates_count": candidates_count,
            "closed_count": closed_count,
            "blocked_ratio": blocked_ratio,
        })
        return cls(
            timestamp=timestamp,
            strategy="portfolio",
            signal_id="",
            contract_address="",
            event_type=PortfolioEventType.CAPACITY_PRUNE_TRIGGERED,
            reason="capacity_pressure",
            meta=event_meta,
        )
    
    @classmethod
    def create_profit_reset_triggered(
        cls,
        timestamp: datetime,
        marker_signal_id: str,
        marker_contract_address: str,
        closed_positions_count: int,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие PROFIT_RESET_TRIGGERED."""
        event_meta = meta or {}
        event_meta.update({
            "closed_positions_count": closed_positions_count,
        })
        return cls(
            timestamp=timestamp,
            strategy="portfolio",
            signal_id=marker_signal_id,
            contract_address=marker_contract_address,
            event_type=PortfolioEventType.PROFIT_RESET_TRIGGERED,
            reason="equity_threshold",
            meta=event_meta,
        )
    
    @classmethod
    def create_capacity_close_all_triggered(
        cls,
        timestamp: datetime,
        marker_signal_id: str,
        marker_contract_address: str,
        closed_positions_count: int,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие CAPACITY_CLOSE_ALL_TRIGGERED."""
        event_meta = meta or {}
        event_meta.update({
            "closed_positions_count": closed_positions_count,
        })
        return cls(
            timestamp=timestamp,
            strategy="portfolio",
            signal_id=marker_signal_id,
            contract_address=marker_contract_address,
            event_type=PortfolioEventType.CAPACITY_CLOSE_ALL_TRIGGERED,
            reason="capacity_pressure",
            meta=event_meta,
        )
    
    @classmethod
    def create_position_opened(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие POSITION_OPENED."""
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.POSITION_OPENED,
            position_id=position_id,
            reason="opened",
            meta=meta or {},
        )
    
    @classmethod
    def create_position_partial_exit(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        level: float,
        fraction: float,
        raw_price: float,
        exec_price: float,
        pnl_pct_contrib: float,
        pnl_sol_contrib: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие POSITION_PARTIAL_EXIT (для runner ladder)."""
        event_meta = meta or {}
        event_meta.update({
            "level": level,
            "fraction": fraction,
            "raw_price": raw_price,
            "exec_price": exec_price,
            "pnl_pct_contrib": pnl_pct_contrib,
            "pnl_sol_contrib": pnl_sol_contrib,
        })
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.POSITION_PARTIAL_EXIT,
            position_id=position_id,
            reason="ladder_tp",
            meta=event_meta,
        )
    
    @classmethod
    def create_position_closed(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        position_id: str,
        reason: str,
        raw_price: Optional[float] = None,
        exec_price: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        pnl_sol: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие POSITION_CLOSED (канонический тип закрытия)."""
        event_meta = meta or {}
        if raw_price is not None:
            event_meta["raw_price"] = raw_price
        if exec_price is not None:
            event_meta["exec_price"] = exec_price
        if pnl_pct is not None:
            event_meta["pnl_pct"] = pnl_pct
        if pnl_sol is not None:
            event_meta["pnl_sol"] = pnl_sol
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.POSITION_CLOSED,
            position_id=position_id,
            reason=reason,
            meta=event_meta,
        )
    
    @classmethod
    def create_portfolio_reset_triggered(
        cls,
        timestamp: datetime,
        reason: str,
        closed_positions_count: int = 0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """Создает событие PORTFOLIO_RESET_TRIGGERED."""
        event_meta = meta or {}
        event_meta.update({
            "closed_positions_count": closed_positions_count,
            "reset_reason": reason,
        })
        return cls(
            timestamp=timestamp,
            strategy="portfolio",
            signal_id="",
            contract_address="",
            event_type=PortfolioEventType.PORTFOLIO_RESET_TRIGGERED,
            reason=reason,
            meta=event_meta,
        )


