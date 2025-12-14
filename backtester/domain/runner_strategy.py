from __future__ import annotations
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy
from .trade_features import (
    get_total_supply,
    calc_window_features,
    calc_trade_mcap_features,
)


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

        # Вычисляем trade features
        window_features = calc_window_features(
            candles=candles,
            entry_time=entry.timestamp,
            entry_price=entry.close,
        )
        
        # Вычисляем mcap features
        total_supply = get_total_supply(data.signal)
        mcap_features = calc_trade_mcap_features(
            entry_price=entry.close,
            exit_price=exit_.close,
            total_supply=total_supply,
        )

        # Формируем meta с features
        meta = {
            "runner_stub": True,       # Указание, что это заглушка
            "entry_idx": 0,            # Индекс входа
            "exit_idx": len(candles) - 1  # Индекс выхода
        }
        meta.update(window_features)
        meta.update(mcap_features)

        return StrategyOutput(
            entry_time=entry.timestamp,
            entry_price=entry.close,
            exit_time=exit_.timestamp,
            exit_price=exit_.close,
            pnl=pnl_pct,
            reason="timeout",  # Причина выхода — завершение периода
            meta=meta
        )
