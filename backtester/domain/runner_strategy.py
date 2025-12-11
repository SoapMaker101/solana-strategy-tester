from __future__ import annotations
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy


class RunnerStrategy(Strategy):
    """
    Stub-стратегия, имитирующая поведение "buy & hold":
    входим на первой доступной свече, выходим на последней.
    Используется как базовая модель для сравнения с другими стратегиями.
    """

    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        # Упорядочиваем свечи по времени
        candles: List[Candle] = sorted(data.candles, key=lambda c: c.timestamp)

        # Если нет свечей — ничего сделать нельзя
        if len(candles) == 0:
            return StrategyOutput(
                entry_time=None, entry_price=None,
                exit_time=None, exit_price=None,
                pnl=0.0, reason="no_entry",
                meta={"detail": "no candles (runner)"}
            )

        # Вход на первой свече
        entry = candles[0]
        # Выход на последней
        exit_ = candles[-1]

        # Расчет PnL в процентах
        pnl_pct = (exit_.close - entry.close) / entry.close

        return StrategyOutput(
            entry_time=entry.timestamp,
            entry_price=entry.close,
            exit_time=exit_.timestamp,
            exit_price=exit_.close,
            pnl=pnl_pct,
            reason="timeout",  # Причина выхода — завершение периода
            meta={
                "runner_stub": True,       # Указание, что это заглушка
                "entry_idx": 0,            # Индекс входа
                "exit_idx": len(candles) - 1  # Индекс выхода
            }
        )
