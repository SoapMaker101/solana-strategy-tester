"""
Unit tests for RunnerLadderEngine
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone

from backtester.domain.runner_ladder import RunnerLadderEngine, RunnerTradeResult
from backtester.domain.runner_config import RunnerConfig, RunnerTakeProfitLevel, create_runner_config_from_dict


@pytest.fixture
def base_time():
    """Базовое время для тестов"""
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def entry_price():
    """Цена входа для тестов"""
    return 100.0


def create_candles_df(base_time: datetime, prices: list[dict]) -> pd.DataFrame:
    """
    Создает DataFrame со свечами.
    
    Args:
        base_time: Базовое время
        prices: Список словарей с ключами: minutes_offset, open, high, low, close, volume
    
    Returns:
        DataFrame со свечами
    """
    candles_data = []
    for price_info in prices:
        candle_time = base_time + timedelta(minutes=price_info["minutes_offset"])
        candles_data.append({
            "timestamp": candle_time,
            "open": price_info["open"],
            "high": price_info["high"],
            "low": price_info["low"],
            "close": price_info["close"],
            "volume": price_info.get("volume", 1000.0)
        })
    
    return pd.DataFrame(candles_data)


def test_single_level_hit(base_time, entry_price):
    """Тест: достижение x2 → частичное закрытие"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    
    # Свечи: цена растет до 2x (200)
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": 1, "open": 150, "high": 200, "low": 145, "close": 190},  # Достигли 2x
        {"minutes_offset": 2, "open": 190, "high": 210, "low": 185, "close": 200},
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки
    assert result.entry_time == base_time
    assert result.entry_price == entry_price
    assert 2.0 in result.levels_hit
    assert result.fractions_exited[2.0] == pytest.approx(0.4, rel=1e-3)
    assert result.reason == "all_levels_hit"
    # 40% закрыто на 2x, 60% осталось и закрыто на последней свече (200/100 = 2x)
    # realized_multiple = 0.4 * 2.0 + 0.6 * 2.0 = 2.0
    assert result.realized_multiple == pytest.approx(2.0, rel=1e-3)


def test_two_levels_hit(base_time, entry_price):
    """Тест: достижение x2 и x5 → два закрытия"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4},
                {"xn": 5.0, "fraction": 0.4}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    
    # Свечи: цена растет до 2x, затем до 5x
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": 1, "open": 150, "high": 200, "low": 145, "close": 190},  # Достигли 2x
        {"minutes_offset": 2, "open": 190, "high": 300, "low": 185, "close": 280},
        {"minutes_offset": 3, "open": 280, "high": 500, "low": 275, "close": 480},  # Достигли 5x
        {"minutes_offset": 4, "open": 480, "high": 550, "low": 475, "close": 500},
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки
    assert 2.0 in result.levels_hit
    assert 5.0 in result.levels_hit
    assert result.fractions_exited[2.0] == pytest.approx(0.4, rel=1e-3)
    assert result.fractions_exited[5.0] == pytest.approx(0.4, rel=1e-3)
    # 40% закрыто на 2x, 40% закрыто на 5x, 20% осталось и закрыто на последней свече (500/100 = 5x)
    # realized_multiple = 0.4 * 2.0 + 0.4 * 5.0 + 0.2 * 5.0 = 0.8 + 2.0 + 1.0 = 3.8
    assert result.realized_multiple == pytest.approx(3.8, rel=1e-3)
    assert result.reason == "all_levels_hit"


def test_time_stop_closes_remainder(base_time, entry_price):
    """Тест: time_stop закрывает остаток"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4}
            ],
            "time_stop_minutes": 5,  # 5 минут
            "use_high_for_targets": True
        }
    )
    
    # Свечи: цена растет до 2x, но не достигает полного закрытия до time_stop
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": 1, "open": 150, "high": 200, "low": 145, "close": 190},  # Достигли 2x
        {"minutes_offset": 2, "open": 190, "high": 210, "low": 185, "close": 200},
        {"minutes_offset": 3, "open": 200, "high": 220, "low": 195, "close": 210},
        {"minutes_offset": 4, "open": 210, "high": 230, "low": 205, "close": 220},
        {"minutes_offset": 5, "open": 220, "high": 240, "low": 215, "close": 230},  # time_stop срабатывает здесь
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки
    assert result.reason == "time_stop"
    assert result.exit_time == base_time + timedelta(minutes=5)
    # 40% закрыто на 2x, 60% закрыто по time_stop на цене 230 (2.3x)
    # realized_multiple = 0.4 * 2.0 + 0.6 * 2.3 = 0.8 + 1.38 = 2.18
    assert result.realized_multiple == pytest.approx(2.18, rel=1e-3)


