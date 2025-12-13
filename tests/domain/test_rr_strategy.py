"""
Unit tests for RRStrategy
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.rr_strategy import RRStrategy
from backtester.domain.strategy_base import StrategyConfig
from backtester.domain.models import Signal, Candle, StrategyInput


@pytest.fixture
def rr_strategy():
    """Создает RR стратегию с параметрами TP=10%, SL=5%"""
    config = StrategyConfig(
        name="test_rr",
        type="RR",
        params={"tp_pct": 10, "sl_pct": 5}
    )
    return RRStrategy(config)


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


@pytest.fixture
def sample_candles():
    """Создает тестовые свечи"""
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    base_price = 100.0
    
    candles = []
    for i in range(10):
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=base_price + i * 0.1,
            high=base_price + i * 0.1 + 0.5,
            low=base_price + i * 0.1 - 0.5,
            close=base_price + i * 0.1,
            volume=1000.0
        ))
    
    return candles


def test_rr_strategy_tp_hit(rr_strategy, sample_signal, sample_candles):
    """Тест срабатывания TP"""
    # Модифицируем свечи так, чтобы TP сработал
    # Вход по цене 100, TP = 110, SL = 95
    entry_price = 100.0
    tp_price = 110.0
    
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price,
            high=entry_price + 1,
            low=entry_price - 1,
            close=entry_price,
            volume=1000.0
        ),
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price + 5,
            high=tp_price + 1,  # TP сработал
            low=entry_price + 4,
            close=entry_price + 5,
            volume=1000.0
        ),
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rr_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    assert result.exit_price == pytest.approx(tp_price, rel=1e-6)
    assert result.reason == "tp"
    assert result.pnl == pytest.approx(0.10, rel=1e-3)  # 10%


def test_rr_strategy_sl_hit(rr_strategy, sample_signal):
    """Тест срабатывания SL"""
    entry_price = 100.0
    sl_price = 95.0
    
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price,
            high=entry_price + 1,
            low=entry_price - 1,
            close=entry_price,
            volume=1000.0
        ),
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price - 2,
            high=entry_price - 1,
            low=sl_price - 0.5,  # SL сработал
            close=entry_price - 2,
            volume=1000.0
        ),
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rr_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    assert result.exit_price == sl_price
    assert result.reason == "sl"
    assert result.pnl == pytest.approx(-0.05, rel=1e-3)  # -5%


def test_rr_strategy_timeout(rr_strategy, sample_signal):
    """Тест выхода по таймауту"""
    entry_price = 100.0
    
    # Создаем свечи, где TP и SL не срабатывают
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=i),
            open=entry_price + (i - 1) * 0.01,
            high=entry_price + (i - 1) * 0.01 + 0.1,
            low=entry_price + (i - 1) * 0.01 - 0.1,
            close=entry_price + (i - 1) * 0.01,
            volume=1000.0
        )
        for i in range(1, 6)  # Несколько свечей без TP/SL
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={"max_minutes": 10}  # Короткий таймаут
    )
    
    result = rr_strategy.on_signal(data)
    
    assert result.entry_price == entry_price
    assert result.reason == "timeout"
    assert result.exit_price is not None


def test_rr_strategy_no_entry(rr_strategy, sample_signal):
    """Тест отсутствия входа (нет свечей после сигнала)"""
    # Свечи до сигнала
    candles = [
        Candle(
            timestamp=sample_signal.timestamp - timedelta(minutes=i),
            open=100.0 - i * 0.1,
            high=100.0 - i * 0.1 + 0.5,
            low=100.0 - i * 0.1 - 0.5,
            close=100.0 - i * 0.1,
            volume=1000.0
        )
        for i in range(1, 4)
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rr_strategy.on_signal(data)
    
    assert result.entry_price is None
    assert result.exit_price is None
    assert result.reason == "no_entry"


def test_rr_strategy_empty_candles(rr_strategy, sample_signal):
    """Тест с пустым списком свечей"""
    data = StrategyInput(
        signal=sample_signal,
        candles=[],
        global_params={}
    )
    
    result = rr_strategy.on_signal(data)
    
    assert result.entry_price is None
    assert result.reason == "no_entry"

