# backtester/research/window_aggregator.py
# Aggregates strategy trades into time windows and calculates metrics

from __future__ import annotations

from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
import statistics


# DEFAULT split counts for equal window analysis
DEFAULT_SPLITS = [2, 3, 4, 5]

# Legacy windows (deprecated, kept for backward compatibility)
WINDOWS = {
    "6m": relativedelta(months=6),
    "3m": relativedelta(months=3),
    "2m": relativedelta(months=2),
    "1m": relativedelta(months=1),
}


def load_trades_csv(csv_path: Path) -> pd.DataFrame:
    """
    Загружает trades table из CSV файла.
    
    :param csv_path: Путь к CSV файлу с trades table.
    :return: DataFrame с обязательными колонками: entry_time, exit_time, pnl_pct, reason.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Trades CSV not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    
    # Проверяем обязательные колонки
    required_cols = ["entry_time", "exit_time", "pnl_pct", "reason"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in {csv_path}: {missing_cols}")
    
    # Конвертируем временные колонки в datetime
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    
    return df


def calculate_window_metrics(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Вычисляет метрики для окна сделок.
    
    :param trades_df: DataFrame с колонками entry_time, exit_time, pnl_pct, reason.
    :return: Словарь с метриками.
    """
    if len(trades_df) == 0:
        return {
            "trades_count": 0,
            "winrate": 0.0,
            "total_pnl": 0.0,
            "median_pnl": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "worst_trade": 0.0,
            "best_trade": 0.0,
        }
    
    # pnl_pct в долях (0.1 = 10%)
    pnls = trades_df["pnl_pct"].tolist()
    
    # Базовые метрики
    trades_count = len(pnls)
    winning_pnls = [p for p in pnls if p > 0]
    losing_pnls = [p for p in pnls if p < 0]
    winrate = len(winning_pnls) / trades_count if trades_count > 0 else 0.0
    total_pnl = sum(pnls)
    median_pnl = statistics.median(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0
    best_trade = max(pnls) if pnls else 0.0
    
    # Max drawdown (по cumulative pnl внутри окна)
    cumulative_pnl = np.cumsum(pnls)
    if len(cumulative_pnl) > 0:
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = cumulative_pnl - running_max
        max_drawdown = float(min(drawdowns)) if len(drawdowns) > 0 else 0.0
    else:
        max_drawdown = 0.0
    
    # Profit factor
    total_profit = sum(winning_pnls) if winning_pnls else 0.0
    total_loss = abs(sum(losing_pnls)) if losing_pnls else 0.0
    profit_factor = total_profit / total_loss if total_loss > 0 else (float('inf') if total_profit > 0 else 0.0)
    
    return {
        "trades_count": trades_count,
        "winrate": winrate,
        "total_pnl": total_pnl,
        "median_pnl": median_pnl,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "worst_trade": worst_trade,
        "best_trade": best_trade,
    }


def split_into_windows(
    trades_df: pd.DataFrame,
    window_delta: relativedelta,
) -> Dict[str, pd.DataFrame]:
    """
    Разделяет trades на временные окна.
    
    :param trades_df: DataFrame с колонкой entry_time.
    :param window_delta: Длительность окна.
    :return: Словарь {window_start_str: DataFrame}, где window_start_str - начало окна в ISO формате.
    """
    if len(trades_df) == 0:
        return {}
    
    # Сортируем по entry_time для стабильности
    df_sorted = trades_df.sort_values("entry_time").copy()
    
    # Находим минимальное и максимальное время
    min_time = df_sorted["entry_time"].min()
    max_time = df_sorted["entry_time"].max()
    
    # Проверяем на NaN/NaT (явно конвертируем результат pd.isna в bool)
    if bool(pd.isna(min_time)) or bool(pd.isna(max_time)):
        return {}
    
    windows = {}
    current_start = min_time
    
    while current_start <= max_time:
        current_end = current_start + window_delta
        
        # Фильтруем сделки, где entry_time попадает в окно [start, end)
        window_trades = df_sorted[
            (df_sorted["entry_time"] >= current_start) &
            (df_sorted["entry_time"] < current_end)
        ].copy()
        
        # Используем ISO формат для ключа
        window_key = current_start.strftime("%Y-%m-%dT%H:%M:%S%z")
        if len(window_trades) > 0:
            windows[window_key] = window_trades
        
        current_start = current_end
    
    return windows


def split_into_equal_windows(
    trades_df: pd.DataFrame,
    split_n: int,
) -> List[Dict[str, Any]]:
    """
    Разделяет trades на split_n равных по времени окон.
    
    :param trades_df: DataFrame с колонкой entry_time.
    :param split_n: Количество окон для разбиения.
    :return: Список словарей с информацией о каждом окне:
             [{"window_index": int, "window_start": datetime, "window_end": datetime, "trades": DataFrame}, ...]
             Включает ВСЕ окна, даже пустые (для корректного расчёта survival_rate).
    """
    if len(trades_df) == 0:
        return []
    
    if split_n <= 0:
        raise ValueError(f"split_n must be positive, got {split_n}")
    
    # Сортируем по entry_time для стабильности
    df_sorted = trades_df.sort_values("entry_time").copy()
    
    # Находим минимальное и максимальное время
    # min_time по entry_time, max_time по exit_time (как указано в требованиях)
    min_time = df_sorted["entry_time"].min()
    max_time = df_sorted["exit_time"].max()
    
    # Проверяем на NaN/NaT (явно конвертируем результат pd.isna в bool)
    if bool(pd.isna(min_time)) or bool(pd.isna(max_time)):
        return []
    
    # Вычисляем длительность каждого окна
    total_duration = max_time - min_time
    if total_duration.total_seconds() == 0:
        # Все сделки в один момент времени - возвращаем одно окно
        return [{
            "window_index": 0,
            "window_start": min_time,
            "window_end": max_time,
            "trades": df_sorted,
        }]
    
    window_duration = total_duration / split_n
    
    windows = []
    for i in range(split_n):
        window_start = min_time + (window_duration * i)
        window_end = min_time + (window_duration * (i + 1))
        
        # Для последнего окна включаем границу (<= вместо <)
        if i == split_n - 1:
            window_trades = df_sorted[
                (df_sorted["entry_time"] >= window_start) &
                (df_sorted["entry_time"] <= window_end)
            ].copy()
        else:
            window_trades = df_sorted[
                (df_sorted["entry_time"] >= window_start) &
                (df_sorted["entry_time"] < window_end)
            ].copy()
        
        # ВАЖНО: Включаем ВСЕ окна, даже пустые (для корректного расчёта survival_rate)
        windows.append({
            "window_index": i,
            "window_start": window_start,
            "window_end": window_end,
            "trades": window_trades,
        })
    
    return windows


def aggregate_strategy_windows(
    csv_path: Path,
    windows: Optional[Dict[str, relativedelta]] = None,
    split_counts: Optional[List[int]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Агрегирует trades стратегии по временным окнам.
    
    :param csv_path: Путь к CSV файлу с trades table.
    :param windows: Словарь {window_name: relativedelta}. Если None, используется WINDOWS.
                   Используется только если split_counts не указан (legacy режим).
    :param split_counts: Список значений split_n для мульти-масштабного разбиения.
                        Если указан, используется вместо windows.
                        Если None, используется DEFAULT_SPLITS.
    :return: Словарь {window_name: [window_info_dict, ...]}.
             Если используется split_counts, window_name будет "split_{split_n}".
             Каждый window_info_dict содержит:
             - window_index: int
             - window_start: datetime
             - window_end: datetime
             - metrics: dict с метриками окна
    """
    # Загружаем trades
    trades_df = load_trades_csv(csv_path)
    
    # Результат: {window_name: [window_info_dict, ...]}
    result = {}
    
    # Если указан split_counts (или используется по умолчанию), используем равные окна
    if split_counts is not None or windows is None:
        if split_counts is None:
            split_counts = DEFAULT_SPLITS
        
        for split_n in split_counts:
            window_list = split_into_equal_windows(trades_df, split_n)
            
            window_infos = []
            for window_info in window_list:
                window_trades = window_info["trades"]
                metrics = calculate_window_metrics(window_trades)
                
                window_infos.append({
                    "window_index": window_info["window_index"],
                    "window_start": window_info["window_start"],
                    "window_end": window_info["window_end"],
                    "metrics": metrics,
                })
            
            # Используем имя вида "split_{split_n}" для идентификации
            window_name = f"split_{split_n}"
            result[window_name] = window_infos
    else:
        # Старое поведение: используем windows (legacy режим)
        if windows is None:
            windows = WINDOWS
        
        for window_name, window_delta in windows.items():
            window_windows = split_into_windows(trades_df, window_delta)
            
            window_infos = []
            for window_start_str, window_trades in window_windows.items():
                metrics = calculate_window_metrics(window_trades)
                window_start_dt = pd.to_datetime(window_start_str)
                window_end_dt = window_start_dt + window_delta
                
                window_infos.append({
                    "window_index": len(window_infos),  # Простой индекс для legacy режима
                    "window_start": window_start_dt,
                    "window_end": window_end_dt,
                    "metrics": metrics,
                })
            
            result[window_name] = window_infos
    
    return result


def aggregate_all_strategies(
    reports_dir: Path,
    windows: Optional[Dict[str, relativedelta]] = None,
    split_counts: Optional[List[int]] = None,
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """
    Агрегирует все стратегии из reports_dir по временным окнам.
    
    :param reports_dir: Директория с *_trades.csv файлами.
    :param windows: Словарь {window_name: relativedelta}. Если None, используется WINDOWS.
                   Используется только если split_counts не указан (legacy режим).
    :param split_counts: Список значений split_n для мульти-масштабного разбиения.
                        Если указан, используется вместо windows.
                        Если None и windows=None, используется DEFAULT_SPLITS.
    :return: Словарь {strategy_name: {window_name: [window_info_dict, ...]}}.
    """
    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        raise FileNotFoundError(f"Reports directory not found: {reports_dir}")
    
    # Находим все *_trades.csv файлы
    trades_files = list(reports_dir.glob("*_trades.csv"))
    
    result = {}
    for trades_file in trades_files:
        # Извлекаем имя стратегии из имени файла (убираем _trades.csv)
        strategy_name = trades_file.stem.replace("_trades", "")
        
        try:
            strategy_windows = aggregate_strategy_windows(
                trades_file, 
                windows=windows,
                split_counts=split_counts
            )
            result[strategy_name] = strategy_windows
        except Exception as e:
            print(f"[WARNING] Failed to aggregate {strategy_name}: {e}")
            continue
    
    return result



