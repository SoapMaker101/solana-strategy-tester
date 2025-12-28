# backtester/cli/audit_trade.py
# CLI команда для детального разбора одной позиции

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..audit.trade_replay import replay_position


def main():
    """CLI entry point для audit_trade."""
    parser = argparse.ArgumentParser(
        description="Detailed replay of a single position (Runner-only)"
    )
    
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Directory with backtest results"
    )
    
    parser.add_argument(
        "--position-id",
        type=str,
        default=None,
        help="Position ID (priority)"
    )
    
    parser.add_argument(
        "--signal-id",
        type=str,
        default=None,
        help="Signal ID (if no position-id)"
    )
    
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Strategy name (if no position-id)"
    )
    
    parser.add_argument(
        "--contract-address",
        type=str,
        default=None,
        help="Contract address (if no position-id)"
    )
    
    parser.add_argument(
        "--candles-dir",
        type=str,
        default=None,
        help="Directory with candles (default: data/candles/)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file (default: stdout)"
    )
    
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: Run directory does not exist: {run_dir}", file=sys.stderr)
        sys.exit(1)
    
    candles_dir = Path(args.candles_dir) if args.candles_dir else None
    
    try:
        replay = replay_position(
            run_dir=run_dir,
            position_id=args.position_id,
            signal_id=args.signal_id,
            strategy=args.strategy,
            contract_address=args.contract_address,
            candles_dir=candles_dir,
        )
        
        if replay is None:
            print("ERROR: Position not found", file=sys.stderr)
            sys.exit(1)
        
        replay_dict = replay.to_dict()
        
        if args.output:
            output_path = Path(args.output)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(replay_dict, f, indent=2, ensure_ascii=False)
            print(f"Saved trade replay to: {output_path}")
        else:
            print(json.dumps(replay_dict, indent=2, ensure_ascii=False))
        
        sys.exit(0)
    
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

