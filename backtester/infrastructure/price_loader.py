# backtester/infrastructure/price_loader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import pandas as pd

from ..domain.models import Candle   # ← ВАЖНО!

class PriceLoader(ABC):
    @abstractmethod
    def load_prices(
        self,
        contract_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        raise NotImplementedError


class CsvPriceLoader(PriceLoader):
    def __init__(self, candles_dir: str, timeframe: str = "1m"):
        self.candles_dir = Path(candles_dir)
        self.timeframe = timeframe

    def _build_path(self, contract_address: str) -> Path:
        filename = f"{contract_address}_{self.timeframe}.csv"
        return self.candles_dir / filename

    def load_prices(self, contract_address: str,
                    start_time=None, end_time=None) -> List[Candle]:
        path = self._build_path(contract_address)

        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")

        if start_time is not None:
            df = df[df["timestamp"] >= start_time]
        if end_time is not None:
            df = df[df["timestamp"] <= end_time]

        candles = []
        for row in df.itertuples(index=False):
            candles.append(Candle(
                timestamp=row.timestamp.to_pydatetime(),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            ))
        return candles
