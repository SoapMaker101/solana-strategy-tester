# backtester/decision/strategy_selector.py
# Applies selection rules to filter strategies

from __future__ import annotations

from typing import List, Optional
from pathlib import Path
import pandas as pd
import numpy as np

from .selection_rules import SelectionCriteria, DEFAULT_CRITERIA, DEFAULT_RUNNER_CRITERIA


def is_runner_strategy(strategy_name: str) -> bool:
    """
    Определяет, является ли стратегия Runner стратегией.
    
    :param strategy_name: Имя стратегии.
    :return: True если стратегия Runner, False иначе.
    """
    # Проверяем по имени стратегии (обычно содержит "runner" или "Runner")
    strategy_lower = strategy_name.lower()
    return "runner" in strategy_lower or strategy_name.startswith("Runner")


def normalize_stability_schema(stability_df: pd.DataFrame) -> pd.DataFrame:
    """
    Нормализует схему stability DataFrame для совместимости с разными версиями Stage A.
    
    Выполняет:
    - Маппинг split_count <-> split_n
    - Заполнение windows_total из split_n/split_count
    - Вычисление windows_positive из survival_rate и windows_total (если отсутствует)
    - Обработка NaN значений
    
    :param stability_df: Исходный DataFrame из strategy_stability.csv
    :return: Нормализованный DataFrame
    """
    if len(stability_df) == 0:
        return stability_df.copy()
    
    df = stability_df.copy()
    
    # a) Нормализация split поля
    has_split_count = "split_count" in df.columns
    has_split_n = "split_n" in df.columns
    
    if has_split_count and not has_split_n:
        # Создаем split_n из split_count
        df["split_n"] = df["split_count"]
    elif has_split_n and not has_split_count:
        # Создаем split_count из split_n
        df["split_count"] = df["split_n"]
    # Если есть оба - ничего не делаем
    
    # b) Гарантирование windows_total
    if "windows_total" not in df.columns:
        # Пытаемся вычислить из split_n или split_count
        if "split_n" in df.columns:
            df["windows_total"] = df["split_n"]
        elif "split_count" in df.columns:
            df["windows_total"] = df["split_count"]
        else:
            # Если нет ни split_n, ни split_count, ставим 0
            df["windows_total"] = 0
    else:
        # Заполняем NaN в windows_total из split_n/split_count
        if "split_n" in df.columns:
            df["windows_total"] = df["windows_total"].fillna(df["split_n"])
        elif "split_count" in df.columns:
            df["windows_total"] = df["windows_total"].fillna(df["split_count"])
        # Заполняем оставшиеся NaN нулями
        df["windows_total"] = df["windows_total"].fillna(0).astype(int)
    
    # c) Гарантирование windows_positive (только если нужно)
    # Вычисляем из survival_rate и windows_total, если отсутствует
    if "windows_positive" not in df.columns:
        if "survival_rate" in df.columns and "windows_total" in df.columns:
            # Вычисляем windows_positive = round(survival_rate * windows_total)
            # Заполняем NaN в survival_rate и windows_total перед вычислением
            survival_filled = df["survival_rate"].fillna(0.0)
            windows_filled = df["windows_total"].fillna(0).astype(int)
            df["windows_positive"] = (survival_filled * windows_filled).round().astype(int)
            # Clamp: 0..windows_total
            df["windows_positive"] = df["windows_positive"].clip(lower=0, upper=windows_filled)
        else:
            # Если нет данных для вычисления, ставим 0
            df["windows_positive"] = 0
    else:
        # Заполняем NaN в windows_positive
        if "survival_rate" in df.columns and "windows_total" in df.columns:
            mask = df["windows_positive"].isna()
            if mask.any():
                survival_filled = df.loc[mask, "survival_rate"].fillna(0.0)
                windows_filled = df.loc[mask, "windows_total"].fillna(0).astype(int)
                df.loc[mask, "windows_positive"] = (survival_filled * windows_filled).round().astype(int)
                df.loc[mask, "windows_positive"] = df.loc[mask, "windows_positive"].clip(
                    lower=0, upper=windows_filled
                )
        # Заполняем оставшиеся NaN нулями
        df["windows_positive"] = df["windows_positive"].fillna(0).astype(int)
    
    # d) survival_rate не пересчитываем, если он уже задан
    # (это уже есть в df, ничего не делаем)
    
    # e) NaN-safe для критичных полей
    # Заполняем NaN в основных полях нулями/дефолтными значениями
    critical_fields = {
        "survival_rate": 0.0,
        "pnl_variance": 0.0,
        "worst_window_pnl": 0.0,
        "median_window_pnl": 0.0,
        "windows_total": 0,
        "windows_positive": 0,
        "hit_rate_x2": 0.0,
        "hit_rate_x4": 0.0,
        "hit_rate_x5": 0.0,
        "tail_pnl_share": 0.0,
        "non_tail_pnl_share": 0.0,
        "tail_contribution": 0.0,
        "max_drawdown_pct": 0.0,
    }
    
    for field, default_value in critical_fields.items():
        if field in df.columns:
            df[field] = df[field].fillna(default_value)
    
    return df


