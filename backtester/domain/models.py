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
    reason: Literal["tp", "sl", "timeout", "no_entry", "error"]  # Причина выхода из сделки
    meta: Dict[str, Any] = field(default_factory=dict)           # Доп. информация (например, индекс свечи выхода)
