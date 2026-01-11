"""
Unit tests for selection_aggregator module
"""
import pytest
import pandas as pd
import numpy as np

from backtester.decision.selection_aggregator import (
    aggregate_stability,
    aggregate_selection,
)


@pytest.fixture
def sample_stability_df():
    """Создаёт sample DataFrame с метриками стратегий по разным split_count"""
    return pd.DataFrame({
        "strategy": ["strategy1", "strategy1", "strategy1", "strategy2", "strategy2", "strategy2"],
        "split_count": [2, 3, 4, 2, 3, 4],
        "survival_rate": [0.8, 0.75, 0.85, 0.6, 0.65, 0.7],
        "pnl_variance": [0.05, 0.06, 0.04, 0.15, 0.14, 0.16],
        "worst_window_pnl": [-0.1, -0.12, -0.08, -0.3, -0.25, -0.35],
        "median_window_pnl": [0.05, 0.04, 0.06, -0.05, -0.04, -0.03],
        "windows_total": [2, 3, 4, 2, 3, 4],
        "trades_total": [10, 10, 10, 8, 8, 8],  # Constant per strategy
    })


@pytest.fixture
def sample_selection_df():
    """Создаёт sample DataFrame с результатами отбора по разным split_count"""
    return pd.DataFrame({
        "strategy": ["strategy1", "strategy1", "strategy1", "strategy1", "strategy2", "strategy2"],
        "split_count": [2, 3, 4, 5, 2, 3],
        "survival_rate": [0.8, 0.75, 0.85, 0.9, 0.6, 0.65],
        "pnl_variance": [0.05, 0.06, 0.04, 0.03, 0.15, 0.14],
        "worst_window_pnl": [-0.1, -0.12, -0.08, -0.07, -0.3, -0.25],
        "median_window_pnl": [0.05, 0.04, 0.06, 0.07, -0.05, -0.04],
        "windows_total": [2, 3, 4, 5, 2, 3],
        "passed": [True, True, False, False, False, False],
        "failed_reasons": [[], [], ["low_survival"], ["low_survival"], ["low_survival"], ["low_survival"]],
        "trades_total": [10, 10, 10, 10, 8, 8],  # Constant per strategy
    })


def test_aggregate_stability_keeps_one_row_per_strategy(sample_stability_df):
    """Проверяет, что агрегированная таблица содержит по одной строке на стратегию"""
    result_df = aggregate_stability(sample_stability_df)
    
    assert len(result_df) == 2, "Должно быть 2 стратегии"
    assert set(result_df["strategy"].unique()) == {"strategy1", "strategy2"}
    assert len(result_df["strategy"].unique()) == len(result_df)


def test_aggregate_stability_computes_metrics_correctly(sample_stability_df):
    """Проверяет корректность вычисления агрегированных метрик"""
    result_df = aggregate_stability(sample_stability_df)
    
    # Проверяем strategy1
    s1_row = result_df[result_df["strategy"] == "strategy1"].iloc[0]
    
    assert s1_row["splits_total"] == 3
    assert s1_row["worst_case_window_pnl"] == -0.12  # min of [-0.1, -0.12, -0.08]
    assert s1_row["median_survival_rate"] == 0.8  # median of [0.8, 0.75, 0.85]
    assert s1_row["median_median_window_pnl"] == 0.05  # median of [0.05, 0.04, 0.06]
    assert s1_row["max_pnl_variance"] == 0.06  # max of [0.05, 0.06, 0.04]
    assert s1_row["trades_total"] == 10  # Constant value kept


def test_aggregate_stability_handles_empty_df():
    """Проверяет обработку пустого DataFrame"""
    empty_df = pd.DataFrame(columns=["strategy", "split_count", "survival_rate"])
    result_df = aggregate_stability(empty_df)
    
    assert len(result_df) == 0
    assert list(result_df.columns) == list(empty_df.columns)


def test_aggregate_stability_handles_no_split_count():
    """Проверяет обработку DataFrame без split_count"""
    df_no_split = pd.DataFrame({
        "strategy": ["strategy1", "strategy2"],
        "survival_rate": [0.8, 0.6],
    })
    result_df = aggregate_stability(df_no_split)
    
    # Should return as-is if no split_count
    assert len(result_df) == 2
    assert "splits_total" not in result_df.columns


def test_aggregate_selection_pass_rate_and_worst_case(sample_selection_df):
    """Проверяет вычисление robust_pass_rate, passed_any, passed_all, worst_case_window_pnl"""
    result_df = aggregate_selection(sample_selection_df)
    
    # Проверяем strategy1 (2 passed, 2 rejected out of 4 splits)
    s1_row = result_df[result_df["strategy"] == "strategy1"].iloc[0]
    
    assert s1_row["splits_total"] == 4
    assert abs(s1_row["robust_pass_rate"] - 0.5) < 1e-6  # 2/4 = 0.5
    assert s1_row["passed_any"] == True  # At least one passed
    assert s1_row["passed_all"] == False  # Not all passed
    assert s1_row["worst_case_window_pnl"] == -0.12  # min of [-0.1, -0.12, -0.08, -0.07]
    
    # Проверяем strategy2 (0 passed out of 2 splits)
    s2_row = result_df[result_df["strategy"] == "strategy2"].iloc[0]
    
    assert s2_row["splits_total"] == 2
    assert s2_row["robust_pass_rate"] == 0.0  # 0/2 = 0.0
    assert s2_row["passed_any"] == False  # None passed
    assert s2_row["passed_all"] == False  # Not all passed (all failed)


