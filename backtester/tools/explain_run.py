"""
CLI инструмент для объяснения прогона (Run) на уровне артефактов.

Генерирует форензический markdown-документ с анализом reset-событий, аномалий и метрик.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import warnings

import pandas as pd

warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)


def parse_args():
    """Парсит аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Explain a backtest run by analyzing artifacts (CSV files)."
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to run directory (e.g., runs/C)"
    )
    parser.add_argument(
        "--reports-subdir",
        type=str,
        default="reports",
        help="Subdirectory with CSV files (default: reports)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output markdown file path (default: <run-dir>/<reports-subdir>/RUN_EXPLAIN.md)"
    )
    parser.add_argument(
        "--format",
        choices=["md", "json"],
        default="md",
        help="Output format: md (markdown) or json (default: md)"
    )
    parser.add_argument(
        "--fail-on-anomaly",
        action="store_true",
        help="Exit with code 2 if critical anomalies found"
    )
    parser.add_argument(
        "--max-reset-rows",
        type=int,
        default=200,
        help="Maximum rows in reset table (default: 200)"
    )
    parser.add_argument(
        "--no-xlsx",
        action="store_true",
        help="Skip reading report_pack.xlsx"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extended diagnostics"
    )
    return parser.parse_args()


def load_csv_safe(path: Path, description: str) -> Optional[pd.DataFrame]:
    """Безопасно загружает CSV файл."""
    if not path.exists():
        if description:
            print(f"[WARNING] {description} not found: {path}", file=sys.stderr)
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"[ERROR] Failed to load {path}: {e}", file=sys.stderr)
        return None


def parse_meta_json(meta_str: str) -> Dict[str, Any]:
    """Парсит meta_json с обработкой ошибок."""
    if pd.isna(meta_str) or not meta_str:
        return {}
    try:
        return json.loads(meta_str)
    except (json.JSONDecodeError, TypeError) as e:
        return {"_parse_error": str(e), "_raw": str(meta_str)}


def extract_reset_events(events_df: pd.DataFrame) -> pd.DataFrame:
    """Извлекает reset события из portfolio_events.csv."""
    if events_df is None or events_df.empty:
        return pd.DataFrame()
    
    # Фильтруем reset события
    if "event_type" not in events_df.columns:
        events_df["event_type"] = ""
    if "reason" not in events_df.columns:
        events_df["reason"] = ""
    
    reset_mask = (
        (events_df["event_type"] == "portfolio_reset_triggered") |
        (events_df["reason"] == "profit_reset")
    )
    reset_df = events_df[reset_mask].copy()
    
    if reset_df.empty:
        return pd.DataFrame()
    
    # Парсим meta_json и извлекаем поля
    if "meta_json" not in reset_df.columns:
        reset_df["meta_json"] = ""
    # Убеждаемся, что это Series, а не ndarray
    meta_json_series = reset_df["meta_json"] if isinstance(reset_df["meta_json"], pd.Series) else pd.Series(reset_df["meta_json"])
    reset_df["meta_parsed"] = meta_json_series.apply(parse_meta_json)
    
    # Извлекаем ключевые поля из meta
    meta_fields = [
        "reset_id", "trigger_basis", "multiple", "threshold",
        "cycle_start_equity", "equity_peak_in_cycle",
        "cycle_start_balance", "current_balance",
        "closed_positions_count", "eligibility_reason"
    ]
    
    # Убеждаемся, что meta_parsed это Series
    meta_parsed_series = reset_df["meta_parsed"] if isinstance(reset_df["meta_parsed"], pd.Series) else pd.Series(reset_df["meta_parsed"])
    for field in meta_fields:
        reset_df[field] = meta_parsed_series.apply(
            lambda m: m.get(field) if isinstance(m, dict) else None
        )
    
    return reset_df


