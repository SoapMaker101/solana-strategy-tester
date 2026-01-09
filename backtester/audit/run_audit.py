# backtester/audit/run_audit.py
# Audit module entry point for Runner-only v2.0.1
#
# Run:
#   python -m backtester.audit.run_audit --reports-dir output/reports
#   python -m backtester.audit.run_audit --reports-dir output/reports

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple

import pandas as pd

from .invariant_checker import InvariantChecker


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        # pd.read_csv returns DataFrame when chunksize is not specified
        if isinstance(df, pd.DataFrame):
            return df
        return None
    except Exception:
        return None


def audit_run(reports_dir: Path) -> Tuple[int, int]:
    import logging
    logger = logging.getLogger(__name__)
    
    # Resolve absolute path and log it
    reports_dir_abs = reports_dir.resolve()
    print(f"[audit] Reports directory (resolved): {reports_dir_abs}")
    
    # Load CSVs and log file paths and row counts
    positions_path = reports_dir_abs / "portfolio_positions.csv"
    events_path = reports_dir_abs / "portfolio_events.csv"
    executions_path = reports_dir_abs / "portfolio_executions.csv"
    
    print(f"[audit] Loading positions from: {positions_path}")
    positions_df = _load_csv(positions_path)
    if positions_df is not None:
        print(f"[audit] Loaded {len(positions_df)} positions")
    else:
        print(f"[audit] Positions file not found or empty")
    
    print(f"[audit] Loading events from: {events_path}")
    events_df = _load_csv(events_path)
    if events_df is not None:
        print(f"[audit] Loaded {len(events_df)} events")
    else:
        print(f"[audit] Events file not found or empty")
    
    print(f"[audit] Loading executions from: {executions_path}")
    executions_df = _load_csv(executions_path)
    if executions_df is not None:
        print(f"[audit] Loaded {len(executions_df)} executions")
    else:
        print(f"[audit] Executions file not found or empty")

    checker = InvariantChecker(positions_df, events_df, executions_df)
    anomalies = checker.check()

    p0 = [a for a in anomalies if a.severity == "P0"]
    p1 = [a for a in anomalies if a.severity == "P1"]

    if anomalies:
        anomalies_path = reports_dir / "audit_anomalies.csv"
        pd.DataFrame([a.__dict__ for a in anomalies]).to_csv(anomalies_path, index=False)
        print(f"[audit] Saved anomalies to {anomalies_path}")

    print(f"[audit] P0={len(p0)} P1={len(p1)}")
    for a in anomalies:
        print(f"[{a.severity}] {a.code}: {a.message}")

    return len(p0), len(p1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit v2 runner-only invariants")
    parser.add_argument(
        "--reports-dir",
        type=str,
        default="output/reports",
        help="Directory containing portfolio_positions.csv / portfolio_events.csv / portfolio_executions.csv",
    )
    args = parser.parse_args()
    reports_dir = Path(args.reports_dir)
    p0, _ = audit_run(reports_dir)
    if p0 > 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
