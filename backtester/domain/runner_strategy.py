# backtester/strategy/runner_strategy.py
from __future__ import annotations

from typing import List

from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy



class RunnerStrategy(Strategy):
    """
    Простая стратегия: держим от первой свечи до последней.
    """
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        candles: List[Candle] = data.candles

        if len(candles) == 0:
            return StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "no candles (runner)"},
            )

        entry = candles[0]
        exit_ = candles[-1]

        entry_price = entry.close
        exit_price = exit_.close

        pnl_pct = (exit_price - entry_price) / entry_price

        return StrategyOutput(
            entry_time=entry.timestamp,
            entry_price=entry_price,
            exit_time=exit_.timestamp,
            exit_price=exit_price,
            pnl=pnl_pct,
            reason="timeout",
            meta={
                "runner_stub": True,
                "entry_idx": 0,
                "exit_idx": len(candles) - 1,
            },
        )
