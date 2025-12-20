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
from .selection_rules import DEFAULT_CRITERIA, DEFAULT_RUNNER_CRITERIA, DEFAULT_CRITERIA_V1, DEFAULT_RUNNER_CRITERIA_V1
from .strategy_selector import is_runner_strategy


def format_selection_summary(selection_df) -> str:
    """
    Форматирует краткий summary для вывода в консоль.
    
    Для Runner стратегий показывает Runner-метрики, для RR/RRD - стандартные.
    
    :param selection_df: DataFrame с результатами отбора.
    :return: Форматированная строка.
    """
    if len(selection_df) == 0:
        return "No strategies found in stability table."
    
    lines = ["\n" + "="*100]
    lines.append("Strategy Selection Results")
    lines.append("="*100)
    
    # Заголовок для RR/RRD
    lines.append(f"{'Strategy':<30} {'Passed':<8} {'Survival':<10} {'Worst':<12} {'Variance':<12}")
    lines.append("-"*100)
    
    for _, row in selection_df.iterrows():
        strategy = str(row["strategy"])[:28]
        passed = "YES" if row["passed"] else "NO"
        
        if is_runner_strategy(strategy):
            # Для Runner стратегий показываем Runner-метрики
            hit_x2 = f"{row.get('hit_rate_x2', 0.0):.2f}" if 'hit_rate_x2' in row else "N/A"
            hit_x5 = f"{row.get('hit_rate_x5', 0.0):.2f}" if 'hit_rate_x5' in row else "N/A"
            tail = f"{row.get('tail_contribution', 0.0):.2f}" if 'tail_contribution' in row else "N/A"
            lines.append(f"{strategy:<30} {passed:<8} HitX2:{hit_x2:<6} HitX5:{hit_x5:<6} Tail:{tail:<6}")
        else:
            # Для RR/RRD стратегий показываем стандартные метрики
            survival = f"{row.get('survival_rate', 0.0):.2f}" if 'survival_rate' in row else "N/A"
            worst = f"{row.get('worst_window_pnl', 0.0):.4f}" if 'worst_window_pnl' in row else "N/A"
            variance = f"{row.get('pnl_variance', 0.0):.6f}" if 'pnl_variance' in row else "N/A"
            lines.append(f"{strategy:<30} {passed:<8} {survival:<10} {worst:<12} {variance:<12}")
    
    lines.append("="*100)
    
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
    print(f"Using v1 criteria (fixed/1%/exposure=0.95/100 pos/no reset)")
    print(f"RR/RRD Criteria v1: min_survival_rate={DEFAULT_CRITERIA_V1.min_survival_rate}, "
          f"max_pnl_variance={DEFAULT_CRITERIA_V1.max_pnl_variance}, "
          f"min_worst_window_pnl={DEFAULT_CRITERIA_V1.min_worst_window_pnl}, "
          f"min_median_window_pnl={DEFAULT_CRITERIA_V1.min_median_window_pnl}, "
          f"min_windows={DEFAULT_CRITERIA_V1.min_windows}")
    print(f"Runner Criteria v1: min_hit_rate_x2={DEFAULT_RUNNER_CRITERIA_V1.min_hit_rate_x2}, "
          f"min_hit_rate_x5={DEFAULT_RUNNER_CRITERIA_V1.min_hit_rate_x5}, "
          f"max_tail_contribution={DEFAULT_RUNNER_CRITERIA_V1.max_tail_contribution}, "
          f"max_p90_hold_days={DEFAULT_RUNNER_CRITERIA_V1.max_p90_hold_days}, "
          f"max_drawdown_pct={DEFAULT_RUNNER_CRITERIA_V1.max_drawdown_pct}")
    print("")
    
    # Генерируем таблицу отбора (используем v1 критерии)
    try:
        output_path = Path(args.output_csv) if args.output_csv else None
        selection_df = generate_selection_table_from_stability(
            stability_csv_path=stability_csv_path,
            output_path=output_path,
            criteria=DEFAULT_CRITERIA_V1,
            runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
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



