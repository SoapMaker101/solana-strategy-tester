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

    POSITION_OPENED = "POSITION_OPENED"
    POSITION_PARTIAL_EXIT = "POSITION_PARTIAL_EXIT"
    POSITION_CLOSED = "POSITION_CLOSED"
    PORTFOLIO_RESET_TRIGGERED = "PORTFOLIO_RESET_TRIGGERED"


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