def test_fractions_sum_validation(base_time, entry_price):
    """Тест: fractions суммарно <= 1.0"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4},
                {"xn": 5.0, "fraction": 0.4},
                {"xn": 10.0, "fraction": 0.2}  # Сумма = 1.0
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    
    # Свечи: цена растет до всех уровней
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": 1, "open": 150, "high": 200, "low": 145, "close": 190},  # 2x
        {"minutes_offset": 2, "open": 190, "high": 500, "low": 185, "close": 480},  # 5x
        {"minutes_offset": 3, "open": 480, "high": 1000, "low": 475, "close": 950},  # 10x
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки
    total_fraction = sum(result.fractions_exited.values())
    assert total_fraction <= 1.0 + 1e-6  # Учитываем погрешности float
    assert result.reason == "all_levels_hit"
    # Все доли закрыты: 0.4 * 2.0 + 0.4 * 5.0 + 0.2 * 10.0 = 0.8 + 2.0 + 2.0 = 4.8
    assert result.realized_multiple == pytest.approx(4.8, rel=1e-3)


def test_levels_sorted_correctly(base_time, entry_price):
    """Тест: уровни сортируются и работают корректно"""
    # Создаем конфиг с уровнями в неправильном порядке
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 10.0, "fraction": 0.2},  # Самый высокий
                {"xn": 2.0, "fraction": 0.4},   # Самый низкий
                {"xn": 5.0, "fraction": 0.4}   # Средний
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    
    # Свечи: цена растет последовательно
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": 1, "open": 150, "high": 200, "low": 145, "close": 190},  # 2x
        {"minutes_offset": 2, "open": 190, "high": 500, "low": 185, "close": 480},  # 5x
        {"minutes_offset": 3, "open": 480, "high": 1000, "low": 475, "close": 950},  # 10x
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки: уровни должны быть достигнуты в правильном порядке (2x, 5x, 10x)
    assert 2.0 in result.levels_hit
    assert 5.0 in result.levels_hit
    assert 10.0 in result.levels_hit
    
    # Проверяем порядок времени достижения
    assert result.levels_hit[2.0] < result.levels_hit[5.0]
    assert result.levels_hit[5.0] < result.levels_hit[10.0]
    
    # Проверяем доли
    assert result.fractions_exited[2.0] == pytest.approx(0.4, rel=1e-3)
    assert result.fractions_exited[5.0] == pytest.approx(0.4, rel=1e-3)
    assert result.fractions_exited[10.0] == pytest.approx(0.2, rel=1e-3)


def test_use_close_instead_of_high(base_time, entry_price):
    """Тест: использование close вместо high для триггера"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": False  # Используем close
        }
    )
    
    # Свечи: high достигает 2x, но close не достигает
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 200, "low": 95, "close": 150},  # high = 2x, но close < 2x
        {"minutes_offset": 1, "open": 150, "high": 210, "low": 145, "close": 200},  # close достигает 2x
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки: уровень должен быть достигнут на второй свече (когда close >= 2x)
    assert 2.0 in result.levels_hit
    assert result.levels_hit[2.0] == base_time + timedelta(minutes=1)


def test_exit_on_first_tp(base_time, entry_price):
    """Тест: exit_on_first_tp закрывает всю позицию на первом TP"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4},
                {"xn": 5.0, "fraction": 0.4}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True,
            "exit_on_first_tp": True  # Закрываем всю позицию на первом TP
        }
    )
    
    # Свечи: цена растет до 2x
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": 0, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": 1, "open": 150, "high": 200, "low": 145, "close": 190},  # Достигли 2x
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки: вся позиция должна быть закрыта на первом уровне
    assert 2.0 in result.levels_hit
    assert result.fractions_exited[2.0] == pytest.approx(1.0, rel=1e-3)  # Вся позиция
    assert 5.0 not in result.levels_hit  # Второй уровень не достигнут
    assert result.realized_multiple == pytest.approx(2.0, rel=1e-3)
    assert result.reason == "all_levels_hit"


def test_no_data(base_time, entry_price):
    """Тест: обработка отсутствия данных"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    
    # Пустой DataFrame
    candles_df = pd.DataFrame()
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки
    assert result.reason == "no_data"
    assert result.realized_multiple == pytest.approx(1.0, rel=1e-3)
    assert result.realized_pnl_pct == pytest.approx(0.0, rel=1e-3)


def test_no_candles_after_entry(base_time, entry_price):
    """Тест: нет свечей после времени входа"""
    config = create_runner_config_from_dict(
        "test",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    
    # Свечи до времени входа
    candles_df = create_candles_df(base_time, [
        {"minutes_offset": -2, "open": 100, "high": 150, "low": 95, "close": 150},
        {"minutes_offset": -1, "open": 150, "high": 200, "low": 145, "close": 190},
    ])
    
    result = RunnerLadderEngine.simulate(
        entry_time=base_time,
        entry_price=entry_price,
        candles_df=candles_df,
        config=config
    )
    
    # Проверки
    assert result.reason == "no_data"
    assert result.realized_multiple == pytest.approx(1.0, rel=1e-3)



















