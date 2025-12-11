"""
Unit tests for RunnerStrategy
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.strategy_base import StrategyConfig
from backtester.domain.models import Signal, Candle, StrategyInput


@pytest.fixture
def runner_strategy():
    """Создает Runner стратегию"""
    config = StrategyConfig(
        name="test_runner",
        type="RUNNER",
        params={}
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
    """Тест базового поведения Runner стратегии"""
    entry_price = 100.0
    exit_price = 110.0
    
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=i),
            open=entry_price + i * 2,
            high=entry_price + i * 2 + 0.5,
            low=entry_price + i * 2 - 0.5,
            close=entry_price + i * 2,
            volume=1000.0
        )
        for i in range(5)
    ]
    candles[-1].close = exit_price  # Последняя свеча с exit_price
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    assert result.exit_price == exit_price
    assert result.reason == "timeout"
    assert result.pnl == pytest.approx(0.10, rel=1e-3)  # 10%


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


def test_runner_strategy_negative_pnl(runner_strategy, sample_signal):
    """Тест с отрицательным PnL"""
    entry_price = 100.0
    exit_price = 90.0
    
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=i),
            open=entry_price - i * 2,
            high=entry_price - i * 2 + 0.5,
            low=entry_price - i * 2 - 0.5,
            close=entry_price - i * 2,
            volume=1000.0
        )
        for i in range(5)
    ]
    candles[-1].close = exit_price
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    assert result.exit_price == exit_price
    assert result.pnl == pytest.approx(-0.10, rel=1e-3)  # -10%

