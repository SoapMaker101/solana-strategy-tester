# backtester/strategy/rrd.py
from typing import Dict, Any
import pandas as pd

from .base import Strategy, StrategyConfig


class RRDStrategy(Strategy):
    """
    Заглушка для RRD (Risk-Reward with Drawdown).
    """

    def on_signal(self, signal: Dict[str, Any], price_series: pd.DataFrame) -> Dict[str, Any]:
        # TODO: реализовать нормальный RRD-алгоритм
        return {
            "strategy": self.config.name,
            "type": self.config.type,
            "signal_id": signal.get("id"),
            "contract_address": signal.get("contract_address"),
            "entry_time": signal.get("timestamp"),
            "exit_time": signal.get("timestamp"),
            "entry_price": float(price_series["close"].iloc[0]) if not price_series.empty else None,
            "exit_price": float(price_series["close"].iloc[-1]) if not price_series.empty else None,
            "pnl_pct": 0.0,
            "meta": {
                "params": self.config.params,
                "note": "stub RRD implementation (Phase 1 skeleton)",
            },
        }
