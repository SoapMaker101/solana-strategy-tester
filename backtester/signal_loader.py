# backtester/signal_loader.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd


class SignalLoader(ABC):
    @abstractmethod
    def load_signals(self) -> List[Dict[str, Any]]:
        raise NotImplementedError


class CsvSignalLoader(SignalLoader):
    def __init__(self, path: str):
        self.path = path

    def load_signals(self) -> List[Dict[str, Any]]:
        df = pd.read_csv(self.path)
        # На фазе 1 считаем, что CSV уже нормализован
        return df.to_dict(orient="records")
