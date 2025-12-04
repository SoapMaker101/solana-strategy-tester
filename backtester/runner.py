# backtester/runner.py
from typing import List, Dict, Any

from .signal_loader import SignalLoader
from .price_loader import PriceLoader
from .reporter import Reporter
from .strategy.base import Strategy


class BacktestRunner:
    def __init__(
        self,
        signal_loader: SignalLoader,
        price_loader: PriceLoader,
        reporter: Reporter,
        strategies: List[Strategy],
        global_config: Dict[str, Any],
    ):
        self.signal_loader = signal_loader
        self.price_loader = price_loader
        self.reporter = reporter
        self.strategies = strategies
        self.global_config = global_config

    def run(self) -> None:
        signals = self.signal_loader.load_signals()

        for strategy in self.strategies:
            self._run_for_strategy(strategy, signals)

    def _run_for_strategy(self, strategy: Strategy, signals) -> None:
        results: List[Dict[str, Any]] = []

        for signal in signals:
            contract_address = signal.get("contract_address")
            if not contract_address:
                # Пока просто скипаем такие сигналы
                continue

            price_series = self.price_loader.load_prices(contract_address)
            trade_result = strategy.on_signal(signal, price_series)
            results.append(trade_result)

        self.reporter.save_results(strategy.config.name, results)
