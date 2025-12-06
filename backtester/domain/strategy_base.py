# backtester/domain/strategy_base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from .models import StrategyInput, StrategyOutput  # ← ВАЖНО: .models, а не ..models


@dataclass
class StrategyConfig:
    name: str
    type: str
    params: Dict[str, Any]


class Strategy(ABC):
    """
    Базовый интерфейс стратегии.
    Все конкретные стратегии должны реализовать on_signal.
    """

    def __init__(self, config: StrategyConfig):
        self.config = config

    @abstractmethod
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        """
        Основной метод стратегии.

        :param data: StrategyInput (signal + candles + global_params)
        :return: StrategyOutput
        """
        raise NotImplementedError
