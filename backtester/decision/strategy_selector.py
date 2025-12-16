# backtester/decision/strategy_selector.py
# Applies selection rules to filter strategies

from __future__ import annotations

from typing import List, Optional
from pathlib import Path
import pandas as pd

from .selection_rules import SelectionCriteria, DEFAULT_CRITERIA


def check_strategy_criteria(
    row: pd.Series,
    criteria: SelectionCriteria,
) -> tuple[bool, List[str]]:
    """
    Проверяет, проходит ли стратегия все критерии отбора.
    
    :param row: Строка DataFrame с метриками стратегии.
    :param criteria: Критерии отбора.
    :return: (passed: bool, failed_reasons: List[str])
    """
    failed_reasons = []
    
    # Проверка 1: survival_rate >= min_survival_rate
    if row["survival_rate"] < criteria.min_survival_rate:
        failed_reasons.append(f"survival_rate {row['survival_rate']:.3f} < {criteria.min_survival_rate}")
    
    # Проверка 2: pnl_variance <= max_pnl_variance
    if row["pnl_variance"] > criteria.max_pnl_variance:
        failed_reasons.append(f"pnl_variance {row['pnl_variance']:.6f} > {criteria.max_pnl_variance}")
    
    # Проверка 3: worst_window_pnl >= min_worst_window_pnl
    if row["worst_window_pnl"] < criteria.min_worst_window_pnl:
        failed_reasons.append(f"worst_window_pnl {row['worst_window_pnl']:.4f} < {criteria.min_worst_window_pnl}")
    
    # Проверка 4: median_window_pnl >= min_median_window_pnl
    if row["median_window_pnl"] < criteria.min_median_window_pnl:
        failed_reasons.append(f"median_window_pnl {row['median_window_pnl']:.4f} < {criteria.min_median_window_pnl}")
    
    # Проверка 5: windows_total >= min_windows
    if row["windows_total"] < criteria.min_windows:
        failed_reasons.append(f"windows_total {row['windows_total']} < {criteria.min_windows}")
    
    passed = len(failed_reasons) == 0
    return passed, failed_reasons


def select_strategies(
    stability_df: pd.DataFrame,
    criteria: SelectionCriteria = DEFAULT_CRITERIA,
) -> pd.DataFrame:
    """
    Применяет критерии отбора к стратегиям из stability table.
    
    Стратегия проходит, если ВСЕ условия выполнены:
    - survival_rate >= min_survival_rate
    - pnl_variance <= max_pnl_variance
    - worst_window_pnl >= min_worst_window_pnl
    - median_window_pnl >= min_median_window_pnl
    - windows_total >= min_windows
    
    :param stability_df: DataFrame из strategy_stability.csv.
    :param criteria: Критерии отбора. По умолчанию DEFAULT_CRITERIA.
    :return: DataFrame с колонками из stability_df + passed (bool) + failed_reasons (List[str]).
             ВАЖНО: НЕ СОРТИРУЕТСЯ по pnl или другим метрикам.
    """
    if len(stability_df) == 0:
        # Возвращаем пустой DataFrame с правильными колонками
        result_df = stability_df.copy()
        result_df["passed"] = []
        result_df["failed_reasons"] = []
        return result_df
    
    # Проверяем обязательные колонки
    required_cols = [
        "strategy",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "median_window_pnl",
        "windows_total",
    ]
    missing_cols = [col for col in required_cols if col not in stability_df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in stability_df: {missing_cols}")
    
    # Применяем критерии к каждой стратегии
    results = []
    for _, row in stability_df.iterrows():
        passed, failed_reasons = check_strategy_criteria(row, criteria)
        
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
    
    :param csv_path: Путь к CSV файлу.
    :return: DataFrame с метриками стратегий.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Stability CSV not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    
    # Проверяем обязательные колонки
    required_cols = [
        "strategy",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "median_window_pnl",
        "windows_total",
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in {csv_path}: {missing_cols}")
    
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
) -> pd.DataFrame:
    """
    Генерирует таблицу отбора из stability CSV.
    
    :param stability_csv_path: Путь к strategy_stability.csv.
    :param output_path: Опциональный путь для сохранения CSV. 
                        Если None, сохраняется в той же директории как strategy_selection.csv.
    :param criteria: Опциональные критерии отбора. Если None, используется DEFAULT_CRITERIA.
    :return: DataFrame с таблицей отбора.
    """
    if criteria is None:
        criteria = DEFAULT_CRITERIA
    
    stability_csv_path = Path(stability_csv_path)
    
    # Загружаем stability table
    stability_df = load_stability_csv(stability_csv_path)
    
    # Применяем отбор
    selection_df = select_strategies(stability_df, criteria)
    
    # Сохраняем если указан путь
    if output_path is None:
        output_path = stability_csv_path.parent / "strategy_selection.csv"
    
    if len(selection_df) > 0:
        save_selection_table(selection_df, output_path)
    
    return selection_df




