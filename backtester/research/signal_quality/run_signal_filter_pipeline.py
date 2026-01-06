# backtester/research/signal_quality/run_signal_filter_pipeline.py
"""
CLI runner для пайплайна фильтрации сигналов.

Запускает:
1. Извлечение признаков сигналов (signal_features.csv)
2. Анализ порогов market cap (cap_threshold_report.csv)
3. Фильтрацию сигналов (signals_filtered.csv)
4. Сохранение summary (signal_filter_summary.json)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .cap_thresholds import analyze_cap_thresholds, save_cap_threshold_report
from .feature_extractor import extract_signal_features, load_signals
from .filter_signals import (
    filter_signals,
    generate_filter_summary,
    save_filtered_signals,
    save_filter_summary,
)


def parse_args():
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Signal quality analysis and filtering pipeline"
    )
    
    parser.add_argument(
        "--signals",
        type=str,
        required=True,
        help="Путь к CSV файлу с сигналами"
    )
    parser.add_argument(
        "--candles-dir",
        type=str,
        default="data/candles",
        help="Базовая директория со свечами (default: data/candles)"
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1m",
        choices=["1m", "5m", "15m"],
        help="Таймфрейм свечей (default: 1m)"
    )
    parser.add_argument(
        "--entry-mode",
        type=str,
        default="t+1m",
        choices=["t", "t+1m"],
        help="Режим поиска entry_price: t (на момент сигнала) или t+1m (через 1 минуту, default)"
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=14,
        help="Горизонт анализа в днях (default: 14)"
    )
    parser.add_argument(
        "--use-high",
        type=str,
        default="true",
        choices=["true", "false"],
        help="Использовать high цену для max_xn (default: true)"
    )
    parser.add_argument(
        "--runner-xn-threshold",
        type=float,
        default=3.0,
        help="Порог для определения runner'а (default: 3.0)"
    )
    parser.add_argument(
        "--thresholds",
        type=float,
        nargs="+",
        default=[10000, 20000, 30000, 40000, 50000, 60000, 80000, 100000, 150000, 200000],
        help="Список порогов для анализа (default: 10k, 20k, 30k, 40k, 50k, 60k, 80k, 100k, 150k, 200k)"
    )
    parser.add_argument(
        "--min-market-cap-proxy",
        type=float,
        required=True,
        help="Минимальный порог market cap proxy для фильтрации"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/signal_analysis",
        help="Директория для сохранения результатов (default: output/signal_analysis)"
    )
    
    return parser.parse_args()


def main():
    """Главная функция CLI runner."""
    args = parse_args()
    
    # Создаём выходную директорию
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("SIGNAL QUALITY ANALYSIS & FILTERING PIPELINE")
    print("=" * 60)
    print(f"Signals: {args.signals}")
    print(f"Candles dir: {args.candles_dir}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Entry mode: {args.entry_mode}")
    print(f"Horizon: {args.horizon_days} days")
    print(f"Use high: {args.use_high}")
    print(f"Runner XN threshold: {args.runner_xn_threshold}")
    print(f"Min market cap proxy: {args.min_market_cap_proxy}")
    print(f"Output dir: {args.output_dir}")
    print("=" * 60)
    
    # Шаг 1: Загружаем сигналы
    print("\n[1/4] Loading signals...")
    signals_df = load_signals(args.signals)
    print(f"Loaded {len(signals_df)} signals")
    
    # Шаг 2: Извлекаем признаки
    print("\n[2/4] Extracting signal features...")
    use_high_bool = args.use_high.lower() == "true"
    features_df = extract_signal_features(
        signals_df=signals_df,
        candles_dir=args.candles_dir,
        timeframe=args.timeframe,
        entry_mode=args.entry_mode,
        horizon_days=args.horizon_days,
        use_high=use_high_bool
    )
    
    # Сохраняем features
    features_path = output_dir / "signal_features.csv"
    features_df.to_csv(features_path, index=False)
    print(f"Saved {len(features_df)} signal features to {features_path}")
    
    # Статистика по статусам
    status_counts = features_df["status"].value_counts()
    print("\nStatus distribution:")
    for status, count in status_counts.items():
        print(f"  {status}: {count}")
    
    # Шаг 3: Анализ порогов
    print("\n[3/4] Analyzing cap thresholds...")
    threshold_report = analyze_cap_thresholds(
        features_df=features_df,
        thresholds=args.thresholds,
        runner_xn_threshold=args.runner_xn_threshold
    )
    
    if not threshold_report.empty:
        report_path = output_dir / "cap_threshold_report.csv"
        save_cap_threshold_report(threshold_report, report_path)
        print(f"Saved threshold report with {len(threshold_report)} thresholds")
    else:
        print("Warning: No valid signals for threshold analysis")
    
    # Шаг 4: Фильтрация сигналов
    print("\n[4/4] Filtering signals...")
    filtered_df = filter_signals(
        signals_path=args.signals,
        features_df=features_df,
        min_market_cap_proxy=args.min_market_cap_proxy,
        require_status_ok=True
    )
    
    # Сохраняем отфильтрованные сигналы
    filtered_path = output_dir / "signals_filtered.csv"
    save_filtered_signals(filtered_df, filtered_path)
    
    # Генерируем summary
    original_count = len(signals_df)
    filtered_count = len(filtered_df)
    summary = generate_filter_summary(
        original_count=original_count,
        filtered_count=filtered_count,
        features_df=features_df,
        min_market_cap_proxy=args.min_market_cap_proxy
    )
    
    summary_path = output_dir / "signal_filter_summary.json"
    save_filter_summary(summary, summary_path)
    
    # Выводим итоги
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETED")
    print("=" * 60)
    print(f"Original signals: {original_count}")
    print(f"Filtered signals: {filtered_count}")
    print(f"Removed: {original_count - filtered_count} ({summary['removed_pct']:.2f}%)")
    print(f"\nOutput files:")
    print(f"  - {features_path}")
    if not threshold_report.empty:
        print(f"  - {report_path}")
    print(f"  - {filtered_path}")
    print(f"  - {summary_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()



























