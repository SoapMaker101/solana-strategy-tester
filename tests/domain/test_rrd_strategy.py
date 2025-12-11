"""
Unit tests for RRDStrategy
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.rrd_strategy import RRDStrategy
from backtester.domain.strategy_base import StrategyConfig
from backtester.domain.models import Signal, Candle, StrategyInput


@pytest.fixture
def rrd_strategy():
    """Создает RRD стратегию с параметрами drawdown_entry=25%, TP=20%, SL=10%"""
    config = StrategyConfig(
        name="test_rrd",
        type="RRD",
        params={
            "drawdown_entry_pct": 25,
            "tp_pct": 20,
            "sl_pct": 10,
            "max_minutes": 1000,
            "entry_wait_minutes": 360  # 6 часов
        }
    )
    return RRDStrategy(config)


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


def test_rrd_strategy_tp_after_entry(rrd_strategy, sample_signal):
    """✅ Тест: Успешный вход и выход по TP"""
    # Первая свеча после сигнала (базовая цена)
    first_candle_close = 100.0
    drawdown_entry_pct = 0.25  # 25%
    entry_price_target = first_candle_close * (1 - drawdown_entry_pct)  # 75.0
    tp_pct = 0.20  # 20%
    tp_price = entry_price_target * (1 + tp_pct)  # 90.0
    
    candles = [
        # Первая свеча после сигнала (базовая)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=first_candle_close,
            high=first_candle_close + 1,
            low=first_candle_close - 1,
            close=first_candle_close,
            volume=1000.0
        ),
        # Свеча с просадкой до entry_price_target (вход)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price_target + 1,
            high=entry_price_target + 2,
            low=entry_price_target - 0.5,  # low <= entry_price_target → вход
            close=entry_price_target + 1,
            volume=1000.0
        ),
        # Свеча с TP (выход)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=3),
            open=entry_price_target + 5,
            high=tp_price + 1,  # high >= tp_price → TP сработал
            low=entry_price_target + 4,
            close=entry_price_target + 5,
            volume=1000.0
        ),
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rrd_strategy.on_signal(data)
    
    assert result.entry_price == pytest.approx(entry_price_target, rel=1e-3)
    assert result.exit_price == pytest.approx(tp_price, rel=1e-3)
    assert result.reason == "tp"
    assert result.pnl == pytest.approx(tp_pct, rel=1e-3)  # 20%
    assert result.entry_time == candles[1].timestamp
    assert result.exit_time == candles[2].timestamp


def test_rrd_strategy_sl_after_entry(rrd_strategy, sample_signal):
    """❌ Тест: Успешный вход и выход по SL"""
    first_candle_close = 100.0
    drawdown_entry_pct = 0.25
    entry_price_target = first_candle_close * (1 - drawdown_entry_pct)  # 75.0
    sl_pct = 0.10  # 10%
    sl_price = entry_price_target * (1 - sl_pct)  # 67.5
    
    candles = [
        # Первая свеча после сигнала
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=first_candle_close,
            high=first_candle_close + 1,
            low=first_candle_close - 1,
            close=first_candle_close,
            volume=1000.0
        ),
        # Вход по drawdown
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price_target + 1,
            high=entry_price_target + 2,
            low=entry_price_target - 0.5,  # low <= entry_price_target → вход
            close=entry_price_target + 1,
            volume=1000.0
        ),
        # Свеча с SL (выход)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=3),
            open=entry_price_target - 2,
            high=entry_price_target - 1,
            low=sl_price - 0.5,  # low <= sl_price → SL сработал
            close=entry_price_target - 2,
            volume=1000.0
        ),
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rrd_strategy.on_signal(data)
    
    assert result.entry_price == pytest.approx(entry_price_target, rel=1e-3)
    assert result.exit_price == pytest.approx(sl_price, rel=1e-3)
    assert result.reason == "sl"
    assert result.pnl == pytest.approx(-sl_pct, rel=1e-3)  # -10%


def test_rrd_strategy_timeout_after_entry(rrd_strategy, sample_signal):
    """⏱ Тест: Вход был, TP/SL не было, сработал timeout"""
    first_candle_close = 100.0
    drawdown_entry_pct = 0.25
    entry_price_target = first_candle_close * (1 - drawdown_entry_pct)  # 75.0
    
    candles = [
        # Первая свеча после сигнала
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=first_candle_close,
            high=first_candle_close + 1,
            low=first_candle_close - 1,
            close=first_candle_close,
            volume=1000.0
        ),
        # Вход по drawdown
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=entry_price_target + 1,
            high=entry_price_target + 2,
            low=entry_price_target - 0.5,  # вход
            close=entry_price_target + 1,
            volume=1000.0
        ),
        # Несколько свечей без TP/SL (цена между TP и SL)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=3),
            open=entry_price_target + 2,
            high=entry_price_target + 3,
            low=entry_price_target + 1,
            close=entry_price_target + 2,
            volume=1000.0
        ),
    ]
    
    # Используем короткий max_minutes для теста таймаута
    config = StrategyConfig(
        name="test_rrd_timeout",
        type="RRD",
        params={
            "drawdown_entry_pct": 25,
            "tp_pct": 20,
            "sl_pct": 10,
            "max_minutes": 5,  # Короткий таймаут
            "entry_wait_minutes": 360
        }
    )
    strategy = RRDStrategy(config)
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = strategy.on_signal(data)
    
    assert result.entry_price == pytest.approx(entry_price_target, rel=1e-3)
    assert result.reason == "timeout"
    assert result.exit_price is not None
    assert result.exit_price == pytest.approx(candles[-1].close, rel=1e-3)


def test_rrd_strategy_no_entry_drawdown_not_reached(rrd_strategy, sample_signal):
    """🚫 Тест: Не было входа в течение окна entry_wait_minutes"""
    first_candle_close = 100.0
    drawdown_entry_pct = 0.25
    entry_price_target = first_candle_close * (1 - drawdown_entry_pct)  # 75.0
    
    # Свечи с небольшой просадкой, но не доходящие до entry_price_target
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=i),
            open=first_candle_close - i * 0.1,  # Небольшая просадка
            high=first_candle_close - i * 0.1 + 0.5,
            low=first_candle_close - i * 0.1 - 0.5,  # Но low всегда > entry_price_target
            close=first_candle_close - i * 0.1,
            volume=1000.0
        )
        for i in range(1, 6)
    ]
    
    # Используем короткий entry_wait_minutes для теста
    config = StrategyConfig(
        name="test_rrd_no_entry",
        type="RRD",
        params={
            "drawdown_entry_pct": 25,
            "tp_pct": 20,
            "sl_pct": 10,
            "max_minutes": 1000,
            "entry_wait_minutes": 10  # Короткое окно ожидания
        }
    )
    strategy = RRDStrategy(config)
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = strategy.on_signal(data)
    
    assert result.entry_price is None
    assert result.exit_price is None
    assert result.reason == "no_entry"
    assert "entry_price_target" in result.meta


def test_rrd_strategy_no_candles_after_signal(rrd_strategy, sample_signal):
    """🕳 Тест: Нет свечей после сигнала"""
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
    
    result = rrd_strategy.on_signal(data)
    
    assert result.entry_price is None
    assert result.exit_price is None
    assert result.reason == "no_entry"
    assert "no candles after signal" in result.meta.get("detail", "")


def test_rrd_strategy_entry_wait_minutes_default(rrd_strategy, sample_signal):
    """Тест: Проверка значения по умолчанию для entry_wait_minutes"""
    # Создаем стратегию без указания entry_wait_minutes
    config = StrategyConfig(
        name="test_rrd_default",
        type="RRD",
        params={
            "drawdown_entry_pct": 25,
            "tp_pct": 20,
            "sl_pct": 10,
            "max_minutes": 1000,
            # entry_wait_minutes не указан
        }
    )
    strategy = RRDStrategy(config)
    
    # Должно быть 360 минут (6 часов) по умолчанию
    assert strategy.entry_wait_minutes == 360


def test_rrd_strategy_entry_price_target_calculation(rrd_strategy, sample_signal):
    """Тест: Проверка правильности расчета entry_price_target"""
    first_candle_close = 100.0
    drawdown_entry_pct = 0.25
    expected_entry_price = first_candle_close * (1 - drawdown_entry_pct)  # 75.0
    
    candles = [
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=first_candle_close,
            high=first_candle_close + 1,
            low=first_candle_close - 1,
            close=first_candle_close,
            volume=1000.0
        ),
        # Свеча с просадкой до entry_price_target
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=expected_entry_price + 1,
            high=expected_entry_price + 2,
            low=expected_entry_price - 0.5,  # вход
            close=expected_entry_price + 1,
            volume=1000.0
        ),
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rrd_strategy.on_signal(data)
    
    # Проверяем, что entry_price равен entry_price_target
    assert result.entry_price == pytest.approx(expected_entry_price, rel=1e-3)
    assert result.meta.get("entry_price_target") == pytest.approx(expected_entry_price, rel=1e-3)
