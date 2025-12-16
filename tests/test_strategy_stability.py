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
    from datetime import datetime, timezone
    
    strategy_windows = {
        "split_2": [
            {
                "window_index": 0,
                "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {
                    "total_pnl": 0.1,
                    "trades_count": 5,
                    "winrate": 0.6,
                }
            }
        ]
    }
    
    metrics = calculate_stability_metrics(strategy_windows, split_n=2)
    
    assert metrics["windows_total"] == 1
    assert metrics["windows_positive"] == 1
    assert metrics["survival_rate"] == 1.0
    assert metrics["worst_window_pnl"] == 0.1
    assert metrics["best_window_pnl"] == 0.1
    assert metrics["median_window_pnl"] == 0.1
    assert metrics["pnl_variance"] == 0.0  # Одно значение → variance = 0


def test_calculate_stability_metrics_multiple_windows():
    """Проверяет расчёт метрик для нескольких окон"""
    from datetime import datetime, timezone
    
    strategy_windows = {
        "split_3": [
            {
                "window_index": 0,
                "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.1}
            },
            {
                "window_index": 1,
                "window_start": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 2, 10, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": -0.05}
            },
            {
                "window_index": 2,
                "window_start": datetime(2024, 2, 10, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.2}
            },
        ]
    }
    
    metrics = calculate_stability_metrics(strategy_windows, split_n=3)
    
    assert metrics["windows_total"] == 3
    assert metrics["windows_positive"] == 2
    assert metrics["survival_rate"] == pytest.approx(2/3)
    assert metrics["worst_window_pnl"] == -0.05
    assert metrics["best_window_pnl"] == 0.2
    assert metrics["median_window_pnl"] == 0.1
    assert metrics["pnl_variance"] > 0  # Разные значения → variance > 0


def test_calculate_stability_metrics_survival_rate_correct():
    """Проверяет корректность расчёта survival_rate"""
    from datetime import datetime, timezone
    
    strategy_windows = {
        "split_5": [
            {
                "window_index": 0,
                "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.1}
            },
            {
                "window_index": 1,
                "window_start": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 2, 10, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": -0.05}
            },
            {
                "window_index": 2,
                "window_start": datetime(2024, 2, 10, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.0}  # Ноль не считается положительным
            },
            {
                "window_index": 3,
                "window_start": datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 3, 20, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.15}
            },
            {
                "window_index": 4,
                "window_start": datetime(2024, 3, 20, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 4, 10, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": -0.1}
            },
        ]
    }
    
    metrics = calculate_stability_metrics(strategy_windows, split_n=5)
    
    # 2 положительных из 5 = 0.4
    assert metrics["survival_rate"] == pytest.approx(0.4)
    assert metrics["windows_positive"] == 2
    assert metrics["windows_total"] == 5


def test_calculate_stability_metrics_variance_zero():
    """Проверяет, что variance = 0 при одинаковых окнах"""
    from datetime import datetime, timezone
    
    strategy_windows = {
        "split_3": [
            {
                "window_index": 0,
                "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.1}
            },
            {
                "window_index": 1,
                "window_start": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 2, 10, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.1}
            },
            {
                "window_index": 2,
                "window_start": datetime(2024, 2, 10, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.1}
            },
        ]
    }
    
    metrics = calculate_stability_metrics(strategy_windows, split_n=3)
    
    # Variance для одинаковых значений = 0 (или близка к нулю из-за float)
    assert metrics["pnl_variance"] == pytest.approx(0.0, abs=1e-10)


def test_build_stability_table_empty():
    """Проверяет построение таблицы для пустых стратегий"""
    aggregated_strategies = {}
    df = build_stability_table(aggregated_strategies)
    
    assert len(df) == 0
    assert list(df.columns) == [
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


def test_build_stability_table_single_strategy():
    """Проверяет построение таблицы для одной стратегии"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "test_strategy": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.05}
                },
            ]
        }
    }
    
    df = build_stability_table(aggregated_strategies, split_counts=[2])
    
    assert len(df) == 1
    assert df.iloc[0]["strategy"] == "test_strategy"
    assert df.iloc[0]["split_count"] == 2
    assert df.iloc[0]["windows_total"] == 2
    assert df.iloc[0]["windows_positive"] == 1
    assert df.iloc[0]["survival_rate"] == pytest.approx(0.5)


def test_build_stability_table_multiple_strategies():
    """Проверяет построение таблицы для нескольких стратегий"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "strategy1": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.1}
                },
            ]
        },
        "strategy2": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.05}
                },
            ]
        },
    }
    
    df = build_stability_table(aggregated_strategies, split_counts=[2])
    
    assert len(df) == 2
    assert set(df["strategy"].tolist()) == {"strategy1", "strategy2"}
    
    # Проверяем, что стратегии не отсортированы по pnl (важное правило!)
    # Таблица должна сохранить порядок стратегий как есть


