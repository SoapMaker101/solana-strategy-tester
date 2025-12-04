# backtester/position.py
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class Position:
    signal_id: Any
    contract_address: str
    entry_time: datetime
    entry_price: float
    size: float

    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    status: str = "open"  # "open" / "closed"
    meta: Dict[str, Any] = None
