"""
Unit tests for trade_features module
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.trade_features import (
    get_total_supply,
    calc_mcap_proxy,
    calc_window_features,
    calc_trade_mcap_features,
)
from backtester.domain.models import Signal, Candle
from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.runner_config import RunnerConfig, RunnerTakeProfitLevel
from backtester.domain.models import StrategyInput


def test_total_supply_fallback_default():
    """Signal.extra пустой → supply=1e9"""
    signal = Signal(
        id="test1",
        contract_address="TEST",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        narrative="test",
        extra={}
    )
    supply = get_total_supply(signal)
    assert supply == 1_000_000_000.0


def test_total_supply_from_signal_extra():
    """Signal.extra["total_supply"]=123 → используется 123"""
    signal = Signal(
        id="test1",
        contract_address="TEST",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        narrative="test",
        extra={"total_supply": 123}
    )
    supply = get_total_supply(signal)
    assert supply == 123.0


def test_mcap_proxy_calculation():
    """price=2, supply=10 → mcap=20"""
    mcap = calc_mcap_proxy(price=2.0, supply=10.0)
    assert mcap == 20.0


def test_window_features_volume_sum():
    """Собрать 10 свечей по минутам, entry_time в конце, проверить суммы volume за 5/15 минут."""
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаём 10 свечей с разными объёмами
    candles = []
    for i in range(10):
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=100.0 + i,
            high=100.0 + i + 0.5,
            low=100.0 + i - 0.5,
            close=100.0 + i,
            volume=100.0 * (i + 1)  # Объёмы: 100, 200, 300, ..., 1000
        ))
    
    entry_time = base_time + timedelta(minutes=9)  # Вход на последней свече
    entry_price = 109.0
    
    features = calc_window_features(
        candles=candles,
        entry_time=entry_time,
        entry_price=entry_price,
        windows_min=(5, 15, 60)
    )
    
    # Проверяем, что окна берутся ДО entry_time (строго < entry_time)
    # Для 5 минут: должны быть свечи с индексами 4,5,6,7,8 (5 свечей до входа)
    # Объёмы: 500, 600, 700, 800, 900 = 3500
    expected_vol_sum_5m = sum(100.0 * (i + 1) for i in range(4, 9))
    assert features["vol_sum_5m"] == expected_vol_sum_5m
    
    # Для 15 минут: должны быть свечи с индексами 0..8 (9 свечей)
    # Объёмы: 100+200+...+900 = 4500
    expected_vol_sum_15m = sum(100.0 * (i + 1) for i in range(9))
    assert features["vol_sum_15m"] == expected_vol_sum_15m
    
    # Проверяем наличие всех ключей
    assert "vol_sum_5m" in features
    assert "vol_sum_15m" in features
    assert "vol_sum_60m" in features
    assert "range_pct_5m" in features
    assert "range_pct_15m" in features
    assert "range_pct_60m" in features
    assert "volat_5m" in features
    assert "volat_15m" in features
    assert "volat_60m" in features


def test_window_features_no_candles_before_entry():
    """Тест, когда нет свечей до входа"""
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Свечи только после entry_time
    candles = [
        Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1000.0
        )
        for i in range(5, 10)
    ]
    
    entry_time = base_time  # Вход раньше всех свечей
    entry_price = 100.0
    
    features = calc_window_features(
        candles=candles,
        entry_time=entry_time,
        entry_price=entry_price,
        windows_min=(5, 15)
    )
    
    # Все фичи должны быть 0
    assert features["vol_sum_5m"] == 0.0
    assert features["vol_sum_15m"] == 0.0
    assert features["range_pct_5m"] == 0.0
    assert features["range_pct_15m"] == 0.0
    assert features["volat_5m"] == 0.0
    assert features["volat_15m"] == 0.0


def test_calc_trade_mcap_features():
    """Тест расчёта mcap features"""
    features = calc_trade_mcap_features(
        entry_price=2.0,
        exit_price=3.0,
        total_supply=10.0
    )
    
    assert features["total_supply_used"] == 10.0
    assert features["entry_mcap_proxy"] == 20.0  # 2 * 10
    assert features["exit_mcap_proxy"] == 30.0   # 3 * 10
    assert features["mcap_change_pct"] == 0.5    # (30-20)/20 = 0.5


def test_calc_trade_mcap_features_no_exit():
    """Тест mcap features без exit_price"""
    features = calc_trade_mcap_features(
        entry_price=2.0,
        exit_price=None,
        total_supply=10.0
    )
    
    assert features["total_supply_used"] == 10.0
    assert features["entry_mcap_proxy"] == 20.0
    assert "exit_mcap_proxy" not in features
    assert "mcap_change_pct" not in features




def test_runner_strategy_includes_features_in_meta():
    """Проверка наличия features в meta для RunnerStrategy"""
    config = RunnerConfig(
        name="test_runner",
        type="RUNNER",
        params={},
        take_profit_levels=[
            RunnerTakeProfitLevel(xn=2.0, fraction=0.5),
            RunnerTakeProfitLevel(xn=5.0, fraction=0.3),
            RunnerTakeProfitLevel(xn=10.0, fraction=0.2),
        ],
        time_stop_minutes=None,
        use_high_for_targets=True,
        exit_on_first_tp=False,
        allow_partial_fills=True
    )
    strategy = RunnerStrategy(config)
    
    signal = Signal(
        id="test1",
        contract_address="TESTTOKEN",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        narrative="test signal",
        extra={"total_supply": 500000.0}
    )
    
    # Создаём несколько свечей
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    candles = []
    for i in range(5):
        candles.append(Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.0 + i,
            volume=2000.0
        ))
    
    data = StrategyInput(
        signal=signal,
        candles=candles,
        global_params={}
    )
    
    result = strategy.on_signal(data)
    
    # Проверяем, что вошли и вышли
    assert result.entry_price is not None
    assert result.exit_price is not None
    
    # Проверяем наличие ключей в meta
    assert "total_supply_used" in result.meta
    assert result.meta["total_supply_used"] == 500000.0
    assert "entry_mcap_proxy" in result.meta
    assert "exit_mcap_proxy" in result.meta
    assert "mcap_change_pct" in result.meta
    assert "vol_sum_5m" in result.meta
    assert "vol_sum_15m" in result.meta
    assert "vol_sum_60m" in result.meta






