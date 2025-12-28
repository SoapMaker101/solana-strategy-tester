# tests/decision/test_stage_b_schema_normalization.py
"""
Тесты для проверки нормализации схемы stability DataFrame в Stage B.

Проверяет, что normalize_stability_schema() корректно обрабатывает различные варианты схемы.
"""

import pytest
import pandas as pd
import numpy as np

from backtester.decision.strategy_selector import normalize_stability_schema


def test_normalize_split_count_to_split_n():
    """
    Тест: df содержит split_count, нет split_n → после normalize есть оба и равны.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 1.0,
            "windows_total": 3,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert "split_n" in normalized.columns, "split_n должен быть создан"
    assert "split_count" in normalized.columns, "split_count должен остаться"
    assert normalized["split_n"].iloc[0] == 3, "split_n должен быть равен split_count"
    assert normalized["split_count"].iloc[0] == 3, "split_count должен остаться 3"


def test_normalize_split_n_to_split_count():
    """
    Тест: df содержит split_n, нет split_count → после normalize есть оба и равны.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_n": 4,
            "survival_rate": 1.0,
            "windows_total": 4,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert "split_count" in normalized.columns, "split_count должен быть создан"
    assert "split_n" in normalized.columns, "split_n должен остаться"
    assert normalized["split_count"].iloc[0] == 4, "split_count должен быть равен split_n"
    assert normalized["split_n"].iloc[0] == 4, "split_n должен остаться 4"


def test_normalize_windows_total_from_split_n():
    """
    Тест: нет windows_total → появится = split_n.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_n": 5,
            "survival_rate": 1.0,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert "windows_total" in normalized.columns, "windows_total должен быть создан"
    assert normalized["windows_total"].iloc[0] == 5, "windows_total должен быть равен split_n"


def test_normalize_windows_total_from_split_count():
    """
    Тест: нет windows_total, но есть split_count → появится = split_count.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 1.0,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert "windows_total" in normalized.columns, "windows_total должен быть создан"
    assert normalized["windows_total"].iloc[0] == 3, "windows_total должен быть равен split_count"


def test_normalize_windows_positive_from_survival_rate():
    """
    Тест: нет windows_positive, но есть survival_rate/windows_total → появится windows_positive корректно.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 1.0,
            "windows_total": 3,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert "windows_positive" in normalized.columns, "windows_positive должен быть создан"
    assert normalized["windows_positive"].iloc[0] == 3, "windows_positive должен быть round(1.0 * 3) = 3"


def test_normalize_windows_positive_clamp():
    """
    Тест: windows_positive вычисляется и clamp'ится корректно.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 0.6,  # 0.6 * 3 = 1.8 → round = 2
            "windows_total": 3,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert normalized["windows_positive"].iloc[0] == 2, "windows_positive должен быть round(0.6 * 3) = 2"
    assert normalized["windows_positive"].iloc[0] <= normalized["windows_total"].iloc[0], "windows_positive не должен превышать windows_total"


def test_normalize_survival_rate_not_recalculated():
    """
    Тест: survival_rate задан → не меняется.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 0.8,
            "windows_total": 3,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert normalized["survival_rate"].iloc[0] == 0.8, "survival_rate не должен изменяться"


def test_normalize_fills_nan_in_critical_fields():
    """
    Тест: NaN в критичных полях заполняются дефолтными значениями.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": np.nan,
            "windows_total": np.nan,
            "hit_rate_x4": np.nan,
            "tail_pnl_share": np.nan,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    # Проверяем, что NaN заполнены
    assert not pd.isna(normalized["survival_rate"].iloc[0]), "survival_rate не должен быть NaN"
    assert not pd.isna(normalized["windows_total"].iloc[0]), "windows_total не должен быть NaN"
    assert not pd.isna(normalized["hit_rate_x4"].iloc[0]), "hit_rate_x4 не должен быть NaN"
    assert not pd.isna(normalized["tail_pnl_share"].iloc[0]), "tail_pnl_share не должен быть NaN"


def test_normalize_empty_dataframe():
    """
    Тест: пустой DataFrame обрабатывается корректно.
    """
    df = pd.DataFrame([])
    
    normalized = normalize_stability_schema(df)
    
    assert len(normalized) == 0, "Пустой DataFrame должен остаться пустым"


def test_normalize_preserves_existing_windows_positive():
    """
    Тест: если windows_positive уже есть, он не пересчитывается (если не NaN).
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 1.0,
            "windows_total": 3,
            "windows_positive": 2,  # Уже задан
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert normalized["windows_positive"].iloc[0] == 2, "windows_positive не должен пересчитываться, если уже задан"


def test_normalize_fills_nan_windows_positive():
    """
    Тест: если windows_positive есть, но NaN → заполняется из survival_rate и windows_total.
    """
    df = pd.DataFrame([
        {
            "strategy": "Runner_Test",
            "split_count": 3,
            "survival_rate": 0.7,
            "windows_total": 3,
            "windows_positive": np.nan,
        }
    ])
    
    normalized = normalize_stability_schema(df)
    
    assert not pd.isna(normalized["windows_positive"].iloc[0]), "windows_positive не должен быть NaN"
    assert normalized["windows_positive"].iloc[0] == 2, "windows_positive должен быть round(0.7 * 3) = 2"







