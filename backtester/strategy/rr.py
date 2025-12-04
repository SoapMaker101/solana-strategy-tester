# backtester/strategy/rr.py
from typing import Dict, Any
import pandas as pd

from .base import Strategy, StrategyConfig


class RRStrategy(Strategy):
    """
    Простейший заглушечный RR (Risk-Reward) для Фазы 1.
    Дальше заменим реальной логикой.
    """

    def on_signal(self, signal: Dict[str, Any], price_series: pd.DataFrame) -> Dict[str, Any]:
        # TODO: реализовать нормальный RR-алгоритм
        return {
            "strategy": self.config.name,
            "type": self.config.type,
            "signal_id": signal.get("id"),
            "contract_address": signal.get("contract_address"),
            "entry_time": signal.get("timestamp"),
            "exit_time": signal.get("timestamp"),  # временная заглушка
            "entry_price": float(price_series["close"].iloc[0]) if not price_series.empty else None,
            "exit_price": float(price_series["close"].iloc[-1]) if not price_series.empty else None,
            "pnl_pct": 0.0,
            "meta": {
                "params": self.config.params,
                "note": "stub RR implementation (Phase 1 skeleton)",
            },
        }
