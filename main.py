# main.py
import argparse
from pathlib import Path
from typing import List

import yaml

from backtester.runner import BacktestRunner
from backtester.signal_loader import CsvSignalLoader
from backtester.price_loader import CsvPriceLoader
from backtester.reporter import Reporter
from backtester.strategy.base import StrategyConfig, Strategy
from backtester.strategy.rr import RRStrategy
from backtester.strategy.rrd import RRDStrategy


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
    if cfg.type.upper() == "RR":
        return RRStrategy(cfg)
    if cfg.type.upper() == "RRD":
        return RRDStrategy(cfg)

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
    report_cfg = backtest_cfg.get("report", {})

    candles_dir = data_cfg.get("candles_dir", "data/candles")
    timeframe = data_cfg.get("timeframe", "1m")
    output_dir = report_cfg.get("output_dir", "output/reports")

    signal_loader = CsvSignalLoader(args.signals)
    price_loader = CsvPriceLoader(candles_dir, timeframe=timeframe)
    reporter = Reporter(output_dir=output_dir)

    strategies = load_strategies(args.strategies_config)

    runner = BacktestRunner(
        signal_loader=signal_loader,
        price_loader=price_loader,
        reporter=reporter,
        strategies=strategies,
        global_config=backtest_cfg,
    )

    runner.run()
    print("Backtest finished.")


if __name__ == "__main__":
    main()
