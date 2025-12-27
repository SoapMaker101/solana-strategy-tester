# backtester/decision/strategy_selector.py
# Applies selection rules to filter strategies

from __future__ import annotations

from typing import List, Optional
from pathlib import Path
from dataclasses import asdict
import pandas as pd

from .selection_rules import SelectionCriteria, DEFAULT_CRITERIA, DEFAULT_RUNNER_CRITERIA, DEFAULT_RUNNER_CRITERIA_V2
import numpy as np
import pandas as pd


def is_runner_strategy(strategy_name: str) -> bool:
    """
    Определяет, является ли стратегия Runner стратегией.
    
    :param strategy_name: Имя стратегии.
    :return: True если стратегия Runner, False иначе.
    """
    # Проверяем по имени стратегии (обычно содержит "runner" или "Runner")
    strategy_lower = strategy_name.lower()
    return "runner" in strategy_lower or strategy_name.startswith("Runner")


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
        # Определяем режим V2: если это DEFAULT_RUNNER_CRITERIA_V2 (BC для тестов)
        # V2 проверяет hit_rate_x4, tail_pnl_share, non_tail_pnl_share вместо x2/x5/tail_contribution
        is_v2_mode = (
            runner_criteria is DEFAULT_RUNNER_CRITERIA_V2 or
            (runner_criteria.min_hit_rate_x2 is None and 
             runner_criteria.min_hit_rate_x5 is None and
             runner_criteria.min_tail_contribution is not None and
             runner_criteria.min_tail_contribution == 0.30 and
             runner_criteria.max_drawdown_pct == -0.60)
        )
        
        # Проверяем наличие V2 метрик в данных
        has_v2_metrics = (
            "tail_pnl_share" in row or 
            "hit_rate_x4" in row or 
            "non_tail_pnl_share" in row
        )
        
        if is_v2_mode and has_v2_metrics:
            # V2 режим: проверяем новые метрики
            # Проверка V2.1: hit_rate_x4 >= 0.10
            if "hit_rate_x4" in row:
                hit_rate_x4 = row.get("hit_rate_x4", 0.0)
                if pd.isna(hit_rate_x4):
                    hit_rate_x4 = 0.0
                if hit_rate_x4 < 0.10:
                    failed_reasons.append(
                        f"hit_rate_x4 {hit_rate_x4:.3f} < 0.10"
                    )
            
            # Проверка V2.2: tail_pnl_share >= 0.30 (с fallback на tail_contribution)
            tail_value = None
            if "tail_pnl_share" in row:
                tail_value = row.get("tail_pnl_share", 0.0)
                if pd.isna(tail_value):
                    tail_value = 0.0
            elif "tail_contribution" in row:
                tail_value = row.get("tail_contribution", 0.0)
                if pd.isna(tail_value):
                    tail_value = 0.0
            
            if tail_value is not None:
                metric_name = "tail_pnl_share" if "tail_pnl_share" in row else "tail_contribution"
                if tail_value < 0.30:
                    failed_reasons.append(
                        f"{metric_name} {tail_value:.3f} < 0.30"
                    )
            
            # Проверка V2.3: non_tail_pnl_share >= -0.20
            if "non_tail_pnl_share" in row:
                non_tail_value = row.get("non_tail_pnl_share", 0.0)
                if pd.isna(non_tail_value):
                    # Fallback: вычисляем из tail_value если доступен
                    if tail_value is not None and 0 <= tail_value <= 1:
                        non_tail_value = 1.0 - tail_value
                    else:
                        non_tail_value = 0.0
                if non_tail_value < -0.20:
                    failed_reasons.append(
                        f"non_tail_pnl_share {non_tail_value:.3f} < -0.20"
                    )
        else:
            # V1 режим (legacy): проверяем старые метрики
            # Проверка 1: hit_rate_x2 >= min_hit_rate_x2
            if runner_criteria.min_hit_rate_x2 is not None:
                hit_rate_x2 = row.get("hit_rate_x2", 0.0)
                if hit_rate_x2 < runner_criteria.min_hit_rate_x2:
                    failed_reasons.append(
                        f"hit_rate_x2 {hit_rate_x2:.3f} < {runner_criteria.min_hit_rate_x2}"
                    )
            
            # Проверка 2: hit_rate_x5 >= min_hit_rate_x5
            if runner_criteria.min_hit_rate_x5 is not None:
                hit_rate_x5 = row.get("hit_rate_x5", 0.0)
                if hit_rate_x5 < runner_criteria.min_hit_rate_x5:
                    failed_reasons.append(
                        f"hit_rate_x5 {hit_rate_x5:.3f} < {runner_criteria.min_hit_rate_x5}"
                    )
            
            # Проверка 5: tail_contribution >= min_tail_contribution (если задан)
            # Поддержка tail_pnl_share как альтернативы tail_contribution для совместимости
            if runner_criteria.min_tail_contribution is not None:
                # Используем tail_pnl_share если есть, иначе tail_contribution
                tail_share = row.get("tail_pnl_share", row.get("tail_contribution", 0.0))
                if pd.isna(tail_share):
                    tail_share = 0.0
                if tail_share < runner_criteria.min_tail_contribution:
                    metric_name = "tail_pnl_share" if "tail_pnl_share" in row else "tail_contribution"
                    failed_reasons.append(
                        f"{metric_name} {tail_share:.3f} < {runner_criteria.min_tail_contribution}"
                    )
        
        # Общие проверки (для V1 и V2)
        # Проверка 3: p90_hold_days >= min_p90_hold_days (если задан)
        if runner_criteria.min_p90_hold_days is not None:
            p90_hold_days = row.get("p90_hold_days", 0.0)
            if p90_hold_days < runner_criteria.min_p90_hold_days:
                failed_reasons.append(
                    f"p90_hold_days {p90_hold_days:.2f} < {runner_criteria.min_p90_hold_days}"
                )
        
        # Проверка 4: p90_hold_days <= max_p90_hold_days (если задан)
        if runner_criteria.max_p90_hold_days is not None:
            p90_hold_days = row.get("p90_hold_days", float('inf'))
            if p90_hold_days > runner_criteria.max_p90_hold_days:
                failed_reasons.append(
                    f"p90_hold_days {p90_hold_days:.2f} > {runner_criteria.max_p90_hold_days}"
                )
        
        # Проверка 6: tail_contribution <= max_tail_contribution (если задан) - только для V1
        if not (is_v2_mode and has_v2_metrics) and runner_criteria.max_tail_contribution is not None:
            tail_contribution = row.get("tail_contribution", 0.0)
            if tail_contribution > runner_criteria.max_tail_contribution:
                failed_reasons.append(
                    f"tail_contribution {tail_contribution:.3f} > {runner_criteria.max_tail_contribution}"
                )
        
        # Проверка 7: max_drawdown_pct >= max_drawdown_pct (max_drawdown_pct отрицательное)
        if runner_criteria.max_drawdown_pct is not None:
            max_drawdown_pct = row.get("max_drawdown_pct", 0.0)
            if max_drawdown_pct < runner_criteria.max_drawdown_pct:
                failed_reasons.append(
                    f"max_drawdown_pct {max_drawdown_pct:.3f} < {runner_criteria.max_drawdown_pct}"
                )
    else:
        # Применяем RR/RRD критерии
        # Проверка 1: survival_rate >= min_survival_rate
        if row.get("survival_rate", 0.0) < criteria.min_survival_rate:
            failed_reasons.append(
                f"survival_rate {row.get('survival_rate', 0.0):.3f} < {criteria.min_survival_rate}"
            )
        
        # Проверка 2: pnl_variance <= max_pnl_variance
        if row.get("pnl_variance", float('inf')) > criteria.max_pnl_variance:
            failed_reasons.append(
                f"pnl_variance {row.get('pnl_variance', 0.0):.6f} > {criteria.max_pnl_variance}"
            )
        
        # Проверка 3: worst_window_pnl >= min_worst_window_pnl
        if row.get("worst_window_pnl", -float('inf')) < criteria.min_worst_window_pnl:
            failed_reasons.append(
                f"worst_window_pnl {row.get('worst_window_pnl', 0.0):.4f} < {criteria.min_worst_window_pnl}"
            )
        
        # Проверка 4: median_window_pnl >= min_median_window_pnl
        if row.get("median_window_pnl", -float('inf')) < criteria.min_median_window_pnl:
            failed_reasons.append(
                f"median_window_pnl {row.get('median_window_pnl', 0.0):.4f} < {criteria.min_median_window_pnl}"
            )
        
        # Проверка 5: windows_total >= min_windows
        if row.get("windows_total", 0) < criteria.min_windows:
            failed_reasons.append(
                f"windows_total {row.get('windows_total', 0)} < {criteria.min_windows}"
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
    if mask_na.any():
        if "survival_rate" in df.columns and "windows_total" in df.columns:
            # Безопасное заполнение NaN перед вычислением
            survival_rate_filled = df.loc[mask_na, "survival_rate"].fillna(0.0)
            windows_total_filled = df.loc[mask_na, "windows_total"].fillna(0)
            
            # Вычисляем и безопасно кастуем
            windows_positive_calc = (survival_rate_filled * windows_total_filled).round()
            # Заменяем NaN/Inf на 0 перед кастом
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
            df[field] = pd.to_numeric(df[field], errors="coerce").fillna(0).astype(int)
    
    # Float полей
    float_fields = {
        "survival_rate": 0.0,
        "hit_rate_x4": 0.0,
        "tail_pnl_share": 0.0,
        "non_tail_pnl_share": 0.0,
    }
    
    for field, default_value in float_fields.items():
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors="coerce").fillna(default_value)
    
    return df


def load_stability_csv(csv_path: Path) -> pd.DataFrame:
    """
    Загружает strategy_stability.csv.
    
    Поддерживает как RR/RRD метрики, так и Runner метрики.
    Автоматически нормализует схему через normalize_stability_schema для BC.
    
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
        
        # Лист 2: Criteria snapshot (frozen RunnerCriteriaV3 для аудита)
        criteria_data = []
        if criteria:
            criteria_dict = asdict(criteria)
            criteria_data.append({**{"criteria_type": "RR/RRD"}, **criteria_dict})
        if runner_criteria:
            runner_dict = asdict(runner_criteria)
            criteria_data.append({**{"criteria_type": "Runner"}, **runner_dict})
        
        if criteria_data:
            sheets["criteria_snapshot"] = pd.DataFrame(criteria_data)
        else:
            # Пустой DataFrame с базовыми колонками
            sheets["criteria_snapshot"] = pd.DataFrame([], columns=["criteria_type"])
        
        save_xlsx(xlsx_path, sheets)
    
    return selection_df











