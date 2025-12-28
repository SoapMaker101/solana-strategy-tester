# backtester/research/xn_analysis/xn_runner.py
# XN runner - CLI script for XN analysis execution

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path if running as script (before other imports)
# This allows the script to be run directly: python backtester/research/xn_analysis/xn_runner.py
if not __package__:
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import argparse
import re
from typing import List
import pandas as pd
import numpy as np

from backtester.domain.models import Candle
from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.infrastructure.price_loader import CsvPriceLoader, GeckoTerminalPriceLoader
from backtester.research.xn_analysis.xn_models import XNAnalysisConfig, XNSignalResult, XNSummaryStats
from backtester.research.xn_analysis.xn_analyzer import XNAnalyzer


def resolve_candles_path(contract: str, timeframe: str, base_dir: str = "data/candles") -> Path | None:
    """
    Resolve path to candles CSV file, checking multiple possible locations.
    
    Checks paths in the following order and returns the first existing one:
    a) {base_dir}/cached/{timeframe}/{contract}.csv          # основной формат проекта (ОБЯЗАТЕЛЬНО)
    b) {base_dir}/cached/{contract}_{timeframe}.csv
    c) {base_dir}/cached/{contract}.csv
    d) {base_dir}/{timeframe}/{contract}.csv
    e) {base_dir}/{contract}.csv
    
    :param contract: Contract address
    :param timeframe: Timeframe (e.g., "1m", "5m", "15m")
    :param base_dir: Base directory for candles (default: "data/candles")
    :return: Path to candles file if found, None otherwise
    """
    base_path = Path(base_dir)
    
    # Check paths in order of priority
    candidates = [
        base_path / "cached" / timeframe / f"{contract}.csv",          # основной формат
        base_path / "cached" / f"{contract}_{timeframe}.csv",           # старый формат
        base_path / "cached" / f"{contract}.csv",                       # без таймфрейма в имени
        base_path / timeframe / f"{contract}.csv",                      # без cached
        base_path / f"{contract}.csv",                                  # прямо в base_dir
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


class XNCsvPriceLoader(CsvPriceLoader):
    """
    Custom CSV price loader for XN analysis that uses resolve_candles_path
    to find candles in multiple possible locations.
    """
    def __init__(self, candles_dir: str, timeframe: str = "1m", strict_validation: bool = False):
        # Store base_dir for resolve_candles_path
        self.base_dir = candles_dir
        # Initialize parent with a dummy dir (we override _build_path anyway)
        super().__init__(candles_dir=candles_dir, timeframe=timeframe, strict_validation=strict_validation)
    
    def _build_path(self, contract_address: str) -> Path:
        """
        Override to use resolve_candles_path for flexible path resolution.
        """
        resolved = resolve_candles_path(contract_address, self.timeframe, self.base_dir)
        if resolved is None:
            # Return a non-existent path to trigger FileNotFoundError in load_prices
            return Path(self.base_dir) / f"{contract_address}_{self.timeframe}.csv"
        return resolved


def candles_to_dataframe(candles: List[Candle]) -> pd.DataFrame:
    """
    Convert list of Candle objects to pandas DataFrame.
    
    :param candles: List of Candle objects
    :return: DataFrame with columns: timestamp, open, high, low, close, volume
    """
    rows = []
    for candle in candles:
        rows.append({
            "timestamp": candle.timestamp,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def calculate_summary_stats(
    results: List[XNSignalResult],
    xn_levels: List[float],
) -> List[XNSummaryStats]:
    """
    Calculate summary statistics for each XN level.
    
    :param results: List of XNSignalResult objects
    :param xn_levels: List of XN levels to calculate stats for
    :return: List of XNSummaryStats objects
    """
    if not results:
        return []
    
    total_signals = len(results)
    stats_list = []
    
    for xn_level in xn_levels:
        # Collect times to reach this XN level (excluding None values)
        times = []
        reached_count = 0
        
        for result in results:
            # time_to_xn should contain all xn_levels from config
            if xn_level in result.time_to_xn:
                time_minutes = result.time_to_xn[xn_level]
                if time_minutes is not None:
                    times.append(time_minutes)
                    reached_count += 1
        
        # Calculate percentage
        reached_pct = (reached_count / total_signals * 100) if total_signals > 0 else 0.0
        
        # Calculate median and p90 if we have times
        if times:
            median_time = float(np.median(times))
            p90_time = float(np.percentile(times, 90))
        else:
            median_time = None
            p90_time = None
        
        stats = XNSummaryStats(
            xn_level=xn_level,
            reached_count=reached_count,
            reached_pct=reached_pct,
            median_time_minutes=median_time,
            p90_time_minutes=p90_time,
        )
        stats_list.append(stats)
    
    return stats_list


def aggregate_summary_from_csv(per_signal_csv_path: Path) -> pd.DataFrame:
    """
    Aggregate XN summary statistics from xn_per_signal.csv file.
    
    Reads the per-signal CSV and calculates summary statistics for each XN level.
    
    :param per_signal_csv_path: Path to xn_per_signal.csv file
    :return: DataFrame with columns: xn_level, reached_count, reached_pct, 
             median_time_minutes, p90_time_minutes (sorted by xn_level)
    """
    per_signal_csv_path = Path(per_signal_csv_path)
    if not per_signal_csv_path.exists():
        raise FileNotFoundError(f"Per-signal CSV not found: {per_signal_csv_path}")
    
    # Read per-signal CSV
    df = pd.read_csv(per_signal_csv_path)
    
    if df.empty:
        return pd.DataFrame(columns=["xn_level", "reached_count", "reached_pct", 
                                     "median_time_minutes", "p90_time_minutes"])  # type: ignore[call-overload]
    
    total_signals = len(df)
    
    # Find all time_to_x{N} columns
    time_to_x_pattern = re.compile(r"^time_to_x(\d+(?:\.\d+)?)$")
    
    xn_levels = []
    for col in df.columns:
        match = time_to_x_pattern.match(col)
        if match:
            xn_level = float(match.group(1))
            xn_levels.append(xn_level)
    
    if not xn_levels:
        raise ValueError("No time_to_x{N} columns found in CSV")
    
    # Sort XN levels
    xn_levels = sorted(xn_levels)
    
    # Calculate statistics for each XN level
    summary_rows = []
    for xn_level in xn_levels:
        # Get column name for this XN level
        if isinstance(xn_level, int) or (isinstance(xn_level, float) and xn_level.is_integer()):
            col_name = f"time_to_x{int(xn_level)}"
        else:
            col_name = f"time_to_x{xn_level}"
        
        if col_name not in df.columns:
            continue
        
        # Get times (exclude NaN/None values)
        times_series = df[col_name].dropna()
        times = times_series.tolist()
        
        reached_count = len(times)
        reached_pct = (reached_count / total_signals * 100) if total_signals > 0 else 0.0
        
        # Calculate median and p90 if we have times
        if len(times) > 0:
            median_time = float(np.median(times))
            p90_time = float(np.percentile(times, 90))
        else:
            median_time = None
            p90_time = None
        
        summary_rows.append({
            "xn_level": xn_level,
            "reached_count": reached_count,
            "reached_pct": reached_pct,
            "median_time_minutes": median_time,
            "p90_time_minutes": p90_time,
        })
    
    # Create DataFrame and sort by xn_level
    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values("xn_level").reset_index(drop=True)
    
    return summary_df


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="XN Analysis - Analyze XN potential of signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--signals",
        type=str,
        required=True,
        help="Path to CSV file with signals",
    )
    
    parser.add_argument(
        "--holding-days",
        type=int,
        default=90,
        help="Holding period in days (default: 90)",
    )
    
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1m",
        choices=["1m", "5m", "15m"],
        help="Price timeframe (default: 1m)",
    )
    
    parser.add_argument(
        "--xn-levels",
        type=float,
        nargs="+",
        default=[2, 3, 4, 5, 10, 20, 50, 100],
        help="XN levels to track (default: 2 3 4 5 10 20 50 100)",
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/xn_analysis/",
        help="Output directory for results (default: output/xn_analysis/)",
    )
    
    parser.add_argument(
        "--candles-dir",
        type=str,
        default="data/candles",
        help="Base directory for candles CSV files (default: data/candles)",
    )
    
    parser.add_argument(
        "--loader",
        type=str,
        default="csv",
        choices=["csv", "gecko"],
        help="Price loader type: csv (local files) or gecko (API) (default: csv)",
    )
    
    return parser.parse_args()


def main():
    """Main CLI entry point."""
    args = parse_args()
    
    # Validate inputs
    signals_path = Path(args.signals)
    if not signals_path.exists():
        print(f"[ERROR] Signals file not found: {signals_path}", file=sys.stderr)
        sys.exit(1)
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create configuration
    config = XNAnalysisConfig(
        holding_days=args.holding_days,
        xn_levels=args.xn_levels,
        price_timeframe=args.timeframe,
        price_source="high",
    )
    
    print(f"[XN] Configuration:")
    print(f"  Holding period: {config.holding_days} days")
    print(f"  Timeframe: {config.price_timeframe}")
    print(f"  XN levels: {config.xn_levels}")
    print()
    
    # Load signals
    print(f"[XN] Loading signals from {signals_path}...")
    signal_loader = CsvSignalLoader(str(signals_path))
    signals = signal_loader.load_signals()
    
    if not signals:
        print("[ERROR] No signals found", file=sys.stderr)
        sys.exit(1)
    
    print(f"[XN] Loaded {len(signals)} signals")
    print()
    
    # Create price loader
    if args.loader == "csv":
        price_loader = XNCsvPriceLoader(
            candles_dir=args.candles_dir,
            timeframe=args.timeframe,
        )
        print(f"[XN] Using CSV price loader (base_dir: {args.candles_dir})")
    else:
        price_loader = GeckoTerminalPriceLoader(
            cache_dir=args.candles_dir,
            timeframe=args.timeframe,
        )
        print(f"[XN] Using GeckoTerminal price loader (cache: {args.candles_dir})")
    print()
    
    # Analyze signals
    print(f"[XN] Analyzing {len(signals)} signals...")
    results: List[XNSignalResult] = []
    missing_count = 0
    total_signals = len(signals)
    
    for i, signal in enumerate(signals, 1):
        print(f"[XN] [{i}/{len(signals)}] Analyzing signal {signal.id} ({signal.contract_address})...")
        
        try:
            # Check if candles file exists (for CSV loader)
            if args.loader == "csv":
                candles_path = resolve_candles_path(
                    contract=signal.contract_address,
                    timeframe=args.timeframe,
                    base_dir=args.candles_dir,
                )
                if candles_path is None:
                    print(f"  ⚠️  [XN] missing candles: {signal.contract_address}")
                    missing_count += 1
                    continue
            
            # Load candles - need enough range for holding period
            from datetime import timedelta
            start_time = signal.timestamp
            end_time = signal.timestamp + timedelta(days=config.holding_days + 1)  # +1 for safety
            
            candles = price_loader.load_prices(
                contract_address=signal.contract_address,
                start_time=start_time,
                end_time=end_time,
            )
            
            if not candles:
                print(f"  ⚠️  No candles found, skipping")
                continue
            
            # Convert to DataFrame
            candles_df = candles_to_dataframe(candles)
            
            # Analyze signal
            result = XNAnalyzer.analyze_signal(signal, candles_df, config)
            
            if result is None:
                print(f"  ⚠️  Analysis returned None, skipping")
                continue
            
            results.append(result)
            print(f"  ✓ Max XN: {result.max_xn:.2f}x")
        
        except FileNotFoundError as e:
            # Handle case where file wasn't found (shouldn't happen if we checked, but just in case)
            print(f"  ⚠️  [XN] missing candles: {signal.contract_address}")
            missing_count += 1
            continue
        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue
    
    print()
    print(f"[XN] Analysis complete: {len(results)} results")
    
    # Print summary statistics
    processed_count = len(results)
    missing_pct = (missing_count / total_signals * 100) if total_signals > 0 else 0.0
    print()
    print("[XN] Summary:")
    print(f"  Total signals: {total_signals}")
    print(f"  Processed: {processed_count}")
    print(f"  Missing candles: {missing_count} ({missing_pct:.1f}%)")
    
    if not results:
        print("[ERROR] No results generated", file=sys.stderr)
        sys.exit(1)
    
    # Save per-signal results
    per_signal_path = output_dir / "xn_per_signal.csv"
    print(f"[XN] Saving per-signal results to {per_signal_path}...")
    
    per_signal_rows = []
    for result in results:
        # Convert time_to_xn dict to columns
        row = {
            "signal_id": result.signal_id,
            "contract_address": result.contract_address,
            "entry_time": result.entry_time.isoformat(),
            "entry_price": result.entry_price,
            "max_price": result.max_price,
            "max_xn": result.max_xn,
        }
        
        # Add time_to_xn columns
        for xn_level in config.xn_levels:
            # Format column name: use integer format if level is whole number
            if isinstance(xn_level, int) or (isinstance(xn_level, float) and xn_level.is_integer()):
                col_name = f"time_to_x{int(xn_level)}"
            else:
                col_name = f"time_to_x{xn_level}"
            row[col_name] = result.time_to_xn.get(xn_level)
        
        per_signal_rows.append(row)
    
    per_signal_df = pd.DataFrame(per_signal_rows)
    per_signal_df.to_csv(per_signal_path, index=False)
    print(f"[XN] Saved {len(results)} signal results")
    
    # Calculate and save summary statistics from CSV
    summary_path = output_dir / "xn_summary.csv"
    print(f"[XN] Calculating summary statistics from {per_signal_path}...")
    
    summary_df = aggregate_summary_from_csv(per_signal_path)
    summary_df.to_csv(summary_path, index=False)
    print(f"[XN] Saved summary statistics to {summary_path}")
    
    # Print summary
    print()
    print("[XN] Summary:")
    print(summary_df.to_string(index=False))
    print()
    print(f"[XN] Results saved to {output_dir}")


if __name__ == "__main__":
    main()






















