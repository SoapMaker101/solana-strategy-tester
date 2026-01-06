"""
Backward-compatible API для RunnerConfig.

Этот модуль предоставляет совместимые классы и функции для работы с конфигурацией Runner стратегии.
В Этапе 3 структура конфигурации изменилась, но тесты и legacy код все еще используют старый API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .strategy_base import StrategyConfig


@dataclass
class RunnerTakeProfitLevel:
    """
    Уровень тейк-профита для Runner стратегии.
    
    Attributes:
        xn: Целевой множитель (например, 2.0 для 2x)
        fraction: Доля позиции для закрытия на этом уровне (например, 0.4 для 40%)
    """
    xn: float
    fraction: float


@dataclass
class RunnerConfig(StrategyConfig):
    """
    Конфигурация Runner стратегии.
    
    Наследуется от StrategyConfig для совместимости с базовым классом Strategy.
    Расширяет StrategyConfig специфичными для Runner полями.
    
    Attributes:
        name: Имя стратегии
        type: Тип стратегии (должен быть "RUNNER")
        params: Словарь параметров (для обратной совместимости)
        take_profit_levels: Список уровней тейк-профита
        use_high_for_targets: Использовать HIGH свечи для определения достижения уровней
    """
    take_profit_levels: List[RunnerTakeProfitLevel] = field(default_factory=list)
    use_high_for_targets: bool = True
    
    def __post_init__(self):
        """Инициализация после создания dataclass."""
        # Устанавливаем type если не задан
        if not hasattr(self, 'type') or self.type is None:
            self.type = "RUNNER"
        # Инициализируем params если не задан
        if not hasattr(self, 'params') or self.params is None:
            self.params = {}


def create_runner_config_from_dict(
    name: str,
    params: Dict[str, Any],
) -> RunnerConfig:
    """
    Создает RunnerConfig из словаря параметров (backward-compatible API).
    
    Args:
        name: Имя стратегии
        params: Словарь параметров, содержащий:
            - take_profit_levels: список словарей с ключами "xn" и "fraction"
            - use_high_for_targets: bool (опционально, по умолчанию True)
            - time_stop_minutes: int или None (deprecated, игнорируется)
    
    Returns:
        RunnerConfig объект
    
    Example:
        >>> config = create_runner_config_from_dict(
        ...     "test_runner",
        ...     {
        ...         "take_profit_levels": [
        ...             {"xn": 2.0, "fraction": 0.4},
        ...             {"xn": 5.0, "fraction": 0.4},
        ...             {"xn": 10.0, "fraction": 0.2},
        ...         ],
        ...         "use_high_for_targets": True,
        ...     }
        ... )
    """
    # Извлекаем take_profit_levels
    take_profit_levels_data = params.get("take_profit_levels", [])
    take_profit_levels = [
        RunnerTakeProfitLevel(
            xn=float(level.get("xn", 0.0)),
            fraction=float(level.get("fraction", 0.0)),
        )
        for level in take_profit_levels_data
    ]
    
    # Извлекаем use_high_for_targets (по умолчанию True)
    use_high_for_targets = params.get("use_high_for_targets", True)
    
    # time_stop_minutes игнорируется (удален в Этапе 3)
    # Но не вызываем ошибку, если он присутствует для обратной совместимости
    
    # Создаем RunnerConfig
    config = RunnerConfig(
        name=name,
        type="RUNNER",
        params=params,  # Сохраняем оригинальные params для обратной совместимости
        take_profit_levels=take_profit_levels,
        use_high_for_targets=use_high_for_targets,
    )
    
    return config
