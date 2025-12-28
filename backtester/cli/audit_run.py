# backtester/cli/audit_run.py
# CLI команда для запуска аудита

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..audit.audit_pipeline import run_audit


def main():
    """CLI entry point для audit_run."""
    parser = argparse.ArgumentParser(
        description="Run audit on backtest results (Runner-only)"
    )
    
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Directory with backtest results (contains portfolio_positions.csv, portfolio_events.csv, etc.)"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for audit reports (default: run_dir/audit/)"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: Run directory does not exist: {run_dir}", file=sys.stderr)
        sys.exit(1)
    
    output_dir = Path(args.output_dir) if args.output_dir else None
    
    try:
        report = run_audit(
            run_dir=run_dir,
            output_dir=output_dir,
            verbose=not args.quiet,
        )
        
        # Exit code: 0 если нет аномалий, 1 если есть
        if len(report.anomalies) > 0:
            print(f"\n⚠️  Found {len(report.anomalies)} anomalies. See audit report for details.")
            sys.exit(1)
        else:
            print("\n✅ No anomalies found. All checks passed.")
            sys.exit(0)
    
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

