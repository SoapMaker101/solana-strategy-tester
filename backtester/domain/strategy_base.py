from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from .models import StrategyInput, StrategyOutput  # Импортируем модели, используемые в стратегиях


@dataclass
class StrategyConfig:
    """
    Конфигурация стратегии, получаемая из YAML:
    - name: человекочитаемое имя стратегии
    - type: тип стратегии (RUNNER)
    - params: словарь параметров, передаваемых в конкретную реализацию
    """
    name: str
    type: str
    params: Dict[str, Any]


class Strategy(ABC):
    """
    Абстрактный базовый класс (ABC) для всех стратегий.
    Все стратегии должны реализовать метод on_signal().
    """

    def __init__(self, config: StrategyConfig):
        # Сохраняем конфигурацию (имя, тип, параметры)
        self.config = config

    @abstractmethod
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        """
        Основной метод стратегии.
        Принимает входной набор данных по сигналу, свечам и глобальным параметрам.

        :param data: StrategyInput — структура с сигналом, ценовым рядом и глобальными параметрами
        :return: StrategyOutput — структура с результатами работы стратегии
        """
        raise NotImplementedError  # Обязательно к реализации в наследниках
