# backtester/research/strategy_stability.py
# Builds stability table from aggregated window metrics

from __future__ import annotations

from typing import Dict, List, Any, Optional, Mapping, Union
from pathlib import Path
from datetime import datetime
import pandas as pd
import statistics
import numpy as np
import json
import ast

from .window_aggregator import (
    aggregate_all_strategies, WINDOWS, load_trades_csv,
    split_into_equal_windows, calculate_window_metrics
)

# Type aliases
Number = Union[int, float]


def _to_float(v: Any) -> Optional[float]:
    """
    Безопасно конвертирует значение в float.
    
    :param v: Значение для конвертации.
    :return: float или None если конвертация невозможна.
    """
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        # pandas/np scalars
        return float(v)
    except Exception:
        return None


def _get_row_value(row: Any, key: str) -> Any:
    """
    Безопасно получает значение из row (dict/Series/другой объект).
    
    :param row: Объект с данными (dict, Series, и т.д.).
    :param key: Ключ для доступа.
    :return: Значение или None.
    """
    if hasattr(row, "get"):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _calc_max_xn_from_row(row: Any) -> Optional[float]:
    """
    Вычисляет max_xn (максимальный множитель) из цен в строке.
    
    Сначала пытается использовать exec_entry_price/exec_exit_price,
    затем fallback на raw_entry_price/raw_exit_price.
    
    :param row: Словарь/Series с данными позиции (любой объект с .get() или [] доступом).
    :return: max_xn или None если цены недоступны/невалидны.
    """
    exec_entry = _to_float(_get_row_value(row, "exec_entry_price"))
    exec_exit = _to_float(_get_row_value(row, "exec_exit_price"))
    if exec_entry is not None and exec_exit is not None and exec_entry > 0:
        return exec_exit / exec_entry

    raw_entry = _to_float(_get_row_value(row, "raw_entry_price"))
    raw_exit = _to_float(_get_row_value(row, "raw_exit_price"))
    if raw_entry is not None and raw_exit is not None and raw_entry > 0:
        return raw_exit / raw_entry

    return None