def test_aggregate_selection_handles_insufficient_data():
    """Проверяет вычисление insufficient_data_rate при наличии selection_status"""
    selection_df = pd.DataFrame({
        "strategy": ["strategy1", "strategy1", "strategy1", "strategy2"],
        "split_count": [2, 3, 4, 2],
        "survival_rate": [0.8, 0.75, 0.85, 0.6],
        "pnl_variance": [0.05, 0.06, 0.04, 0.15],
        "worst_window_pnl": [-0.1, -0.12, -0.08, -0.3],
        "median_window_pnl": [0.05, 0.04, 0.06, -0.05],
        "windows_total": [2, 3, 4, 2],
        "passed": [True, False, True, False],
        "selection_status": ["passed", "insufficient_data", "passed", "rejected"],
        "failed_reasons": [[], ["insufficient_data"], [], ["low_survival"]],
    })
    
    result_df = aggregate_selection(selection_df)
    
    # Проверяем strategy1 (1 insufficient_data out of 3 splits)
    s1_row = result_df[result_df["strategy"] == "strategy1"].iloc[0]
    
    assert abs(s1_row["insufficient_data_rate"] - 1/3) < 1e-6  # 1/3
    assert abs(s1_row["rejected_rate"] - 0.0) < 1e-6  # 0/3
    
    # Проверяем strategy2 (1 rejected out of 1 split)
    s2_row = result_df[result_df["strategy"] == "strategy2"].iloc[0]
    
    assert abs(s2_row["insufficient_data_rate"] - 0.0) < 1e-6  # 0/1
    assert abs(s2_row["rejected_rate"] - 1.0) < 1e-6  # 1/1


def test_aggregate_selection_keeps_one_row_per_strategy(sample_selection_df):
    """Проверяет, что агрегированная таблица содержит по одной строке на стратегию"""
    result_df = aggregate_selection(sample_selection_df)
    
    assert len(result_df) == 2, "Должно быть 2 стратегии"
    assert set(result_df["strategy"].unique()) == {"strategy1", "strategy2"}
    assert len(result_df["strategy"].unique()) == len(result_df)


def test_aggregate_selection_handles_empty_df():
    """Проверяет обработку пустого DataFrame"""
    empty_df = pd.DataFrame(columns=["strategy", "split_count", "passed"])
    result_df = aggregate_selection(empty_df)
    
    assert len(result_df) == 0


def test_aggregate_selection_handles_no_split_count():
    """Проверяет обработку DataFrame без split_count"""
    df_no_split = pd.DataFrame({
        "strategy": ["strategy1", "strategy2"],
        "passed": [True, False],
    })
    result_df = aggregate_selection(df_no_split)
    
    # Should still compute robust_pass_rate, passed_any, passed_all
    assert len(result_df) == 2
    assert "robust_pass_rate" in result_df.columns
    assert "passed_any" in result_df.columns
    assert "passed_all" in result_df.columns
    
    # Each row should have robust_pass_rate = passed value
    s1_row = result_df[result_df["strategy"] == "strategy1"].iloc[0]
    assert s1_row["robust_pass_rate"] == 1.0
    assert s1_row["passed_any"] == True
    assert s1_row["passed_all"] == True


def test_aggregate_selection_requires_passed_column():
    """Проверяет, что aggregate_selection требует колонку passed"""
    df_no_passed = pd.DataFrame({
        "strategy": ["strategy1"],
        "split_count": [2],
    })
    
    with pytest.raises(ValueError, match="Missing required columns"):
        aggregate_selection(df_no_passed)


def test_aggregate_selection_computes_all_metrics():
    """Проверяет вычисление всех метрик агрегации"""
    selection_df = pd.DataFrame({
        "strategy": ["strategy1", "strategy1", "strategy1"],
        "split_count": [2, 3, 4],
        "survival_rate": [0.8, 0.75, 0.85],
        "pnl_variance": [0.05, 0.06, 0.04],
        "worst_window_pnl": [-0.1, -0.12, -0.08],
        "median_window_pnl": [0.05, 0.04, 0.06],
        "windows_total": [2, 3, 4],
        "passed": [True, True, False],
    })
    
    result_df = aggregate_selection(selection_df)
    s1_row = result_df.iloc[0]
    
    # Проверяем наличие всех ключевых метрик
    assert "splits_total" in result_df.columns
    assert "robust_pass_rate" in result_df.columns
    assert "passed_any" in result_df.columns
    assert "passed_all" in result_df.columns
    assert "worst_case_window_pnl" in result_df.columns
    assert "median_survival_rate" in result_df.columns
    assert "median_median_window_pnl" in result_df.columns
    assert "max_pnl_variance" in result_df.columns
    
    # Проверяем типы
    assert isinstance(s1_row["splits_total"], (int, np.integer))
    assert isinstance(s1_row["robust_pass_rate"], (float, np.floating))
    assert isinstance(s1_row["passed_any"], (bool, np.bool_))
    assert isinstance(s1_row["passed_all"], (bool, np.bool_))