def check_strategy_criteria(
    row: pd.Series,
    criteria: SelectionCriteria,
    runner_criteria: Optional[SelectionCriteria] = None,
) -> tuple[bool, List[str]]:
    """
    Проверяет, проходит ли стратегия все критерии отбора.
    
    Для Runner стратегий применяются Runner-специфичные критерии,
    для RR/RRD - стандартные критерии.
    
    :param row: Строка DataFrame с метриками стратегии.
    :param criteria: Критерии отбора для RR/RRD стратегий.
    :param runner_criteria: Опциональные критерии для Runner стратегий.
                           Если None, используется DEFAULT_RUNNER_CRITERIA.
    :return: (passed: bool, failed_reasons: List[str])
    """
    if runner_criteria is None:
        runner_criteria = DEFAULT_RUNNER_CRITERIA
    
    failed_reasons = []
    strategy_name = str(row.get("strategy", ""))
    is_runner = is_runner_strategy(strategy_name)
    
    if is_runner:
        # Применяем Runner критерии
        # Проверяем, используем ли мы v2 критерии (если задан min_hit_rate_x4 или min_tail_pnl_share)
        use_v2 = (runner_criteria.min_hit_rate_x4 is not None or 
                  runner_criteria.min_tail_pnl_share is not None or
                  runner_criteria.min_non_tail_pnl_share is not None)
        
        if use_v2:
            # V2 критерии: используем hit_rate_x4 и tail_pnl_share
            # Проверка 1: hit_rate_x4 >= min_hit_rate_x4
            if runner_criteria.min_hit_rate_x4 is not None:
                hit_rate_x4 = row.get("hit_rate_x4")
                if hit_rate_x4 is None or (isinstance(hit_rate_x4, float) and np.isnan(hit_rate_x4)):
                    failed_reasons.append("missing_hit_rate_x4")
                else:
                    hit_rate_x4 = float(hit_rate_x4)
                    if hit_rate_x4 < runner_criteria.min_hit_rate_x4:
                        failed_reasons.append(
                            f"hit_rate_x4 {hit_rate_x4:.3f} < {runner_criteria.min_hit_rate_x4}"
                        )
            
            # Проверка 2: tail_pnl_share >= min_tail_pnl_share
            if runner_criteria.min_tail_pnl_share is not None:
                tail_pnl_share = row.get("tail_pnl_share")
                if tail_pnl_share is None or (isinstance(tail_pnl_share, float) and np.isnan(tail_pnl_share)):
                    failed_reasons.append("missing_tail_pnl_share")
                else:
                    tail_pnl_share = float(tail_pnl_share)
                    if tail_pnl_share < runner_criteria.min_tail_pnl_share:
                        failed_reasons.append(
                            f"tail_pnl_share {tail_pnl_share:.3f} < {runner_criteria.min_tail_pnl_share}"
                        )
            
            # Проверка 3: non_tail_pnl_share >= min_non_tail_pnl_share
            if runner_criteria.min_non_tail_pnl_share is not None:
                non_tail_pnl_share = row.get("non_tail_pnl_share")
                if non_tail_pnl_share is None or (isinstance(non_tail_pnl_share, float) and np.isnan(non_tail_pnl_share)):
                    failed_reasons.append("missing_non_tail_pnl_share")
                else:
                    non_tail_pnl_share = float(non_tail_pnl_share)
                    if non_tail_pnl_share < runner_criteria.min_non_tail_pnl_share:
                        failed_reasons.append(
                            f"non_tail_pnl_share {non_tail_pnl_share:.3f} < {runner_criteria.min_non_tail_pnl_share}"
                        )
        else:
            # V1 критерии: используем hit_rate_x2, hit_rate_x5, tail_contribution
            # Проверка 1: hit_rate_x2 >= min_hit_rate_x2
            if runner_criteria.min_hit_rate_x2 is not None:
                hit_rate_x2 = row.get("hit_rate_x2")
                hit_rate_x2 = 0.0 if hit_rate_x2 is None else hit_rate_x2
                if hit_rate_x2 < runner_criteria.min_hit_rate_x2:
                    failed_reasons.append(
                        f"hit_rate_x2 {hit_rate_x2:.3f} < {runner_criteria.min_hit_rate_x2}"
                    )
            
            # Проверка 2: hit_rate_x5 >= min_hit_rate_x5
            if runner_criteria.min_hit_rate_x5 is not None:
                hit_rate_x5 = row.get("hit_rate_x5")
                hit_rate_x5 = 0.0 if hit_rate_x5 is None else hit_rate_x5
                if hit_rate_x5 < runner_criteria.min_hit_rate_x5:
                    failed_reasons.append(
                        f"hit_rate_x5 {hit_rate_x5:.3f} < {runner_criteria.min_hit_rate_x5}"
                    )
        
        # Проверка p90_hold_days (только если задан в критериях)
        # Проверка 1: p90_hold_days >= min_p90_hold_days (если задан)
        if runner_criteria.min_p90_hold_days is not None:
            p90_hold_days = row.get("p90_hold_days")
            if p90_hold_days is None or (isinstance(p90_hold_days, float) and np.isnan(p90_hold_days)):
                failed_reasons.append("missing_p90_hold_days")
            else:
                p90_hold_days = float(p90_hold_days)
                if p90_hold_days < runner_criteria.min_p90_hold_days:
                    failed_reasons.append(
                        f"p90_hold_days {p90_hold_days:.2f} < {runner_criteria.min_p90_hold_days}"
                    )
        
        # Проверка 2: p90_hold_days <= max_p90_hold_days (если задан)
        if runner_criteria.max_p90_hold_days is not None:
            p90_hold_days = row.get("p90_hold_days")
            if p90_hold_days is None or (isinstance(p90_hold_days, float) and np.isnan(p90_hold_days)):
                # Если нет значения, но есть max ограничение, не считаем это fail (опциональное поле)
                pass
            else:
                p90_hold_days = float(p90_hold_days)
                if p90_hold_days > runner_criteria.max_p90_hold_days:
                    failed_reasons.append(
                        f"p90_hold_days {p90_hold_days:.2f} > {runner_criteria.max_p90_hold_days}"
                    )
        
        # Проверка tail_contribution (только если задан в критериях, только для v1)
        # Проверка 1: tail_contribution >= min_tail_contribution (если задан)
        if runner_criteria.min_tail_contribution is not None:
            tail_contribution = row.get("tail_contribution")
            if tail_contribution is None or (isinstance(tail_contribution, float) and np.isnan(tail_contribution)):
                failed_reasons.append("missing_tail_contribution")
            else:
                tail_contribution = float(tail_contribution)
                if tail_contribution < runner_criteria.min_tail_contribution:
                    failed_reasons.append(
                        f"tail_contribution {tail_contribution:.3f} < {runner_criteria.min_tail_contribution}"
                    )
        
        # Проверка 2: tail_contribution <= max_tail_contribution (если задан)
        if runner_criteria.max_tail_contribution is not None:
            tail_contribution = row.get("tail_contribution")
            if tail_contribution is None or (isinstance(tail_contribution, float) and np.isnan(tail_contribution)):
                # Если нет значения, но есть max ограничение, не считаем это fail (опциональное поле)
                pass
            else:
                tail_contribution = float(tail_contribution)
                if tail_contribution > runner_criteria.max_tail_contribution:
                    failed_reasons.append(
                        f"tail_contribution {tail_contribution:.3f} > {runner_criteria.max_tail_contribution}"
                    )
        
        # Проверка max_drawdown_pct (применяется и в v1, и в v2)
        if runner_criteria.max_drawdown_pct is not None:
            max_drawdown_pct = row.get("max_drawdown_pct")
            if max_drawdown_pct is None or (isinstance(max_drawdown_pct, float) and np.isnan(max_drawdown_pct)):
                # Если нет значения, но есть ограничение, не считаем это fail (опциональное поле)
                pass
            else:
                max_drawdown_pct = float(max_drawdown_pct)
                if max_drawdown_pct < runner_criteria.max_drawdown_pct:
                    failed_reasons.append(
                        f"max_drawdown_pct {max_drawdown_pct:.3f} < {runner_criteria.max_drawdown_pct}"
                    )
    else:
        # Применяем RR/RRD критерии
        # Проверка 1: survival_rate >= min_survival_rate
        survival_rate = row.get("survival_rate")
        survival_rate = 0.0 if survival_rate is None else survival_rate
        if survival_rate < criteria.min_survival_rate:
            failed_reasons.append(
                f"survival_rate {survival_rate:.3f} < {criteria.min_survival_rate}"
            )
        
        # Проверка 2: pnl_variance <= max_pnl_variance
        pnl_variance = row.get("pnl_variance")
        pnl_variance = float('inf') if pnl_variance is None else pnl_variance
        if pnl_variance > criteria.max_pnl_variance:
            failed_reasons.append(
                f"pnl_variance {pnl_variance:.6f} > {criteria.max_pnl_variance}"
            )
        
        # Проверка 3: worst_window_pnl >= min_worst_window_pnl
        worst_window_pnl = row.get("worst_window_pnl")
        worst_window_pnl = -float('inf') if worst_window_pnl is None else worst_window_pnl
        if worst_window_pnl < criteria.min_worst_window_pnl:
            failed_reasons.append(
                f"worst_window_pnl {worst_window_pnl:.4f} < {criteria.min_worst_window_pnl}"
            )
        
        # Проверка 4: median_window_pnl >= min_median_window_pnl
        median_window_pnl = row.get("median_window_pnl")
        median_window_pnl = -float('inf') if median_window_pnl is None else median_window_pnl
        if median_window_pnl < criteria.min_median_window_pnl:
            failed_reasons.append(
                f"median_window_pnl {median_window_pnl:.4f} < {criteria.min_median_window_pnl}"
            )
        
        # Проверка 5: windows_total >= min_windows
        windows_total = row.get("windows_total")
        windows_total = 0 if windows_total is None else windows_total
        if windows_total < criteria.min_windows:
            failed_reasons.append(
                f"windows_total {windows_total} < {criteria.min_windows}"
            )
    
    passed = len(failed_reasons) == 0
    return passed, failed_reasons


