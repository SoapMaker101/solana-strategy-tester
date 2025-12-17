# backtester/research/signal_quality/cap_thresholds.py
"""
Модуль для анализа порогов market cap proxy.

Вычисляет метрики для разных порогов min_market_cap_proxy:
- kept_signals: сколько сигналов осталось
- kept_pct: процент оставшихся сигналов
- kept_runners: сколько runner'ов осталось
- runner_recall_pct: процент runner'ов, которые остались
- non_runner_removed_pct: процент non-runner'ов, которые были отрезаны
- runner_share_before, runner_share_after: доля runner'ов до и после фильтрации
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd


def compute_runner_label(
    features_df: pd.DataFrame,
    runner_xn_threshold: float = 3.0
) -> pd.Series:
    """
    Вычисляет метку is_runner для каждого сигнала.
    
    :param features_df: DataFrame с признаками (должна быть колонка max_xn)
    :param runner_xn_threshold: Порог для определения runner'а (по умолчанию 3.0)
    :return: Series с булевыми значениями is_runner
    """
    if "max_xn" not in features_df.columns:
        return pd.Series([False] * len(features_df), index=features_df.index)
    
    return features_df["max_xn"] >= runner_xn_threshold


def analyze_cap_thresholds(
    features_df: pd.DataFrame,
    thresholds: List[float],
    runner_xn_threshold: float = 3.0
) -> pd.DataFrame:
    """
    Анализирует влияние разных порогов min_market_cap_proxy на фильтрацию сигналов.
    
    :param features_df: DataFrame с признаками сигналов (должна быть колонка market_cap_proxy)
    :param thresholds: Список порогов для анализа
    :param runner_xn_threshold: Порог для определения runner'а
    :return: DataFrame с метриками по каждому порогу
    """
    if features_df.empty:
        return pd.DataFrame()
    
    # Вычисляем is_runner
    features_df = features_df.copy()
    features_df["is_runner"] = compute_runner_label(features_df, runner_xn_threshold)
    
    # Базовые метрики (до фильтрации)
    total_signals = len(features_df)
    total_runners = features_df["is_runner"].sum()
    runner_share_before = (total_runners / total_signals * 100) if total_signals > 0 else 0.0
    
    # Фильтруем только валидные сигналы (status == "ok")
    valid_features = features_df[features_df["status"] == "ok"].copy()
    
    if valid_features.empty:
        # Если нет валидных сигналов, возвращаем пустой результат
        return pd.DataFrame()
    
    results = []
    
    for threshold in sorted(thresholds):
        # Фильтруем по порогу
        filtered = valid_features[valid_features["market_cap_proxy"] >= threshold]
        
        kept_signals = len(filtered)
        kept_pct = (kept_signals / len(valid_features) * 100) if len(valid_features) > 0 else 0.0
        
        kept_runners = filtered["is_runner"].sum() if len(filtered) > 0 else 0
        runner_recall_pct = (kept_runners / total_runners * 100) if total_runners > 0 else 0.0
        
        # Вычисляем сколько non-runner'ов было отрезано
        total_non_runners = total_signals - total_runners
        kept_non_runners = kept_signals - kept_runners
        removed_non_runners = total_non_runners - (len(valid_features) - total_runners - (kept_signals - kept_runners))
        # Более точный расчет:
        valid_non_runners = len(valid_features) - valid_features["is_runner"].sum()
        kept_valid_non_runners = kept_signals - kept_runners
        removed_valid_non_runners = valid_non_runners - kept_valid_non_runners
        non_runner_removed_pct = (removed_valid_non_runners / valid_non_runners * 100) if valid_non_runners > 0 else 0.0
        
        runner_share_after = (kept_runners / kept_signals * 100) if kept_signals > 0 else 0.0
        
        results.append({
            "min_market_cap_proxy": threshold,
            "kept_signals": kept_signals,
            "kept_pct": round(kept_pct, 2),
            "kept_runners": kept_runners,
            "runner_recall_pct": round(runner_recall_pct, 2),
            "non_runner_removed_pct": round(non_runner_removed_pct, 2),
            "runner_share_before": round(runner_share_before, 2),
            "runner_share_after": round(runner_share_after, 2),
        })
    
    return pd.DataFrame(results)


def save_cap_threshold_report(
    report_df: pd.DataFrame,
    output_path: str | Path
) -> None:
    """
    Сохраняет отчёт по порогам в CSV.
    
    :param report_df: DataFrame с результатами анализа
    :param output_path: Путь для сохранения CSV
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_path, index=False)
    print(f"[report] Saved cap threshold report to {output_path}")
