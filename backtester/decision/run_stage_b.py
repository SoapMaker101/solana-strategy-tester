# backtester/decision/run_stage_b.py
# CLI entry-point for Stage B: Strategy Selection

from __future__ import annotations

import argparse
from pathlib import Path

from .strategy_selector import (
    generate_selection_table_from_stability,
    load_stability_csv,
    select_strategies,
)
from .selection_rules import DEFAULT_CRITERIA


def format_selection_summary(selection_df) -> str:
    """
    Форматирует краткий summary для вывода в консоль.
    
    :param selection_df: DataFrame с результатами отбора.
    :return: Форматированная строка.
    """
    if len(selection_df) == 0:
        return "No strategies found in stability table."
    
    lines = ["\n" + "="*80]
    lines.append("Strategy Selection Results")
    lines.append("="*80)
    lines.append(f"{'Strategy':<30} {'Passed':<8} {'Survival':<10} {'Worst':<12} {'Variance':<12}")
    lines.append("-"*80)
    
    for _, row in selection_df.iterrows():
        strategy = str(row["strategy"])[:28]
        passed = "YES" if row["passed"] else "NO"
        survival = f"{row['survival_rate']:.2f}"
        worst = f"{row['worst_window_pnl']:.4f}"
        variance = f"{row['pnl_variance']:.6f}"
        
        lines.append(f"{strategy:<30} {passed:<8} {survival:<10} {worst:<12} {variance:<12}")
    
    lines.append("="*80)
    
    # Статистика
    total = len(selection_df)
    passed_count = selection_df["passed"].sum()
    lines.append(f"\nTotal strategies: {total}")
    lines.append(f"Passed: {passed_count}")
    lines.append(f"Rejected: {total - passed_count}")
    lines.append("")
    
    return "\n".join(lines)


def main():
    """
    Точка входа для запуска этапа B.
    """
    parser = argparse.ArgumentParser(
        description="Stage B: Strategy Selection (Decision Layer)"
    )
    
    parser.add_argument(
        "--stability-csv",
        type=str,
        default="output/reports/strategy_stability.csv",
        help="Path to strategy_stability.csv from Stage A",
    )
    
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help="Path for output strategy_selection.csv (default: same dir as stability-csv)",
    )
    
    args = parser.parse_args()
    
    stability_csv_path = Path(args.stability_csv)
    
    if not stability_csv_path.exists():
        print(f"ERROR: Stability CSV not found: {stability_csv_path}")
        print("Please run Stage A first to generate strategy_stability.csv")
        return
    
    print(f"Stage B: Strategy Selection (Decision Layer)")
    print(f"Stability CSV: {stability_csv_path}")
    print(f"Criteria: min_survival_rate={DEFAULT_CRITERIA.min_survival_rate}, "
          f"max_pnl_variance={DEFAULT_CRITERIA.max_pnl_variance}, "
          f"min_worst_window_pnl={DEFAULT_CRITERIA.min_worst_window_pnl}, "
          f"min_median_window_pnl={DEFAULT_CRITERIA.min_median_window_pnl}, "
          f"min_windows={DEFAULT_CRITERIA.min_windows}")
    print("")
    
    # Генерируем таблицу отбора
    try:
        output_path = Path(args.output_csv) if args.output_csv else None
        selection_df = generate_selection_table_from_stability(
            stability_csv_path=stability_csv_path,
            output_path=output_path,
            criteria=DEFAULT_CRITERIA,
        )
        
        # Печатаем summary
        summary = format_selection_summary(selection_df)
        print(summary)
        
        # Показываем причины отклонения для непрошедших стратегий
        rejected = selection_df[~selection_df["passed"]]
        if len(rejected) > 0:
            print("Rejection reasons:")
            for _, row in rejected.iterrows():
                reasons = row["failed_reasons"]
                if isinstance(reasons, list) and len(reasons) > 0:
                    print(f"  {row['strategy']}: {', '.join(reasons)}")
            print("")
        
        output_file = output_path if output_path else stability_csv_path.parent / "strategy_selection.csv"
        print(f"OK: Stage B completed successfully!")
        print(f"Selection table saved to: {output_file}")
        
    except Exception as e:
        print(f"ERROR: Error during Stage B: {e}")
        raise


if __name__ == "__main__":
    main()




