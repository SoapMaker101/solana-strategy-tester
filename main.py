# main.py
# main.py — точка входа для запуска системы бэктестинга стратегий Solana

import argparse                         # Для обработки аргументов командной строки
import json                             # Для сохранения результатов в формате JSON
from pathlib import Path                # Удобная работа с путями к файлам и директориям
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import defaultdict     # Для группировки результатов по стратегиям
import yaml                             # Для загрузки YAML конфигураций
import sys                              # Для определения платформы
import pandas as pd                     # Для генерации summary CSV

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
from backtester.domain.runner_config import RunnerConfig, create_runner_config_from_dict


def parse_args():
    """
    Разбирает аргументы, переданные при запуске скрипта из командной строки.
    """
    parser = argparse.ArgumentParser(description="Solana strategy backtester")

    parser.add_argument(
        "--signals",
        default="signals/example_signals.csv",
        help="Путь к CSV-файлу с сигналами"
    )
    parser.add_argument(
        "--strategies-config",
        default="config/strategies_example.yaml",
        help="YAML-файл с описанием стратегий"
    )
    parser.add_argument(
        "--backtest-config",
        default="config/backtest_example.yaml",
        help="YAML-файл с глобальными настройками бэктеста"
    )
    parser.add_argument(
        "--json-output",
        default="output/results.json",
        help="Путь для сохранения JSON-отчета"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Максимальное количество потоков для параллельной обработки (по умолчанию: 1 на Windows, 4 на Linux/mac)"
    )
    parser.add_argument(
        "--report-mode",
        choices=["none", "summary", "top", "all"],
        default="summary",
        help="Режим генерации отчетов: none (только results.json), summary (агрегированные summary), top (top-N стратегий), all (все отчеты)"
    )
    parser.add_argument(
        "--report-top-n",
        type=int,
        default=50,
        help="Количество топ стратегий для генерации отчетов (работает только с --report-mode top)"
    )
    parser.add_argument(
        "--report-metric",
        default="portfolio_return",
        choices=["portfolio_return", "strategy_total_pnl", "sharpe"],
        help="Метрика для выбора top-N стратегий (работает только с --report-mode top)"
    )
    parser.add_argument(
        "--no-charts",
        action="store_true",
        default=None,
        help="Не генерировать PNG графики (по умолчанию True для none/summary/top, False для all)"
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        default=None,
        help="Не генерировать HTML отчеты (по умолчанию True для none/summary/top, False для all)"
    )
    parser.add_argument(
        "--execution-profile",
        choices=["realistic", "stress", "custom"],
        default=None,
        help="Execution profile для применения slippage (realistic/stress/custom). Переопределяет YAML конфиг."
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
    strategies = []
    for s in data:
        strategy_type = s.get("type", "").upper()
        name = s["name"]
        params = s.get("params", {})
        
        # Для RUNNER создаем RunnerConfig, для остальных - обычный StrategyConfig
        if strategy_type == "RUNNER":
            config = create_runner_config_from_dict(name, params)
        else:
            config = StrategyConfig(
                name=name,
                type=s["type"],
                params=params
            )
        strategies.append(build_strategy(config))
    return strategies


class ConditionalReporter:
    """
    Обертка над Reporter, которая контролирует генерацию отчетов в зависимости от режима.
    """
    def __init__(self, reporter: Reporter, report_mode: str, no_charts: bool, no_html: bool):
        self.reporter = reporter
        self.report_mode = report_mode
        self.no_charts = no_charts
        self.no_html = no_html
    
    def generate_full_report(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        """Генерирует полный отчет с учетом флагов no_charts и no_html."""
        metrics = self.reporter.calculate_metrics(results)
        
        # Сохраняем JSON
        self.reporter.save_results(strategy_name, results)
        
        # Сохраняем CSV
        self.reporter.save_csv_report(strategy_name, results)
        
        # HTML только если разрешено
        if not self.no_html:
            self.reporter.generate_html_report(strategy_name, metrics, results)
        
        # Графики только если разрешено
        if not self.no_charts:
            self.reporter.plot_equity_curve(results, strategy_name)
            self.reporter.plot_pnl_distribution(results, strategy_name)
            self.reporter.plot_exit_reasons(metrics, strategy_name)
            self.reporter.plot_trades_timeline(results, strategy_name)
        
        # Текстовый отчет всегда
        summary = self.reporter.generate_summary_report(strategy_name, metrics)
        print(f"\n{summary}\n")
    
    def save_trades_table(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        """Сохраняет таблицу сделок."""
        self.reporter.save_trades_table(strategy_name, results)
    
    def save_portfolio_results(self, strategy_name: str, portfolio_result) -> None:
        """Сохраняет портфельные результаты с учетом флагов."""
        from backtester.domain.portfolio import PortfolioResult
        
        if not isinstance(portfolio_result, PortfolioResult):
            return
        
        # Сохраняем CSV всегда
        import pandas as pd
        valid_equity = [
            point for point in portfolio_result.equity_curve
            if point.get("timestamp") is not None
        ]
        if valid_equity:
            equity_df = pd.DataFrame(valid_equity)
            equity_path = self.reporter.output_dir / f"{strategy_name}_equity_curve.csv"
            equity_df.to_csv(equity_path, index=False)
            print(f"[chart] Saved equity curve to {equity_path}")
        
        # Сохраняем позиции в CSV
        positions_data = []
        for pos in portfolio_result.positions:
            positions_data.append({
                "signal_id": pos.signal_id,
                "contract_address": pos.contract_address,
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "entry_price": pos.entry_price,
                "exit_time": pos.exit_time.isoformat() if pos.exit_time else None,
                "exit_price": pos.exit_price,
                "size_sol": pos.size,
                "pnl_pct": pos.pnl_pct,
                "pnl_sol": pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0,
                "raw_pnl_pct": pos.meta.get("raw_pnl_pct", 0.0) if pos.meta else 0.0,
                "fee_pct": pos.meta.get("fee_pct", 0.0) if pos.meta else 0.0,
                "status": pos.status,
            })
        
        if positions_data:
            positions_df = pd.DataFrame(positions_data)
            positions_path = self.reporter.output_dir / f"{strategy_name}_portfolio_positions.csv"
            positions_df.to_csv(positions_path, index=False)
            print(f"💼 Saved portfolio positions to {positions_path}")
        
        # Сохраняем статистику в JSON
        stats_data = {
            "final_balance_sol": portfolio_result.stats.final_balance_sol,
            "total_return_pct": portfolio_result.stats.total_return_pct,
            "max_drawdown_pct": portfolio_result.stats.max_drawdown_pct,
            "trades_executed": portfolio_result.stats.trades_executed,
            "trades_skipped_by_risk": portfolio_result.stats.trades_skipped_by_risk,
        }
        
        stats_path = self.reporter.output_dir / f"{strategy_name}_portfolio_stats.json"
        with stats_path.open("w", encoding="utf-8") as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)
        print(f"[report] Saved portfolio stats to {stats_path}")
        
        # График только если разрешено
        if not self.no_charts:
            self.reporter.plot_portfolio_equity_curve(strategy_name, portfolio_result)


def generate_strategy_summary(
    results_by_strategy: Dict[str, List[Dict[str, Any]]],
    portfolio_results: Optional[Dict[str, Any]],
    output_dir: Path,
    reporter: Reporter
) -> None:
    """
    Генерирует агрегированный summary отчет по всем стратегиям.
    """
    summary_rows = []
    
    for strategy_name, strategy_results in results_by_strategy.items():
        metrics = reporter.calculate_metrics(strategy_results)
        
        row = {
            "strategy": strategy_name,
            "total_trades": metrics["total_trades"],
            "winning_trades": metrics["winning_trades"],
            "losing_trades": metrics["losing_trades"],
            "winrate": metrics["winrate"],
            "strategy_total_pnl": metrics["total_pnl"],
            "avg_pnl": metrics["avg_pnl"],
            "median_pnl": metrics["median_pnl"],
            "best_trade": metrics["best_trade"],
            "worst_trade": metrics["worst_trade"],
            "sharpe": metrics["sharpe_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "profit_factor": metrics["profit_factor"],
        }
        
        # Добавляем портфельные метрики если есть
        if portfolio_results and strategy_name in portfolio_results:
            p_result = portfolio_results[strategy_name]
            row["portfolio_return"] = p_result.stats.total_return_pct
            row["final_balance_sol"] = p_result.stats.final_balance_sol
            row["portfolio_max_drawdown"] = p_result.stats.max_drawdown_pct
            row["trades_executed"] = p_result.stats.trades_executed
        else:
            row["portfolio_return"] = None
            row["final_balance_sol"] = None
            row["portfolio_max_drawdown"] = None
            row["trades_executed"] = None
        
        summary_rows.append(row)
    
    df = pd.DataFrame(summary_rows)
    summary_path = output_dir / "strategy_summary.csv"
    df.to_csv(summary_path, index=False)
    print(f"\n📊 Saved strategy summary to {summary_path}")


def generate_portfolio_summary(
    portfolio_results: Dict[str, Any],
    output_dir: Path
) -> None:
    """
    Генерирует агрегированный портфельный summary отчет.
    """
    summary_rows = []
    
    for strategy_name, p_result in portfolio_results.items():
        row = {
            "strategy": strategy_name,
            "final_balance_sol": p_result.stats.final_balance_sol,
            "total_return_pct": p_result.stats.total_return_pct,
            "max_drawdown_pct": p_result.stats.max_drawdown_pct,
            "trades_executed": p_result.stats.trades_executed,
            "trades_skipped_by_risk": p_result.stats.trades_skipped_by_risk,
            "trades_skipped_by_reset": p_result.stats.trades_skipped_by_reset,
        }
        
        # Добавляем поля для portfolio-level reset
        row["reset_count"] = p_result.stats.reset_count
        row["last_reset_time"] = (
            p_result.stats.last_reset_time.isoformat() 
            if p_result.stats.last_reset_time else None
        )
        row["cycle_start_equity"] = p_result.stats.cycle_start_equity
        row["equity_peak_in_cycle"] = p_result.stats.equity_peak_in_cycle
        
        summary_rows.append(row)
    
    df = pd.DataFrame(summary_rows)
    summary_path = output_dir / "portfolio_summary.csv"
    df.to_csv(summary_path, index=False)
    print(f"💼 Saved portfolio summary to {summary_path}")


def select_top_strategies(
    results_by_strategy: Dict[str, List[Dict[str, Any]]],
    portfolio_results: Optional[Dict[str, Any]],
    reporter: Reporter,
    top_n: int,
    metric: str
) -> List[str]:
    """
    Выбирает top-N стратегий по указанной метрике.
    """
    strategy_scores = []
    
    for strategy_name, strategy_results in results_by_strategy.items():
        if metric == "portfolio_return":
            if portfolio_results and strategy_name in portfolio_results:
                score = portfolio_results[strategy_name].stats.total_return_pct
            else:
                continue  # Пропускаем если нет портфельных результатов
        elif metric == "strategy_total_pnl":
            metrics = reporter.calculate_metrics(strategy_results)
            score = metrics["total_pnl"]
        elif metric == "sharpe":
            metrics = reporter.calculate_metrics(strategy_results)
            score = metrics["sharpe_ratio"]
        else:
            continue
        
        strategy_scores.append((strategy_name, score))
    
    # Сортируем по убыванию (лучшие первыми)
    strategy_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Возвращаем top-N
    return [name for name, _ in strategy_scores[:top_n]]



def main():
    args = parse_args()  # Получаем аргументы запуска

    # Загружаем глобальные настройки бэктеста
    backtest_cfg = load_yaml(args.backtest_config)
    
    # Переопределяем execution_profile из CLI если указан
    if args.execution_profile is not None:
        if "portfolio" not in backtest_cfg:
            backtest_cfg["portfolio"] = {}
        backtest_cfg["portfolio"]["execution_profile"] = args.execution_profile
        print(f"[config] Overriding execution_profile to: {args.execution_profile}")
    
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
        rate_limit_config = data_cfg.get("rate_limit", {})
        price_loader = GeckoTerminalPriceLoader(
            cache_dir=candles_dir,
            timeframe=timeframe,
            rate_limit_config=rate_limit_config
        )
    else:
        # Для CsvPriceLoader: base_dir можно указать в конфиге или использовать candles_dir как fallback
        csv_base_dir = data_cfg.get("price_loader", {}).get("csv_base_dir") or candles_dir
        price_loader = CsvPriceLoader(
            candles_dir=candles_dir,
            timeframe=timeframe,
            base_dir=csv_base_dir
        )

    # Загружаем стратегии
    strategies = load_strategies(args.strategies_config)

    # Создаем Reporter для генерации отчетов
    report_cfg = backtest_cfg.get("report", {})
    output_dir = report_cfg.get("output_dir", "output/reports")
    base_reporter = Reporter(output_dir=output_dir)
    
    # Определяем дефолты для no_charts и no_html в зависимости от режима
    # Если флаг явно не указан (None), используем дефолт на основе режима:
    #   - Для режимов "none", "summary", "top": графики и HTML отключены по умолчанию (no_charts=True, no_html=True)
    #   - Для режима "all": графики и HTML включены по умолчанию (no_charts=False, no_html=False)
    # Если флаг указан явно (True), используем его значение (пользователь переопределил дефолт)
    if args.no_charts is None:
        # Дефолт: True для none/summary/top (графики отключены), False для all (графики включены)
        no_charts = args.report_mode in ["none", "summary", "top"]
    else:
        no_charts = args.no_charts
    
    if args.no_html is None:
        # Дефолт: True для none/summary/top (HTML отключен), False для all (HTML включен)
        no_html = args.report_mode in ["none", "summary", "top"]
    else:
        no_html = args.no_html
    
    # Создаем условный репортер
    reporter = ConditionalReporter(base_reporter, args.report_mode, no_charts, no_html)

    # Получаем настройки параллельной обработки
    runtime_cfg = backtest_cfg.get("runtime", {})
    parallel = runtime_cfg.get("parallel", False)
    
    # Определяем дефолт для max_workers в зависимости от платформы
    if args.max_workers is not None:
        max_workers = args.max_workers
    elif "max_workers" in runtime_cfg:
        max_workers = runtime_cfg.get("max_workers")
    else:
        # Дефолт: Windows = 1 (стабильно), Linux/mac = 4
        if sys.platform == "win32":
            max_workers = 1
        else:
            max_workers = 4

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

    # Группируем результаты по стратегиям
    results_by_strategy = defaultdict(list)
    
    for row in results:
        # Добавляем информацию о сигнале для Reporter
        signal = signal_map.get(row["signal_id"])
        if signal:
            row["source"] = signal.source
            row["narrative"] = signal.narrative
        
        results_by_strategy[row["strategy"]].append(row)

    # Сохраняем таблицы сделок для всех стратегий
    for strategy_name, strategy_results in results_by_strategy.items():
        reporter.save_trades_table(strategy_name, strategy_results)

    # Генерируем отчеты в зависимости от режима
    strategies_to_report = []
    
    if args.report_mode == "none":
        # Не генерируем никаких отчетов по стратегиям
        pass
    elif args.report_mode == "summary":
        # Генерируем только summary (будет создан после портфельной симуляции)
        pass
    elif args.report_mode == "top":
        # Выберем top-N после портфельной симуляции
        pass
    elif args.report_mode == "all":
        # Генерируем отчеты для всех стратегий
        strategies_to_report = list(results_by_strategy.keys())
    
    # Генерируем отчеты для выбранных стратегий
    for strategy_name in strategies_to_report:
        strategy_results = results_by_strategy[strategy_name]
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

    # Определяем стратегии для генерации отчетов после портфельной симуляции
    if args.report_mode == "top":
        # Выбираем top-N стратегий
        top_strategies = select_top_strategies(
            results_by_strategy,
            portfolio_results,
            base_reporter,
            args.report_top_n,
            args.report_metric
        )
        strategies_to_report = top_strategies
        print(f"\n📊 Selected top {len(top_strategies)} strategies by {args.report_metric}")
        
        # Генерируем отчеты по стратегиям для top режима
        for strategy_name in strategies_to_report:
            if strategy_name in results_by_strategy:
                strategy_results = results_by_strategy[strategy_name]
                print(f"\n📊 Generating report for strategy: {strategy_name}")
                reporter.generate_full_report(strategy_name, strategy_results)
    elif args.report_mode == "all":
        # Все стратегии уже обработаны выше, но нужно обработать портфельные результаты
        strategies_to_report = list(results_by_strategy.keys())
    else:
        strategies_to_report = []

    # Сохраняем портфельные результаты только для выбранных стратегий
    if portfolio_results:
        for strategy_name in strategies_to_report:
            if strategy_name in portfolio_results:
                p_result = portfolio_results[strategy_name]
                reporter.save_portfolio_results(strategy_name, p_result)
                print(f"\n💼 Portfolio results saved for: {strategy_name}")
        
        # Сохраняем единую таблицу portfolio trades для всех стратегий (используется Stage A)
        # Используем все portfolio_results, не только strategies_to_report, чтобы Stage A видел все executed trades
        base_reporter.save_portfolio_positions_table(portfolio_results)
        base_reporter.save_portfolio_executions_table(portfolio_results)
    
    # Генерируем summary отчеты
    if args.report_mode in ["summary", "top"]:
        output_path_obj = Path(output_dir)
        output_path_obj.mkdir(parents=True, exist_ok=True)
        generate_strategy_summary(results_by_strategy, portfolio_results, output_path_obj, base_reporter)
        if portfolio_results:
            generate_portfolio_summary(portfolio_results, output_path_obj)

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
