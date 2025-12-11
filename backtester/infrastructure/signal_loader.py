# backtester/infrastructure/signal_loader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import json
import pandas as pd

from ..domain.models import Signal  # Модель сигнала, используемая стратегиями и раннерами


# === Абстрактный базовый класс ===

class SignalLoader(ABC):
    """
    Абстрактный интерфейс загрузчика сигналов.
    Любая реализация (CSV, API и т.п.) должна реализовать метод load_signals.
    """

    @abstractmethod
    def load_signals(self) -> List[Signal]:
        """
        Метод должен вернуть список сигналов.
        """
        raise NotImplementedError


# === Реализация загрузки сигналов из CSV ===

class CsvSignalLoader(SignalLoader):
    """
    Загрузчик сигналов из CSV-файла.

    Поддерживаемые поля в файле:
    - id: уникальный идентификатор сигнала
    - contract_address: адрес токена
    - timestamp: ISO-время сигнала (в UTC)
    - source: откуда пришёл сигнал (e.g. "Twitter")
    - narrative: текстовое описание
    - extra_json (необязательно): JSON-строка с произвольными полями
    """

    def __init__(self, path: str):
        self.path = Path(path)  # Преобразуем путь в объект Pathlib для удобства

    def load_signals(self) -> List[Signal]:
        # Проверка наличия файла
        if not self.path.exists():
            raise FileNotFoundError(f"Signals file not found: {self.path}")

        # Читаем CSV в DataFrame
        df = pd.read_csv(self.path)

        # Обязательные колонки
        required_cols = ["id", "contract_address", "timestamp", "source", "narrative"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column '{col}' in {self.path}")

        # Преобразуем столбец timestamp в pandas datetime в UTC
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # Обработка дополнительного поля extra_json (если есть)
        if "extra_json" in df.columns:
            def parse_extra(val: Any) -> Dict[str, Any]:
                if isinstance(val, str) and val.strip():  # Пропускаем пустые строки
                    try:
                        return json.loads(val)  # Парсим строку как JSON
                    except json.JSONDecodeError:
                        # Если невалидный JSON — сохраняем с меткой ошибки
                        return {"raw": val, "parse_error": True}
                return {}

            df["extra"] = df["extra_json"].apply(parse_extra)
        else:
            # Если колонки extra_json нет — создаём пустые словари
            df["extra"] = [{} for _ in range(len(df))]

        # Преобразуем строки DataFrame в список объектов Signal
        signals: List[Signal] = []
        for row in df.itertuples(index=False):
            signals.append(
                Signal(
                    id=str(row.id),
                    contract_address=str(row.contract_address),
                    timestamp=row.timestamp.to_pydatetime(),  # pandas.Timestamp → datetime
                    source=str(row.source),
                    narrative=str(row.narrative),
                    extra=getattr(row, "extra", {}) or {},  # безопасно извлекаем поле extra
                )
            )

        # Логгируем загруженное количество
        print(f"📩 Loaded {len(signals)} signals from {self.path}")

        return signals
