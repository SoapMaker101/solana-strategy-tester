# main.py
import argparse
import json
from pathlib import Path
from typing import List
from datetime import datetime

import yaml

from backtester.application.runner import BacktestRunner
from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.infrastructure.price_loader import CsvPriceLoader, GeckoTerminalPriceLoader
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
    parser.add_argument(
        "--json-output",
        type=str,
        default="output/results.json",
        help="Optional path to save JSON output"
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
    return [build_strategy(StrategyConfig(
        name=s["name"],
        type=s["type"],
        params=s.get("params", {})
    )) for s in data]


def main():
    args = parse_args()

    backtest_cfg = load_yaml(args.backtest_config)
    data_cfg = backtest_cfg.get("data", {})

    candles_dir = data_cfg.get("candles_dir", "data/candles")
    timeframe = data_cfg.get("timeframe", "1m")

    signal_loader = CsvSignalLoader(args.signals)

    if data_cfg.get("loader", "csv") == "gecko":
        price_loader = GeckoTerminalPriceLoader(
            cache_dir=candles_dir,
            timeframe=timeframe
        )
    else:
        price_loader = CsvPriceLoader(
            candles_dir=candles_dir,
            timeframe=timeframe
        )

    strategies = load_strategies(args.strategies_config)

    runner = BacktestRunner(
        signal_loader=signal_loader,
        price_loader=price_loader,
        reporter=None,
        strategies=strategies,
        global_config=backtest_cfg,
    )

    results = runner.run()
    print(f"Backtest finished. Results count: {len(results)}")
    for row in results:
        r = row["result"]
        print(f"🔁 {row['strategy']} → entry: {r.entry_price}, exit: {r.exit_price}, pnl: {round(r.pnl*100, 2)}%, reason: {r.reason}")

    try:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        **{
                            **row,
                            "timestamp": row["timestamp"].isoformat() if isinstance(row["timestamp"], datetime) else row["timestamp"],
                            "result": {
                                "entry_time": r.entry_time.isoformat() if r.entry_time else None,
                                "entry_price": r.entry_price,
                                "exit_time": r.exit_time.isoformat() if r.exit_time else None,
                                "exit_price": r.exit_price,
                                "pnl": r.pnl,
                                "reason": r.reason,
                                "meta": r.meta,
                            },
                        }
                    }
                    for row in results
                    for r in [row["result"]]
                ],
                f,
                indent=2
            )
        print(f"📤 Saved JSON output to {output_path}")
    except Exception as e:
        print(f"⚠️ Failed to save JSON output: {e}")


if __name__ == "__main__":
    main()
