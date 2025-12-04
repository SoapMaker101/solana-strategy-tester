# backtester/price_loader.py
from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path

import pandas as pd


class PriceLoader(ABC):
    @abstractmethod
    def load_prices(self, contract_address: str) -> pd.DataFrame:
        raise NotImplementedError


class CsvPriceLoader(PriceLoader):
    """
    Ожидается формат: data/candles/{contract}_{timeframe}.csv
    """

    def __init__(self, base_dir: str, timeframe: str = "1m"):
        self.base_dir = Path(base_dir)
        self.timeframe = timeframe

    def _build_path(self, contract_address: str) -> Path:
        filename = f"{contract_address}_{self.timeframe}.csv"
        return self.base_dir / filename

    def load_prices(self, contract_address: str) -> pd.DataFrame:
        path = self._build_path(contract_address)
        if not path.exists():
            # На Фазе 1 просто возвращаем пустой DataFrame
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.read_csv(path)
        return df
