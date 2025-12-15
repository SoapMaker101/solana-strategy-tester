# backtester/research/strategy_stability.py
# Builds stability table from aggregated window metrics

from __future__ import annotations

from typing import Dict, List, Any, Optional
from pathlib import Path
import pandas as pd
import statistics
import numpy as np

from .window_aggregator import aggregate_all_strategies, WINDOWS


def calculate_stability_metrics(
    strategy_windows: Dict[str, Dict[str, Any]],
    split_n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Вычисляет показатели устойчивости стратегии на основе агрегированных окон.
    
    :param strategy_windows: Словарь {window_name: {window_start: metrics_dict}}.
    :param split_n: Опциональное значение split_n для мульти-масштабного анализа.
                   Если указано, используется только окно с именем "split_{split_n}".
    :return: Словарь с показателями устойчивости.
    """
    # Собираем все total_pnl из всех окон
    all_window_pnls = []
    
    # Если указан split_n, используем только соответствующее окно
    if split_n is not None:
        window_name = f"split_{split_n}"
        if window_name in strategy_windows:
            windows = strategy_windows[window_name]
            for window_start, metrics in windows.items():
                total_pnl = metrics.get("total_pnl", 0.0)
                all_window_pnls.append(total_pnl)
    else:
        # Старое поведение: собираем все окна
        for window_name, windows in strategy_windows.items():
            for window_start, metrics in windows.items():
                total_pnl = metrics.get("total_pnl", 0.0)
                all_window_pnls.append(total_pnl)
    
    if not all_window_pnls:
        return {
            "survival_rate": 0.0,
            "pnl_variance": 0.0,
            "worst_window_pnl": 0.0,
            "best_window_pnl": 0.0,
            "median_window_pnl": 0.0,
            "windows_positive": 0,
            "windows_total": 0,
        }
    
    # Вычисляем производные показатели
    windows_total = len(all_window_pnls)
    windows_positive = sum(1 for pnl in all_window_pnls if pnl > 0)
    survival_rate = windows_positive / windows_total if windows_total > 0 else 0.0
    
    # Variance (дисперсия)
    if len(all_window_pnls) > 1:
        pnl_variance = statistics.variance(all_window_pnls)
    else:
        pnl_variance = 0.0
    
    worst_window_pnl = min(all_window_pnls) if all_window_pnls else 0.0
    best_window_pnl = max(all_window_pnls) if all_window_pnls else 0.0
    median_window_pnl = statistics.median(all_window_pnls) if all_window_pnls else 0.0
    
    return {
        "survival_rate": survival_rate,
        "pnl_variance": pnl_variance,
        "worst_window_pnl": worst_window_pnl,
        "best_window_pnl": best_window_pnl,
        "median_window_pnl": median_window_pnl,
        "windows_positive": windows_positive,
        "windows_total": windows_total,
    }


def build_stability_table(
    aggregated_strategies: Dict[str, Dict[str, Dict[str, Any]]],
    split_counts: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    Строит единую таблицу устойчивости стратегий.
    
    :param aggregated_strategies: Словарь {strategy_name: {window_name: {window_start: metrics_dict}}}.
    :param split_counts: Опциональный список значений split_n для мульти-масштабного анализа.
                        Если указан, генерируется одна строка на (strategy, split_n).
    :return: DataFrame с колонками: strategy, split_n (если используется), survival_rate, pnl_variance, 
             worst_window_pnl, best_window_pnl, median_window_pnl, windows_positive, windows_total.
    """
    stability_rows = []
    
    for strategy_name, strategy_windows in aggregated_strategies.items():
        if split_counts is not None:
            # Мульти-масштабный режим: одна строка на split_n
            for split_n in split_counts:
                stability_metrics = calculate_stability_metrics(strategy_windows, split_n=split_n)
                
                stability_rows.append({
                    "strategy": strategy_name,
                    "split_n": split_n,
                    "survival_rate": stability_metrics["survival_rate"],
                    "pnl_variance": stability_metrics["pnl_variance"],
                    "worst_window_pnl": stability_metrics["worst_window_pnl"],
                    "best_window_pnl": stability_metrics["best_window_pnl"],
                    "median_window_pnl": stability_metrics["median_window_pnl"],
                    "windows_positive": stability_metrics["windows_positive"],
                    "windows_total": stability_metrics["windows_total"],
                })
        else:
            # Старое поведение: одна строка на стратегию
            stability_metrics = calculate_stability_metrics(strategy_windows)
            
            stability_rows.append({
                "strategy": strategy_name,
                "survival_rate": stability_metrics["survival_rate"],
                "pnl_variance": stability_metrics["pnl_variance"],
                "worst_window_pnl": stability_metrics["worst_window_pnl"],
                "best_window_pnl": stability_metrics["best_window_pnl"],
                "median_window_pnl": stability_metrics["median_window_pnl"],
                "windows_positive": stability_metrics["windows_positive"],
                "windows_total": stability_metrics["windows_total"],
            })
    
    if not stability_rows:
        # Создаём пустой DataFrame с правильными колонками
        columns = [
            "strategy",
            "survival_rate",
            "pnl_variance",
            "worst_window_pnl",
            "best_window_pnl",
            "median_window_pnl",
            "windows_positive",
            "windows_total",
        ]
        if split_counts is not None:
            columns.insert(1, "split_n")  # Вставляем split_n после strategy
        return pd.DataFrame(columns=columns)
    
    df = pd.DataFrame(stability_rows)
    
    # ВАЖНО: НЕ сортируем по pnl, НЕ делаем score, НЕ фильтруем
    # Возвращаем как есть
    
    return df


def save_stability_table(
    stability_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Сохраняет таблицу устойчивости в CSV.
    
    :param stability_df: DataFrame с таблицей устойчивости.
    :param output_path: Путь для сохранения CSV файла.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stability_df.to_csv(output_path, index=False)
    print(f"Saved strategy stability table to {output_path}")


def generate_stability_table_from_reports(
    reports_dir: Path,
    output_path: Optional[Path] = None,
    windows: Optional[Dict[str, Any]] = None,
    split_counts: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    Генерирует таблицу устойчивости из reports директории.
    
    :param reports_dir: Директория с *_trades.csv файлами.
    :param output_path: Опциональный путь для сохранения CSV. Если None, сохраняется в reports_dir/strategy_stability.csv.
    :param windows: Опциональный словарь окон. Если None, используется WINDOWS.
                   Используется только если split_counts не указан.
    :param split_counts: Опциональный список значений split_n для мульти-масштабного анализа.
                        Если указан, используется вместо windows.
    :return: DataFrame с таблицей устойчивости.
    """
    reports_dir = Path(reports_dir)
    
    # Агрегируем все стратегии
    aggregated_strategies = aggregate_all_strategies(
        reports_dir, 
        windows=windows,
        split_counts=split_counts
    )
    
    # Строим таблицу устойчивости
    stability_df = build_stability_table(aggregated_strategies, split_counts=split_counts)
    
    # Сохраняем если указан путь
    if output_path is None:
        output_path = reports_dir / "strategy_stability.csv"
    
    if len(stability_df) > 0:
        save_stability_table(stability_df, output_path)
    
    return stability_df


