# backtester/research/strategy_stability.py
# Builds stability table from aggregated window metrics

from __future__ import annotations

from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import pandas as pd
import statistics
import numpy as np
import json
import ast

from .window_aggregator import aggregate_all_strategies, WINDOWS, load_trades_csv


def calculate_stability_metrics(
    strategy_windows: Dict[str, List[Dict[str, Any]]],
    split_n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Вычисляет показатели устойчивости стратегии на основе агрегированных окон.
    
    :param strategy_windows: Словарь {window_name: [window_info_dict, ...]}.
                            Каждый window_info_dict содержит window_index, window_start, window_end, metrics.
    :param split_n: Опциональное значение split_n для мульти-масштабного анализа.
                   Если указано, используется только окно с именем "split_{split_n}".
    :return: Словарь с показателями устойчивости.
    """
    # Собираем все total_pnl из всех окон (включая пустые окна)
    all_window_pnls = []
    
    # Если указан split_n, используем только соответствующее окно
    if split_n is not None:
        window_name = f"split_{split_n}"
        if window_name in strategy_windows:
            window_list = strategy_windows[window_name]
            for window_info in window_list:
                metrics = window_info.get("metrics", {})
                total_pnl = metrics.get("total_pnl", 0.0)
                all_window_pnls.append(total_pnl)
    else:
        # Старое поведение: собираем все окна (для legacy режима)
        for window_name, window_list in strategy_windows.items():
            for window_info in window_list:
                metrics = window_info.get("metrics", {})
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
    # ВАЖНО: survival_rate считается по окнам, не по трейдам
    # Окно считается выжившим, если total_pnl > 0
    # Пустое окно (0 сделок) имеет total_pnl = 0.0, поэтому считается невыжившим
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


def calculate_runner_metrics(
    trades_df: pd.DataFrame,
    portfolio_summary_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Вычисляет Runner-специфичные метрики из trades DataFrame.
    
    :param trades_df: DataFrame с колонками entry_time, exit_time, pnl_pct, meta (JSON строка).
    :param portfolio_summary_path: Опциональный путь к portfolio_summary.csv для max_drawdown_pct.
    :return: Словарь с Runner метриками.
    """
    if len(trades_df) == 0:
        return {
            "hit_rate_x2": 0.0,
            "hit_rate_x5": 0.0,
            "p90_hold_days": 0.0,
            "tail_contribution": 0.0,
            "max_drawdown_pct": 0.0,
        }
    
    # Парсим meta для получения levels_hit
    total_trades = len(trades_df)
    hit_x2_count = 0
    hit_x5_count = 0
    hold_days_list = []
    pnl_list = []
    
    for _, row in trades_df.iterrows():
        # Парсим meta (может быть JSON строка или dict)
        meta_str = row.get("meta", "{}")
        if isinstance(meta_str, str):
            try:
                meta = json.loads(meta_str)
            except (json.JSONDecodeError, ValueError):
                try:
                    meta = ast.literal_eval(meta_str)
                except (ValueError, SyntaxError):
                    meta = {}
        else:
            meta = meta_str if isinstance(meta_str, dict) else {}
        
        # Проверяем levels_hit
        levels_hit = meta.get("levels_hit", {})
        if isinstance(levels_hit, str):
            try:
                levels_hit = json.loads(levels_hit)
            except (json.JSONDecodeError, ValueError):
                try:
                    levels_hit = ast.literal_eval(levels_hit)
                except (ValueError, SyntaxError):
                    levels_hit = {}
        
        # Проверяем, достигнут ли уровень x2
        if levels_hit:
            # levels_hit может быть dict с ключами как строки "2.0" или числа
            hit_levels = []
            for k, v in levels_hit.items():
                try:
                    level = float(k)
                    hit_levels.append(level)
                except (ValueError, TypeError):
                    continue
            
            if any(level >= 2.0 for level in hit_levels):
                hit_x2_count += 1
            if any(level >= 5.0 for level in hit_levels):
                hit_x5_count += 1
        
        # Вычисляем время удержания в днях
        entry_time = row.get("entry_time")
        exit_time = row.get("exit_time")
        if entry_time and exit_time:
            if isinstance(entry_time, str):
                entry_time = pd.to_datetime(entry_time, utc=True)
            if isinstance(exit_time, str):
                exit_time = pd.to_datetime(exit_time, utc=True)
            
            if isinstance(entry_time, datetime) and isinstance(exit_time, datetime):
                hold_days = (exit_time - entry_time).total_seconds() / (24 * 3600)
                hold_days_list.append(hold_days)
        
        # Собираем PnL для tail contribution
        pnl = row.get("pnl_pct", 0.0)
        if isinstance(pnl, (int, float)):
            pnl_list.append(pnl)
    
    # Вычисляем hit rates
    hit_rate_x2 = hit_x2_count / total_trades if total_trades > 0 else 0.0
    hit_rate_x5 = hit_x5_count / total_trades if total_trades > 0 else 0.0
    
    # Вычисляем p90_hold_days
    if hold_days_list:
        p90_hold_days = np.percentile(hold_days_list, 90)
    else:
        p90_hold_days = 0.0
    
    # Вычисляем tail_contribution (доля PnL от top 5% сделок)
    tail_contribution = 0.0
    if pnl_list:
        total_pnl = sum(pnl_list)
        if total_pnl > 0:
            # Сортируем по убыванию PnL
            sorted_pnls = sorted(pnl_list, reverse=True)
            top_5_percent_count = max(1, int(len(sorted_pnls) * 0.05))
            top_5_percent_pnl = sum(sorted_pnls[:top_5_percent_count])
            tail_contribution = top_5_percent_pnl / total_pnl if total_pnl > 0 else 0.0
    
    # Загружаем max_drawdown_pct из portfolio_summary (если доступен)
    # Примечание: portfolio_summary обычно содержит одну строку на стратегию
    # или агрегированные данные, поэтому берем первое значение
    max_drawdown_pct = 0.0
    if portfolio_summary_path and portfolio_summary_path.exists():
        try:
            portfolio_df = pd.read_csv(portfolio_summary_path)
            if len(portfolio_df) > 0 and "max_drawdown_pct" in portfolio_df.columns:
                # Берем первое значение (обычно portfolio_summary содержит одну строку)
                max_drawdown_pct = float(portfolio_df.iloc[0]["max_drawdown_pct"])
        except Exception:
            pass  # Игнорируем ошибки при загрузке portfolio_summary
    
    return {
        "hit_rate_x2": hit_rate_x2,
        "hit_rate_x5": hit_rate_x5,
        "p90_hold_days": p90_hold_days,
        "tail_contribution": tail_contribution,
        "max_drawdown_pct": max_drawdown_pct,
    }


def is_runner_strategy(strategy_name: str) -> bool:
    """
    Определяет, является ли стратегия Runner стратегией.
    
    :param strategy_name: Имя стратегии.
    :return: True если стратегия Runner, False иначе.
    """
    strategy_lower = strategy_name.lower()
    return "runner" in strategy_lower or strategy_name.startswith("Runner")


def build_stability_table(
    aggregated_strategies: Dict[str, Dict[str, List[Dict[str, Any]]]],
    split_counts: Optional[List[int]] = None,
    reports_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Строит единую таблицу устойчивости стратегий.
    
    Для Runner стратегий добавляет Runner-специфичные метрики.
    
    :param aggregated_strategies: Словарь {strategy_name: {window_name: [window_info_dict, ...]}}.
    :param split_counts: Опциональный список значений split_n для мульти-масштабного анализа.
                        Если указан, генерируется одна строка на (strategy, split_n).
                        Если None, используется DEFAULT_SPLITS из window_aggregator.
    :param reports_dir: Опциональная директория с *_trades.csv файлами для Runner метрик.
    :return: DataFrame с колонками: strategy, split_count, survival_rate, pnl_variance, 
             worst_window_pnl, best_window_pnl, median_window_pnl, windows_positive, windows_total,
             и для Runner: hit_rate_x2, hit_rate_x5, p90_hold_days, tail_contribution, max_drawdown_pct.
    """
    from .window_aggregator import DEFAULT_SPLITS
    
    # Если split_counts не указан, используем DEFAULT_SPLITS
    if split_counts is None:
        split_counts = DEFAULT_SPLITS
    
    stability_rows = []
    
    for strategy_name, strategy_windows in aggregated_strategies.items():
        # Мульти-масштабный режим: одна строка на split_n
        for split_n in split_counts:
            stability_metrics = calculate_stability_metrics(strategy_windows, split_n=split_n)
            
            row = {
                "strategy": strategy_name,
                "split_count": split_n,  # Используем split_count вместо split_n для ясности
                "survival_rate": stability_metrics["survival_rate"],
                "pnl_variance": stability_metrics["pnl_variance"],
                "worst_window_pnl": stability_metrics["worst_window_pnl"],
                "best_window_pnl": stability_metrics["best_window_pnl"],
                "median_window_pnl": stability_metrics["median_window_pnl"],
                "windows_positive": stability_metrics["windows_positive"],
                "windows_total": stability_metrics["windows_total"],
            }
            
            # Для Runner стратегий добавляем Runner-метрики
            if is_runner_strategy(strategy_name) and reports_dir:
                trades_file = reports_dir / f"{strategy_name}_trades.csv"
                portfolio_summary_file = reports_dir / "portfolio_summary.csv"
                
                if trades_file.exists():
                    try:
                        trades_df = load_trades_csv(trades_file)
                        runner_metrics = calculate_runner_metrics(
                            trades_df,
                            portfolio_summary_path=portfolio_summary_file if portfolio_summary_file.exists() else None
                        )
                        row.update(runner_metrics)
                    except Exception as e:
                        # Если не удалось вычислить Runner метрики, используем значения по умолчанию
                        row.update({
                            "hit_rate_x2": 0.0,
                            "hit_rate_x5": 0.0,
                            "p90_hold_days": 0.0,
                            "tail_contribution": 0.0,
                            "max_drawdown_pct": 0.0,
                        })
            
            stability_rows.append(row)
    
    if not stability_rows:
        # Создаём пустой DataFrame с правильными колонками
        columns = [
            "strategy",
            "split_count",
            "survival_rate",
            "pnl_variance",
            "worst_window_pnl",
            "best_window_pnl",
            "median_window_pnl",
            "windows_positive",
            "windows_total",
        ]
        empty_df = pd.DataFrame({col: [] for col in columns})
        return empty_df

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


def build_detailed_windows_table(
    aggregated_strategies: Dict[str, Dict[str, List[Dict[str, Any]]]],
    split_counts: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    Строит детальную таблицу с информацией по каждому окну.
    
    :param aggregated_strategies: Словарь {strategy_name: {window_name: [window_info_dict, ...]}}.
    :param split_counts: Опциональный список значений split_n.
                        Если None, используется DEFAULT_SPLITS из window_aggregator.
    :return: DataFrame с колонками: strategy, split_count, window_index, window_start, window_end,
             window_trades, window_pnl.
    """
    from .window_aggregator import DEFAULT_SPLITS
    
    if split_counts is None:
        split_counts = DEFAULT_SPLITS
    
    detailed_rows = []
    
    for strategy_name, strategy_windows in aggregated_strategies.items():
        for split_n in split_counts:
            window_name = f"split_{split_n}"
            if window_name in strategy_windows:
                window_list = strategy_windows[window_name]
                for window_info in window_list:
                    metrics = window_info.get("metrics", {})
                    
                    detailed_rows.append({
                        "strategy": strategy_name,
                        "split_count": split_n,
                        "window_index": window_info.get("window_index", 0),
                        "window_start": window_info.get("window_start"),
                        "window_end": window_info.get("window_end"),
                        "window_trades": metrics.get("trades_count", 0),
                        "window_pnl": metrics.get("total_pnl", 0.0),
                    })
    
    if not detailed_rows:
        columns = [
            "strategy",
            "split_count",
            "window_index",
            "window_start",
            "window_end",
            "window_trades",
            "window_pnl",
        ]
        return pd.DataFrame({col: [] for col in columns})
    
    df = pd.DataFrame(detailed_rows)
    return df


def save_detailed_windows_table(
    detailed_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Сохраняет детальную таблицу окон в CSV.
    
    :param detailed_df: DataFrame с детальной информацией по окнам.
    :param output_path: Путь для сохранения CSV файла.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    detailed_df.to_csv(output_path, index=False)
    print(f"Saved detailed windows table to {output_path}")


def generate_stability_table_from_reports(
    reports_dir: Path,
    output_path: Optional[Path] = None,
    detailed_output_path: Optional[Path] = None,
    windows: Optional[Dict[str, Any]] = None,
    split_counts: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    Генерирует таблицу устойчивости из reports директории.
    
    :param reports_dir: Директория с *_trades.csv файлами.
    :param output_path: Опциональный путь для сохранения CSV. Если None, сохраняется в reports_dir/strategy_stability.csv.
    :param detailed_output_path: Опциональный путь для детального CSV с окнами. Если None, сохраняется в reports_dir/stage_a_summary.csv.
    :param windows: Опциональный словарь окон (legacy режим). Если None и split_counts=None, используется DEFAULT_SPLITS.
    :param split_counts: Опциональный список значений split_n для мульти-масштабного анализа.
                        Если указан, используется вместо windows.
                        Если None и windows=None, используется DEFAULT_SPLITS.
    :return: DataFrame с таблицей устойчивости.
    """
    from .window_aggregator import DEFAULT_SPLITS
    
    reports_dir = Path(reports_dir)
    
    # Если оба параметра None, используем DEFAULT_SPLITS
    if split_counts is None and windows is None:
        split_counts = DEFAULT_SPLITS
    
    # Агрегируем все стратегии
    aggregated_strategies = aggregate_all_strategies(
        reports_dir, 
        windows=windows,
        split_counts=split_counts
    )
    
    # Строим таблицу устойчивости (передаем reports_dir для Runner метрик)
    stability_df = build_stability_table(
        aggregated_strategies, 
        split_counts=split_counts,
        reports_dir=reports_dir
    )
    
    # Сохраняем если указан путь
    if output_path is None:
        output_path = reports_dir / "strategy_stability.csv"
    
    if len(stability_df) > 0:
        save_stability_table(stability_df, output_path)
    
    # Генерируем детальную таблицу с окнами
    if detailed_output_path is None:
        detailed_output_path = reports_dir / "stage_a_summary.csv"
    
    detailed_df = build_detailed_windows_table(aggregated_strategies, split_counts=split_counts)
    if len(detailed_df) > 0:
        save_detailed_windows_table(detailed_df, detailed_output_path)
    
    return stability_df






