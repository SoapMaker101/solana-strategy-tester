# main.py
# main.py — точка входа для запуска системы бэктестинга стратегий Solana

import argparse                         # Для обработки аргументов командной строки
import json                             # Для сохранения результатов в формате JSON
from pathlib import Path                # Удобная работа с путями к файлам и директориям
from typing import List
from datetime import datetime
import yaml                             # Для загрузки YAML конфигураций

# Импорт основных компонентов бэктестера
from backtester.application.runner import BacktestRunner  # Главный исполнитель бэктеста

# Загрузчики сигналов и цен
from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.infrastructure.price_loader import CsvPriceLoader, GeckoTerminalPriceLoader

# Reporter для генерации отчетов
from backtester.infrastructure.reporter import Reporter

# Базовая стратегия и конкретные реализации стратегий
from backtester.domain.strategy_base import StrategyConfig, Strategy
from backtester.domain.rr_strategy import RRStrategy
from backtester.domain.rrd_strategy import RRDStrategy
from backtester.domain.runner_strategy import RunnerStrategy


def parse_args():
    """
    Разбирает аргументы, переданные при запуске скрипта из командной строки.
    """
    parser = argparse.ArgumentParser(description="Solana strategy backtester")

    parser.add_argument(
        "--signals",
        type=str,
        default="signals/example_signals.csv",
        help="Путь к CSV-файлу с сигналами"
    )
    parser.add_argument(
        "--strategies-config",
        type=str,
        default="config/strategies_example.yaml",
        help="YAML-файл с описанием стратегий"
    )
    parser.add_argument(
        "--backtest-config",
        type=str,
        default="config/backtest_example.yaml",
        help="YAML-файл с глобальными настройками бэктеста"
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default="output/results.json",
        help="Путь для сохранения JSON-отчета"
    )
    return parser.parse_args()


def load_yaml(path: str):
    """
    Загружает YAML-файл по указанному пути.
    Возвращает словарь или пустой словарь, если файл не найден.
    """
    path_obj = Path(path)
    if not path_obj.exists():
        return {}
    with path_obj.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_strategy(cfg: StrategyConfig) -> Strategy:
    """
    По типу стратегии создает и возвращает соответствующий объект стратегии.
    """
    t = cfg.type.upper()
    if t == "RR":
        return RRStrategy(cfg)
    if t == "RRD":
        return RRDStrategy(cfg)
    if t == "RUNNER":
        return RunnerStrategy(cfg)
    raise ValueError(f"Unknown strategy type: {cfg.type}")


def load_strategies(config_path: str) -> List[Strategy]:
    """
    Загружает стратегии из YAML-файла и инициализирует каждый класс стратегии.
    """
    data = load_yaml(config_path)
    return [build_strategy(StrategyConfig(
        name=s["name"],
        type=s["type"],
        params=s.get("params", {})
    )) for s in data]



def main():
    args = parse_args()  # Получаем аргументы запуска

    # Загружаем глобальные настройки бэктеста
    backtest_cfg = load_yaml(args.backtest_config)
    data_cfg = backtest_cfg.get("data", {})

    # Извлекаем настройки загрузки свечей
    candles_dir = data_cfg.get("candles_dir", "data/candles")
    timeframe = data_cfg.get("timeframe", "1m")

    # Загружаем сигналы из CSV
    signal_loader = CsvSignalLoader(args.signals)
    signals = signal_loader.load_signals()  # Загружаем один раз для использования в Reporter
    signal_map = {s.id: s for s in signals}  # Создаем карту для быстрого доступа

    # Выбираем загрузчик цен: либо Gecko API, либо CSV
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

    # Загружаем стратегии
    strategies = load_strategies(args.strategies_config)

    # Создаем Reporter для генерации отчетов
    report_cfg = backtest_cfg.get("report", {})
    output_dir = report_cfg.get("output_dir", "output/reports")
    reporter = Reporter(output_dir=output_dir)

    # Получаем настройки параллельной обработки
    runtime_cfg = backtest_cfg.get("runtime", {})
    parallel = runtime_cfg.get("parallel", False)
    max_workers = runtime_cfg.get("max_workers", 4)

    # Создаем и запускаем бэктест
    runner = BacktestRunner(
        signal_loader=signal_loader,
        price_loader=price_loader,
        reporter=reporter,
        strategies=strategies,
        global_config=backtest_cfg,
        parallel=parallel,
        max_workers=max_workers,
    )

    # Запуск стратегий
    results = runner.run()
    print(f"Backtest finished. Results count: {len(results)}")

    # Группируем результаты по стратегиям и генерируем отчеты
    from collections import defaultdict
    results_by_strategy = defaultdict(list)
    
    for row in results:
        # Добавляем информацию о сигнале для Reporter
        signal = signal_map.get(row["signal_id"])
        if signal:
            row["source"] = signal.source
            row["narrative"] = signal.narrative
        
        results_by_strategy[row["strategy"]].append(row)

    # Генерируем полные отчеты для каждой стратегии (на уровне стратегий)
    for strategy_name, strategy_results in results_by_strategy.items():
        print(f"\n📊 Generating report for strategy: {strategy_name}")
        reporter.generate_full_report(strategy_name, strategy_results)

    # Печатаем краткий результат для каждой стратегии
    print("\n📈 Strategy-level Summary:")
    for row in results:
        r = row["result"]
        print(f"🔁 {row['strategy']} → entry: {r.entry_price}, exit: {r.exit_price}, pnl: {round(r.pnl * 100, 2)}%, reason: {r.reason}")

    # Запускаем портфельную симуляцию
    print("\n" + "="*60)
    print("💼 PORTFOLIO SIMULATION")
    print("="*60)
    portfolio_results = runner.run_portfolio()

    # Сохраняем портфельные результаты
    if portfolio_results:
        for strategy_name, p_result in portfolio_results.items():
            reporter.save_portfolio_results(strategy_name, p_result)
            print(f"\n💼 Portfolio results saved for: {strategy_name}")

    # Сохраняем общий JSON файл (для обратной совместимости)
    try:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Сериализация результатов в JSON
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
        print(f"\n📤 Saved JSON output to {output_path}")
    except Exception as e:
        print(f"⚠️ Failed to save JSON output: {e}")


if __name__ == "__main__":
    main()
