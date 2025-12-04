# backtester/price_loader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


class PriceLoader(ABC):
    """
    Базовый интерфейс загрузчика цен.
    BacktestRunner работает через этот абстрактный класс.
    """

    @abstractmethod
    def load_prices(
        self,
        contract_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Должен вернуть DataFrame со свечами по контракту.
        Минимальные колонки:
        timestamp, open, high, low, close, volume
        """
        raise NotImplementedError


class CsvPriceLoader(PriceLoader):
    """
    Загрузка свечей из локальных CSV.

    Ожидаемый формат файлов:
    - путь: <candles_dir>/<contract_address>_<timeframe>.csv
    - колонки: timestamp, open, high, low, close, volume
    """

    def __init__(self, candles_dir: str, timeframe: str = "1m"):
        self.candles_dir = Path(candles_dir)
        self.timeframe = timeframe

    def _build_path(self, contract_address: str) -> Path:
        filename = f"{contract_address}_{self.timeframe}.csv"
        return self.candles_dir / filename

    def load_prices(
        self,
        contract_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        path = self._build_path(contract_address)

        if not path.exists():
            raise FileNotFoundError(f"Candles file not found: {path}")

        df = pd.read_csv(path)

        required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column '{col}' in {path}")

        # Приводим timestamp к datetime с UTC
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # Сортируем по времени
        df = df.sort_values("timestamp")

        # Фильтруем по окну [start_time, end_time], если оно задано
        if start_time is not None:
            start_ts = pd.to_datetime(start_time).tz_convert(df["timestamp"].dt.tz)
            df = df[df["timestamp"] >= start_ts]

        if end_time is not None:
            end_ts = pd.to_datetime(end_time).tz_convert(df["timestamp"].dt.tz)
            df = df[df["timestamp"] <= end_ts]

        return df.reset_index(drop=True)
