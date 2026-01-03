"""StrategyTradeBlueprint describes strategy intent without portfolio or money."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PartialExitBlueprint:
    """Blueprint for a partial exit from a position."""

    timestamp: datetime
    xn: float
    fraction: float

    def to_dict(self) -> dict:
        """Serialize to dictionary with ISO8601 timestamp."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "xn": self.xn,
            "fraction": self.fraction,
        }


@dataclass
class FinalExitBlueprint:
    """Blueprint for a final exit from a position."""

    timestamp: datetime
    reason: str

    def to_dict(self) -> dict:
        """Serialize to dictionary with ISO8601 timestamp."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
        }


@dataclass
class StrategyTradeBlueprint:
    """StrategyTradeBlueprint describes strategy intent without portfolio or money."""

    signal_id: str
    strategy_id: str
    contract_address: str
    entry_time: datetime
    entry_price_raw: float
    entry_mcap_proxy: Optional[float]
    partial_exits: list[PartialExitBlueprint]
    final_exit: Optional[FinalExitBlueprint]
    realized_multiple: float
    max_xn_reached: float
    reason: str

    def to_row(self) -> dict:
        """Serialize to dictionary for CSV export.

        Returns dict with keys:
        - signal_id
        - strategy_id
        - contract_address
        - entry_time (ISO string)
        - entry_price_raw
        - entry_mcap_proxy
        - partial_exits_json (JSON string)
        - final_exit_json (JSON string or empty string)
        - realized_multiple
        - max_xn_reached
        - reason
        """
        # Sort partial_exits by timestamp before serialization
        sorted_partial_exits = sorted(self.partial_exits, key=lambda x: x.timestamp)
        partial_exits_json = json.dumps([exit.to_dict() for exit in sorted_partial_exits])

        final_exit_json = json.dumps(self.final_exit.to_dict()) if self.final_exit else ""

        return {
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "contract_address": self.contract_address,
            "entry_time": self.entry_time.isoformat(),
            "entry_price_raw": self.entry_price_raw,
            "entry_mcap_proxy": self.entry_mcap_proxy,
            "partial_exits_json": partial_exits_json,
            "final_exit_json": final_exit_json,
            "realized_multiple": self.realized_multiple,
            "max_xn_reached": self.max_xn_reached,
            "reason": self.reason,
        }

