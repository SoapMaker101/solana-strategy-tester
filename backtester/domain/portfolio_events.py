# backtester/domain/portfolio_events.py
# Portfolio Event System (v1.9) - Canonical event semantics

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from .strategy import StrategyOutput


class PortfolioEventType(Enum):
    """
    Типы событий портфеля (v1.9).
    
    Семантика:
    - ATTEMPT_*: попытки входа (стратегия хотела войти)
    - EXECUTED_*: реальные исполнения (позиция открыта/закрыта)
    - *_TRIGGERED: события триггеров портфеля (prune, reset, etc.)
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
    EXECUTED_CLOSE = "executed_close"  # Обычное закрытие позиции (tp/sl/timeout)
    CLOSED_BY_CAPACITY_PRUNE = "closed_by_capacity_prune"  # Закрыто prune'ом
    CLOSED_BY_PROFIT_RESET = "closed_by_profit_reset"  # Закрыто profit reset
    CLOSED_BY_CAPACITY_CLOSE_ALL = "closed_by_capacity_close_all"  # Закрыто legacy close-all
    
    # Portfolio maintenance events
    PORTFOLIO_CYCLE_START_UPDATED = "portfolio_cycle_start_updated"  # Обновлен cycle_start_equity
    CAPACITY_PRESSURE_TRIGGERED = "capacity_pressure_triggered"  # Capacity pressure сработал (debug marker)
    CAPACITY_PRUNE_TRIGGERED = "capacity_prune_triggered"  # Prune триггер сработал
    CAPACITY_CLOSE_ALL_TRIGGERED = "capacity_close_all_triggered"  # Close-all триггер сработал
    PROFIT_RESET_TRIGGERED = "profit_reset_triggered"  # Profit reset триггер сработал


@dataclass
class PortfolioEvent:
    """
    Событие портфеля (v1.9) - источник истины для всех решений портфеля.
    
    События append-only, создаются во время симуляции и хранятся в PortfolioStats.
    Используются для:
    - Расчет capacity pressure / window
    - Триггеры prune / reset
    - Backward compatibility счетчиков
    - Отладка и аналитика (portfolio_events.csv)
    """
    
    timestamp: datetime
    strategy: str
    signal_id: str
    contract_address: str
    event_type: PortfolioEventType
    reason: Optional[str] = None  # Детализация причины (например "capacity_full", "max_exposure", "tp", "sl")
    result: Optional[StrategyOutput] = None  # StrategyOutput если есть (для attempts с entry_time)
    meta: Dict[str, Any] = field(default_factory=dict)  # Дополнительные поля (blocked_by_capacity, open_positions, etc.)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Сериализация события в dict для CSV/JSON экспорта.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "strategy": self.strategy,
            "signal_id": self.signal_id,
            "contract_address": self.contract_address,
            "event_type": self.event_type.value,
            "reason": self.reason,
            "has_result": self.result is not None,
            "entry_time": self.result.entry_time.isoformat() if self.result and self.result.entry_time else None,
            "entry_price": self.result.entry_price if self.result else None,
            "meta": self.meta,
        }
    
    @classmethod
    def create_attempt_received(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        result: Optional[StrategyOutput] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PortfolioEvent:
        """Создает событие ATTEMPT_RECEIVED."""
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.ATTEMPT_RECEIVED,
            result=result,
            meta=meta or {},
        )
    
    @classmethod
    def create_attempt_accepted(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        result: StrategyOutput,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PortfolioEvent:
        """Создает событие ATTEMPT_ACCEPTED_OPEN."""
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.ATTEMPT_ACCEPTED_OPEN,
            result=result,
            reason="position_opened",
            meta=meta or {},
        )
    
    @classmethod
    def create_attempt_rejected_capacity(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        result: StrategyOutput,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PortfolioEvent:
        """Создает событие ATTEMPT_REJECTED_CAPACITY."""
        event_meta = meta or {}
        event_meta["blocked_by_capacity"] = True
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.ATTEMPT_REJECTED_CAPACITY,
            result=result,
            reason=reason,
            meta=event_meta,
        )
    
    @classmethod
    def create_attempt_rejected_risk(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        result: StrategyOutput,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PortfolioEvent:
        """Создает событие ATTEMPT_REJECTED_RISK."""
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.ATTEMPT_REJECTED_RISK,
            result=result,
            reason=reason,
            meta=meta or {},
        )
    
    @classmethod
    def create_closed_by_prune(
        cls,
        timestamp: datetime,
        strategy: str,
        signal_id: str,
        contract_address: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PortfolioEvent:
        """Создает событие CLOSED_BY_CAPACITY_PRUNE."""
        event_meta = meta or {}
        event_meta["capacity_prune"] = True
        return cls(
            timestamp=timestamp,
            strategy=strategy,
            signal_id=signal_id,
            contract_address=contract_address,
            event_type=PortfolioEventType.CLOSED_BY_CAPACITY_PRUNE,
            reason="capacity_prune",
            meta=event_meta,
        )
    
    @classmethod
    def create_capacity_prune_triggered(
        cls,
        timestamp: datetime,
        candidates_count: int,
        closed_count: int,
        blocked_ratio: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PortfolioEvent:
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
    ) -> PortfolioEvent:
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
    ) -> PortfolioEvent:
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


