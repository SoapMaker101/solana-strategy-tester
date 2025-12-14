"""
Unit tests for window_aggregator module
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
import tempfile
import shutil

from backtester.research.window_aggregator import (
    load_trades_csv,
    calculate_window_metrics,
    split_into_windows,
    aggregate_strategy_windows,
    WINDOWS,
)


@pytest.fixture
def sample_trades_df():
    """Создаёт sample DataFrame с trades"""
    return pd.DataFrame({
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-15T10:00:00Z",
            "2024-02-01T10:00:00Z",
            "2024-03-01T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-15T10:01:00Z",
            "2024-02-01T10:01:00Z",
            "2024-03-01T10:01:00Z",
        ], utc=True),
        "pnl_pct": [0.1, -0.05, 0.15, 0.2],
        "reason": ["tp", "sl", "tp", "tp"],
    })


@pytest.fixture
def tmp_csv_file(tmp_path, sample_trades_df):
    """Создаёт временный CSV файл с trades"""
    csv_path = tmp_path / "test_strategy_trades.csv"
    sample_trades_df.to_csv(csv_path, index=False)
    return csv_path


def test_load_trades_csv(tmp_csv_file):
    """Проверяет загрузку trades CSV"""
    df = load_trades_csv(tmp_csv_file)
    
    assert len(df) == 4
    assert "entry_time" in df.columns
    assert "exit_time" in df.columns
    assert "pnl_pct" in df.columns
    assert "reason" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["entry_time"])
    assert pd.api.types.is_datetime64_any_dtype(df["exit_time"])


def test_load_trades_csv_missing_file(tmp_path):
    """Проверяет обработку отсутствующего файла"""
    csv_path = tmp_path / "nonexistent.csv"
    with pytest.raises(FileNotFoundError):
        load_trades_csv(csv_path)


def test_load_trades_csv_missing_columns(tmp_path):
    """Проверяет обработку отсутствующих колонок"""
    csv_path = tmp_path / "invalid.csv"
    df = pd.DataFrame({"wrong_column": [1, 2, 3]})
    df.to_csv(csv_path, index=False)
    
    with pytest.raises(ValueError, match="Missing required columns"):
        load_trades_csv(csv_path)


def test_calculate_window_metrics_empty():
    """Проверяет расчёт метрик для пустого окна"""
    empty_df = pd.DataFrame(columns=["entry_time", "exit_time", "pnl_pct", "reason"])
    metrics = calculate_window_metrics(empty_df)
    
    assert metrics["trades_count"] == 0
    assert metrics["winrate"] == 0.0
    assert metrics["total_pnl"] == 0.0
    assert metrics["median_pnl"] == 0.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["profit_factor"] == 0.0
    assert metrics["worst_trade"] == 0.0
    assert metrics["best_trade"] == 0.0


def test_calculate_window_metrics_single_trade():
    """Проверяет расчёт метрик для окна с 1 сделкой"""
    df = pd.DataFrame({
        "entry_time": pd.to_datetime(["2024-01-01T10:00:00Z"], utc=True),
        "exit_time": pd.to_datetime(["2024-01-01T10:01:00Z"], utc=True),
        "pnl_pct": [0.1],
        "reason": ["tp"],
    })
    
    metrics = calculate_window_metrics(df)
    
    assert metrics["trades_count"] == 1
    assert metrics["winrate"] == 1.0
    assert metrics["total_pnl"] == 0.1
    assert metrics["median_pnl"] == 0.1
    assert metrics["best_trade"] == 0.1
    assert metrics["worst_trade"] == 0.1
    assert metrics["max_drawdown"] == 0.0  # Нет просадки если только прибыль


def test_calculate_window_metrics_multiple_trades():
    """Проверяет расчёт метрик для окна с несколькими сделками"""
    df = pd.DataFrame({
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-01T11:00:00Z",
            "2024-01-01T12:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-01T11:01:00Z",
            "2024-01-01T12:01:00Z",
        ], utc=True),
        "pnl_pct": [0.1, -0.05, 0.15],
        "reason": ["tp", "sl", "tp"],
    })
    
    metrics = calculate_window_metrics(df)
    
    assert metrics["trades_count"] == 3
    assert metrics["winrate"] == pytest.approx(2/3)
    assert metrics["total_pnl"] == pytest.approx(0.2)
    assert metrics["median_pnl"] == 0.1
    assert metrics["best_trade"] == 0.15
    assert metrics["worst_trade"] == -0.05


def test_calculate_window_metrics_max_drawdown():
    """Проверяет расчёт max_drawdown"""
    # Серия: +0.1, -0.2, +0.1
    # Cumulative: 0.1, -0.1, 0.0
    # Running max: 0.1, 0.1, 0.1
    # Drawdown: 0.0, -0.2, -0.1
    # Max drawdown: -0.2
    df = pd.DataFrame({
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-01T11:00:00Z",
            "2024-01-01T12:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-01T11:01:00Z",
            "2024-01-01T12:01:00Z",
        ], utc=True),
        "pnl_pct": [0.1, -0.2, 0.1],
        "reason": ["tp", "sl", "tp"],
    })
    
    metrics = calculate_window_metrics(df)
    
    assert metrics["max_drawdown"] < 0
    # Max drawdown должен быть примерно -0.2 (наихудший момент)


def test_calculate_window_metrics_profit_factor():
    """Проверяет расчёт profit_factor"""
    df = pd.DataFrame({
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-01T11:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-01T11:01:00Z",
        ], utc=True),
        "pnl_pct": [0.2, -0.1],  # profit = 0.2, loss = 0.1, factor = 2.0
        "reason": ["tp", "sl"],
    })
    
    metrics = calculate_window_metrics(df)
    
    assert metrics["profit_factor"] == pytest.approx(2.0)


def test_split_into_windows(sample_trades_df):
    """Проверяет разделение на временные окна"""
    window_delta = relativedelta(months=1)
    windows = split_into_windows(sample_trades_df, window_delta)
    
    # Должно быть минимум одно окно
    assert len(windows) > 0
    
    # Проверяем, что все сделки попали в окна
    total_trades = sum(len(df) for df in windows.values())
    assert total_trades == len(sample_trades_df)


def test_split_into_windows_empty():
    """Проверяет разделение пустого DataFrame"""
    empty_df = pd.DataFrame(columns=["entry_time", "exit_time", "pnl_pct", "reason"])
    window_delta = relativedelta(months=1)
    windows = split_into_windows(empty_df, window_delta)
    
    assert len(windows) == 0


def test_split_into_windows_filtering_by_entry_time(sample_trades_df):
    """Проверяет корректную фильтрацию по entry_time"""
    window_delta = relativedelta(months=1)
    windows = split_into_windows(sample_trades_df, window_delta)
    
    # Проверяем, что каждая сделка попадает только в своё окно
    for window_start, window_df in windows.items():
        window_start_dt = pd.to_datetime(window_start)
        window_end_dt = window_start_dt + window_delta
        
        for _, row in window_df.iterrows():
            assert window_start_dt <= row["entry_time"] < window_end_dt


def test_split_into_windows_stability_order(sample_trades_df):
    """Проверяет стабильность метрик при разном порядке строк"""
    # Оригинальный порядок
    windows1 = split_into_windows(sample_trades_df, relativedelta(months=1))
    
    # Перемешанный порядок
    shuffled_df = sample_trades_df.sample(frac=1.0).reset_index(drop=True)
    windows2 = split_into_windows(shuffled_df, relativedelta(months=1))
    
    # Количество окон должно быть одинаковым
    assert len(windows1) == len(windows2)
    
    # Количество сделок в каждом окне должно быть одинаковым
    for window_start in windows1.keys():
        if window_start in windows2:
            assert len(windows1[window_start]) == len(windows2[window_start])


def test_aggregate_strategy_windows(tmp_csv_file):
    """Проверяет агрегацию стратегии по окнам"""
    result = aggregate_strategy_windows(tmp_csv_file, WINDOWS)
    
    assert "1m" in result
    assert "2m" in result
    assert "3m" in result
    assert "6m" in result
    
    # Проверяем структуру результата
    for window_name, windows in result.items():
        assert isinstance(windows, dict)
        for window_start, metrics in windows.items():
            assert "trades_count" in metrics
            assert "winrate" in metrics
            assert "total_pnl" in metrics


def test_aggregate_strategy_windows_custom_windows(tmp_csv_file):
    """Проверяет агрегацию с пользовательскими окнами"""
    custom_windows = {
        "1m": relativedelta(months=1),
    }
    result = aggregate_strategy_windows(tmp_csv_file, custom_windows)
    
    assert "1m" in result
    assert "2m" not in result
