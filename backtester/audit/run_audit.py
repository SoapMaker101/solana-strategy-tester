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
        return pd.read_csv(path)
    except Exception:
        return None


def audit_run(reports_dir: Path) -> Tuple[int, int]:
    positions_df = _load_csv(reports_dir / "portfolio_positions.csv")
    events_df = _load_csv(reports_dir / "portfolio_events.csv")
    executions_df = _load_csv(reports_dir / "portfolio_executions.csv")

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
