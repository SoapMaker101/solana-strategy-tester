from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Sequence

from ..infrastructure.signal_loader import SignalLoader
from ..infrastructure.price_loader import PriceLoader
from ..domain.strategy_base import Strategy
from ..domain.models import StrategyInput, StrategyOutput, Signal, Candle


class BacktestRunner:
    def __init__(
        self,
        signal_loader: SignalLoader,
        price_loader: PriceLoader,
        reporter: Any,
        strategies: Sequence[Strategy],
        global_config: Dict[str, Any] | None = None,
    ) -> None:

        self.signal_loader = signal_loader
        self.price_loader = price_loader
        self.reporter = reporter
        self.strategies = list(strategies)
        self.global_config = global_config or {}
        self.results: List[Dict[str, Any]] = []

        data_cfg = self.global_config.get("data", {})
        self.before_minutes = int(data_cfg.get("before_minutes", 60))
        self.after_minutes = int(data_cfg.get("after_minutes", 360))

    def _load_signals(self) -> List[Signal]:
        signals = self.signal_loader.load_signals()
        if not isinstance(signals, list):
            raise ValueError("SignalLoader must return List[Signal]")
        return signals

    def run(self) -> List[Dict[str, Any]]:
        signals: List[Signal] = self._load_signals()

        for sig in signals:
            contract = sig.contract_address
            ts = sig.timestamp

            start_time = ts - timedelta(minutes=self.before_minutes)
            end_time = ts + timedelta(minutes=self.after_minutes)

            candles: List[Candle] = self.price_loader.load_prices(
                contract_address=contract,
                start_time=start_time,
                end_time=end_time,
            )

            if candles:
                print(f"⏱️ Candle range requested: {start_time} to {end_time}")
                print(f"📉 Candles available: {len(candles)}")
                if candles[0].timestamp > ts:
                    print(f"⚠️ WARNING: Signal time {ts} is earlier than first candle {candles[0].timestamp}")
            else:
                print(f"⚠️ No candles found for signal at {ts}")

            data = StrategyInput(
                signal=sig,
                candles=candles,
                global_params=self.global_config,
            )

            for strategy in self.strategies:
                try:
                    out: StrategyOutput = strategy.on_signal(data)
                except Exception as e:
                    out = StrategyOutput(
                        entry_time=None,
                        entry_price=None,
                        exit_time=None,
                        exit_price=None,
                        pnl=0.0,
                        reason="error",
                        meta={"exception": str(e)},
                    )

                self.results.append(
                    {
                        "signal_id": sig.id,
                        "contract_address": contract,
                        "strategy": strategy.config.name,
                        "timestamp": ts,
                        "result": out,
                    }
                )

        return self.results
