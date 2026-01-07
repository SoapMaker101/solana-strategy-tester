# backtester/decision/strategy_selector.py
# Applies selection rules to filter strategies

from __future__ import annotations

from typing import List, Optional
from pathlib import Path
from dataclasses import asdict
import pandas as pd

from .selection_rules import SelectionCriteria, DEFAULT_RUNNER_CRITERIA, DEFAULT_RUNNER_CRITERIA_V2, DEFAULT_CRITERIA_V1
import numpy as np
import pandas as pd
from ..utils.typing_utils import safe_float, is_nonempty_series


def is_runner_strategy(strategy_name: str) -> bool:
    """
    Runner-only v2.0: все стратегии считаются Runner.
    
    :param strategy_name: Имя стратегии.
    :return: True если стратегия Runner, False иначе.
    """
    return True


def check_strategy_criteria(
    row: pd.Series,
    criteria: SelectionCriteria,
    runner_criteria: Optional[SelectionCriteria] = None,
) -> tuple[bool, List[str]]:
    """
    Проверяет, проходит ли стратегия все критерии отбора.
    
    Сначала применяет базовые критерии (SelectionCriteria v1):
    - survival_rate >= criteria.min_survival_rate
    - pnl_variance <= criteria.max_pnl_variance
    - worst_window_pnl >= criteria.min_worst_window_pnl
    - median_window_pnl >= criteria.min_median_window_pnl
    - windows_total >= criteria.min_windows
    
    Затем опционально применяет Runner критерии, если они заданы и есть нужные колонки.
    
    :param row: Строка DataFrame с метриками стратегии.
    :param criteria: Базовые критерии отбора (SelectionCriteria v1).
    :param runner_criteria: Опциональные критерии для Runner стратегий.
                           Применяются только если есть нужные колонки в row.
    :return: (passed: bool, failed_reasons: List[str])
    """
    failed_reasons = []
    
    def get(name):
        """Безопасное получение значения из row."""
        if name not in row:
            failed_reasons.append(f"missing_{name}")
            return None
        val = row[name]
        # Явная проверка на NaN без truthiness на потенциальном Series/NDFrame
        # row[name] из Series.iterrows() возвращает скаляр, но basedpyright может не знать это
        if isinstance(val, (pd.DataFrame, pd.Series)):
            # Если это Series/DataFrame (не должно быть, но для типизации)
            failed_reasons.append(f"missing_{name}")
            return None
        if pd.isna(val):
            failed_reasons.append(f"missing_{name}")
            return None
        return safe_float(val, default=0.0)
    
    # Базовые критерии (SelectionCriteria v1) - обязательные
    survival = get("survival_rate")
    variance = get("pnl_variance")
    worst = get("worst_window_pnl")
    median = get("median_window_pnl")
    
    # windows_total может называться windows_total или windows (alias)
    # Явная проверка на NaN без truthiness на потенциальном Series/NDFrame
    if "windows_total" in row:
        windows_total_val = row["windows_total"]
        if (windows_total_val is not None and 
            not isinstance(windows_total_val, (pd.DataFrame, pd.Series)) and
            not pd.isna(windows_total_val)):
            windows_total = int(windows_total_val)
        else:
            windows_total = None
    else:
        windows_total = None
    
    if windows_total is None and "windows" in row:
        windows_val = row["windows"]
        if (windows_val is not None and 
            not isinstance(windows_val, (pd.DataFrame, pd.Series)) and
            not pd.isna(windows_val)):
            windows_total = int(windows_val)
    
    if windows_total is None:
        failed_reasons.append("missing_windows_total")
    
    # Проверка базовых критериев (только если значения не missing)
    if survival is not None and survival < criteria.min_survival_rate:
        failed_reasons.append(f"survival_rate {survival:.3f} < {criteria.min_survival_rate}")
    if variance is not None and variance > criteria.max_pnl_variance:
        failed_reasons.append(f"pnl_variance {variance:.3f} > {criteria.max_pnl_variance}")
    if worst is not None and worst < criteria.min_worst_window_pnl:
        failed_reasons.append(f"worst_window_pnl {worst:.3f} < {criteria.min_worst_window_pnl}")
    if median is not None and median < criteria.min_median_window_pnl:
        failed_reasons.append(f"median_window_pnl {median:.3f} < {criteria.min_median_window_pnl}")
    if windows_total is not None and windows_total < criteria.min_windows:
        failed_reasons.append(f"windows_total {windows_total} < {criteria.min_windows}")
    
    # Runner критерии - опциональные, применяются только если есть нужные колонки
    if runner_criteria is not None:
        # Определяем, является ли runner_criteria V2 (проверяем наличие V2 колонок в row)
        required_v2_cols = {"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}
        has_v2_cols = required_v2_cols.issubset(set(row.index))
        
        # Проверяем, что это V2 критерии (по наличию V2 колонок и отсутствию V1 колонок)
        is_v2 = has_v2_cols and (
            "hit_rate_x2" not in row or
            (runner_criteria.min_hit_rate_x2 is None and runner_criteria.min_hit_rate_x5 is None)
        )
        
        if is_v2:
            # Применяем Runner критерии V2
            # Пороги из тестов: hit_rate_x4 >= 0.10, tail_pnl_share >= 0.30, non_tail_pnl_share >= -0.20
            min_hit_rate_x4 = 0.10
            min_tail_pnl_share = 0.30
            min_non_tail_pnl_share = -0.20
            
            # hit_rate_x4
            if "hit_rate_x4" in row:
                hit_rate_x4 = row.get("hit_rate_x4")
                # Явная проверка на NaN без truthiness на потенциальном Series/NDFrame
                if (hit_rate_x4 is not None and 
                    not isinstance(hit_rate_x4, (pd.DataFrame, pd.Series)) and
                    not pd.isna(hit_rate_x4)):
                    hit_rate_x4 = safe_float(hit_rate_x4, default=0.0)
                    if hit_rate_x4 < min_hit_rate_x4:
                        failed_reasons.append(f"hit_rate_x4 {hit_rate_x4:.3f} < {min_hit_rate_x4}")
                else:
                    failed_reasons.append("missing_hit_rate_x4")
            
            # tail_pnl_share
            if "tail_pnl_share" in row:
                tail_pnl_share = row.get("tail_pnl_share")
                # Явная проверка на NaN без truthiness на потенциальном Series/NDFrame
                if (tail_pnl_share is not None and 
                    not isinstance(tail_pnl_share, (pd.DataFrame, pd.Series)) and
                    not pd.isna(tail_pnl_share)):
                    tail_pnl_share = safe_float(tail_pnl_share, default=0.0)
                    if tail_pnl_share < min_tail_pnl_share:
                        failed_reasons.append(f"tail_pnl_share {tail_pnl_share:.3f} < {min_tail_pnl_share}")
                else:
                    failed_reasons.append("missing_tail_pnl_share")
            
            # non_tail_pnl_share
            if "non_tail_pnl_share" in row:
                non_tail_pnl_share = row.get("non_tail_pnl_share")
                # Явная проверка на NaN без truthiness на потенциальном Series/NDFrame
                if (non_tail_pnl_share is not None and 
                    not isinstance(non_tail_pnl_share, (pd.DataFrame, pd.Series)) and
                    not pd.isna(non_tail_pnl_share)):
                    non_tail_pnl_share = safe_float(non_tail_pnl_share, default=0.0)
                    if non_tail_pnl_share < min_non_tail_pnl_share:
                        failed_reasons.append(f"non_tail_pnl_share {non_tail_pnl_share:.3f} < {min_non_tail_pnl_share}")
                else:
                    failed_reasons.append("missing_non_tail_pnl_share")
            
            # max_drawdown_pct (опционально для V2)
            if runner_criteria.max_drawdown_pct is not None and "max_drawdown_pct" in row:
                max_drawdown_pct = safe_float(row.get("max_drawdown_pct", 0.0), default=0.0)
                if max_drawdown_pct < runner_criteria.max_drawdown_pct:
                    failed_reasons.append(
                        f"max_drawdown_pct {max_drawdown_pct:.3f} < {runner_criteria.max_drawdown_pct}"
                    )
        else:
            # Применяем Runner критерии V1 (если есть нужные колонки)
            has_runner_metrics = (
                "hit_rate_x2" in row or
                "hit_rate_x5" in row or
                "tail_contribution" in row or
                "tail_pnl_share" in row or
                "p90_hold_days" in row or
                "max_drawdown_pct" in row
            )
            
            if has_runner_metrics:
                # Применяем Runner критерии V1 только если есть нужные колонки
                if runner_criteria.min_hit_rate_x2 is not None and "hit_rate_x2" in row:
                    hit_rate_x2_raw = row.get("hit_rate_x2", 0.0)
                    hit_rate_x2 = safe_float(hit_rate_x2_raw, default=0.0)
                    if hit_rate_x2 < runner_criteria.min_hit_rate_x2:
                        failed_reasons.append(
                            f"hit_rate_x2 {hit_rate_x2:.3f} < {runner_criteria.min_hit_rate_x2}"
                        )
                
                if runner_criteria.min_hit_rate_x5 is not None and "hit_rate_x5" in row:
                    hit_rate_x5_raw = row.get("hit_rate_x5", 0.0)
                    hit_rate_x5 = safe_float(hit_rate_x5_raw, default=0.0)
                    if hit_rate_x5 < runner_criteria.min_hit_rate_x5:
                        failed_reasons.append(
                            f"hit_rate_x5 {hit_rate_x5:.3f} < {runner_criteria.min_hit_rate_x5}"
                        )
                
                if runner_criteria.max_p90_hold_days is not None and "p90_hold_days" in row:
                    p90_hold_days_raw = row.get("p90_hold_days", float('inf'))
                    p90_hold_days = safe_float(p90_hold_days_raw, default=float('inf'))
                    if p90_hold_days > runner_criteria.max_p90_hold_days:
                        failed_reasons.append(
                            f"p90_hold_days {p90_hold_days:.2f} > {runner_criteria.max_p90_hold_days}"
                        )
                
                if runner_criteria.max_tail_contribution is not None:
                    tail_contribution_raw = row.get("tail_contribution", row.get("tail_pnl_share", 0.0))
                    tail_contribution = safe_float(tail_contribution_raw, default=0.0)
                    if tail_contribution > runner_criteria.max_tail_contribution:
                        metric_name = "tail_pnl_share" if "tail_pnl_share" in row else "tail_contribution"
                        failed_reasons.append(
                            f"{metric_name} {tail_contribution:.3f} > {runner_criteria.max_tail_contribution}"
                        )
                
                if runner_criteria.max_drawdown_pct is not None and "max_drawdown_pct" in row:
                    max_drawdown_pct = safe_float(row.get("max_drawdown_pct", 0.0), default=0.0)
                    if max_drawdown_pct < runner_criteria.max_drawdown_pct:
                        failed_reasons.append(
                            f"max_drawdown_pct {max_drawdown_pct:.3f} < {runner_criteria.max_drawdown_pct}"
                        )
    
    # Если есть missing_* - сразу fail
    has_missing = any(r.startswith("missing_") for r in failed_reasons)
    passed = (len([x for x in failed_reasons if not x.startswith("missing_")]) == 0) and not has_missing
    
    return bool(passed), failed_reasons


def select_strategies(
    stability_df: pd.DataFrame,
    criteria: SelectionCriteria = DEFAULT_RUNNER_CRITERIA,
    runner_criteria: Optional[SelectionCriteria] = None,
) -> pd.DataFrame:
    """
    Применяет критерии отбора к стратегиям из stability table.
    
    Сначала применяет базовые критерии (SelectionCriteria v1), затем опционально Runner критерии.
    
    :param stability_df: DataFrame из strategy_stability.csv.
    :param criteria: Базовые критерии отбора (SelectionCriteria v1).
    :param runner_criteria: Опциональные критерии отбора для Runner.
    :return: DataFrame с колонками из stability_df + passed (bool) + failed_reasons (List[str]).
             ВАЖНО: НЕ СОРТИРУЕТСЯ по pnl или другим метрикам.
    """
    if len(stability_df) == 0:
        # Возвращаем пустой DataFrame с правильными колонками
        result_df = stability_df.copy()
        result_df["passed"] = []
        result_df["failed_reasons"] = []
        return result_df
    
    # Хак для совместимости: если runner_criteria is None и criteria имеет V2 признаки, используем criteria как runner_criteria
    if runner_criteria is None:
        # Проверяем, является ли criteria V2 критериями (по наличию V2 колонок в df)
        required_v2_cols = {"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}
        has_v2_cols = required_v2_cols.issubset(set(stability_df.columns))
        if has_v2_cols and (criteria.min_hit_rate_x2 is None and criteria.min_hit_rate_x5 is None):
            runner_criteria = criteria
            criteria = DEFAULT_CRITERIA_V1
    
    # Проверяем обязательные колонки (базовые для всех стратегий)
    required = {"strategy", "survival_rate", "pnl_variance", "worst_window_pnl", "median_window_pnl"}
    has_windows = ("windows_total" in stability_df.columns) or ("windows" in stability_df.columns)
    
    if not required.issubset(stability_df.columns) or not has_windows:
        missing = sorted(list(required - set(stability_df.columns)))
        if not has_windows:
            missing.append("windows_total")
        raise ValueError(f"Missing required columns: {missing}")
    
    # Применяем критерии к каждой стратегии
    results = []
    for _, row in stability_df.iterrows():
        passed, failed_reasons = check_strategy_criteria(row, criteria, runner_criteria)
        
        result_row = row.to_dict()
        result_row["passed"] = bool(passed)  # Явно конвертируем в python bool
        result_row["failed_reasons"] = failed_reasons
        results.append(result_row)
    
    # Создаём результат
    result_df = pd.DataFrame(results)
    
    # ВАЖНО: НЕ сортируем по pnl или другим метрикам
    # Сохраняем исходный порядок
    
    return result_df


def normalize_stability_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Нормализует схему stability DataFrame для обратной совместимости.
    
    Поддерживает различные варианты названий колонок и заполняет недостающие поля.
    Это BC-функция для тестов/старых файлов, которая позволяет Stage B принимать
    любые старые stability.csv файлы.
    
    Выполняет:
    - Преобразование split_count <-> split_n
    - Создание windows_total из split_n или split_count
    - Создание windows_positive из survival_rate * windows_total
    - Заполнение NaN в критичных полях дефолтными значениями
    
    :param df: Входной DataFrame (может быть любой схемой).
    :return: Новый DataFrame с нормализованной схемой (копия).
    """
    df = df.copy()
    
    if len(df) == 0:
        return df
    
    # 1. Нормализация split_count <-> split_n
    if "split_count" in df.columns and "split_n" not in df.columns:
        df["split_n"] = df["split_count"]
    elif "split_n" in df.columns and "split_count" not in df.columns:
        df["split_count"] = df["split_n"]
    
    # 2. Создание windows_total из split_n или split_count
    if "windows_total" not in df.columns:
        if "split_n" in df.columns:
            # Безопасное заполнение NaN перед кастом в int
            df["windows_total"] = df["split_n"].fillna(0).astype(int)
        elif "split_count" in df.columns:
            # Безопасное заполнение NaN перед кастом в int
            df["windows_total"] = df["split_count"].fillna(0).astype(int)
        else:
            df["windows_total"] = 0
    
    # 3. Создание windows_positive из survival_rate * windows_total
    if "windows_positive" not in df.columns:
        df["windows_positive"] = np.nan
    
    # Заполняем windows_positive только если он NaN
    mask_na = pd.isna(df["windows_positive"])
    if isinstance(mask_na, pd.Series) and mask_na.any():
        if "survival_rate" in df.columns and "windows_total" in df.columns:
            # Безопасное заполнение NaN перед вычислением
            survival_rate_filled = df.loc[mask_na, "survival_rate"].fillna(0.0)
            windows_total_filled = df.loc[mask_na, "windows_total"].fillna(0)
            
            # Вычисляем и безопасно кастуем
            windows_positive_calc = (survival_rate_filled * windows_total_filled).round()
            # Заменяем NaN/Inf на 0 перед кастом
            # Runtime guard для basedpyright: df.loc[] и операции над Series возвращают Series
            # В runtime это всегда Series, но basedpyright не может это гарантировать
            assert isinstance(windows_positive_calc, pd.Series), "windows_positive_calc должен быть Series в runtime"
            windows_positive_calc = windows_positive_calc.fillna(0).replace([float('inf'), float('-inf')], 0)
            df.loc[mask_na, "windows_positive"] = windows_positive_calc.astype(int)
            
            # Clamp: windows_positive не должен превышать windows_total
            df.loc[mask_na, "windows_positive"] = df.loc[mask_na, "windows_positive"].clip(
                upper=df.loc[mask_na, "windows_total"].fillna(0).astype(int)
            )
        else:
            df.loc[mask_na, "windows_positive"] = 0
    
    # 4. Заполнение NaN в критичных полях дефолтными значениями
    # Список int-like полей, которые часто встречаются и должны безопасно каститься в int
    int_like_fields = [
        "windows_total",
        "windows_positive",
        "windows_negative",
        "trades_total",
        "trades_executed",
        "min_windows",
        "split_count",
        "split_n",
    ]
    
    for field in int_like_fields:
        if field in df.columns:
            # Безопасное заполнение NaN и каст в int
            s = pd.Series(df[field]) if not isinstance(df[field], pd.Series) else df[field]
            # Runtime guard для basedpyright: pd.to_numeric() на Series возвращает Series
            # В runtime это всегда Series, но basedpyright не может это гарантировать
            numeric_result = pd.to_numeric(s, errors="coerce")
            assert isinstance(numeric_result, pd.Series), "pd.to_numeric() на Series должен возвращать Series в runtime"
            df[field] = numeric_result.fillna(0).astype(int)
    
    # Float полей
    float_fields = {
        "survival_rate": 0.0,
        "hit_rate_x4": 0.0,
        "tail_pnl_share": 0.0,
        "non_tail_pnl_share": 0.0,
    }
    
    for field, default_value in float_fields.items():
        if field in df.columns:
            s = pd.Series(df[field]) if not isinstance(df[field], pd.Series) else df[field]
            # Runtime guard для basedpyright: pd.to_numeric() на Series возвращает Series
            # В runtime это всегда Series, но basedpyright не может это гарантировать
            numeric_result = pd.to_numeric(s, errors="coerce")
            if isinstance(numeric_result, pd.Series):
                df[field] = numeric_result.fillna(default_value)
            else:
                # Если не Series (не должно быть в runtime, но для типизации) - создаём Series
                df[field] = pd.Series([numeric_result] * len(df), index=df.index, dtype="float64").fillna(default_value)
    
    return df


def load_stability_csv(csv_path: Path) -> pd.DataFrame:
    """
    Загружает strategy_stability.csv.
    
    Runner-only: нормализует схему через normalize_stability_schema для BC.
    
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
    
    # Нормализуем схему для обратной совместимости
    df = normalize_stability_schema(df)
    
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
    
    Сначала применяет базовые критерии (SelectionCriteria v1), затем опционально Runner критерии.
    
    :param stability_csv_path: Путь к strategy_stability.csv.
    :param output_path: Опциональный путь для сохранения CSV. 
                        Если None, сохраняется в той же директории как strategy_selection.csv.
    :param criteria: Базовые критерии отбора (SelectionCriteria v1). Если None, используется DEFAULT_CRITERIA_V1.
    :param runner_criteria: Опциональные критерии отбора для Runner. Если None, не применяются.
    :return: DataFrame с таблицей отбора.
    """
    if criteria is None:
        criteria = DEFAULT_CRITERIA_V1
    
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
    
    # Сохраняем XLSX отчет с несколькими листами
    if len(selection_df) > 0:
        from ..infrastructure.xlsx_writer import save_xlsx
        
        xlsx_path = stability_csv_path.parent / "stage_b_selection.xlsx"
        sheets = {}
        
        # Лист 1: Selection results
        sheets["selection"] = selection_df.copy()
        # Конвертируем failed_reasons в строку для XLSX (если это список)
        if "failed_reasons" in sheets["selection"].columns:
            sheets["selection"]["failed_reasons"] = sheets["selection"]["failed_reasons"].apply(
                lambda x: "; ".join(x) if isinstance(x, list) else str(x)
            )
        
        # Лист 2: Criteria snapshot (Runner-only)
        criteria_data = []
        if criteria:
            criteria_dict = asdict(criteria)
            criteria_data.append({**{"criteria_type": "Runner (default)"}, **criteria_dict})
        if runner_criteria:
            runner_dict = asdict(runner_criteria)
            criteria_data.append({**{"criteria_type": "Runner (override)"}, **runner_dict})
        
        if criteria_data:
            sheets["criteria_snapshot"] = pd.DataFrame(criteria_data)
        else:
            # Пустой DataFrame с базовыми колонками
            sheets["criteria_snapshot"] = pd.DataFrame([], columns=pd.Index(["criteria_type"]))
        
        save_xlsx(xlsx_path, sheets)
    
    return selection_df






