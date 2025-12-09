from __future__ import annotations
from datetime import timedelta
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy

class RRStrategy(Strategy):
    """
    Реальный RR: вход по первой свече после сигнала,
    выход по TP или SL, с возможностью дозагрузки свечей.
    """

    def __init__(self, config) -> None:
        super().__init__(config)
        self.tp_pct = float(config.params.get("tp_pct", 10)) / 100.0
        self.sl_pct = float(config.params.get("sl_pct", 10)) / 100.0
        self.max_minutes = int(config.params.get("max_minutes", 43200))  # 30 дней

    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        candles: List[Candle] = data.candles

        # Оставляем свечи после сигнала
        candles = [c for c in candles if c.timestamp >= data.signal.timestamp]
        if not candles:
            return StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "no candles after signal"},
            )

        entry_candle = candles[0]
        entry_price = entry_candle.close
        tp_price = entry_price * (1 + self.tp_pct)
        sl_price = entry_price * (1 - self.sl_pct)

        all_candles = [entry_candle]
        current_candles = candles[1:]
        next_from = all_candles[-1].timestamp + timedelta(minutes=1)

        loader = data.global_params.get("_price_loader")
        contract = data.signal.contract_address

        while True:
            for c in current_candles:
                if c.low <= sl_price:
                    return StrategyOutput(
                        entry_time=entry_candle.timestamp,
                        entry_price=entry_price,
                        exit_time=c.timestamp,
                        exit_price=sl_price,
                        pnl=(sl_price - entry_price) / entry_price,
                        reason="sl",
                        meta={"exit_idx": len(all_candles)},
                    )
                if c.high >= tp_price:
                    return StrategyOutput(
                        entry_time=entry_candle.timestamp,
                        entry_price=entry_price,
                        exit_time=c.timestamp,
                        exit_price=tp_price,
                        pnl=(tp_price - entry_price) / entry_price,
                        reason="tp",
                        meta={"exit_idx": len(all_candles)},
                    )

            all_candles.extend(current_candles)
            total_minutes = (all_candles[-1].timestamp - entry_candle.timestamp).total_seconds() / 60
            if total_minutes >= self.max_minutes:
                break

            if not loader:
                break

            # Загружаем новые свечи строго после предыдущих
            new = loader.load_prices(contract, start_time=next_from)
            # после new = loader.load_prices(...)

            new = [c for c in new if c.timestamp > all_candles[-1].timestamp]
            new = sorted(new, key=lambda c: c.timestamp)  # 🔧 обязательно сортируем


            if not new:
                break

            current_candles = new
            next_from = current_candles[-1].timestamp + timedelta(minutes=1)

        last = all_candles[-1]
        print(f"📊 Entry at {entry_candle.timestamp}, entry_price={entry_price}")
        print(f"📈 TP: {tp_price}, SL: {sl_price}")
        print(f"📉 Candles available: {len(all_candles)}")

        return StrategyOutput(
            entry_time=entry_candle.timestamp,
            entry_price=entry_price,
            exit_time=last.timestamp,
            exit_price=last.close,
            pnl=(last.close - entry_price) / entry_price,
            reason="timeout",
            meta={"exit_idx": len(all_candles)},
        )
