"""
Unit tests for RunnerStrategy
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.runner_config import create_runner_config_from_dict
from backtester.domain.models import Signal, Candle, StrategyInput


@pytest.fixture
def runner_strategy():
    """Создает Runner стратегию"""
    config = create_runner_config_from_dict(
        "test_runner",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.5}
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True
        }
    )
    return RunnerStrategy(config)


@pytest.fixture
def sample_signal():
    """Создает тестовый сигнал"""
    return Signal(
        id="test1",
        contract_address="TESTTOKEN",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        narrative="test signal"
    )


def test_runner_strategy_basic(runner_strategy, sample_signal):
    """Тест базового поведения Runner стратегии с достижением уровня 2x"""
    entry_price = 100.0
    
    # Свечи: цена растет до 2x (200)
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=i),
            open=entry_price + i * 50,
            high=entry_price + i * 50 + 10,
            low=entry_price + i * 50 - 10,
            close=entry_price + i * 50,
            volume=1000.0
        )
        for i in range(5)
    ]
    # Вторая свеча достигает уровня 2x (high = 200)
    candles[1].high = 200.0
    candles[1].close = 190.0
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    assert result.reason == "ladder_tp"  # Все уровни достигнуты = take profit
    assert "realized_multiple" in result.meta
    assert "levels_hit" in result.meta
    assert "fractions_exited" in result.meta
    assert "time_stop_triggered" in result.meta
    assert result.meta["time_stop_triggered"] == False


def test_runner_strategy_empty_candles(runner_strategy, sample_signal):
    """Тест с пустым списком свечей"""
    data = StrategyInput(
        signal=sample_signal,
        candles=[],
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    assert result.entry_price is None
    assert result.exit_price is None
    assert result.reason == "no_entry"


def test_runner_strategy_single_candle(runner_strategy, sample_signal):
    """Тест с одной свечой"""
    price = 100.0
    
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=1000.0
        )
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    assert result.entry_price == price
    assert result.exit_price == price
    assert result.pnl == pytest.approx(0.0, rel=1e-3)


def test_runner_strategy_no_levels_hit(runner_strategy, sample_signal):
    """Тест когда уровни не достигнуты - позиция закрывается по последней свече"""
    entry_price = 100.0
    
    # Свечи: цена не достигает уровня 2x (максимум 150)
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=i),
            open=entry_price + i * 10,
            high=entry_price + i * 10 + 5,
            low=entry_price + i * 10 - 5,
            close=entry_price + i * 10,
            volume=1000.0
        )
        for i in range(5)
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    # Позиция закрывается по последней свече (close = 140)
    # realized_multiple = 140 / 100 = 1.4
    assert result.meta["realized_multiple"] == pytest.approx(1.4, rel=1e-3)
    assert len(result.meta["levels_hit"]) == 0  # Уровни не достигнуты
