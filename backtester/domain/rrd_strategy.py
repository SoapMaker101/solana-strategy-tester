from __future__ import annotations
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy


class RRDStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.drawdown_pct = float(config.params.get("drawdown_entry_pct", 5)) / 100
        self.tp_pct = float(config.params.get("tp_pct", 10)) / 100
        self.sl_pct = float(config.params.get("sl_pct", 10)) / 100

    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        candles: List[Candle] = sorted(data.candles, key=lambda c: c.timestamp)

        if len(candles) == 0:
            return StrategyOutput(
                entry_time=None, entry_price=None,
                exit_time=None, exit_price=None,
                pnl=0.0, reason="no_entry",
                meta={"detail": "no candles (rrd)"}
            )

        entry = candles[0]
        exit_ = candles[-1]

        entry_price = entry.close
        exit_price = exit_.close
        pnl = (exit_price - entry_price) / entry_price

        return StrategyOutput(
            entry_time=entry.timestamp,
            entry_price=entry_price,
            exit_time=exit_.timestamp,
            exit_price=exit_price,
            pnl=pnl,
            reason="timeout",
            meta={
                "rrd_stub": True,
                "entry_idx": 0,
                "exit_idx": len(candles) - 1
            }
        )
