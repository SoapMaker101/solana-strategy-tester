from __future__ import annotations
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy


class RunnerStrategy(Strategy):
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        candles: List[Candle] = sorted(data.candles, key=lambda c: c.timestamp)

        if len(candles) == 0:
            return StrategyOutput(
                entry_time=None, entry_price=None,
                exit_time=None, exit_price=None,
                pnl=0.0, reason="no_entry",
                meta={"detail": "no candles (runner)"}
            )

        entry = candles[0]
        exit_ = candles[-1]

        pnl_pct = (exit_.close - entry.close) / entry.close

        return StrategyOutput(
            entry_time=entry.timestamp,
            entry_price=entry.close,
            exit_time=exit_.timestamp,
            exit_price=exit_.close,
            pnl=pnl_pct,
            reason="timeout",
            meta={
                "runner_stub": True,
                "entry_idx": 0,
                "exit_idx": len(candles) - 1
            }
        )