def select_strategies(
    stability_df: pd.DataFrame,
    criteria: SelectionCriteria = DEFAULT_CRITERIA,
    runner_criteria: Optional[SelectionCriteria] = None,
) -> pd.DataFrame:
    """
    Применяет критерии отбора к стратегиям из stability table.
    
    Для Runner стратегий применяются Runner-специфичные критерии,
    для RR/RRD - стандартные критерии.
    
    :param stability_df: DataFrame из strategy_stability.csv.
    :param criteria: Критерии отбора для RR/RRD. По умолчанию DEFAULT_CRITERIA.
    :param runner_criteria: Критерии отбора для Runner. По умолчанию DEFAULT_RUNNER_CRITERIA.
    :return: DataFrame с колонками из stability_df + passed (bool) + failed_reasons (List[str]).
             ВАЖНО: НЕ СОРТИРУЕТСЯ по pnl или другим метрикам.
    """
    if len(stability_df) == 0:
        # Возвращаем пустой DataFrame с правильными колонками
        result_df = stability_df.copy()
        result_df["passed"] = []
        result_df["failed_reasons"] = []
        return result_df
    
    # Нормализуем схему DataFrame для совместимости
    stability_df = normalize_stability_schema(stability_df)
    
    # Проверяем обязательные колонки (базовые для всех стратегий)
    required_cols = ["strategy"]
    missing_cols = [col for col in required_cols if col not in stability_df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in stability_df: {missing_cols}")
    
    # Разделяем стратегии на Runner и RR/RRD
    runner_strategies = []
    rr_strategies = []
    
    for _, row in stability_df.iterrows():
        strategy_name = str(row.get("strategy", ""))
        if is_runner_strategy(strategy_name):
            runner_strategies.append(row)
        else:
            rr_strategies.append(row)
    
    # Проверяем обязательные колонки для RR/RRD
    if rr_strategies:
        rr_required_cols = [
            "survival_rate",
            "pnl_variance",
            "worst_window_pnl",
            "median_window_pnl",
            "windows_total",
        ]
        rr_missing_cols = [col for col in rr_required_cols if col not in stability_df.columns]
        if rr_missing_cols:
            raise ValueError(f"Missing required columns for RR/RRD strategies: {rr_missing_cols}")
    
    # Проверяем обязательные колонки для Runner (опциональные, могут отсутствовать)
    # Runner метрики могут быть не вычислены, если Stage A не был обновлен
    
    # Применяем критерии к каждой стратегии
    results = []
    for _, row in stability_df.iterrows():
        passed, failed_reasons = check_strategy_criteria(row, criteria, runner_criteria)
        
        result_row = row.to_dict()
        result_row["passed"] = passed
        result_row["failed_reasons"] = failed_reasons
        results.append(result_row)
    
    # Создаём результат
    result_df = pd.DataFrame(results)
    
    # ВАЖНО: НЕ сортируем по pnl или другим метрикам
    # Сохраняем исходный порядок
    
    return result_df


def load_stability_csv(csv_path: Path) -> pd.DataFrame:
    """
    Загружает strategy_stability.csv.
    
    Поддерживает как RR/RRD метрики, так и Runner метрики.
    
    :param csv_path: Путь к CSV файлу.
    :return: DataFrame с метриками стратегий.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Stability CSV not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    
    # Проверяем обязательные колонки (только strategy)
    required_cols = ["strategy"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in {csv_path}: {missing_cols}")
    
    # RR/RRD колонки опциональны (могут отсутствовать для Runner стратегий)
    # Runner колонки опциональны (могут отсутствовать для RR/RRD стратегий)
    
    return df


def save_selection_table(
    selection_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Сохраняет таблицу отбора в CSV.
    
    :param selection_df: DataFrame с результатами отбора.
    :param output_path: Путь для сохранения CSV файла.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Конвертируем failed_reasons (List[str]) в строку для CSV
    df_to_save = selection_df.copy()
    if "failed_reasons" in df_to_save.columns:
        df_to_save["failed_reasons"] = df_to_save["failed_reasons"].apply(
            lambda x: "; ".join(x) if isinstance(x, list) else str(x)
        )
    
    df_to_save.to_csv(output_path, index=False)
    print(f"Saved strategy selection table to {output_path}")


def generate_selection_table_from_stability(
    stability_csv_path: Path,
    output_path: Optional[Path] = None,
    criteria: Optional[SelectionCriteria] = None,
    runner_criteria: Optional[SelectionCriteria] = None,
) -> pd.DataFrame:
    """
    Генерирует таблицу отбора из stability CSV.
    
    :param stability_csv_path: Путь к strategy_stability.csv.
    :param output_path: Опциональный путь для сохранения CSV. 
                        Если None, сохраняется в той же директории как strategy_selection.csv.
    :param criteria: Опциональные критерии отбора для RR/RRD. Если None, используется DEFAULT_CRITERIA.
    :param runner_criteria: Опциональные критерии отбора для Runner. Если None, используется DEFAULT_RUNNER_CRITERIA.
    :return: DataFrame с таблицей отбора.
    """
    if criteria is None:
        criteria = DEFAULT_CRITERIA
    if runner_criteria is None:
        runner_criteria = DEFAULT_RUNNER_CRITERIA
    
    stability_csv_path = Path(stability_csv_path)
    
    # Загружаем stability table
    stability_df = load_stability_csv(stability_csv_path)
    
    # Применяем отбор
    selection_df = select_strategies(stability_df, criteria, runner_criteria)
    
    # Сохраняем если указан путь
    if output_path is None:
        output_path = stability_csv_path.parent / "strategy_selection.csv"
    
    if len(selection_df) > 0:
        save_selection_table(selection_df, output_path)
    
    return selection_df











