#models.py
from __future__ import annotations  # Позволяет использовать аннотации типов самого себя внутри класса

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

@dataclass
class Signal:
    id: str                      # Уникальный идентификатор сигнала (например, "test1")
    contract_address: str        # Контракт токена/пула (используется для загрузки свечей)
    timestamp: datetime          # Время генерации сигнала (ключевая точка входа)
    source: str                  # Источник сигнала (например, бот, модель)
    narrative: str               # Краткое описание сигнала (для человека)
    extra: Dict[str, Any] = field(default_factory=dict)  # Доп. произвольные поля


@dataclass
class Candle:
    timestamp: datetime   # Время закрытия свечи
    open: float           # Цена открытия
    high: float           # Максимум
    low: float            # Минимум
    close: float          # Цена закрытия
    volume: float         # Объём торгов


@dataclass
class StrategyInput:
    """
    То, что получает стратегия на вход:
    - один сигнал
    - ценовой ряд вокруг этого сигнала
    - глобальные параметры теста (баланс, комиссии и т.п.)
    """
    signal: Signal                    # Исходный сигнал
    candles: List[Candle]            # Свечи, доступные для анализа стратегии
    global_params: Dict[str, Any]    # Глобальные параметры (настройки теста, price loader и т.д.)


@dataclass
class StrategyOutput:
    """
    То, что стратегия должна вернуть по результату обработки одного сигнала.
    """
    entry_time: Optional[datetime]              # Момент входа в сделку (если был)
    entry_price: Optional[float]                # Цена входа
    exit_time: Optional[datetime]               # Момент выхода
    exit_price: Optional[float]                 # Цена выхода
    pnl: float                                  # Прибыль/убыток в процентах (в десятичной форме)
    reason: str  # Причина выхода из сделки (legacy или canonical: "tp", "sl", "timeout", "ladder_tp", "stop_loss", "time_stop", "max_hold_minutes", "no_entry", "error", и т.д.)
    canonical_reason: Optional[Literal[
        "ladder_tp",
        "stop_loss",
        "time_stop",
        "capacity_prune",
        "profit_reset",
        "manual_close",
        "no_entry",
        "error",
        "max_hold_minutes",
    ]] = None  # Каноническая причина выхода из сделки (автоматически вычисляется если None)
    meta: Dict[str, Any] = field(default_factory=dict)           # Доп. информация (например, индекс свечи выхода)
    
    def __post_init__(self):
        """Автоматически вычисляет canonical_reason если не задан."""
        if self.canonical_reason is None:
            # Сначала проверяем meta["ladder_reason"] (канон в meta)
            if self.meta and isinstance(self.meta.get("ladder_reason"), str):
                ladder_reason = self.meta["ladder_reason"]
                # Проверяем, что это валидный канонический reason
                valid_canonical = {
                    "ladder_tp", "stop_loss", "time_stop", "capacity_prune",
                    "profit_reset", "manual_close", "no_entry", "error", "max_hold_minutes"
                }
                if ladder_reason in valid_canonical:
                    self.canonical_reason = ladder_reason
                    return
            
            # Валидные канонические reasons
            valid_canonical = {
                "ladder_tp", "stop_loss", "time_stop", "capacity_prune",
                "profit_reset", "manual_close", "no_entry", "error", "max_hold_minutes"
            }
            
            # Если reason уже канонический (например "ladder_tp" или "max_hold_minutes" в тестах портфеля)
            reason_str = str(self.reason).strip().lower()
            if reason_str in valid_canonical:
                self.canonical_reason = reason_str
                return
            
            # Маппинг legacy → canonical
            legacy_to_canonical = {
                "tp": "ladder_tp",
                "sl": "stop_loss",
                "timeout": "time_stop",
                "no_entry": "no_entry",
                "error": "error",
            }
            # Маппим legacy → canonical
            # Если reason не найден в маппинге и не канонический - используем как есть (может быть "max_hold_minutes" и т.д.)
            self.canonical_reason = legacy_to_canonical.get(reason_str, reason_str if reason_str in valid_canonical else "error")