def _empty_df(columns: list[str]) -> pd.DataFrame:
    """
    Создает пустой DataFrame с указанными колонками.
    
    :param columns: Список имен колонок.
    :return: Пустой DataFrame с правильными типами колонок.
    """
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def calculate_stability_metrics(
    strategy_windows: Dict[str, List[Dict[str, Any]]],
    split_n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Вычисляет показатели устойчивости стратегии на основе агрегированных окон.
    
    Поддерживает два режима:
    1. Portfolio trades: использует total_pnl_sol (если доступен) или total_pnl
    2. Legacy strategy trades: использует total_pnl (pnl_pct сумма)
    
    :param strategy_windows: Словарь {window_name: [window_info_dict, ...]}.
                            Каждый window_info_dict содержит window_index, window_start, window_end, metrics.
    :param split_n: Опциональное значение split_n для мульти-масштабного анализа.
                   Если указано, используется только окно с именем "split_{split_n}".
    :return: Словарь с показателями устойчивости.
    """
    # Собираем все total_pnl из всех окон (включая пустые окна)
    # Используем total_pnl_sol если доступен (portfolio trades), иначе total_pnl (legacy)
    all_window_pnls = []
    
    # Если указан split_n, используем только соответствующее окно
    if split_n is not None:
        window_name = f"split_{split_n}"
        if window_name in strategy_windows:
            window_list = strategy_windows[window_name]
            for window_info in window_list:
                metrics = window_info.get("metrics", {})
                # Для portfolio trades используем total_pnl_sol, для legacy - total_pnl
                total_pnl = metrics.get("total_pnl_sol", metrics.get("total_pnl", 0.0))
                all_window_pnls.append(total_pnl)
    else:
        # Старое поведение: собираем все окна (для legacy режима)
        for window_name, window_list in strategy_windows.items():
            for window_info in window_list:
                metrics = window_info.get("metrics", {})
                total_pnl = metrics.get("total_pnl_sol", metrics.get("total_pnl", 0.0))
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
    strategy_name: str,
    portfolio_positions_path: Optional[Path] = None,
    portfolio_summary_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Вычисляет Runner-специфичные метрики из portfolio_positions.csv (источник правды).
    
    Теперь использует portfolio_positions.csv вместо strategy output для корректных hit rates.
    
    :param strategy_name: Имя стратегии для фильтрации позиций.
    :param portfolio_positions_path: Путь к portfolio_positions.csv.
    :param portfolio_summary_path: Опциональный путь к portfolio_summary.csv для max_drawdown_pct.
    :return: Словарь с Runner метриками.
    """
    # Значения по умолчанию
    default_metrics = {
        "hit_rate_x2": 0.0,
        "hit_rate_x5": 0.0,
        "hit_rate_x4": 0.0,  # Новое поле для tail threshold x4
        "p90_hold_days": 0.0,
        "tail_contribution": 0.0,
        "tail_pnl_share": 0.0,  # Новое поле: доля прибыли от tail-ног (0..1)
        "non_tail_pnl_share": 0.0,  # Новое поле: доля прибыли от non-tail (может быть <0)
        "max_drawdown_pct": 0.0,
    }
    
    # Загружаем portfolio_positions.csv
    if not portfolio_positions_path or not portfolio_positions_path.exists():
        return default_metrics
    
    try:
        positions_df = pd.read_csv(portfolio_positions_path)
    except Exception:
        return default_metrics
    
    if len(positions_df) == 0:
        return default_metrics
    
    # Фильтруем по стратегии
    strategy_positions = positions_df[positions_df["strategy"] == strategy_name]
    
    if len(strategy_positions) == 0:
        return default_metrics
    
    # Hit rates из max_xn_reached или hit_x2/hit_x5 колонок
    if "hit_x2" in strategy_positions.columns:
        hit_x2_count = strategy_positions["hit_x2"].sum()
        hit_x5_count = strategy_positions["hit_x5"].sum()
    elif "max_xn_reached" in strategy_positions.columns:
        hit_x2_count = (strategy_positions["max_xn_reached"] >= 2.0).sum()
        hit_x5_count = (strategy_positions["max_xn_reached"] >= 5.0).sum()
    elif "max_xn" in strategy_positions.columns:
        # Backward compatibility: старая колонка max_xn
        hit_x2_count = (strategy_positions["max_xn"] >= 2.0).sum()
        hit_x5_count = (strategy_positions["max_xn"] >= 5.0).sum()
    else:
        # Fallback: вычисляем из exec или raw цен
        hit_x2_count = 0
        hit_x5_count = 0
        for _, row in strategy_positions.iterrows():
            max_xn = _calc_max_xn_from_row(row)
            if max_xn is not None:
                if max_xn >= 2.0:
                    hit_x2_count += 1
                if max_xn >= 5.0:
                    hit_x5_count += 1
    
    total_positions = len(strategy_positions)
    hit_rate_x2 = hit_x2_count / total_positions if total_positions > 0 else 0.0
    hit_rate_x5 = hit_x5_count / total_positions if total_positions > 0 else 0.0
    
    # hit_rate_x4: доля сделок, где max_xn_reached >= 4.0 (tail threshold)
    TAIL_XN_THRESHOLD = 4.0
    if "hit_x4" in strategy_positions.columns:
        hit_x4_count = strategy_positions["hit_x4"].sum()
    elif "max_xn_reached" in strategy_positions.columns:
        hit_x4_count = (strategy_positions["max_xn_reached"] >= TAIL_XN_THRESHOLD).sum()
    elif "max_xn" in strategy_positions.columns:
        # Backward compatibility
        hit_x4_count = (strategy_positions["max_xn"] >= TAIL_XN_THRESHOLD).sum()
    else:
        # Fallback: вычисляем из exec или raw цен
        hit_x4_count = 0
        for _, row in strategy_positions.iterrows():
            max_xn = _calc_max_xn_from_row(row)
            if max_xn is not None and max_xn >= TAIL_XN_THRESHOLD:
                hit_x4_count += 1
    
    hit_rate_x4 = hit_x4_count / total_positions if total_positions > 0 else 0.0
    
    # p90_hold_days из hold_minutes
    if "hold_minutes" in strategy_positions.columns:
        hold_minutes_series = strategy_positions["hold_minutes"]
        if isinstance(hold_minutes_series, pd.Series):
            hold_minutes_values = hold_minutes_series.dropna()
            if not hold_minutes_values.empty:
                hold_days_values = hold_minutes_values / (24 * 60)  # Конвертируем минуты в дни
                p90_hold_days = float(np.percentile(hold_days_values, 90))
            else:
                p90_hold_days = 0.0
        else:
            p90_hold_days = 0.0
    else:
        p90_hold_days = 0.0
    
    # tail_contribution: доля PnL от позиций с max_xn_reached >= 5.0 (legacy, оставляем для совместимости)
    # Определение tail: max_xn_reached >= tail_threshold (по умолчанию 5.0)
    tail_threshold = 5.0  # Порог для tail trades (можно вынести в конфиг Stage B)
    tail_contribution = 0.0
    
    # tail_pnl_share и non_tail_pnl_share: новые метрики на основе realized PnL
    # Используем realized_tail_pnl_sol и realized_total_pnl_sol из portfolio_positions.csv
    TAIL_XN_THRESHOLD = 4.0  # Tail threshold для Runner (x4)
    tail_pnl_share = 0.0
    non_tail_pnl_share = 0.0
    
    if "pnl_sol" in strategy_positions.columns and "max_xn_reached" in strategy_positions.columns:
        total_pnl_sol = strategy_positions["pnl_sol"].sum()
        # Исправление: проверяем abs(pnl_total) < eps
        eps = 1e-6
        if abs(total_pnl_sol) < eps:
            tail_contribution = 0.0
        else:
            tail_pnl_sol = strategy_positions[strategy_positions["max_xn_reached"] >= tail_threshold]["pnl_sol"].sum()
            tail_contribution = tail_pnl_sol / total_pnl_sol
    elif "pnl_sol" in strategy_positions.columns and "max_xn" in strategy_positions.columns:
        # Backward compatibility: старая колонка max_xn
        total_pnl_sol = strategy_positions["pnl_sol"].sum()
        eps = 1e-6
        if abs(total_pnl_sol) < eps:
            tail_contribution = 0.0
        else:
            tail_pnl_sol = strategy_positions[strategy_positions["max_xn"] >= tail_threshold]["pnl_sol"].sum()
            tail_contribution = tail_pnl_sol / total_pnl_sol
    elif "pnl_sol" in strategy_positions.columns:
        # Fallback: вычисляем max_xn на лету
        total_pnl_sol = strategy_positions["pnl_sol"].sum()
        eps = 1e-6
        if abs(total_pnl_sol) < eps:
            tail_contribution = 0.0
        else:
            tail_pnl_sol = 0.0
            for _, row in strategy_positions.iterrows():
                max_xn = _calc_max_xn_from_row(row)
                if max_xn is not None and max_xn >= tail_threshold:
                    pnl_sol = _to_float(row.get("pnl_sol"))
                    if pnl_sol is not None:
                        tail_pnl_sol += pnl_sol
            tail_contribution = tail_pnl_sol / total_pnl_sol
    
    # Вычисляем tail_pnl_share и non_tail_pnl_share из realized PnL
    if "realized_total_pnl_sol" in strategy_positions.columns and "realized_tail_pnl_sol" in strategy_positions.columns:
        pnl_total_sol_pos = strategy_positions["realized_total_pnl_sol"].sum()
        pnl_tail_sol = strategy_positions["realized_tail_pnl_sol"].sum()
        
        eps = 1e-6
        if abs(pnl_total_sol_pos) > eps:
            tail_pnl_share = pnl_tail_sol / pnl_total_sol_pos
            # non_tail_pnl_share может быть отрицательным (leak)
            non_tail_pnl_share = (pnl_total_sol_pos - pnl_tail_sol) / pnl_total_sol_pos
        else:
            tail_pnl_share = 0.0
            non_tail_pnl_share = 0.0
    else:
        # Fallback: если колонок нет, создаем их на лету из pnl_sol и max_xn_reached
        TAIL_XN_THRESHOLD = 4.0
        if "pnl_sol" in strategy_positions.columns:
            # Создаем realized колонки на лету
            strategy_positions = strategy_positions.copy()
            
            # Вычисляем realized_total_pnl_sol = pnl_sol
            strategy_positions["realized_total_pnl_sol"] = strategy_positions["pnl_sol"]
            
            # Вычисляем realized_tail_pnl_sol из max_xn_reached
            if "max_xn_reached" in strategy_positions.columns:
                # realized_tail_pnl_sol = pnl_sol if max_xn_reached >= 4.0 else 0.0
                def _calc_tail_from_max_xn_reached(row: Any) -> float:
                    max_xn_val = _to_float(_get_row_value(row, "max_xn_reached"))
                    if max_xn_val is not None and max_xn_val >= TAIL_XN_THRESHOLD:
                        pnl_val = _to_float(_get_row_value(row, "pnl_sol"))
                        return pnl_val if pnl_val is not None else 0.0
                    return 0.0
                strategy_positions["realized_tail_pnl_sol"] = strategy_positions.apply(_calc_tail_from_max_xn_reached, axis=1)
            elif "max_xn" in strategy_positions.columns:
                # Backward compatibility
                def _calc_tail_from_max_xn(row: Any) -> float:
                    max_xn_val = _to_float(_get_row_value(row, "max_xn"))
                    if max_xn_val is not None and max_xn_val >= TAIL_XN_THRESHOLD:
                        pnl_val = _to_float(_get_row_value(row, "pnl_sol"))
                        return pnl_val if pnl_val is not None else 0.0
                    return 0.0
                strategy_positions["realized_tail_pnl_sol"] = strategy_positions.apply(_calc_tail_from_max_xn, axis=1)
            else:
                # Fallback: вычисляем max_xn на лету из цен
                def calc_tail_pnl(row: Any) -> float:
                    max_xn = _calc_max_xn_from_row(row)
                    if max_xn is not None and max_xn >= TAIL_XN_THRESHOLD:
                        pnl_sol = _to_float(_get_row_value(row, "pnl_sol"))
                        return pnl_sol if pnl_sol is not None else 0.0
                    return 0.0
                
                strategy_positions["realized_tail_pnl_sol"] = strategy_positions.apply(calc_tail_pnl, axis=1)
            
            # Теперь используем созданные колонки для расчета метрик
            pnl_total_sol_pos = strategy_positions["realized_total_pnl_sol"].sum()
            pnl_tail_sol = strategy_positions["realized_tail_pnl_sol"].sum()
            
            eps = 1e-6
            if abs(pnl_total_sol_pos) > eps:
                tail_pnl_share = pnl_tail_sol / pnl_total_sol_pos
                # non_tail_pnl_share может быть отрицательным (leak)
                non_tail_pnl_share = (pnl_total_sol_pos - pnl_tail_sol) / pnl_total_sol_pos
            else:
                tail_pnl_share = 0.0
                non_tail_pnl_share = 0.0
        else:
            # Если нет даже pnl_sol, оставляем 0.0
            tail_pnl_share = 0.0
            non_tail_pnl_share = 0.0
    
    # Загружаем max_drawdown_pct из portfolio_summary (если доступен)
    max_drawdown_pct = 0.0
    if portfolio_summary_path and portfolio_summary_path.exists():
        try:
            portfolio_df = pd.read_csv(portfolio_summary_path)
            if len(portfolio_df) > 0 and "max_drawdown_pct" in portfolio_df.columns:
                # Ищем строку для нашей стратегии
                strategy_row = portfolio_df[portfolio_df["strategy"] == strategy_name]
                if len(strategy_row) > 0:
                    max_drawdown_pct = float(strategy_row.iloc[0]["max_drawdown_pct"])
                else:
                    # Fallback: берем первое значение
                    max_drawdown_pct = float(portfolio_df.iloc[0]["max_drawdown_pct"])
        except Exception:
            pass  # Игнорируем ошибки при загрузке portfolio_summary
    
    return {
        "hit_rate_x2": hit_rate_x2,
        "hit_rate_x5": hit_rate_x5,
        "hit_rate_x4": hit_rate_x4,  # Новое поле
        "p90_hold_days": p90_hold_days,
        "tail_contribution": tail_contribution,  # Legacy, оставляем для совместимости
        "tail_pnl_share": tail_pnl_share,  # Новое поле
        "non_tail_pnl_share": non_tail_pnl_share,  # Новое поле
        "max_drawdown_pct": max_drawdown_pct,
    }


def is_runner_strategy(strategy_name: str) -> bool:
    """
    Определяет, является ли стратегия Runner стратегией.
    
    Поддерживает legacy-детекцию для обратной совместимости:
    - имена, содержащие "runner" (case-insensitive)
    - имена, начинающиеся на "RR_" (case-insensitive) - legacy
    
    :param strategy_name: Имя стратегии.
    :return: True если стратегия Runner, False иначе.
    """
    if not strategy_name:
        return False
    s = strategy_name.strip().lower()
    return ("runner" in s) or s.startswith("rr_")


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
            
            # Для Runner стратегий добавляем Runner-метрики из portfolio_positions.csv
            if is_runner_strategy(strategy_name) and reports_dir:
                portfolio_positions_file = reports_dir / "portfolio_positions.csv"
                portfolio_summary_file = reports_dir / "portfolio_summary.csv"
                
                if portfolio_positions_file.exists():
                    try:
                        runner_metrics = calculate_runner_metrics(
                            strategy_name=strategy_name,
                            portfolio_positions_path=portfolio_positions_file,
                            portfolio_summary_path=portfolio_summary_file if portfolio_summary_file.exists() else None
                        )
                        row.update(runner_metrics)
                    except Exception as e:
                        # Если не удалось вычислить Runner метрики, используем значения по умолчанию
                        row.update({
                            "hit_rate_x2": 0.0,
                            "hit_rate_x5": 0.0,
                            "hit_rate_x4": 0.0,
                            "p90_hold_days": 0.0,
                            "tail_contribution": 0.0,
                            "tail_pnl_share": 0.0,
                            "non_tail_pnl_share": 0.0,
                            "max_drawdown_pct": 0.0,
                        })
                else:
                    # Если portfolio_positions.csv не найден, используем значения по умолчанию
                    row.update({
                        "hit_rate_x2": 0.0,
                        "hit_rate_x5": 0.0,
                        "hit_rate_x4": 0.0,
                        "p90_hold_days": 0.0,
                        "tail_contribution": 0.0,
                        "tail_pnl_share": 0.0,
                        "non_tail_pnl_share": 0.0,
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
        return _empty_df(columns)

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
                    
                    # Используем total_pnl_sol для portfolio trades, иначе total_pnl (legacy)
                    window_pnl = metrics.get("total_pnl_sol", metrics.get("total_pnl", 0.0))
                    
                    detailed_rows.append({
                        "strategy": strategy_name,
                        "split_count": split_n,
                        "window_index": window_info.get("window_index", 0),
                        "window_start": window_info.get("window_start"),
                        "window_end": window_info.get("window_end"),
                        "window_trades": metrics.get("trades_count", 0),
                        "window_pnl": window_pnl,
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
        return _empty_df(columns)
    
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
    
    # Сохраняем XLSX отчет с несколькими листами
    if len(stability_df) > 0 or len(detailed_df) > 0:
        from ..infrastructure.xlsx_writer import save_xlsx
        import warnings
        
        xlsx_path = reports_dir / "stage_a_report.xlsx"
        sheets = {}
        
        if len(stability_df) > 0:
            sheets["window_metrics"] = stability_df
        else:
            # Пустой DataFrame с правильными колонками
            sheets["window_metrics"] = _empty_df([
                "strategy", "split_count", "survival_rate", "pnl_variance",
                "worst_window_pnl", "best_window_pnl", "median_window_pnl",
                "windows_positive", "windows_total", "trades_total"
            ])
        
        if len(detailed_df) > 0:
            sheets["strategy_summary"] = detailed_df
        else:
            # Пустой DataFrame с правильными колонками
            sheets["strategy_summary"] = _empty_df([
                "strategy", "split_count", "window_index", "window_start",
                "window_end", "window_trades", "window_pnl"
            ])
        
        try:
            save_xlsx(xlsx_path, sheets)
        except Exception as e:
            warnings.warn(
                f"Excel export failed for Stage A report: {e}. Continuing with CSV only.",
                UserWarning,
                stacklevel=2
            )
    
    return stability_df


def generate_stability_table_from_portfolio_trades(
    trades_path: Path,
    reports_dir: Path,
    output_path: Optional[Path] = None,
    detailed_output_path: Optional[Path] = None,
    split_counts: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    Генерирует таблицу устойчивости из единого portfolio_trades.csv файла.
    
    Это основной метод для Stage A - работает на portfolio executed trades, а не на strategy-level trades.
    
    :param trades_path: Путь к portfolio_trades.csv файлу с исполненными портфельными сделками.
    :param reports_dir: Директория для output файлов и опциональных дополнительных данных (например, portfolio_summary.csv).
    :param output_path: Опциональный путь для сохранения CSV. Если None, сохраняется в reports_dir/strategy_stability.csv.
    :param detailed_output_path: Опциональный путь для детального CSV с окнами. Если None, сохраняется в reports_dir/stage_a_summary.csv.
    :param split_counts: Опциональный список значений split_n для мульти-масштабного анализа.
                        Если None, используется DEFAULT_SPLITS.
    :return: DataFrame с таблицей устойчивости.
    """
    from .window_aggregator import DEFAULT_SPLITS, validate_trades_table
    
    trades_path = Path(trades_path)
    reports_dir = Path(reports_dir)
    
    if split_counts is None:
        split_counts = DEFAULT_SPLITS
    
    print(f"[stage_a] Loading portfolio trades from: {trades_path}")
    
    # Загружаем и валидируем trades table
    trades_df = load_trades_csv(trades_path, validate=True)
    
    print(f"[stage_a] Trades loaded: {len(trades_df)}")
    
    # Фильтруем только закрытые позиции (должно быть уже отфильтровано, но на всякий случай)
    filtered_df = trades_df[trades_df["status"] == "closed"].copy()
    removed_count = len(trades_df) - len(filtered_df)
    if removed_count > 0:
        print(f"[stage_a] Trades after filters (closed-only): {len(filtered_df)} (removed {removed_count} non-closed)")
    
    if len(filtered_df) == 0:
        print(f"[stage_a] WARNING: No executed trades found in portfolio_trades.csv")
        # Возвращаем пустой DataFrame с правильными колонками
        columns = [
            "strategy", "split_count", "survival_rate", "pnl_variance",
            "worst_window_pnl", "best_window_pnl", "median_window_pnl",
            "windows_positive", "windows_total", "trades_total",
        ]
        return _empty_df(columns)
    
    # Получаем уникальные стратегии
    strategy_series = pd.Series(filtered_df["strategy"])
    unique_strategies = strategy_series.unique()
    print(f"[stage_a] Strategies: {len(unique_strategies)} ({', '.join(str(s) for s in unique_strategies)})")
    print(f"[stage_a] Splits: {split_counts}")
    
    # Агрегируем по стратегиям
    aggregated_strategies = {}
    
    for strategy_name in unique_strategies:
        strategy_trades = filtered_df.loc[filtered_df["strategy"] == strategy_name].copy()
        
        print(f"[stage_a] Strategy '{strategy_name}': {len(strategy_trades)} executed trades")
        
        # Агрегируем окна для этой стратегии
        strategy_windows = {}
        
        for split_n in split_counts:
            window_list = split_into_equal_windows(strategy_trades, split_n)
            
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
            
            window_name = f"split_{split_n}"
            strategy_windows[window_name] = window_infos
        
        aggregated_strategies[strategy_name] = strategy_windows
    
    # Строим таблицу устойчивости
    stability_df = build_stability_table(
        aggregated_strategies,
        split_counts=split_counts,
        reports_dir=reports_dir,  # Для Runner метрик если нужно
    )
    
    # Добавляем trades_total для каждой стратегии (общее количество исполненных сделок)
    if len(stability_df) > 0:
        trades_total_map: Dict[str, int] = {}
        for strategy_name in unique_strategies:
            strategy_trades_count = len(filtered_df.loc[filtered_df["strategy"] == strategy_name])
            trades_total_map[str(strategy_name)] = strategy_trades_count
        
        stability_df["trades_total"] = stability_df["strategy"].map(lambda x: trades_total_map.get(str(x), 0)).fillna(0).astype(int)
    
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
    
    # Сохраняем XLSX отчет с несколькими листами
    if len(stability_df) > 0 or len(detailed_df) > 0:
        from ..infrastructure.xlsx_writer import save_xlsx
        import warnings
        
        xlsx_path = reports_dir / "stage_a_report.xlsx"
        sheets = {}
        
        if len(stability_df) > 0:
            sheets["window_metrics"] = stability_df
        else:
            # Пустой DataFrame с правильными колонками
            sheets["window_metrics"] = _empty_df([
                "strategy", "split_count", "survival_rate", "pnl_variance",
                "worst_window_pnl", "best_window_pnl", "median_window_pnl",
                "windows_positive", "windows_total", "trades_total"
            ])
        
        if len(detailed_df) > 0:
            sheets["strategy_summary"] = detailed_df
        else:
            # Пустой DataFrame с правильными колонками
            sheets["strategy_summary"] = _empty_df([
                "strategy", "split_count", "window_index", "window_start",
                "window_end", "window_trades", "window_pnl"
            ])
        
        try:
            save_xlsx(xlsx_path, sheets)
        except Exception as e:
            warnings.warn(
                f"Excel export failed for Stage A report: {e}. Continuing with CSV only.",
                UserWarning,
                stacklevel=2
            )
    
    return stability_df





