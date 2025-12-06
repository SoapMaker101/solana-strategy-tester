# main.py
import argparse
from pathlib import Path
from typing import List

import yaml

from backtester.application.runner import BacktestRunner
from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.infrastructure.price_loader import CsvPriceLoader

from backtester.domain.strategy_base import StrategyConfig, Strategy
from backtester.domain.rr_strategy import RRStrategy
from backtester.domain.rrd_strategy import RRDStrategy
from backtester.domain.runner_strategy import RunnerStrategy


def parse_args():
    parser = argparse.ArgumentParser(description="Solana strategy backtester")
    parser.add_argument(
        "--signals",
        type=str,
        default="signals/example_signals.csv",
        help="Path to signals CSV",
    )
    parser.add_argument(
        "--strategies-config",
        type=str,
        default="config/strategies_example.yaml",
        help="YAML with strategies configs",
    )
    parser.add_argument(
        "--backtest-config",
        type=str,
        default="config/backtest_example.yaml",
        help="Global backtest config (YAML)",
    )
    return parser.parse_args()


def load_yaml(path: str):
    path_obj = Path(path)
    if not path_obj.exists():
        return {}
    with path_obj.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_strategy(cfg: StrategyConfig) -> Strategy:
    t = cfg.type.upper()
    if t == "RR":
        return RRStrategy(cfg)
    if t == "RRD":
        return RRDStrategy(cfg)
    if t == "RUNNER":
        return RunnerStrategy(cfg)

    raise ValueError(f"Unknown strategy type: {cfg.type}")


def load_strategies(config_path: str) -> List[Strategy]:
    data = load_yaml(config_path)
    strategies: List[Strategy] = []

    for s in data:
        cfg = StrategyConfig(
            name=s["name"],
            type=s["type"],
            params=s.get("params", {}),
        )
        strategies.append(build_strategy(cfg))

    return strategies


def main():
    args = parse_args()

    backtest_cfg = load_yaml(args.backtest_config)
    data_cfg = backtest_cfg.get("data", {})

    candles_dir = data_cfg.get("candles_dir", "data/candles")
    timeframe = data_cfg.get("timeframe", "1m")

    signal_loader = CsvSignalLoader(args.signals)
    price_loader = CsvPriceLoader(candles_dir, timeframe=timeframe)

    strategies = load_strategies(args.strategies_config)

    runner = BacktestRunner(
        signal_loader=signal_loader,
        price_loader=price_loader,
        reporter=None,          # пока не используем
        strategies=strategies,
        global_config=backtest_cfg,
    )

    results = runner.run()
    print(f"Backtest finished. Results count: {len(results)}")
    # для контроля выведем пару строк
    for row in results[:3]:
        print(row)


if __name__ == "__main__":
    main()
