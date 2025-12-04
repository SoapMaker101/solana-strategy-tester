# backtester/runner.py
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Sequence

import pandas as pd

from .signal_loader import SignalLoader
from .price_loader import PriceLoader
from .strategy.base import Strategy


class BacktestRunner:
    """
    Простой раннер:

    - Берёт сигналы из SignalLoader
    - Для каждого сигнала загружает окно свечей через PriceLoader
    - Прогоняет все стратегии: strategy.on_signal(signal_dict, price_df)
    - Складывает результаты в self.results
    """

    def __init__(
        self,
            signal_loader: SignalLoader,
            price_loader: PriceLoader,
            reporter: Any,
            strategies: Sequence[Strategy],
            global_config: Dict[str, Any] | None = None,
    ) -> None:
        self.signal_loader = signal_loader
        self.price_loader = price_loader
        self.reporter = reporter  # пока не трогаем, просто храним
        self.strategies = list(strategies)
        self.global_config = global_config or {}
        self.results: List[Dict[str, Any]] = []

        # Разбираем глобальный конфиг (если есть)
        data_cfg = self.global_config.get("data", {})
        self.before_minutes = int(data_cfg.get("before_minutes", 60))
        self.after_minutes = int(data_cfg.get("after_minutes", 360))

    def _load_signals(self) -> pd.DataFrame:
        df = self.signal_loader.load_signals()

        required_cols = ["id", "contract_address", "timestamp"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(
                    f"Signals DataFrame is missing required column '{col}'"
                )

        # гарантируем datetime с таймзоной
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        return df

    def run(self) -> List[Dict[str, Any]]:
        """
        Основной запуск бэктеста.
        Возвращает список результатов по всем стратегиям и сигналам.
        """
        signals_df = self._load_signals()

        for _, row in signals_df.iterrows():
            contract = str(row["contract_address"])
            ts = pd.to_datetime(row["timestamp"], utc=True).to_pydatetime()

            start_time = ts - timedelta(minutes=self.before_minutes)
            end_time = ts + timedelta(minutes=self.after_minutes)

            # Загружаем окно цен
            prices_df = self.price_loader.load_prices(
                contract_address=contract,
                start_time=start_time,
                end_time=end_time,
            )

            signal_dict = row.to_dict()

            for strategy in self.strategies:
                try:
                    result = strategy.on_signal(signal_dict, prices_df)
                except Exception as e:
                    result = {
                        "error": str(e),
                        "traceback": repr(e),
                    }

                self.results.append(
                    {
                        "signal_id": signal_dict.get("id"),
                        "contract_address": contract,
                        "strategy": getattr(strategy, "config", None).name
                        if getattr(strategy, "config", None) is not None
                        else getattr(strategy, "name", type(strategy).__name__),
                        "timestamp": ts,
                        "result": result,
                    }
                )

        # На этом этапе можно было бы дернуть репортер, но пока не знаем его интерфейс.
        # Просто вернём результаты.
        return self.results
