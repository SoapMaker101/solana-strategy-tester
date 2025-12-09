# backtester/infrastructure/signal_loader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import json
import pandas as pd

from ..domain.models import Signal


class SignalLoader(ABC):
    """
    Базовый интерфейс загрузчика сигналов.
    Application-слой работает через этот абстрактный класс.
    """

    @abstractmethod
    def load_signals(self) -> List[Signal]:
        """
        Должен вернуть список Signal.
        """
        raise NotImplementedError


class CsvSignalLoader(SignalLoader):
    """
    Загрузка сигналов из CSV-файла.

    Ожидаемые колонки:
    - id
    - contract_address
    - timestamp  (в формате ISO8601, например 2024-06-01T10:00:00Z)
    - source
    - narrative
    - extra_json (опционально, JSON-строка с доп. полями)
    """

    def __init__(self, path: str):
        self.path = Path(path)

    def load_signals(self) -> List[Signal]:
        if not self.path.exists():
            raise FileNotFoundError(f"Signals file not found: {self.path}")

        df = pd.read_csv(self.path)

        required_cols = ["id", "contract_address", "timestamp", "source", "narrative"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column '{col}' in {self.path}")

        # timestamp → datetime с UTC
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # Если есть колонка extra_json — распарсим в dict
        if "extra_json" in df.columns:
            def parse_extra(val: Any) -> Dict[str, Any]:
                if isinstance(val, str) and val.strip():
                    try:
                        return json.loads(val)
                    except json.JSONDecodeError:
                        return {"raw": val, "parse_error": True}
                return {}

            df["extra"] = df["extra_json"].apply(parse_extra)
        else:
            df["extra"] = [{} for _ in range(len(df))]

        signals: List[Signal] = []
        for row in df.itertuples(index=False):
            signals.append(
                Signal(
                    id=str(row.id),
                    contract_address=str(row.contract_address),
                    timestamp=row.timestamp.to_pydatetime(),
                    source=str(row.source),
                    narrative=str(row.narrative),
                    extra=getattr(row, "extra", {}) or {},
                )
            )
        print(f"📩 Loaded {len(signals)} signals from {self.path}")

        return signals
    
