# backtester/research/run_stage_a.py
# CLI entry-point for Stage A: Aggregation & Stability Analysis

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .window_aggregator import aggregate_all_strategies, DEFAULT_SPLITS
from .strategy_stability import generate_stability_table_from_reports, build_stability_table


def format_summary(stability_df) -> str:
    """
    Форматирует краткий summary для вывода в консоль.
    
    :param stability_df: DataFrame с таблицей устойчивости.
    :return: Форматированная строка.
    """
    if len(stability_df) == 0:
        return "No strategies found."
    
    lines = ["\n" + "="*80]
    lines.append("Strategy Stability Summary")
    lines.append("="*80)
    
    # Проверяем наличие колонки split_count
    has_split_count = "split_count" in stability_df.columns
    
    if has_split_count:
        lines.append(f"{'Strategy':<25} {'Split':<8} {'Survival':<10} {'Worst':<12} {'Variance':<12}")
        lines.append("-"*80)
        
        for _, row in stability_df.iterrows():
            strategy = str(row["strategy"])[:23]
            split_count = str(row["split_count"])
            survival = f"{row['survival_rate']:.1%}"
            worst = f"{row['worst_window_pnl']:.4f}"
            variance = f"{row['pnl_variance']:.6f}"
            
            lines.append(f"{strategy:<25} {split_count:<8} {survival:<10} {worst:<12} {variance:<12}")
    else:
        lines.append(f"{'Strategy':<30} {'Survival':<10} {'Worst':<12} {'Variance':<12}")
        lines.append("-"*80)
        
        for _, row in stability_df.iterrows():
            strategy = str(row["strategy"])[:28]
            survival = f"{row['survival_rate']:.1%}"
            worst = f"{row['worst_window_pnl']:.4f}"
            variance = f"{row['pnl_variance']:.6f}"
            
            lines.append(f"{strategy:<30} {survival:<10} {worst:<12} {variance:<12}")
    
    lines.append("="*80)
    lines.append("")
    
    return "\n".join(lines)


def main():
    """
    Точка входа для запуска этапа A.
    """
    parser = argparse.ArgumentParser(
        description="Stage A: Aggregation & Stability Analysis"
    )
    
    parser.add_argument(
        "--reports-dir",
        type=str,
        default="output/reports",
        help="Directory with *_trades.csv files",
    )
    
    parser.add_argument(
        "--splits",
        type=int,
        nargs="+",
        default=None,
        help=f"List of split counts for equal window analysis (e.g., --splits 2 3 4 5). "
             f"If not provided, uses default splits: {DEFAULT_SPLITS}.",
    )
    
    args = parser.parse_args()
    
    reports_dir = Path(args.reports_dir)
    
    if not reports_dir.exists():
        print(f"ERROR: Reports directory not found: {reports_dir}")
        return
    
    print(f"Stage A: Aggregation & Stability Analysis")
    print(f"Reports directory: {reports_dir}")
    
    # Определяем splits для использования
    splits = args.splits if args.splits is not None else DEFAULT_SPLITS
    print(f"Split counts: {splits}")
    print("")
    
    # Генерируем таблицу устойчивости
    try:
        stability_df = generate_stability_table_from_reports(
            reports_dir=reports_dir,
            windows=None,  # Всегда используем равные окна
            split_counts=splits,
        )
        
        # Печатаем summary
        summary = format_summary(stability_df)
        print(summary)
        
        print(f"OK: Stage A completed successfully!")
        print(f"Stability table saved to: {reports_dir / 'strategy_stability.csv'}")
        print(f"Detailed windows table saved to: {reports_dir / 'stage_a_summary.csv'}")
        
    except Exception as e:
        print(f"ERROR: Error during Stage A: {e}")
        raise


if __name__ == "__main__":
    main()






