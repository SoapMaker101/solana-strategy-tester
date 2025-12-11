"""
Unit tests for RR utilities
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.rr_utils import (
    check_candle_quality,
    calculate_volatility_around_entry,
    calculate_signal_to_entry_delay,
)
from backtester.domain.models import Candle


def test_check_candle_quality_valid():
    """Тест проверки качества валидной свечи"""
    candle = Candle(
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0
    )
    
    is_valid, error_msg = check_candle_quality(candle)
    assert is_valid is True
    assert error_msg is None


def test_check_candle_quality_zero_volume():
    """Тест проверки свечи с нулевым объемом"""
    candle = Candle(
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=0.0
    )
    
    is_valid, error_msg = check_candle_quality(candle)
    assert is_valid is False
    assert "volume" in error_msg.lower()


def test_check_candle_quality_high_less_than_low():
    """Тест проверки свечи с high < low"""
    candle = Candle(
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=100.0,
        high=99.0,  # high < low
        low=100.0,
        close=100.5,
        volume=1000.0
    )
    
    is_valid, error_msg = check_candle_quality(candle)
    assert is_valid is False
    assert "high" in error_msg.lower() and "low" in error_msg.lower()


def test_check_candle_quality_price_jump():
    """Тест проверки скачка цены"""
    previous_candle = Candle(
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1000.0
    )
    
    # Свеча с большим скачком цены (1% при лимите 0.5%)
    candle = Candle(
        timestamp=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        open=101.0,  # Скачок 1% от close предыдущей свечи
        high=102.0,
        low=100.5,
        close=101.5,
        volume=1000.0
    )
    
    is_valid, error_msg = check_candle_quality(candle, previous_candle, max_price_jump_pct=0.5)
    assert is_valid is False
    assert "jump" in error_msg.lower()


def test_calculate_volatility_around_entry():
    """Тест расчета волатильности вокруг входа"""
    entry_candle = Candle(
        timestamp=datetime(2024, 1, 1, 12, 30, 0, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1000.0
    )
    
    candles = [
        Candle(
            timestamp=entry_candle.timestamp + timedelta(minutes=i - 30),
            open=100.0 + i * 0.1,
            high=100.0 + i * 0.1 + 0.5,
            low=100.0 + i * 0.1 - 0.5,
            close=100.0 + i * 0.1,
            volume=1000.0
        )
        for i in range(61)  # 60 минут до и после
    ]
    
    volatility = calculate_volatility_around_entry(candles, entry_candle, window_minutes=30)
    assert volatility >= 0.0


def test_calculate_signal_to_entry_delay():
    """Тест расчета задержки между сигналом и входом"""
    signal_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    entry_time = datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    
    delay = calculate_signal_to_entry_delay(signal_time, entry_time)
    assert delay == pytest.approx(5.0, rel=1e-3)


def test_calculate_signal_to_entry_delay_none():
    """Тест расчета задержки при отсутствии входа"""
    signal_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    delay = calculate_signal_to_entry_delay(signal_time, None)
    assert delay == 0.0

