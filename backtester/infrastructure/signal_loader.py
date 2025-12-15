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
    - id: уникальный идентификатор сигнала (обязательно)
    - contract_address: адрес токена (обязательно)
    - timestamp: ISO-время сигнала в UTC (обязательно)
    - source: откуда пришёл сигнал (необязательно, по умолчанию "unknown")
    - narrative: текстовое описание (необязательно, по умолчанию "")
    - extra_json (необязательно): JSON-строка с произвольными полями
    - любые другие колонки: автоматически добавляются в Signal.extra
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
        required_cols = ["id", "contract_address", "timestamp"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column '{col}' in {self.path}")

        # Преобразуем столбец timestamp в pandas datetime в UTC
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # Устанавливаем дефолтные значения для необязательных полей
        if "source" not in df.columns:
            df["source"] = "unknown"
        if "narrative" not in df.columns:
            df["narrative"] = ""

        # Базовые колонки, которые не должны попадать в extra
        base_cols = {"id", "contract_address", "timestamp", "source", "narrative", "extra_json"}

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
        for row in df.itertuples(index=False):  # type: ignore[attr-defined]
            # Начинаем с extra из extra_json (если был)
            extra = getattr(row, "extra", {}) or {}  # type: ignore[attr-defined]
            if not isinstance(extra, dict):
                extra = {}

            # Добавляем все дополнительные колонки в extra
            # Приоритет за колонками (они перезаписывают значения из extra_json)
            # Исключаем также колонку "extra", которую мы создали сами
            for col in df.columns:
                if col not in base_cols and col != "extra":
                    value = getattr(row, col, None)  # type: ignore[attr-defined]
                    # Пропускаем NaN значения
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):  # type: ignore[arg-type]
                        extra[col] = value

            # Получаем source и narrative с дефолтами
            source = getattr(row, "source", "unknown")  # type: ignore[attr-defined]
            if pd.isna(source):
                source = "unknown"
            else:
                source = str(source)

            narrative = getattr(row, "narrative", "")  # type: ignore[attr-defined]
            if pd.isna(narrative):
                narrative = ""
            else:
                narrative = str(narrative)

            # Извлекаем значения из namedtuple (itertuples создает namedtuple с именами колонок)
            row_id = getattr(row, "id", None)  # type: ignore[attr-defined]
            row_contract = getattr(row, "contract_address", None)  # type: ignore[attr-defined]
            row_timestamp = getattr(row, "timestamp", None)  # type: ignore[attr-defined]
            
            signals.append(
                Signal(
                    id=str(row_id) if row_id is not None else "",
                    contract_address=str(row_contract) if row_contract is not None else "",
                    timestamp=row_timestamp.to_pydatetime() if row_timestamp is not None else pd.Timestamp.now().to_pydatetime(),  # type: ignore[attr-defined] # pandas.Timestamp → datetime
                    source=source,
                    narrative=narrative,
                    extra=extra,
                )
            )

        # Логгируем загруженное количество
        print(f"[signals] Loaded {len(signals)} signals from {self.path}")

        return signals
