# backtester/strategy/rr.py
from __future__ import annotations

from typing import Any, Dict

from ..models import StrategyInput, StrategyOutput
from .base import Strategy


class DummyRRStrategy(Strategy):
    """
    Заглушка RR: входит по первой свече после сигнала и выходит через N свечей
    без реального TP/SL. Нужно только, чтобы проверить pipeline.
    """

    def __init__(self, name: str = "RR_dummy", params: Dict[str, Any] | None = None) -> None:
        super().__init__(name, params)
        self.hold_candles = int(self.params.get("hold_candles", 10))

    def run(self, data: StrategyInput) -> StrategyOutput:
        candles = data.candles

        if len(candles) == 0:
            # нет данных по цене — стратегия не входит
            return StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"reason_detail": "no candles"},
            )

        # Берём первую свечу после сигнала как входную
        entry_candle = candles[0]
        entry_price = entry_candle.close

        # Свеча выхода: либо через N свечей, либо последняя
        exit_index = min(self.hold_candles, len(candles) - 1)
        exit_candle = candles[exit_index]
        exit_price = exit_candle.close

        # Пока что без комиссий и слippage ⇒ PnL просто в %
        pnl_pct = (exit_price - entry_price) / entry_price

        return StrategyOutput(
            entry_time=entry_candle.timestamp,
            entry_price=entry_price,
            exit_time=exit_candle.timestamp,
            exit_price=exit_price,
            pnl=pnl_pct,
            reason="timeout",  # формально вышли по времени
            meta={
                "hold_candles": self.hold_candles,
                "entry_idx": 0,
                "exit_idx": exit_index,
            },
        )
