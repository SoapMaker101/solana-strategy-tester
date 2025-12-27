"""
Tests for XN analyzer
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone

from backtester.domain.models import Signal, Candle
from backtester.research.xn_analysis.xn_models import XNAnalysisConfig
from backtester.research.xn_analysis.xn_analyzer import XNAnalyzer


@pytest.fixture
def sample_signal():
    """Create a test signal"""
    return Signal(
        id="test1",
        contract_address="TESTTOKEN",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        narrative="test signal"
    )


@pytest.fixture
def basic_config():
    """Create basic XN analysis config"""
    return XNAnalysisConfig(
        holding_days=90,
        xn_levels=[2, 3, 5, 10],
        price_timeframe="1m",
        price_source="high",
    )


def candles_to_dataframe(candles):
    """Helper to convert candles to DataFrame"""
    rows = []
    for candle in candles:
        rows.append({
            "timestamp": candle.timestamp,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def test_xn_exactly_2x_reached(sample_signal, basic_config):
    """Test 1: If price exactly doubles (2x), x2 should be reached"""
    entry_price = 100.0
    
    # Create candles: entry candle + candles with HIGH exactly at 2x
    candles = [
        # Entry candle (first after signal)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price,
            high=entry_price * 1.1,
            low=entry_price * 0.9,
            close=entry_price,  # entry_price from close
            volume=1000.0
        ),
        # Second candle: HIGH exactly at 2x
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price * 1.5,
            high=entry_price * 2.0,  # Exactly 2x
            low=entry_price * 1.5,
            close=entry_price * 1.9,
            volume=1000.0
        ),
    ]
    
    candles_df = candles_to_dataframe(candles)
    result = XNAnalyzer.analyze_signal(sample_signal, candles_df, basic_config)
    
    assert result is not None
    assert result.entry_price == entry_price
    assert result.max_xn == pytest.approx(2.0, rel=1e-3)
    assert 2.0 in result.time_to_xn
    assert result.time_to_xn[2.0] is not None
    # Entry_time is first candle timestamp (minute 1), XN reached at minute 2, so time = 1 minute
    assert result.time_to_xn[2.0] == 1


def test_xn_reached_at_10_minutes(sample_signal, basic_config):
    """Test 2: If HIGH crosses XN at 10th minute (from entry), time_to_xn should be correct"""
    entry_price = 100.0
    target_xn = 3.0
    target_price = entry_price * target_xn  # 300.0
    
    candles = [
        # Entry candle (first after signal)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price,
            high=entry_price * 1.1,
            low=entry_price * 0.9,
            close=entry_price,
            volume=1000.0
        ),
    ]
    
    # Add candles before reaching target (HIGH < target)
    for i in range(2, 10):
        candles.append(
            Candle(
                timestamp=sample_signal.timestamp + timedelta(minutes=i),
                open=entry_price * 1.5,
                high=target_price - 1.0,  # Just below target
                low=entry_price * 1.5,
                close=entry_price * 1.5,
                volume=1000.0
            )
        )
    
    # 10th minute candle: HIGH crosses target
    candles.append(
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=10),
            open=target_price - 1.0,
            high=target_price,  # Exactly at target (3x)
            low=target_price - 1.0,
            close=target_price - 0.5,
            volume=1000.0
        )
    )
    
    candles_df = candles_to_dataframe(candles)
    result = XNAnalyzer.analyze_signal(sample_signal, candles_df, basic_config)
    
    assert result is not None
    assert target_xn in result.time_to_xn
    assert result.time_to_xn[target_xn] is not None
    # Entry_time is first candle timestamp (minute 1), XN reached at minute 10, so time = 9 minutes
    assert result.time_to_xn[target_xn] == 9


def test_xn_not_reached_is_none(sample_signal, basic_config):
    """Test 3: If XN not reached, time_to_xn should be None"""
    entry_price = 100.0
    unreachable_xn = 10.0  # Very high XN that won't be reached
    
    candles = [
        # Entry candle
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price,
            high=entry_price * 1.5,
            low=entry_price * 0.9,
            close=entry_price,
            volume=1000.0
        ),
        # Some candles with HIGH that never reaches 10x
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price * 2.0,
            high=entry_price * 3.0,  # Only 3x, not 10x
            low=entry_price * 2.0,
            close=entry_price * 2.5,
            volume=1000.0
        ),
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=3),
            open=entry_price * 2.5,
            high=entry_price * 4.0,  # Only 4x, not 10x
            low=entry_price * 2.5,
            close=entry_price * 3.0,
            volume=1000.0
        ),
    ]
    
    candles_df = candles_to_dataframe(candles)
    result = XNAnalyzer.analyze_signal(sample_signal, candles_df, basic_config)
    
    assert result is not None
    assert unreachable_xn in result.time_to_xn
    assert result.time_to_xn[unreachable_xn] is None  # Not reached


def test_max_xn_calculation(sample_signal, basic_config):
    """Test 4: max_xn should be calculated correctly"""
    entry_price = 100.0
    max_high_price = entry_price * 7.5  # Maximum HIGH is 7.5x
    
    candles = [
        # Entry candle
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price,
            high=entry_price * 1.1,
            low=entry_price * 0.9,
            close=entry_price,
            volume=1000.0
        ),
        # Candle with maximum HIGH
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=5),
            open=entry_price * 5.0,
            high=max_high_price,  # Maximum HIGH: 7.5x
            low=entry_price * 5.0,
            close=entry_price * 7.0,
            volume=1000.0
        ),
        # Later candle with lower HIGH
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=10),
            open=entry_price * 6.0,
            high=entry_price * 6.5,  # Lower than previous max
            low=entry_price * 6.0,
            close=entry_price * 6.3,
            volume=1000.0
        ),
    ]
    
    candles_df = candles_to_dataframe(candles)
    result = XNAnalyzer.analyze_signal(sample_signal, candles_df, basic_config)
    
    assert result is not None
    assert result.max_price == pytest.approx(max_high_price, rel=1e-3)
    assert result.max_xn == pytest.approx(7.5, rel=1e-3)  # max_price / entry_price
    # Should have reached levels 2, 3, 5 (but not 10)
    assert result.time_to_xn[2.0] is not None
    assert result.time_to_xn[3.0] is not None
    assert result.time_to_xn[5.0] is not None
    assert result.time_to_xn[10.0] is None  # Not reached


def test_entry_price_from_first_candle_after_signal(sample_signal, basic_config):
    """Test that entry_price is taken from close of first candle AFTER signal timestamp"""
    entry_price = 150.0
    
    candles = [
        # Candle before signal (should be ignored)
        Candle(
            timestamp=sample_signal.timestamp - timedelta(minutes=1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=100.0,
            volume=1000.0
        ),
        # First candle after signal (this should be used for entry_price)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=entry_price * 0.95,
            high=entry_price * 1.05,
            low=entry_price * 0.95,
            close=entry_price,  # This should be entry_price
            volume=1000.0
        ),
    ]
    
    candles_df = candles_to_dataframe(candles)
    result = XNAnalyzer.analyze_signal(sample_signal, candles_df, basic_config)
    
    assert result is not None
    assert result.entry_price == entry_price
    assert result.entry_time == sample_signal.timestamp + timedelta(minutes=1)


def test_no_candles_after_signal_returns_none(sample_signal, basic_config):
    """Test that if no candles exist after signal timestamp, returns None"""
    candles = [
        # Only candle before signal
        Candle(
            timestamp=sample_signal.timestamp - timedelta(minutes=1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=100.0,
            volume=1000.0
        ),
    ]
    
    candles_df = candles_to_dataframe(candles)
    result = XNAnalyzer.analyze_signal(sample_signal, candles_df, basic_config)
    
    assert result is None



















