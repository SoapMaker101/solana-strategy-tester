# backtester/signal_loader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

import json
import pandas as pd


class SignalLoader(ABC):
    """
    Базовый интерфейс загрузчика сигналов.
    BacktestRunner работает через этот абстрактный класс.
    """

    @abstractmethod
    def load_signals(self) -> pd.DataFrame:
        """
        Должен вернуть DataFrame с колонками как минимум:
        id, contract_address, timestamp, source, narrative

        Можно добавлять свои поля (extra и т.п.).
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

    def load_signals(self) -> pd.DataFrame:
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

        return df
    
    def load_signals_from_csv(path: str) -> pd.DataFrame:
        """
        Функция-обёртка для старого интерфейса.
        Используется в runner.py: from .signal_loader import load_signals_from_csv
        """
        loader = CsvSignalLoader(path)
        return loader.load_signals()