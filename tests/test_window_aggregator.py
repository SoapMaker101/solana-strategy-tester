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
    split_into_equal_windows,
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
        "reason": ["ladder_tp", "stop_loss", "ladder_tp", "ladder_tp"],
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
        "reason": ["ladder_tp"],
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
        "reason": ["ladder_tp", "stop_loss", "ladder_tp"],
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
        "reason": ["ladder_tp", "stop_loss", "ladder_tp"],
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
        "reason": ["ladder_tp", "stop_loss"],
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
    """Проверяет агрегацию стратегии по окнам (legacy режим)"""
    result = aggregate_strategy_windows(tmp_csv_file, windows=WINDOWS)
    
    assert "1m" in result
    assert "2m" in result
    assert "3m" in result
    assert "6m" in result
    
    # Проверяем структуру результата (legacy режим возвращает list)
    for window_name, window_list in result.items():
        assert isinstance(window_list, list)
        for window_info in window_list:
            assert "metrics" in window_info
            metrics = window_info["metrics"]
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


def test_split_into_equal_windows_empty():
    """Проверяет разбиение пустого DataFrame"""
    empty_df = pd.DataFrame(columns=["entry_time", "exit_time", "pnl_pct", "reason"])
    windows = split_into_equal_windows(empty_df, split_n=2)
    
    assert len(windows) == 0  # Пустой DataFrame возвращает пустой список


def test_split_into_equal_windows_split_n_2(sample_trades_df):
    """Проверяет, что split_n=2 даёт ровно 2 окна (включая пустые)"""
    windows = split_into_equal_windows(sample_trades_df, split_n=2)
    
    assert len(windows) == 2  # Всегда возвращает все окна, даже пустые
    
    # Проверяем, что все сделки попали в окна
    total_trades = sum(len(window_info["trades"]) for window_info in windows)
    assert total_trades == len(sample_trades_df)
    
    # Проверяем структуру каждого окна
    for window_info in windows:
        assert "window_index" in window_info
        assert "window_start" in window_info
        assert "window_end" in window_info
        assert "trades" in window_info


def test_split_into_equal_windows_split_n_3(sample_trades_df):
    """Проверяет, что split_n=3 даёт ровно 3 окна (включая пустые)"""
    windows = split_into_equal_windows(sample_trades_df, split_n=3)
    
    assert len(windows) == 3  # Всегда возвращает все окна, даже пустые
    
    # Проверяем, что все сделки попали в окна
    total_trades = sum(len(window_info["trades"]) for window_info in windows)
    assert total_trades == len(sample_trades_df)
    
    # Проверяем, что окна имеют правильные индексы
    indices = [w["window_index"] for w in windows]
    assert sorted(indices) == [0, 1, 2]


def test_split_into_equal_windows_different_split_n_give_different_windows_total(sample_trades_df):
    """Проверяет, что одинаковые trades с разными split_n дают разное количество окон"""
    windows_2 = split_into_equal_windows(sample_trades_df, split_n=2)
    windows_3 = split_into_equal_windows(sample_trades_df, split_n=3)
    
    assert len(windows_2) == 2  # Всегда возвращает все окна
    assert len(windows_3) == 3  # Всегда возвращает все окна


def test_split_into_equal_windows_metrics_correct(sample_trades_df):
    """Проверяет, что метрики считаются корректно для каждого окна"""
    windows = split_into_equal_windows(sample_trades_df, split_n=2)
    
    for window_info in windows:
        window_trades = window_info["trades"]
        metrics = calculate_window_metrics(window_trades)
        
        assert "trades_count" in metrics
        assert "winrate" in metrics
        assert "total_pnl" in metrics
        assert "median_pnl" in metrics
        assert "worst_trade" in metrics
        assert "best_trade" in metrics
        assert metrics["trades_count"] == len(window_trades)


def test_split_into_equal_windows_stability_order(sample_trades_df):
    """Проверяет стабильность метрик при разном порядке строк"""
    # Оригинальный порядок
    windows1 = split_into_equal_windows(sample_trades_df, split_n=2)
    
    # Перемешанный порядок
    shuffled_df = sample_trades_df.sample(frac=1.0).reset_index(drop=True)
    windows2 = split_into_equal_windows(shuffled_df, split_n=2)
    
    # Количество окон должно быть одинаковым
    assert len(windows1) == len(windows2)
    
    # Количество сделок в каждом окне должно быть одинаковым
    # (порядок может отличаться, но количество окон и сделок должно совпадать)
    trades_counts1 = sorted([len(w["trades"]) for w in windows1])
    trades_counts2 = sorted([len(w["trades"]) for w in windows2])
    assert trades_counts1 == trades_counts2


def test_split_into_equal_windows_invalid_split_n(sample_trades_df):
    """Проверяет обработку невалидного split_n"""
    with pytest.raises(ValueError, match="split_n must be positive"):
        split_into_equal_windows(sample_trades_df, split_n=0)
    
    with pytest.raises(ValueError, match="split_n must be positive"):
        split_into_equal_windows(sample_trades_df, split_n=-1)


