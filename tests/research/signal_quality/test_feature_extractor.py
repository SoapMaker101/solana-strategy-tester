# tests/research/signal_quality/test_feature_extractor.py
"""
Тесты для модуля feature_extractor.
"""

import pytest
from datetime import datetime, timedelta, timezone

from backtester.domain.models import Candle
from backtester.research.signal_quality.feature_extractor import (
    compute_market_cap_proxy,
    compute_max_xn,
    get_entry_price,
)


class TestMarketCapProxy:
    """Тесты для compute_market_cap_proxy."""
    
    def test_market_cap_proxy_basic(self):
        """Тест базового вычисления market cap proxy."""
        entry_price = 0.0001
        supply = 1_000_000_000
        result = compute_market_cap_proxy(entry_price, supply)
        assert result == 100000.0
    
    def test_market_cap_proxy_custom_supply(self):
        """Тест с кастомным supply."""
        entry_price = 0.001
        supply = 500_000_000
        result = compute_market_cap_proxy(entry_price, supply)
        assert result == 500000.0
    
    def test_market_cap_proxy_zero_price(self):
        """Тест с нулевой ценой."""
        result = compute_market_cap_proxy(0.0)
        assert result == 0.0
    
    def test_market_cap_proxy_none_price(self):
        """Тест с None ценой."""
        result = compute_market_cap_proxy(None)
        assert result == 0.0


class TestEntryPrice:
    """Тесты для get_entry_price."""
    
    def test_entry_price_t_plus_1m(self):
        """Тест получения entry_price в режиме t+1m."""
        signal_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Создаём свечи: одна до сигнала, одна через 1 минуту, одна через 2 минуты
        candles = [
            Candle(
                timestamp=signal_ts - timedelta(minutes=1),
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.0,
                volume=100.0
            ),
            Candle(
                timestamp=signal_ts + timedelta(minutes=1),
                open=1.0,
                high=1.2,
                low=0.95,
                close=1.05,
                volume=150.0
            ),
            Candle(
                timestamp=signal_ts + timedelta(minutes=2),
                open=1.05,
                high=1.3,
                low=1.0,
                close=1.1,
                volume=200.0
            ),
        ]
        
        result = get_entry_price(candles, signal_ts, mode="t+1m")
        assert result == 1.05  # close цена свечи через 1 минуту
    
    def test_entry_price_t_mode(self):
        """Тест получения entry_price в режиме t."""
        signal_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        candles = [
            Candle(
                timestamp=signal_ts,
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.02,
                volume=100.0
            ),
        ]
        
        result = get_entry_price(candles, signal_ts, mode="t")
        assert result == 1.02
    
    def test_entry_price_fallback(self):
        """Тест fallback с t+1m на t если нет свечи через 1 минуту."""
        signal_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Только свеча на момент сигнала
        candles = [
            Candle(
                timestamp=signal_ts,
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.02,
                volume=100.0
            ),
        ]
        
        result = get_entry_price(candles, signal_ts, mode="t+1m")
        assert result == 1.02  # fallback на свечу на момент сигнала
    
    def test_entry_price_no_candles(self):
        """Тест с пустым списком свечей."""
        signal_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        candles = []
        
        result = get_entry_price(candles, signal_ts, mode="t+1m")
        assert result is None
    
    def test_entry_price_no_match(self):
        """Тест когда нет подходящих свечей."""
        signal_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Все свечи до сигнала
        candles = [
            Candle(
                timestamp=signal_ts - timedelta(minutes=5),
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.0,
                volume=100.0
            ),
        ]
        
        result = get_entry_price(candles, signal_ts, mode="t+1m")
        assert result is None


class TestMaxXN:
    """Тесты для compute_max_xn."""
    
    def test_max_xn_basic(self):
        """Тест базового вычисления max_xn."""
        entry_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry_price = 1.0
        horizon_minutes = 60
        
        # Создаём свечи: цена растёт до 3x
        candles = [
            Candle(
                timestamp=entry_time + timedelta(minutes=10),
                open=1.0,
                high=3.0,  # 3x
                low=0.9,
                close=2.5,
                volume=100.0
            ),
            Candle(
                timestamp=entry_time + timedelta(minutes=20),
                open=2.5,
                high=2.8,
                low=2.0,
                close=2.2,
                volume=150.0
            ),
        ]
        
        max_xn, time_to_levels = compute_max_xn(
            candles, entry_price, entry_time, horizon_minutes, use_high=True
        )
        
        assert max_xn == 3.0
        assert time_to_levels["time_to_3x_minutes"] == 10
    
    def test_max_xn_with_levels(self):
        """Тест вычисления времени до достижения уровней."""
        entry_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry_price = 1.0
        horizon_minutes = 60
        
        candles = [
            Candle(
                timestamp=entry_time + timedelta(minutes=5),
                open=1.0,
                high=2.1,  # 2x достигнут
                low=0.9,
                close=2.0,
                volume=100.0
            ),
            Candle(
                timestamp=entry_time + timedelta(minutes=10),
                open=2.0,
                high=3.1,  # 3x достигнут
                low=1.8,
                close=3.0,
                volume=150.0
            ),
            Candle(
                timestamp=entry_time + timedelta(minutes=15),
                open=3.0,
                high=5.2,  # 5x достигнут
                low=2.5,
                close=5.0,
                volume=200.0
            ),
        ]
        
        max_xn, time_to_levels = compute_max_xn(
            candles, entry_price, entry_time, horizon_minutes, use_high=True
        )
        
        assert max_xn == 5.2
        assert time_to_levels["time_to_2x_minutes"] == 5
        assert time_to_levels["time_to_3x_minutes"] == 10
        assert time_to_levels["time_to_5x_minutes"] == 15
        assert time_to_levels["time_to_7x_minutes"] is None  # не достигнут
        assert time_to_levels["time_to_10x_minutes"] is None  # не достигнут
    
    def test_max_xn_use_close(self):
        """Тест с use_high=False (используем close)."""
        entry_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry_price = 1.0
        horizon_minutes = 60
        
        candles = [
            Candle(
                timestamp=entry_time + timedelta(minutes=10),
                open=1.0,
                high=3.0,  # high = 3x, но close = 2x
                low=0.9,
                close=2.0,
                volume=100.0
            ),
        ]
        
        max_xn, _ = compute_max_xn(
            candles, entry_price, entry_time, horizon_minutes, use_high=False
        )
        
        assert max_xn == 2.0  # используется close, а не high
    
    def test_max_xn_empty_candles(self):
        """Тест с пустым списком свечей."""
        entry_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry_price = 1.0
        horizon_minutes = 60
        
        candles = []
        max_xn, time_to_levels = compute_max_xn(
            candles, entry_price, entry_time, horizon_minutes, use_high=True
        )
        
        assert max_xn == 0.0
        assert time_to_levels == {}
    
    def test_max_xn_outside_horizon(self):
        """Тест когда свечи вне горизонта."""
        entry_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry_price = 1.0
        horizon_minutes = 10
        
        # Свеча через 20 минут (вне горизонта)
        candles = [
            Candle(
                timestamp=entry_time + timedelta(minutes=20),
                open=1.0,
                high=3.0,
                low=0.9,
                close=2.0,
                volume=100.0
            ),
        ]
        
        max_xn, time_to_levels = compute_max_xn(
            candles, entry_price, entry_time, horizon_minutes, use_high=True
        )
        
        assert max_xn == 0.0  # свеча вне горизонта
        assert time_to_levels == {}






























