# backtester/domain/position.py
from dataclasses import dataclass, field
from uuid import uuid4
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
from uuid import uuid4


class PositionStatus(Enum):
    """Статус позиции."""
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class Position:
    """
    Позиция в портфеле.
    
    Инварианты:
    1. Position - это identity: один объект живет от entry до финального result
    2. meta всегда существует (никогда не None)
    3. meta никогда не теряется: используем только setdefault/update, никогда не присваиваем meta = ...
    4. position_id - уникальный идентификатор позиции (uuid4 hex), генерируется автоматически
    """
    signal_id: Any                        # Идентификатор сигнала, по которому была открыта позиция
    contract_address: str                 # Адрес токена/контракта, к которому относится позиция
    entry_time: datetime                  # Время входа в позицию
    entry_price: float                    # Цена входа
    size: float                           # Размер позиции в SOL (номинал)
    position_id: str = field(default_factory=lambda: uuid4().hex)  # Уникальный идентификатор позиции

    exit_time: Optional[datetime] = None         # Время выхода из позиции (если закрыта)
    exit_price: Optional[float] = None           # Цена выхода (если закрыта)
    pnl_pct: Optional[float] = None              # Прибыль/убыток в процентах (может быть None до закрытия)
    status: str = "open"                         # Статус позиции: "open" или "closed"
    meta: Dict[str, Any] = field(default_factory=dict)  # Дополнительные данные: причина выхода, стратегия и пр.
    
    def __post_init__(self):
        """Гарантируем, что meta всегда существует."""
        if self.meta is None:
            self.meta = {}
        if not self.position_id:
            self.position_id = uuid4().hex
    
    def mark_closed_by_reset(self) -> None:
        """
        Помечает позицию как закрытую по reset.
        
        ВАЖНО: использует setdefault, чтобы не перезаписать существующий флаг.
        """
        self.meta.setdefault("closed_by_reset", True)
    
    def mark_triggered_reset(self) -> None:
        """
        Помечает позицию как триггерную для runner reset по XN.
        
        ВАЖНО: использует setdefault, чтобы не перезаписать существующий флаг.
        """
        self.meta.setdefault("triggered_reset", True)
    
    def mark_triggered_portfolio_reset(self) -> None:
        """
        Помечает позицию как триггерную для portfolio-level reset.
        
        ВАЖНО: использует setdefault, чтобы не перезаписать существующий флаг.
        """
        self.meta.setdefault("triggered_portfolio_reset", True)
    
    def is_closed_by_reset(self) -> bool:
        """Проверяет, закрыта ли позиция по reset."""
        return self.meta.get("closed_by_reset", False)
    
    def has_triggered_reset(self) -> bool:
        """Проверяет, является ли позиция триггерной для runner reset."""
        return self.meta.get("triggered_reset", False)
    
    def has_triggered_portfolio_reset(self) -> bool:
        """Проверяет, является ли позиция триггерной для portfolio-level reset."""
        return self.meta.get("triggered_portfolio_reset", False)
