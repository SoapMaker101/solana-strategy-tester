#models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional


@dataclass
class Signal:
    id: str
    contract_address: str
    timestamp: datetime
    source: str
    narrative: str
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class StrategyInput:
    """
    То, что получает стратегия на вход:
    - один сигнал
    - ценовой ряд вокруг этого сигнала
    - глобальные параметры теста (баланс, комиссии и т.п.)
    """
    signal: Signal
    candles: List[Candle]
    global_params: Dict[str, Any]


@dataclass
class StrategyOutput:
    """
    То, что стратегия должна вернуть по результату обработки одного сигнала.
    """
    entry_time: Optional[datetime]
    entry_price: Optional[float]
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    pnl: float
    reason: Literal["tp", "sl", "timeout", "no_entry", "error"]
    meta: Dict[str, Any] = field(default_factory=dict)
