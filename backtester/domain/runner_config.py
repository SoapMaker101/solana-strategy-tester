from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any

from .strategy_base import StrategyConfig


@dataclass
class RunnerTakeProfitLevel:
    """
    Уровень тейк-профита для Runner стратегии.
    
    Attributes:
        xn: Множитель от цены входа (например, 2.0 означает 2x от входа)
        fraction: Доля позиции, закрываемая на этом уровне (0..1)
    """
    xn: float
    fraction: float


@dataclass
class RunnerConfig(StrategyConfig):
    """
    Конфигурация для Runner стратегии с лестницей тейк-профитов.
    
    Наследуется от StrategyConfig и добавляет структурированные поля
    для параметров Runner стратегии.
    
    Attributes:
        take_profit_levels: Список уровней тейк-профита
        time_stop_minutes: Максимальное время удержания позиции в минутах (None = без ограничения)
        use_high_for_targets: Ориентироваться на HIGH как триггер для TP
        exit_on_first_tp: Если True — закрывать всю позицию на первом TP (для сравнения)
        allow_partial_fills: Для симуляции частичных фиксаций
    """
    take_profit_levels: List[RunnerTakeProfitLevel]
    time_stop_minutes: int | None
    use_high_for_targets: bool = True
    exit_on_first_tp: bool = False
    allow_partial_fills: bool = True
    
    def __post_init__(self):
        """Устанавливает name по умолчанию, если не указан."""
        if not self.name or self.name == "":
            self.name = "Runner"


def create_runner_config_from_dict(
    name: str,
    params: Dict[str, Any]
) -> RunnerConfig:
    """
    Создает RunnerConfig из словаря параметров (из YAML).
    
    Args:
        name: Имя стратегии
        params: Словарь параметров из YAML
        
    Returns:
        RunnerConfig с распарсенными параметрами
    """
    # Парсим take_profit_levels
    take_profit_levels = []
    if "take_profit_levels" in params:
        for level_dict in params["take_profit_levels"]:
            take_profit_levels.append(
                RunnerTakeProfitLevel(
                    xn=float(level_dict["xn"]),
                    fraction=float(level_dict["fraction"])
                )
            )
    
    # Парсим остальные параметры
    time_stop_minutes = params.get("time_stop_minutes")
    if time_stop_minutes is not None:
        time_stop_minutes = int(time_stop_minutes)
    
    use_high_for_targets = params.get("use_high_for_targets", True)
    exit_on_first_tp = params.get("exit_on_first_tp", False)
    allow_partial_fills = params.get("allow_partial_fills", True)
    
    return RunnerConfig(
        name=name,
        type="RUNNER",
        params=params,  # Сохраняем оригинальные params для совместимости
        take_profit_levels=take_profit_levels,
        time_stop_minutes=time_stop_minutes,
        use_high_for_targets=use_high_for_targets,
        exit_on_first_tp=exit_on_first_tp,
        allow_partial_fills=allow_partial_fills
    )





