def test_build_stability_table_no_sorting():
    """Проверяет, что таблица НЕ сортируется по pnl (критично!)"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "worst_strategy": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.5}
                },
            ]
        },
        "best_strategy": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.5}
                },
            ]
        },
    }
    
    df = build_stability_table(aggregated_strategies, split_counts=[2])
    
    # Первая стратегия должна остаться первой (не отсортировано по pnl)
    assert df.iloc[0]["strategy"] == "worst_strategy"
    assert df.iloc[1]["strategy"] == "best_strategy"


def test_save_stability_table(tmp_path):
    """Проверяет сохранение таблицы в CSV"""
    df = pd.DataFrame({
        "strategy": ["test1", "test2"],
        "split_count": [2, 3],
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


def test_calculate_stability_metrics_with_split_n():
    """Проверяет расчёт метрик с указанным split_n"""
    from datetime import datetime, timezone
    
    strategy_windows = {
        "split_2": [
            {
                "window_index": 0,
                "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.1}
            },
            {
                "window_index": 1,
                "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": -0.05}
            },
        ],
        "split_3": [
            {
                "window_index": 0,
                "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.05}
            },
            {
                "window_index": 1,
                "window_start": datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.03}
            },
            {
                "window_index": 2,
                "window_start": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                "metrics": {"total_pnl": 0.02}
            },
        ],
    }
    
    # Метрики для split_2
    metrics_2 = calculate_stability_metrics(strategy_windows, split_n=2)
    assert metrics_2["windows_total"] == 2
    assert metrics_2["windows_positive"] == 1
    assert metrics_2["survival_rate"] == pytest.approx(0.5)
    
    # Метрики для split_3
    metrics_3 = calculate_stability_metrics(strategy_windows, split_n=3)
    assert metrics_3["windows_total"] == 3
    assert metrics_3["windows_positive"] == 3
    assert metrics_3["survival_rate"] == pytest.approx(1.0)


def test_build_stability_table_with_split_counts():
    """Проверяет построение таблицы с split_counts"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "test_strategy": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.05}
                },
            ],
            "split_3": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.05}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.03}
                },
                {
                    "window_index": 2,
                    "window_start": datetime(2024, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.02}
                },
            ],
        }
    }
    
    split_counts = [2, 3]
    df = build_stability_table(aggregated_strategies, split_counts=split_counts)
    
    # Должно быть 2 строки (одна на split_count)
    assert len(df) == 2
    
    # Проверяем наличие колонки split_count
    assert "split_count" in df.columns
    
    # Проверяем, что есть строки для split_count=2 и split_count=3
    assert set(df["split_count"].tolist()) == {2, 3}
    
    # Проверяем windows_total
    row_2 = df[df["split_count"] == 2].iloc[0]
    assert row_2["windows_total"] == 2
    
    row_3 = df[df["split_count"] == 3].iloc[0]
    assert row_3["windows_total"] == 3


def test_build_stability_table_backward_compatibility():
    """Проверяет обратную совместимость: без split_counts используется DEFAULT_SPLITS"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "test_strategy": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.05}
                },
            ]
        }
    }
    
    df = build_stability_table(aggregated_strategies, split_counts=None)
    
    # Должно быть 4 строки (по одной на каждый split_count из DEFAULT_SPLITS)
    assert len(df) == 4
    
    # Должна быть колонка split_count
    assert "split_count" in df.columns
    
    # Проверяем метрики для split_count=2
    row_2 = df[df["split_count"] == 2].iloc[0]
    assert row_2["strategy"] == "test_strategy"
    assert row_2["windows_total"] == 2


def test_build_stability_table_multiple_strategies_with_split_counts():
    """Проверяет построение таблицы для нескольких стратегий с split_counts"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "strategy1": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.05}
                },
            ],
        },
        "strategy2": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.05}
                },
            ],
        },
    }
    
    split_counts = [2]
    df = build_stability_table(aggregated_strategies, split_counts=split_counts)
    
    # Должно быть 2 строки (одна на стратегию для split_count=2)
    assert len(df) == 2
    
    # Проверяем, что обе стратегии присутствуют
    assert set(df["strategy"].tolist()) == {"strategy1", "strategy2"}
    
    # Все строки должны иметь split_count=2
    assert all(df["split_count"] == 2)


def test_build_stability_table_order_independence():
    """Проверяет, что порядок строк не влияет на результат"""
    from datetime import datetime, timezone
    
    aggregated_strategies = {
        "strategy1": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": 0.05}
                },
            ],
        },
        "strategy2": {
            "split_2": [
                {
                    "window_index": 0,
                    "window_start": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.1}
                },
                {
                    "window_index": 1,
                    "window_start": datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),
                    "window_end": datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
                    "metrics": {"total_pnl": -0.05}
                },
            ],
        },
    }
    
    split_counts = [2]
    
    # Строим таблицу дважды
    df1 = build_stability_table(aggregated_strategies, split_counts=split_counts)
    
    # Меняем порядок стратегий
    aggregated_strategies_reordered = {
        "strategy2": aggregated_strategies["strategy2"],
        "strategy1": aggregated_strategies["strategy1"],
    }
    df2 = build_stability_table(aggregated_strategies_reordered, split_counts=split_counts)
    
    # Результаты должны быть одинаковыми (кроме порядка строк)
    assert len(df1) == len(df2)
    assert set(df1["strategy"].tolist()) == set(df2["strategy"].tolist())
    
    # Проверяем, что метрики одинаковые для каждой стратегии
    for strategy in ["strategy1", "strategy2"]:
        row1 = df1[df1["strategy"] == strategy].iloc[0]
        row2 = df2[df2["strategy"] == strategy].iloc[0]
        
        assert row1["windows_total"] == row2["windows_total"]
        assert row1["survival_rate"] == pytest.approx(row2["survival_rate"])
        assert row1["worst_window_pnl"] == pytest.approx(row2["worst_window_pnl"])




