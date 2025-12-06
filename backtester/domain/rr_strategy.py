# backtester/strategy/rr_strategy.py
from __future__ import annotations

from typing import List

from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy
    


class RRStrategy(Strategy):
    """
    Реальный RR: вход по первой свече после сигнала,
    выход по TP или SL.
    """

    def __init__(self, config) -> None:
        super().__init__(config)
        self.tp_pct = float(config.params.get("tp_pct", 10)) / 100.0
        self.sl_pct = float(config.params.get("sl_pct", 10)) / 100.0

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
                meta={"detail": "no candles"},
            )

        entry_candle = candles[0]
        entry_price = entry_candle.close

        tp_price = entry_price * (1 + self.tp_pct)
        sl_price = entry_price * (1 - self.sl_pct)

        for idx, c in enumerate(candles[1:], start=1):
            # сначала SL
            if c.low <= sl_price:
                return StrategyOutput(
                    entry_time=entry_candle.timestamp,
                    entry_price=entry_price,
                    exit_time=c.timestamp,
                    exit_price=sl_price,
                    pnl=(sl_price - entry_price) / entry_price,
                    reason="sl",
                    meta={"exit_idx": idx},
                )

            # затем TP
            if c.high >= tp_price:
                return StrategyOutput(
                    entry_time=entry_candle.timestamp,
                    entry_price=entry_price,
                    exit_time=c.timestamp,
                    exit_price=tp_price,
                    pnl=(tp_price - entry_price) / entry_price,
                    reason="tp",
                    meta={"exit_idx": idx},
                )

        last = candles[-1]
        exit_price = last.close

        return StrategyOutput(
            entry_time=entry_candle.timestamp,
            entry_price=entry_price,
            exit_time=last.timestamp,
            exit_price=exit_price,
            pnl=(exit_price - entry_price) / entry_price,
            reason="timeout",
            meta={"exit_idx": len(candles) - 1},
        )
