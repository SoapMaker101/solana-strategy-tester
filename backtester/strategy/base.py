# backtester/strategy/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class StrategyConfig:
    name: str
    type: str
    params: Dict[str, Any]


class Strategy(ABC):
    def __init__(self, config: StrategyConfig):
        self.config = config

    @abstractmethod
    def on_signal(self, signal: Dict[str, Any], price_series) -> Dict[str, Any]:
        """
        Основной метод стратегии.

        :param signal: dict с данными сигнала (contract_address, timestamp и т.д.)
        :param price_series: pandas.Series/DataFrame с ценами токена
        :return: dict с результатом обработки (trade / position и т.д.)
        """
        raise NotImplementedError
