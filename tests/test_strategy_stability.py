"""
Unit tests for strategy_stability module
"""
import pytest
import pandas as pd
from pathlib import Path
import statistics
import tempfile
import shutil

from backtester.research.strategy_stability import (
    calculate_stability_metrics,
    build_stability_table,
    save_stability_table,
)


def test_calculate_stability_metrics_empty():
    """Проверяет расчёт метрик для пустых окон"""
    strategy_windows = {}
    metrics = calculate_stability_metrics(strategy_windows)
    
    assert metrics["survival_rate"] == 0.0
    assert metrics["pnl_variance"] == 0.0
    assert metrics["worst_window_pnl"] == 0.0
    assert metrics["best_window_pnl"] == 0.0
    assert metrics["median_window_pnl"] == 0.0
    assert metrics["windows_positive"] == 0
    assert metrics["windows_total"] == 0


def test_calculate_stability_metrics_single_window():
    """Проверяет расчёт метрик для стратегии с 1 окном"""
    strategy_windows = {
        "1m": {
            "2024-01-01T00:00:00+00:00": {
                "total_pnl": 0.1,
                "trades_count": 5,
                "winrate": 0.6,
            }
        }
    }
    
    metrics = calculate_stability_metrics(strategy_windows)
    
    assert metrics["windows_total"] == 1
    assert metrics["windows_positive"] == 1
    assert metrics["survival_rate"] == 1.0
    assert metrics["worst_window_pnl"] == 0.1
    assert metrics["best_window_pnl"] == 0.1
    assert metrics["median_window_pnl"] == 0.1
    assert metrics["pnl_variance"] == 0.0  # Одно значение → variance = 0


def test_calculate_stability_metrics_multiple_windows():
    """Проверяет расчёт метрик для нескольких окон"""
    strategy_windows = {
        "1m": {
            "2024-01-01T00:00:00+00:00": {"total_pnl": 0.1},
            "2024-02-01T00:00:00+00:00": {"total_pnl": -0.05},
            "2024-03-01T00:00:00+00:00": {"total_pnl": 0.2},
        }
    }
    
    metrics = calculate_stability_metrics(strategy_windows)
    
    assert metrics["windows_total"] == 3
    assert metrics["windows_positive"] == 2
    assert metrics["survival_rate"] == pytest.approx(2/3)
    assert metrics["worst_window_pnl"] == -0.05
    assert metrics["best_window_pnl"] == 0.2
    assert metrics["median_window_pnl"] == 0.1
    assert metrics["pnl_variance"] > 0  # Разные значения → variance > 0


def test_calculate_stability_metrics_survival_rate_correct():
    """Проверяет корректность расчёта survival_rate"""
    strategy_windows = {
        "1m": {
            "2024-01-01T00:00:00+00:00": {"total_pnl": 0.1},
            "2024-02-01T00:00:00+00:00": {"total_pnl": -0.05},
            "2024-03-01T00:00:00+00:00": {"total_pnl": 0.0},  # Ноль не считается положительным
            "2024-04-01T00:00:00+00:00": {"total_pnl": 0.15},
            "2024-05-01T00:00:00+00:00": {"total_pnl": -0.1},
        }
    }
    
    metrics = calculate_stability_metrics(strategy_windows)
    
    # 2 положительных из 5 = 0.4
    assert metrics["survival_rate"] == pytest.approx(0.4)
    assert metrics["windows_positive"] == 2
    assert metrics["windows_total"] == 5


def test_calculate_stability_metrics_variance_zero():
    """Проверяет, что variance = 0 при одинаковых окнах"""
    strategy_windows = {
        "1m": {
            "2024-01-01T00:00:00+00:00": {"total_pnl": 0.1},
            "2024-02-01T00:00:00+00:00": {"total_pnl": 0.1},
            "2024-03-01T00:00:00+00:00": {"total_pnl": 0.1},
        }
    }
    
    metrics = calculate_stability_metrics(strategy_windows)
    
    # Variance для одинаковых значений = 0 (или близка к нулю из-за float)
    assert metrics["pnl_variance"] == pytest.approx(0.0, abs=1e-10)


def test_build_stability_table_empty():
    """Проверяет построение таблицы для пустых стратегий"""
    aggregated_strategies = {}
    df = build_stability_table(aggregated_strategies)
    
    assert len(df) == 0
    assert list(df.columns) == [
        "strategy",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "best_window_pnl",
        "median_window_pnl",
        "windows_positive",
        "windows_total",
    ]


def test_build_stability_table_single_strategy():
    """Проверяет построение таблицы для одной стратегии"""
    aggregated_strategies = {
        "test_strategy": {
            "1m": {
                "2024-01-01T00:00:00+00:00": {"total_pnl": 0.1},
                "2024-02-01T00:00:00+00:00": {"total_pnl": -0.05},
            }
        }
    }
    
    df = build_stability_table(aggregated_strategies)
    
    assert len(df) == 1
    assert df.iloc[0]["strategy"] == "test_strategy"
    assert df.iloc[0]["windows_total"] == 2
    assert df.iloc[0]["windows_positive"] == 1
    assert df.iloc[0]["survival_rate"] == pytest.approx(0.5)


def test_build_stability_table_multiple_strategies():
    """Проверяет построение таблицы для нескольких стратегий"""
    aggregated_strategies = {
        "strategy1": {
            "1m": {
                "2024-01-01T00:00:00+00:00": {"total_pnl": 0.1},
            }
        },
        "strategy2": {
            "1m": {
                "2024-01-01T00:00:00+00:00": {"total_pnl": -0.05},
            }
        },
    }
    
    df = build_stability_table(aggregated_strategies)
    
    assert len(df) == 2
    assert set(df["strategy"].tolist()) == {"strategy1", "strategy2"}
    
    # Проверяем, что стратегии не отсортированы по pnl (важное правило!)
    # Таблица должна сохранить порядок стратегий как есть


def test_build_stability_table_no_sorting():
    """Проверяет, что таблица НЕ сортируется по pnl (критично!)"""
    aggregated_strategies = {
        "worst_strategy": {
            "1m": {
                "2024-01-01T00:00:00+00:00": {"total_pnl": -0.5},
            }
        },
        "best_strategy": {
            "1m": {
                "2024-01-01T00:00:00+00:00": {"total_pnl": 0.5},
            }
        },
    }
    
    df = build_stability_table(aggregated_strategies)
    
    # Первая стратегия должна остаться первой (не отсортировано по pnl)
    assert df.iloc[0]["strategy"] == "worst_strategy"
    assert df.iloc[1]["strategy"] == "best_strategy"


def test_save_stability_table(tmp_path):
    """Проверяет сохранение таблицы в CSV"""
    df = pd.DataFrame({
        "strategy": ["test1", "test2"],
        "survival_rate": [0.5, 0.8],
        "pnl_variance": [0.01, 0.02],
        "worst_window_pnl": [-0.1, -0.05],
        "best_window_pnl": [0.2, 0.3],
        "median_window_pnl": [0.05, 0.1],
        "windows_positive": [2, 4],
        "windows_total": [4, 5],
    })
    
    output_path = tmp_path / "stability.csv"
    save_stability_table(df, output_path)
    
    assert output_path.exists()
    
    # Проверяем, что файл можно прочитать
    loaded_df = pd.read_csv(output_path)
    assert len(loaded_df) == 2
    assert list(loaded_df.columns) == list(df.columns)
