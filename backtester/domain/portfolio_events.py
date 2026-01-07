# backtester/domain/portfolio_events.py
# Portfolio Event System (v2.0.1) - Runner-only canonical events

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4


class PortfolioEventType(Enum):
    """
    Canonical event types for Runner-only pipeline (v2.0.1).
    
    Only 4 types:
    - POSITION_OPENED: Position opened
    - POSITION_PARTIAL_EXIT: Partial exit (ladder TP)
    - POSITION_CLOSED: Position closed (any reason in meta.reason)
    - PORTFOLIO_RESET_TRIGGERED: Portfolio reset triggered
    """
    POSITION_OPENED = "position_opened"
    POSITION_PARTIAL_EXIT = "position_partial_exit"
    POSITION_CLOSED = "position_closed"
    PORTFOLIO_RESET_TRIGGERED = "portfolio_reset_triggered"


@dataclass(frozen=True, kw_only=True)
class PortfolioEvent:
    """
    Canonical portfolio event (v2.0.1).

    Position events always include position_id, strategy, signal_id, timestamp, contract_address.
    Reset events also reference marker position_id for audit traceability.
    
    Invariants:
    - event_id: unique UUID (generated automatically)
    - position_id: required for all events (for reset events, use empty string or marker position_id)
    - reason: canonical taxonomy (ladder_tp, stop_loss, time_stop, capacity_prune, profit_reset, manual_close, no_entry, error)
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
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "strategy": self.strategy,
            "signal_id": self.signal_id,
            "contract_address": self.contract_address,
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
        """Create POSITION_OPENED event."""
        return cls(  # type: ignore[call-arg]
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
        level_xn: float,
        fraction: float,
        raw_price: float,
        exec_price: float,
        pnl_pct_contrib: float,
        pnl_sol_contrib: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """
        Create POSITION_PARTIAL_EXIT event (ladder TP).
        
        Args:
            level_xn: Target level (e.g., 2.0 for 2x)
            fraction: Fraction of position exited (e.g., 0.4 for 40%)
            raw_price: Market price at exit
            exec_price: Execution price (after slippage)
            pnl_pct_contrib: PnL contribution in percent (e.g., 80.0 for 80%)
            pnl_sol_contrib: PnL contribution in SOL
        """
        event_meta = meta or {}
        event_meta.update({
            "level_xn": level_xn,
            "fraction": fraction,
            "raw_price": raw_price,
            "exec_price": exec_price,
            "pnl_pct_contrib": pnl_pct_contrib,
            "pnl_sol_contrib": pnl_sol_contrib,
        })
        return cls(  # type: ignore[call-arg]
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.POSITION_PARTIAL_EXIT,
            reason="ladder_tp",
            meta=event_meta,
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
        raw_price: Optional[float] = None,
        exec_price: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        pnl_sol: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """
        Create POSITION_CLOSED event.
        
        Args:
            reason: Canonical reason (stop_loss, time_stop, capacity_prune, profit_reset, manual_close, no_entry, error)
            raw_price: Market price at exit (optional)
            exec_price: Execution price after slippage (optional)
            pnl_pct: Total PnL in percent (optional)
            pnl_sol: Total PnL in SOL (optional)
        """
        event_meta = meta or {}
        if raw_price is not None:
            event_meta["raw_price"] = raw_price
        if exec_price is not None:
            event_meta["exec_price"] = exec_price
        if pnl_pct is not None:
            event_meta["pnl_pct"] = pnl_pct
        if pnl_sol is not None:
            event_meta["pnl_sol"] = pnl_sol
        return cls(  # type: ignore[call-arg]
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.POSITION_CLOSED,
            reason=reason,
            meta=event_meta,
        )

    @classmethod
    def create_portfolio_reset_triggered(
        cls,
        *,
        timestamp: datetime,
        reason: str,
        closed_positions_count: int = 0,
        position_id: str = "",
        signal_id: str = "",
        contract_address: str = "",
        strategy: str = "portfolio",
        meta: Optional[Dict[str, Any]] = None,
    ) -> "PortfolioEvent":
        """
        Create PORTFOLIO_RESET_TRIGGERED event.
        
        Args:
            reason: Reset reason (profit_reset, capacity_prune, etc.)
            closed_positions_count: Number of positions closed by reset
            position_id: Optional marker position_id for audit traceability
        """
        event_meta = meta or {}
        event_meta.update({
            "closed_positions_count": closed_positions_count,
            "reset_reason": reason,
        })
        return cls(  # type: ignore[call-arg]
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            position_id=position_id,
            event_type=PortfolioEventType.PORTFOLIO_RESET_TRIGGERED,
            reason=reason,
            meta=event_meta,
        )
