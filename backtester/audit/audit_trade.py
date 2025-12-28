from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _resolve_position(positions_df: pd.DataFrame, position_id: str | None, signal_id: str | None) -> pd.Series:
    if position_id:
        matches = positions_df[positions_df["position_id"].astype(str) == str(position_id)]
        if not matches.empty:
            return matches.iloc[0]
    if signal_id:
        matches = positions_df[positions_df["signal_id"].astype(str) == str(signal_id)]
        if not matches.empty:
            return matches.iloc[0]
    raise ValueError("Position not found for given identifiers.")


def audit_trade(reports_dir: Path, position_id: str | None, signal_id: str | None) -> None:
    positions_df = _load_csv(reports_dir / "portfolio_positions.csv")
    events_df = _load_csv(reports_dir / "portfolio_events.csv")
    executions_df = _load_csv(reports_dir / "portfolio_executions.csv")

    if positions_df is None:
        raise FileNotFoundError("portfolio_positions.csv not found")

    position = _resolve_position(positions_df, position_id, signal_id)
    pid = position.get("position_id")

    print("=" * 80)
    print("Position Summary")
    print("=" * 80)
    print(position.to_string())

    if events_df is not None:
        print("\nEvents")
        print("=" * 80)
        print(events_df[events_df["position_id"].astype(str) == str(pid)].to_string(index=False))

    if executions_df is not None:
        print("\nExecutions")
        print("=" * 80)
        print(executions_df[executions_df["position_id"].astype(str) == str(pid)].to_string(index=False))

        fills = executions_df[
            (executions_df["position_id"].astype(str) == str(pid))
            & (executions_df["event_type"] == "POSITION_PARTIAL_EXIT")
        ]
        realized_multiple = None
        if not fills.empty and "fraction" in fills.columns and "xn" in fills.columns:
            realized_multiple = (fills["fraction"].astype(float) * fills["xn"].astype(float)).sum()
        if realized_multiple is None:
            realized_multiple = position.get("realized_multiple")

        if realized_multiple is not None:
            pnl_pct_total = (float(realized_multiple) - 1.0) * 100.0
            print("\nPnL Breakdown (fills ledger)")
            print("=" * 80)
            print(f"realized_multiple: {realized_multiple}")
            print(f"pnl_pct_total: {pnl_pct_total:.2f}%")

    print("\nCandle References")
    print("=" * 80)
    print(f"entry_time: {position.get('entry_time')}")
    print(f"exit_time: {position.get('exit_time')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a single trade with events/executions")
    parser.add_argument("--reports-dir", type=str, default="output/reports")
    parser.add_argument("--position-id", type=str, default=None)
    parser.add_argument("--signal-id", type=str, default=None)
    args = parser.parse_args()

    if not args.position_id and not args.signal_id:
        raise SystemExit("Provide --position-id or --signal-id")

    audit_trade(Path(args.reports_dir), args.position_id, args.signal_id)


if __name__ == "__main__":
    main()