def test_aggregate_strategy_windows_with_split_counts(tmp_csv_file):
    """Проверяет агрегацию с split_counts"""
    split_counts = [2, 3, 4]
    result = aggregate_strategy_windows(tmp_csv_file, split_counts=split_counts)
    
    # Должны быть окна для каждого split_n
    assert "split_2" in result
    assert "split_3" in result
    assert "split_4" in result
    
    # Проверяем, что windows_total == split_n (все окна возвращаются, включая пустые)
    for split_n in split_counts:
        window_name = f"split_{split_n}"
        window_list = result[window_name]
        # Количество окон должно быть равно split_n (все окна возвращаются)
        assert len(window_list) == split_n
        # Проверяем структуру каждого окна
        for window_info in window_list:
            assert "window_index" in window_info
            assert "window_start" in window_info
            assert "window_end" in window_info
            assert "metrics" in window_info
            metrics = window_info["metrics"]
            assert isinstance(metrics, dict)
            assert "trades_count" in metrics


def test_aggregate_strategy_windows_backward_compatibility(tmp_csv_file):
    """Проверяет обратную совместимость: с windows используется legacy режим"""
    result = aggregate_strategy_windows(tmp_csv_file, windows=WINDOWS)
    
    # Должны быть стандартные окна
    assert "1m" in result
    assert "2m" in result
    assert "3m" in result
    assert "6m" in result
    
    # Не должно быть split_* окон
    assert not any(key.startswith("split_") for key in result.keys())


def test_split_into_equal_windows_equal_duration(sample_trades_df):
    """Проверяет, что окна имеют одинаковую длительность"""
    windows = split_into_equal_windows(sample_trades_df, split_n=3)
    
    assert len(windows) == 3
    
    # Вычисляем длительность каждого окна
    durations = []
    for window_info in windows:
        duration = (window_info["window_end"] - window_info["window_start"]).total_seconds()
        durations.append(duration)
    
    # Все длительности должны быть одинаковыми (с небольшой погрешностью из-за округления)
    assert len(set(durations)) == 1 or max(durations) - min(durations) < 1.0


def test_split_into_equal_windows_sum_duration_equals_total(sample_trades_df):
    """Проверяет, что сумма длительностей окон равна общей длительности"""
    windows = split_into_equal_windows(sample_trades_df, split_n=3)
    
    assert len(windows) == 3
    
    # Вычисляем общую длительность
    # Используем min(entry_time) и max(exit_time), как в требованиях
    min_time = sample_trades_df["entry_time"].min()
    max_time = sample_trades_df["exit_time"].max()
    total_duration = (max_time - min_time).total_seconds()
    
    # Вычисляем сумму длительностей окон
    sum_durations = sum(
        (w["window_end"] - w["window_start"]).total_seconds()
        for w in windows
    )
    
    # Сумма должна быть примерно равна общей длительности
    # Допускаем погрешность до 120 секунд (2 минуты) из-за возможной разницы между entry_time и exit_time
    assert abs(sum_durations - total_duration) < 120.0


def test_split_into_equal_windows_empty_window_is_not_survived():
    """Проверяет, что пустое окно считается невыжившим (total_pnl = 0.0)"""
    # Создаём DataFrame с сделками, которые попадут только в первое окно
    df = pd.DataFrame({
        "entry_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-02T10:00:00Z",
        ], utc=True),
        "exit_time": pd.to_datetime([
            "2024-01-01T10:01:00Z",
            "2024-01-02T10:01:00Z",
        ], utc=True),
        "pnl_pct": [0.1, 0.1],
        "reason": ["ladder_tp", "ladder_tp"],
    })
    
    windows = split_into_equal_windows(df, split_n=3)
    
    assert len(windows) == 3
    
    # Первое окно должно иметь сделки
    assert len(windows[0]["trades"]) > 0
    
    # Второе и третье окна могут быть пустыми
    empty_windows = [w for w in windows if len(w["trades"]) == 0]
    
    # Проверяем, что пустые окна имеют total_pnl = 0.0
    for window_info in empty_windows:
        metrics = calculate_window_metrics(window_info["trades"])
        assert metrics["total_pnl"] == 0.0
        assert metrics["trades_count"] == 0


def test_split_into_equal_windows_different_splits_different_metrics(tmp_csv_file):
    """Проверяет, что одна стратегия с разными split даёт разные метрики"""
    from backtester.research.strategy_stability import calculate_stability_metrics
    
    result_2 = aggregate_strategy_windows(tmp_csv_file, split_counts=[2])
    result_3 = aggregate_strategy_windows(tmp_csv_file, split_counts=[3])
    
    # Проверяем, что результаты не пустые
    assert "split_2" in result_2
    assert "split_3" in result_3
    assert len(result_2["split_2"]) > 0
    assert len(result_3["split_3"]) > 0
    
    # Получаем метрики для split_n=2
    # calculate_stability_metrics ожидает Dict[str, List[Dict[str, Any]]]
    strategy_windows_2 = {"split_2": result_2["split_2"]}
    metrics_2 = calculate_stability_metrics(strategy_windows_2, split_n=2)
    
    # Получаем метрики для split_n=3
    strategy_windows_3 = {"split_3": result_3["split_3"]}
    metrics_3 = calculate_stability_metrics(strategy_windows_3, split_n=3)
    
    # windows_total должны быть разными
    assert metrics_2["windows_total"] == 2
    assert metrics_3["windows_total"] == 3
    
    # survival_rate могут быть разными (зависит от распределения сделок)
    # Но мы проверяем, что метрики вообще считаются
    assert "survival_rate" in metrics_2
    assert "survival_rate" in metrics_3


































