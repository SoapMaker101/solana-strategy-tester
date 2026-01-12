"""
Timeout exit price validation tool.

Проверяет корректность raw_exit_price для позиций с reason=timeout/time_stop
путём сравнения с реальными свечами на момент exit_time.

Run:
    python -m backtester.tools.check_timeout_exit_price --reports-dir runs/A/reports --candles-dir runs/A/candles --out runs/A/reports/timeout_exit_price_check.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone
import pandas as pd

from ..infrastructure.price_loader import CsvPriceLoader
from ..domain.models import Candle


# Tolerance для сравнения цен (1% по умолчанию)
EXIT_PRICE_TOLERANCE_PCT = 1.0


def find_candle_at_or_after(candles: List[Candle], target_time: datetime) -> Optional[Candle]:
    """
    Находит свечу на момент exit_time или первую после него.
    
    Логика:
    a) если есть candle.timestamp == exit_time: взять её
    b) иначе взять минимальный candle.timestamp > exit_time
    c) если свечей после exit_time нет — вернуть None
    
    Args:
        candles: Список свечей (должен быть отсортирован по timestamp)
        target_time: Время для поиска (exit_time)
    
    Returns:
        Найденная свеча или None
    """
    if not candles:
        return None
    
    # Гарантируем сортировку по timestamp (ascending)
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    
    # Ищем точное совпадение
    for candle in sorted_candles:
        if candle.timestamp == target_time:
            return candle
    
    # Ищем первую свечу после target_time
    for candle in sorted_candles:
        if candle.timestamp > target_time:
            return candle
    
    # Не найдено
    return None


def resolve_candles_file(contract_address: str, candles_dir: Path, timeframe: str = "1m") -> Optional[Path]:
    """
    Разрешает путь к файлу свечей по contract_address.
    
    Использует ту же логику, что и CsvPriceLoader.resolve_candles_path.
    
    Args:
        contract_address: Адрес контракта
        candles_dir: Директория со свечами
        timeframe: Таймфрейм (по умолчанию "1m")
    
    Returns:
        Path к файлу свечей или None, если не найден
    """
    # Порядок проверки путей по приоритету (как в CsvPriceLoader)
    candidate_paths = [
        candles_dir / "cached" / timeframe / f"{contract_address}.csv",      # основной формат
        candles_dir / f"{contract_address}_{timeframe}.csv",                 # legacy формат
        candles_dir / f"{contract_address}.csv",                              # без таймфрейма
        candles_dir / "cached" / f"{contract_address}_{timeframe}.csv",      # cached + legacy
        candles_dir / timeframe / f"{contract_address}.csv",                 # timeframe как папка
    ]
    
    # Возвращаем первый существующий путь
    for path in candidate_paths:
        if path.exists():
            return path
    
    return None


def check_timeout_exit_price(
    position_id: str,
    contract_address: str,
    exit_time: datetime,
    stored_raw_exit_price: float,
    candles_dir: Optional[Path],
    timeframe: str = "1m",
) -> Dict[str, Any]:
    """
    Проверяет корректность raw_exit_price для одной позиции.
    
    Args:
        position_id: ID позиции
        contract_address: Адрес контракта
        exit_time: Время выхода (timezone-aware UTC)
        stored_raw_exit_price: Сохранённая raw_exit_price из portfolio_positions
        candles_dir: Директория со свечами (None если отсутствует)
        timeframe: Таймфрейм свечей
    
    Returns:
        Dict с результатами проверки:
        {
            "position_id": str,
            "contract_address": str,
            "exit_time": str (ISO),
            "stored_raw_exit_price": float,
            "expected_exit_close": Optional[float],
            "abs_diff_pct": Optional[float],
            "status": str,  # ok | suspect_exit_price_after_exit_time | no_candle_after_exit_time | missing_candles_file
        }
    """
    result = {
        "position_id": position_id,
        "contract_address": contract_address,
        "exit_time": exit_time.isoformat(),
        "stored_raw_exit_price": stored_raw_exit_price,
        "expected_exit_close": None,
        "abs_diff_pct": None,
        "status": "unknown",
    }
    
    # Если candles_dir отсутствует — graceful skip
    if candles_dir is None or not candles_dir.exists():
        result["status"] = "missing_candles_file"
        return result
    
    # Ищем файл свечей
    candles_path = resolve_candles_file(contract_address, candles_dir, timeframe)
    if candles_path is None:
        result["status"] = "missing_candles_file"
        return result
    
    # Загружаем свечи
    try:
        from datetime import timedelta
        # CsvPriceLoader использует base_dir для resolve_candles_path, а candles_dir для старого формата
        loader = CsvPriceLoader(
            candles_dir=str(candles_dir), 
            timeframe=timeframe, 
            base_dir=str(candles_dir)  # Используем candles_dir как base_dir
        )
        # Загружаем свечи вокруг exit_time (несколько часов до и после)
        start_time = exit_time - timedelta(hours=24)
        end_time = exit_time + timedelta(hours=24)
        candles = loader.load_prices(
            contract_address=contract_address,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        # Если ошибка загрузки — считаем файл недоступным
        result["status"] = "missing_candles_file"
        return result
    
    # Ищем свечу на момент exit_time или первую после
    exit_candle = find_candle_at_or_after(candles, exit_time)
    
    if exit_candle is None:
        result["status"] = "no_candle_after_exit_time"
        return result
    
    # Сравниваем цены
    expected_exit_close = exit_candle.close
    result["expected_exit_close"] = expected_exit_close
    
    if expected_exit_close is None or expected_exit_close <= 0:
        result["status"] = "suspect_exit_price_after_exit_time"
        return result
    
    # Вычисляем разницу в процентах
    if stored_raw_exit_price > 0:
        abs_diff_pct = abs((stored_raw_exit_price - expected_exit_close) / stored_raw_exit_price) * 100.0
        result["abs_diff_pct"] = abs_diff_pct
        
        # Определяем статус на основе tolerance
        if abs_diff_pct <= EXIT_PRICE_TOLERANCE_PCT:
            result["status"] = "ok"
        else:
            result["status"] = "suspect_exit_price_after_exit_time"
    else:
        result["status"] = "suspect_exit_price_after_exit_time"
    
    return result


def check_all_timeout_positions(
    positions_path: Path,
    candles_dir: Optional[Path],
    executions_path: Optional[Path] = None,
    timeframe: str = "1m",
) -> pd.DataFrame:
    """
    Проверяет все timeout позиции из portfolio_positions.csv.
    
    Args:
        positions_path: Путь к portfolio_positions.csv
        candles_dir: Директория со свечами (None если отсутствует)
        executions_path: Опциональный путь к portfolio_executions.csv (для дополнительной проверки)
        timeframe: Таймфрейм свечей
    
    Returns:
        DataFrame с результатами проверки
    """
    if not positions_path.exists():
        raise FileNotFoundError(f"Positions file not found: {positions_path}")
    
    # Загружаем positions
    positions_df = pd.read_csv(positions_path)
    
    # Фильтруем timeout позиции (reason family: timeout, time_stop, max_hold_minutes)
    timeout_reasons = ["timeout", "time_stop", "max_hold_minutes"]
    timeout_mask = positions_df["reason"].isin(timeout_reasons) | positions_df["reason"].str.contains("time", case=False, na=False)
    timeout_positions = positions_df[timeout_mask].copy()
    
    if timeout_positions.empty:
        print(f"[check] No timeout positions found in {positions_path}")
        return pd.DataFrame()
    
    print(f"[check] Found {len(timeout_positions)} timeout positions to check")
    
    # Проверяем каждую позицию
    results = []
    for _, row in timeout_positions.iterrows():
        position_id = row.get("position_id", "")
        contract_address = row.get("contract_address", "")
        exit_time_str = row.get("exit_time", "")
        stored_raw_exit_price = row.get("raw_exit_price", None)
        
        # Пропускаем если нет обязательных полей
        if not position_id or not contract_address:
            continue
        
        # Type narrowing для exit_time_str и stored_raw_exit_price
        if exit_time_str is None or pd.isna(exit_time_str):
            continue
        if stored_raw_exit_price is None or pd.isna(stored_raw_exit_price):
            continue
        
        # Парсим exit_time
        try:
            # exit_time_str гарантированно не None после проверки выше
            exit_time_dt = pd.to_datetime(exit_time_str, utc=True, errors="coerce")
            if pd.isna(exit_time_dt):
                continue
            exit_time = exit_time_dt.to_pydatetime()
        except Exception:
            continue
        
        # Проверяем позицию
        # stored_raw_exit_price гарантированно не None после проверки выше
        try:
            stored_price_float = float(stored_raw_exit_price)
        except (ValueError, TypeError):
            continue
        
        result = check_timeout_exit_price(
            position_id=str(position_id),
            contract_address=str(contract_address),
            exit_time=exit_time,
            stored_raw_exit_price=stored_price_float,
            candles_dir=candles_dir,
            timeframe=timeframe,
        )
        results.append(result)
    
    # Создаём DataFrame
    if results:
        df = pd.DataFrame(results)
        return df
    else:
        return pd.DataFrame()


def print_summary(results_df: pd.DataFrame) -> None:
    """
    Выводит краткий summary результатов проверки.
    
    Args:
        results_df: DataFrame с результатами проверки
    """
    if results_df.empty:
        print("[summary] No results to summarize")
        return
    
    total = len(results_df)
    ok = len(results_df[results_df["status"] == "ok"])
    suspect = len(results_df[results_df["status"] == "suspect_exit_price_after_exit_time"])
    missing_file = len(results_df[results_df["status"] == "missing_candles_file"])
    no_candle = len(results_df[results_df["status"] == "no_candle_after_exit_time"])
    
    print(f"\n{'='*60}")
    print(f"Timeout Exit Price Check Summary")
    print(f"{'='*60}")
    print(f"Total timeout positions: {total}")
    print(f"  ✓ OK: {ok}")
    print(f"  ⚠ Suspect: {suspect}")
    print(f"  ✗ Missing candles file: {missing_file}")
    print(f"  ✗ No candle after exit_time: {no_candle}")
    print(f"{'='*60}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Check timeout exit price alignment with candles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtester.tools.check_timeout_exit_price \\
      --reports-dir runs/A/reports \\
      --candles-dir runs/A/candles \\
      --out runs/A/reports/timeout_exit_price_check.csv
        """
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        required=True,
        help="Directory containing portfolio_positions.csv",
    )
    parser.add_argument(
        "--candles-dir",
        type=str,
        default=None,
        help="Directory containing candles CSV files (optional, graceful skip if missing)",
    )
    parser.add_argument(
        "--executions-path",
        type=str,
        default=None,
        help="Optional path to portfolio_executions.csv (for additional validation)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output CSV file path for results",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1m",
        help="Candles timeframe (default: 1m)",
    )
    
    args = parser.parse_args()
    
    reports_dir = Path(args.reports_dir)
    positions_path = reports_dir / "portfolio_positions.csv"
    
    candles_dir = Path(args.candles_dir) if args.candles_dir else None
    executions_path = Path(args.executions_path) if args.executions_path else None
    
    if candles_dir is None:
        print(f"[check] WARNING: --candles-dir not provided, will mark all as missing_candles_file")
    
    # Проверяем позиции
    results_df = check_all_timeout_positions(
        positions_path=positions_path,
        candles_dir=candles_dir,
        executions_path=executions_path,
        timeframe=args.timeframe,
    )
    
    # Выводим summary
    print_summary(results_df)
    
    # Сохраняем результаты
    if not results_df.empty:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        results_df.to_csv(out_path, index=False)
        print(f"[check] Saved results to {out_path}")
    else:
        print(f"[check] No results to save")


if __name__ == "__main__":
    main()
