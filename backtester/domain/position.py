# backtester/position.py
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class Position:
    signal_id: Any                        # Идентификатор сигнала, по которому была открыта позиция
    contract_address: str                 # Адрес токена/контракта, к которому относится позиция
    entry_time: datetime                  # Время входа в позицию
    entry_price: float                    # Цена входа
    size: float                           # Размер позиции (может быть в токенах, долларах и т.д.)

    exit_time: Optional[datetime] = None         # Время выхода из позиции (если закрыта)
    exit_price: Optional[float] = None           # Цена выхода (если закрыта)
    pnl_pct: Optional[float] = None              # Прибыль/убыток в процентах (может быть None до закрытия)
    status: str = "open"                         # Статус позиции: "open" или "closed"
    meta: Dict[str, Any] = None                  # Дополнительные данные: причина выхода, стратегия и пр.