def check_anomalies(
    reset_df: pd.DataFrame,
    policy_summary_df: Optional[pd.DataFrame],
    verbose: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Проверяет аномалии и возвращает списки critical и warning."""
    critical = []
    warnings = []
    
    if reset_df.empty:
        return critical, warnings
    
    # CRITICAL: closed_positions_count == 0
    if "closed_positions_count" not in reset_df.columns:
        reset_df["closed_positions_count"] = None
    zero_closed = reset_df[
        (reset_df["closed_positions_count"].isna()) |
        (reset_df["closed_positions_count"] == 0)
    ]
    for idx, row in zero_closed.iterrows():
        critical.append({
            "type": "zero_closed_positions",
            "reset_id": row.get("reset_id", "unknown"),
            "timestamp": row.get("timestamp", "unknown"),
            "message": "Reset event has closed_positions_count == 0"
        })
    
    # CRITICAL: trigger_basis отсутствует или невалидный
    if "trigger_basis" not in reset_df.columns:
        reset_df["trigger_basis"] = None
    invalid_basis = reset_df[
        (~reset_df["trigger_basis"].isin(["equity_peak", "realized_balance"])) |
        (reset_df["trigger_basis"].isna())
    ]
    for idx, row in invalid_basis.iterrows():
        critical.append({
            "type": "invalid_trigger_basis",
            "reset_id": row.get("reset_id", "unknown"),
            "timestamp": row.get("timestamp", "unknown"),
            "trigger_basis": row.get("trigger_basis", "missing"),
            "message": f"Invalid or missing trigger_basis: {row.get('trigger_basis', 'missing')}"
        })
    
    # CRITICAL: multiple отсутствует или <= 1.0
    if "multiple" not in reset_df.columns:
        reset_df["multiple"] = None
    invalid_multiple = reset_df[
        (reset_df["multiple"].isna()) |
        (pd.notna(reset_df["multiple"]) & (reset_df["multiple"] <= 1.0))
    ]
    for idx, row in invalid_multiple.iterrows():
        critical.append({
            "type": "invalid_multiple",
            "reset_id": row.get("reset_id", "unknown"),
            "timestamp": row.get("timestamp", "unknown"),
            "multiple": row.get("multiple"),
            "message": f"Invalid multiple: {row.get('multiple')}"
        })
    
    # CRITICAL: threshold отсутствует
    if "threshold" not in reset_df.columns:
        reset_df["threshold"] = None
    missing_threshold = reset_df[reset_df["threshold"].isna()]
    for idx, row in missing_threshold.iterrows():
        critical.append({
            "type": "missing_threshold",
            "reset_id": row.get("reset_id", "unknown"),
            "timestamp": row.get("timestamp", "unknown"),
            "message": "Missing threshold in reset event"
        })
    
    # CRITICAL: realized_balance с cycle_start_balance <= 0 или threshold <= 0
    if "cycle_start_balance" not in reset_df.columns:
        reset_df["cycle_start_balance"] = None
    realized_balance_resets = reset_df[reset_df["trigger_basis"] == "realized_balance"]
    if not realized_balance_resets.empty:
        # Убеждаемся, что это Series для .isna()
        cycle_start_balance_series = realized_balance_resets["cycle_start_balance"] if isinstance(realized_balance_resets["cycle_start_balance"], pd.Series) else pd.Series(realized_balance_resets["cycle_start_balance"])
        threshold_series = realized_balance_resets["threshold"] if isinstance(realized_balance_resets["threshold"], pd.Series) else pd.Series(realized_balance_resets["threshold"])
        invalid_realized = realized_balance_resets[
            (cycle_start_balance_series.isna()) |
            (pd.notna(cycle_start_balance_series) & (cycle_start_balance_series <= 0)) |
            (threshold_series.isna()) |
            (pd.notna(threshold_series) & (threshold_series <= 0))
        ]
    else:
        invalid_realized = pd.DataFrame()
    for idx, row in invalid_realized.iterrows():
        critical.append({
            "type": "invalid_realized_balance_baseline",
            "reset_id": row.get("reset_id", "unknown"),
            "timestamp": row.get("timestamp", "unknown"),
            "cycle_start_balance": row.get("cycle_start_balance"),
            "threshold": row.get("threshold"),
            "message": f"realized_balance reset with invalid baseline: cycle_start_balance={row.get('cycle_start_balance')}, threshold={row.get('threshold')}"
        })
    
    # CRITICAL: equity_peak с cycle_start_equity <= 0 или threshold <= 0
    if "cycle_start_equity" not in reset_df.columns:
        reset_df["cycle_start_equity"] = None
    equity_peak_resets = reset_df[reset_df["trigger_basis"] == "equity_peak"]
    if not equity_peak_resets.empty:
        # Убеждаемся, что это Series для .isna()
        cycle_start_equity_series = equity_peak_resets["cycle_start_equity"] if isinstance(equity_peak_resets["cycle_start_equity"], pd.Series) else pd.Series(equity_peak_resets["cycle_start_equity"])
        threshold_series = equity_peak_resets["threshold"] if isinstance(equity_peak_resets["threshold"], pd.Series) else pd.Series(equity_peak_resets["threshold"])
        invalid_equity = equity_peak_resets[
            (cycle_start_equity_series.isna()) |
            (pd.notna(cycle_start_equity_series) & (cycle_start_equity_series <= 0)) |
            (threshold_series.isna()) |
            (pd.notna(threshold_series) & (threshold_series <= 0))
        ]
    else:
        invalid_equity = pd.DataFrame()
    for idx, row in invalid_equity.iterrows():
        critical.append({
            "type": "invalid_equity_peak_baseline",
            "reset_id": row.get("reset_id", "unknown"),
            "timestamp": row.get("timestamp", "unknown"),
            "cycle_start_equity": row.get("cycle_start_equity"),
            "threshold": row.get("threshold"),
            "message": f"equity_peak reset with invalid baseline: cycle_start_equity={row.get('cycle_start_equity')}, threshold={row.get('threshold')}"
        })
    
    # WARNING: reset_count не совпадает с количеством событий
    if policy_summary_df is not None and not policy_summary_df.empty:
        if "portfolio_reset_profit_count" in policy_summary_df.columns:
            policy_reset_count = policy_summary_df["portfolio_reset_profit_count"].iloc[0]
        else:
            policy_reset_count = 0
        actual_reset_count = len(reset_df)
        if policy_reset_count != actual_reset_count:
            warnings.append({
                "type": "reset_count_mismatch",
                "policy_count": int(policy_reset_count),
                "actual_count": actual_reset_count,
                "message": f"reset_count mismatch: policy_summary={policy_reset_count}, events={actual_reset_count}"
            })
    
    # WARNING: parse errors в meta_json
    # Убеждаемся, что это Series для .apply() и .any()
    meta_parsed_series = reset_df["meta_parsed"] if isinstance(reset_df["meta_parsed"], pd.Series) else pd.Series(reset_df["meta_parsed"])
    parse_errors = meta_parsed_series.apply(
        lambda m: "_parse_error" in m if isinstance(m, dict) else False
    )
    # Убеждаемся, что parse_errors это Series или bool
    if isinstance(parse_errors, pd.Series):
        has_errors = parse_errors.any()
    else:
        has_errors = bool(parse_errors)
    if has_errors:
        error_count = parse_errors.sum()
        warnings.append({
            "type": "meta_json_parse_errors",
            "count": int(error_count),
            "message": f"Found {error_count} meta_json parse errors"
        })
    
    return critical, warnings


def generate_markdown(
    run_dir: Path,
    artifacts: Dict[str, Optional[pd.DataFrame]],
    reset_df: pd.DataFrame,
    critical: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    max_reset_rows: int = 200
) -> str:
    """Генерирует markdown документ."""
    lines = []
    
    # Title
    lines.append(f"# Run Explain: {run_dir.name}")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().isoformat()}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Artifacts found / missing
    lines.append("## Artifacts Found / Missing")
    lines.append("")
    found = []
    missing = []
    artifact_names = {
        "portfolio_events": "portfolio_events.csv",
        "portfolio_positions": "portfolio_positions.csv",
        "portfolio_executions": "portfolio_executions.csv",
        "portfolio_summary": "portfolio_summary.csv",
        "portfolio_policy_summary": "portfolio_policy_summary.csv",
        "strategy_summary": "strategy_summary.csv",
        "report_pack_xlsx": "report_pack.xlsx"
    }
    
    for key, filename in artifact_names.items():
        if artifacts.get(key) is not None:
            found.append(filename)
        else:
            missing.append(filename)
    
    if found:
        lines.append("**Found:**")
        for f in found:
            lines.append(f"- ✅ {f}")
        lines.append("")
    
    if missing:
        lines.append("**Missing:**")
        for f in missing:
            lines.append(f"- ❌ {f}")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Run Passport
    lines.append("## Run Passport")
    lines.append("")
    
    summary_df = artifacts.get("portfolio_summary")
    policy_df = artifacts.get("portfolio_policy_summary")
    
    passport_data = []
    
    if summary_df is not None and not summary_df.empty:
        row = summary_df.iloc[0]
        if "final_balance_sol" in row:
            passport_data.append(("final_balance_sol", f"{row['final_balance_sol']:.4f} SOL"))
        if "total_return_pct" in row:
            passport_data.append(("total_return_pct", f"{row['total_return_pct']:.2%}"))
        if "max_drawdown_pct" in row:
            passport_data.append(("max_drawdown_pct", f"{row['max_drawdown_pct']:.2%}"))
        if "trades_executed" in row:
            passport_data.append(("trades_executed", int(row["trades_executed"])))
        if "trades_skipped_by_risk" in row:
            passport_data.append(("trades_skipped_by_risk", int(row["trades_skipped_by_risk"])))
        if "cycle_start_equity" in row:
            passport_data.append(("cycle_start_equity", f"{row['cycle_start_equity']:.4f} SOL"))
        if "equity_peak_in_cycle" in row:
            passport_data.append(("equity_peak_in_cycle", f"{row['equity_peak_in_cycle']:.4f} SOL"))
    
    if policy_df is not None and not policy_df.empty:
        row = policy_df.iloc[0]
        if "portfolio_reset_profit_count" in row:
            passport_data.append(("portfolio_reset_profit_count", int(row["portfolio_reset_profit_count"])))
        if "portfolio_capacity_prune_count" in row:
            passport_data.append(("portfolio_capacity_prune_count", int(row["portfolio_capacity_prune_count"])))
    
    if passport_data:
        lines.append("| Parameter | Value |")
        lines.append("|-----------|-------|")
        for key, value in passport_data:
            lines.append(f"| `{key}` | {value} |")
        lines.append("")
    else:
        lines.append("*No passport data available*")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Profit Reset Forensics
    lines.append("## Profit Reset Forensics")
    lines.append("")
    
    reset_count = len(reset_df)
    lines.append(f"**Reset Events Count:** {reset_count}")
    lines.append("")
    
    if reset_df.empty:
        lines.append("*No reset events found*")
        lines.append("")
    else:
        # Таблица reset-событий
        lines.append("### Reset Events Table")
        lines.append("")
        
        # Ограничиваем количество строк
        display_df = reset_df.head(max_reset_rows)
        total_count = len(reset_df)
        
        if total_count > max_reset_rows:
            lines.append(f"*(Showing first {max_reset_rows} of {total_count} resets)*")
            lines.append("")
        
        # Формируем таблицу
        table_cols = [
            "timestamp", "reset_id", "trigger_basis", "multiple", "threshold",
            "cycle_start_equity", "equity_peak_in_cycle",
            "cycle_start_balance", "current_balance",
            "closed_positions_count", "eligibility_reason"
        ]
        
        # Заголовок таблицы
        header = "| " + " | ".join(table_cols) + " |"
        lines.append(header)
        lines.append("|" + "|".join(["---"] * len(table_cols)) + "|")
        
        # Строки таблицы
        # Убеждаемся, что это DataFrame для .iterrows()
        if isinstance(display_df, pd.DataFrame):
            rows_iter = display_df.iterrows()
        else:
            # Fallback: конвертируем в DataFrame
            display_df = pd.DataFrame([display_df]) if not isinstance(display_df, pd.DataFrame) else display_df
            rows_iter = display_df.iterrows()
        
        for idx, row in rows_iter:
            values = []
            for col in table_cols:
                val = row.get(col) if hasattr(row, 'get') else row[col] if col in row.index else None
                # Убеждаемся, что val не Series перед pd.isna()
                if isinstance(val, pd.Series):
                    val = val.iloc[0] if len(val) > 0 else None
                if pd.isna(val) if val is not None else True:
                    values.append("*N/A*")
                elif isinstance(val, (int, float)):
                    if col in ["multiple", "threshold", "cycle_start_equity", "equity_peak_in_cycle",
                               "cycle_start_balance", "current_balance"]:
                        values.append(f"{val:.4f}" if val is not None else "*N/A*")
                    else:
                        values.append(str(int(val)))
                else:
                    values.append(str(val) if val else "*N/A*")
            lines.append("| " + " | ".join(values) + " |")
        
        lines.append("")
    
    # Anomaly checks
    lines.append("### Anomaly Checks")
    lines.append("")
    
    if critical:
        lines.append("#### CRITICAL Anomalies")
        lines.append("")
        for anomaly in critical:
            lines.append(f"- **{anomaly['type']}**: {anomaly['message']}")
            if "reset_id" in anomaly:
                lines.append(f"  - Reset ID: {anomaly['reset_id']}")
            if "timestamp" in anomaly:
                lines.append(f"  - Timestamp: {anomaly['timestamp']}")
        lines.append("")
    
    if warnings:
        lines.append("#### WARNINGS")
        lines.append("")
        for warning in warnings:
            lines.append(f"- **{warning['type']}**: {warning['message']}")
        lines.append("")
    
    if not critical and not warnings:
        lines.append("✅ **No anomalies found**")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Marker & Ledger sanity
    lines.append("## Marker & Ledger Sanity")
    lines.append("")
    
    positions_df = artifacts.get("portfolio_positions")
    executions_df = artifacts.get("portfolio_executions")
    
    marker_positions_count = 0
    marker_executions_count = 0
    
    if positions_df is not None and not positions_df.empty:
        # Ищем marker позиции по signal_id
        if "signal_id" in positions_df.columns:
            marker_mask = positions_df["signal_id"].str.contains("__profit_reset_marker__", na=False)
            marker_positions_count = marker_mask.sum()
        else:
            marker_positions_count = 0
    
    if executions_df is not None and not executions_df.empty:
        # Ищем marker executions по signal_id
        if "signal_id" in executions_df.columns:
            marker_mask = executions_df["signal_id"].str.contains("__profit_reset_marker__", na=False)
            marker_executions_count = marker_mask.sum()
        else:
            marker_executions_count = 0
    
    lines.append(f"**Marker Positions:** {marker_positions_count}")
    lines.append(f"**Marker Executions:** {marker_executions_count}")
    lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Appendix
    lines.append("## Appendix")
    lines.append("")
    lines.append("### File Paths")
    lines.append("")
    for key, filename in artifact_names.items():
        if artifacts.get(key) is not None:
            lines.append(f"- `{filename}`: ✅")
        else:
            lines.append(f"- `{filename}`: ❌")
    lines.append("")
    
    return "\n".join(lines)


def explain_run(
    run_dir: Path,
    reports_subdir: str = "reports",
    out_path: Optional[Path] = None,
    format: str = "md",
    max_reset_rows: int = 200,
    no_xlsx: bool = False,
    verbose: bool = False
) -> Dict[str, Any]:
    """Основная функция анализа прогона."""
    reports_path = run_dir / reports_subdir
    
    # Загружаем артефакты
    artifacts = {
        "portfolio_events": load_csv_safe(reports_path / "portfolio_events.csv", "portfolio_events.csv"),
        "portfolio_positions": load_csv_safe(reports_path / "portfolio_positions.csv", "portfolio_positions.csv"),
        "portfolio_executions": load_csv_safe(reports_path / "portfolio_executions.csv", "portfolio_executions.csv"),
        "portfolio_summary": load_csv_safe(reports_path / "portfolio_summary.csv", "portfolio_summary.csv"),
        "portfolio_policy_summary": load_csv_safe(reports_path / "portfolio_policy_summary.csv", "portfolio_policy_summary.csv"),
        "strategy_summary": load_csv_safe(reports_path / "strategy_summary.csv", "strategy_summary.csv"),
        "report_pack_xlsx": None
    }
    
    if not no_xlsx:
        xlsx_path = reports_path / "report_pack.xlsx"
        if xlsx_path.exists():
            artifacts["report_pack_xlsx"] = "exists"  # Не парсим xlsx, просто отмечаем наличие
    
    # Извлекаем reset события
    events_df = artifacts.get("portfolio_events")
    reset_df = extract_reset_events(events_df) if events_df is not None else pd.DataFrame()
    
    # Проверяем аномалии
    critical, warnings = check_anomalies(
        reset_df,
        artifacts.get("portfolio_policy_summary"),
        verbose=verbose
    )
    
    # Генерируем markdown
    if format == "md":
        md_content = generate_markdown(
            run_dir,
            artifacts,
            reset_df,
            critical,
            warnings,
            max_reset_rows=max_reset_rows
        )
        
        # Определяем путь вывода
        if out_path is None:
            out_path = reports_path / "RUN_EXPLAIN.md"
        else:
            out_path = Path(out_path)
        
        # Сохраняем
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        return {
            "reset_events_count": len(reset_df),
            "critical_count": len(critical),
            "warnings_count": len(warnings),
            "output_path": str(out_path),
            "artifacts_found": [k for k, v in artifacts.items() if v is not None]
        }
    else:
        # JSON format (упрощенный)
        return {
            "reset_events_count": len(reset_df),
            "critical_anomalies": critical,
            "warnings": warnings,
            "artifacts_found": [k for k, v in artifacts.items() if v is not None]
        }


def main():
    """Точка входа CLI."""
    args = parse_args()
    
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"[ERROR] Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Печатаем краткую информацию
    print(f"[explain_run] run_dir={run_dir} reports={run_dir / args.reports_subdir}")
    
    # Выполняем анализ
    result = explain_run(
        run_dir=run_dir,
        reports_subdir=args.reports_subdir,
        out_path=Path(args.out) if args.out else None,
        format=args.format,
        max_reset_rows=args.max_reset_rows,
        no_xlsx=args.no_xlsx,
        verbose=args.verbose
    )
    
    # Печатаем резюме
    artifacts_str = ", ".join(result.get("artifacts_found", []))
    print(f"[explain_run] found: {artifacts_str}")
    print(f"[explain_run] reset_events={result.get('reset_events_count', 0)}")
    print(f"[explain_run] critical={result.get('critical_count', 0)} warning={result.get('warnings_count', 0)}")
    
    if args.format == "md" and "output_path" in result:
        print(f"[explain_run] wrote: {result['output_path']}")
    
    # Exit code
    if args.fail_on_anomaly and result.get("critical_count", 0) > 0:
        sys.exit(2)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
