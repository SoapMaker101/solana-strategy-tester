# tools/generate_reports.py
# Скрипт для генерации детальных отчетов после бэктеста

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
import pandas as pd

from backtester.infrastructure.reporter import Reporter
from backtester.infrastructure.signal_loader import CsvSignalLoader


def load_results(json_path: Path) -> List[Dict[str, Any]]:
    """Загружает результаты из JSON файла."""
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_strategy_selection(csv_path: Path) -> List[str]:
    """Загружает список стратегий из CSV файла."""
    df = pd.read_csv(csv_path)
    if "strategy" in df.columns:
        return df["strategy"].unique().tolist()
    return []


def select_top_strategies_from_summary(
    summary_path: Path,
    top_n: int,
    metric: str
) -> List[str]:
    """
    Выбирает top-N стратегий из summary файла по указанной метрике.
    """
    df = pd.read_csv(summary_path)
    
    if metric not in df.columns:
        raise ValueError(f"Metric '{metric}' not found in summary. Available: {df.columns.tolist()}")
    
    # Сортируем по убыванию (лучшие первыми)
    df_sorted = df.sort_values(by=metric, ascending=False)
    
    # Возвращаем top-N
    return df_sorted["strategy"].head(top_n).tolist()


def main():
    parser = argparse.ArgumentParser(
        description="Генерация детальных отчетов для выбранных стратегий"
    )
    
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Путь к output/results.json"
    )
    parser.add_argument(
        "--strategies",
        type=str,
        default=None,
        help="Путь к CSV со списком стратегий (если не указан, используется --top-n)"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        help="Количество топ стратегий (используется если --strategies не указан)"
    )
    parser.add_argument(
        "--metric",
        type=str,
        default="portfolio_return",
        choices=["portfolio_return", "strategy_total_pnl", "sharpe"],
        help="Метрика для выбора top-N стратегий"
    )
    parser.add_argument(
        "--summary-csv",
        type=str,
        default=None,
        help="Путь к strategy_summary.csv (используется для --top-n если указан)"
    )
    parser.add_argument(
        "--with-charts",
        action="store_true",
        help="Генерировать PNG графики"
    )
    parser.add_argument(
        "--with-html",
        action="store_true",
        help="Генерировать HTML отчеты"
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="output/reports",
        help="Директория для сохранения отчетов"
    )
    parser.add_argument(
        "--signals",
        type=str,
        default=None,
        help="Путь к CSV файлу с сигналами (для добавления source/narrative в отчеты)"
    )
    
    args = parser.parse_args()
    
    # Загружаем результаты
    results_path = Path(args.input)
    if not results_path.exists():
        print(f"❌ Error: File not found: {results_path}")
        return
    
    print(f"📂 Loading results from {results_path}")
    results = load_results(results_path)
    print(f"✅ Loaded {len(results)} results")
    
    # Определяем список стратегий для генерации отчетов
    strategies_to_report = []
    
    if args.strategies:
        # Загружаем из CSV файла
        strategies_path = Path(args.strategies)
        if not strategies_path.exists():
            print(f"❌ Error: File not found: {strategies_path}")
            return
        strategies_to_report = load_strategy_selection(strategies_path)
        print(f"✅ Loaded {len(strategies_to_report)} strategies from {strategies_path}")
    elif args.summary_csv:
        # Выбираем top-N из summary
        summary_path = Path(args.summary_csv)
        if not summary_path.exists():
            print(f"❌ Error: File not found: {summary_path}")
            return
        strategies_to_report = select_top_strategies_from_summary(
            summary_path,
            args.top_n,
            args.metric
        )
        print(f"✅ Selected top {len(strategies_to_report)} strategies by {args.metric} from {summary_path}")
    else:
        # Выбираем top-N из самих результатов (менее точный метод)
        # Группируем по стратегиям
        results_by_strategy = defaultdict(list)
        for row in results:
            strategy_name = row.get("strategy", "unknown")
            results_by_strategy[strategy_name].append(row)
        
        # Создаем временный reporter для расчета метрик
        reporter = Reporter(output_dir=args.out_dir)
        
        strategy_scores = []
        for strategy_name, strategy_results in results_by_strategy.items():
            metrics = reporter.calculate_metrics(strategy_results)
            
            if args.metric == "strategy_total_pnl":
                score = metrics["total_pnl"]
            elif args.metric == "sharpe":
                score = metrics["sharpe_ratio"]
            else:
                # Для portfolio_return нужны портфельные результаты, пропускаем
                continue
            
            strategy_scores.append((strategy_name, score))
        
        # Сортируем по убыванию
        strategy_scores.sort(key=lambda x: x[1], reverse=True)
        strategies_to_report = [name for name, _ in strategy_scores[:args.top_n]]
        print(f"✅ Selected top {len(strategies_to_report)} strategies by {args.metric}")
    
    if not strategies_to_report:
        print("⚠️  No strategies selected for reporting")
        return
    
    # Загружаем сигналы если указаны (для добавления source/narrative)
    signal_map = {}
    if args.signals:
        signal_loader = CsvSignalLoader(args.signals)
        signals = signal_loader.load_signals()
        signal_map = {s.id: s for s in signals}
        print(f"✅ Loaded {len(signals)} signals")
    
    # Группируем результаты по стратегиям
    results_by_strategy = defaultdict(list)
    for row in results:
        strategy_name = row.get("strategy", "unknown")
        if strategy_name in strategies_to_report:
            # Добавляем информацию о сигнале если доступна
            signal_id = row.get("signal_id")
            if signal_id and signal_id in signal_map:
                signal = signal_map[signal_id]
                row["source"] = signal.source
                row["narrative"] = signal.narrative
            
            results_by_strategy[strategy_name].append(row)
    
    # Создаем reporter с нужными флагами
    reporter = Reporter(output_dir=args.out_dir)
    
    # Генерируем отчеты для выбранных стратегий
    print(f"\n📊 Generating reports for {len(strategies_to_report)} strategies...")
    for strategy_name in strategies_to_report:
        if strategy_name not in results_by_strategy:
            print(f"⚠️  Skipping {strategy_name}: no results found")
            continue
        
        strategy_results = results_by_strategy[strategy_name]
        print(f"\n📊 Generating report for strategy: {strategy_name}")
        
        # Генерируем полный отчет
        metrics = reporter.calculate_metrics(strategy_results)
        
        # JSON и CSV всегда
        reporter.save_results(strategy_name, strategy_results)
        reporter.save_csv_report(strategy_name, strategy_results)
        reporter.save_trades_table(strategy_name, strategy_results)
        
        # HTML если разрешено
        if args.with_html:
            reporter.generate_html_report(strategy_name, metrics, strategy_results)
        
        # Графики если разрешено
        if args.with_charts:
            reporter.plot_equity_curve(strategy_results, strategy_name)
            reporter.plot_pnl_distribution(strategy_results, strategy_name)
            reporter.plot_exit_reasons(metrics, strategy_name)
            reporter.plot_trades_timeline(strategy_results, strategy_name)
        
        # Текстовый отчет
        summary = reporter.generate_summary_report(strategy_name, metrics)
        print(f"\n{summary}\n")
    
    print(f"\n✅ Reports generated successfully in {args.out_dir}")


if __name__ == "__main__":
    main()






















