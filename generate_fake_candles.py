import argparse
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def generate_fake_candles_for_contract(
    contract_address: str,
    index: pd.DatetimeIndex,
    candles_dir: Path,
    timeframe: str,
) -> None:
    """
    Генерирует фейковые свечи для одного контракта и сохраняет в CSV.
    Формат файла: <candles_dir>/<contract_address>_<timeframe>.csv
    Колонки: timestamp, open, high, low, close, volume
    """
    # Стартовая цена от 0.01 до 1.0
    start_price = 0.01 + np.random.rand() * 0.99

    # Случайные доходности (лог-нормальное блуждание)
    n = len(index)
    returns = np.random.normal(loc=0.0002, scale=0.01, size=n)
    prices = start_price * np.exp(np.cumsum(returns))

    # close = price, open чуть вокруг close
    close = prices
    open_ = close * (1 + np.random.normal(0, 0.002, size=n))

    # high/low вокруг close в диапазоне ~1%
    high = close * (1 + np.random.rand(n) * 0.01)
    low = close * (1 - np.random.rand(n) * 0.01)

    # volume от 1_000 до 20_000
    volume = np.random.randint(1_000, 20_000, size=n)

    df = pd.DataFrame(
        {
            "timestamp": index.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )

    candles_dir.mkdir(parents=True, exist_ok=True)
    out_path = candles_dir / f"{contract_address}_{timeframe}.csv"
    df.to_csv(out_path, index=False, float_format="%.8f")

    print(f"[OK] Generated candles for {contract_address} -> {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate fake candles for backtester")
    parser.add_argument(
        "--signals",
        type=str,
        default="signals/example_signals.csv",
        help="Path to signals CSV (with contract_address, timestamp columns)",
    )
    parser.add_argument(
        "--candles-dir",
        type=str,
        default="data/candles",
        help="Directory to store candles CSV files",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1m",
        help="Timeframe suffix for candles files (e.g. 1m)",
    )
    parser.add_argument(
        "--before-min",
        type=int,
        default=120,
        help="Minutes before earliest signal to start generating candles",
    )
    parser.add_argument(
        "--after-min",
        type=int,
        default=720,
        help="Minutes after latest signal to stop generating candles",
    )

    args = parser.parse_args()

    signals_path = Path(args.signals)
    if not signals_path.exists():
        raise FileNotFoundError(f"Signals file not found: {signals_path}")

    candles_dir = Path(args.candles_dir)

    df = pd.read_csv(signals_path)

    required_cols = ["contract_address", "timestamp"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column '{col}' in {signals_path}")

    # Приводим timestamp к datetime с UTC
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    if df.empty:
        raise ValueError("Signals file is empty; nothing to generate candles for")

    # Диапазон по времени: от min - before_min до max + after_min
    t_min = df["timestamp"].min()
    t_max = df["timestamp"].max()

    start = t_min - timedelta(minutes=args.before_min)
    end = t_max + timedelta(minutes=args.after_min)

    print(f"Time range for candles: {start} .. {end}")

    index = pd.date_range(start=start, end=end, freq="1min", tz="UTC")

    contracts = sorted(df["contract_address"].astype(str).unique())
    print(f"Found {len(contracts)} unique contracts in signals")

    for contract in contracts:
        generate_fake_candles_for_contract(
            contract_address=contract,
            index=index,
            candles_dir=candles_dir,
            timeframe=args.timeframe,
        )

    print("Done generating fake candles.")


if __name__ == "__main__":
    main()
