"""
Защитные тесты: убеждаемся, что reset-флаги не устанавливаются стратегиями.
Reset-политика - это исключительно портфельная функциональность.
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.rr_strategy import RRStrategy
from backtester.domain.rrd_strategy import RRDStrategy
from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.strategy_base import StrategyConfig
from backtester.domain.models import Signal, Candle, StrategyInput


@pytest.fixture
def rr_strategy():
    """Создает RR стратегию"""
    config = StrategyConfig(
        name="test_rr",
        type="RR",
        params={"tp_pct": 10, "sl_pct": 5}
    )
    return RRStrategy(config)


@pytest.fixture
def rrd_strategy():
    """Создает RRD стратегию"""
    config = StrategyConfig(
        name="test_rrd",
        type="RRD",
        params={
            "drawdown_entry_pct": 25,
            "tp_pct": 20,
            "sl_pct": 10,
            "max_price_jump_pct": 10.0,
            "entry_wait_minutes": 60
        }
    )
    return RRDStrategy(config)


@pytest.fixture
def runner_strategy():
    """Создает Runner стратегию"""
    config = StrategyConfig(
        name="test_runner",
        type="Runner",
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


def test_rr_strategy_does_not_set_reset_flags(rr_strategy, sample_signal):
    """Проверяет, что RRStrategy не устанавливает reset-флаги в meta"""
    # Создаём свечи с успешным TP
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
    
    # Проверяем, что стратегия работает (есть вход и выход)
    assert result.entry_price is not None
    assert result.exit_price is not None
    assert result.reason == "tp"
    
    # КРИТИЧНО: проверяем, что reset-флаги НЕ установлены
    assert "triggered_reset" not in result.meta, \
        "RRStrategy не должен устанавливать triggered_reset в meta"
    assert "closed_by_reset" not in result.meta, \
        "RRStrategy не должен устанавливать closed_by_reset в meta"
    
    # Проверяем, что meta существует и может содержать другие поля
    assert isinstance(result.meta, dict)


def test_rrd_strategy_does_not_set_reset_flags(rrd_strategy, sample_signal):
    """Проверяет, что RRDStrategy не устанавливает reset-флаги в meta"""
    # Создаём свечи для RRD стратегии
    first_candle_close = 100.0
    entry_price_target = first_candle_close * 0.75  # 75.0 (25% drawdown)
    tp_price = entry_price_target * 1.21  # TP = 20%
    
    candles = [
        # Первая свеча (базовая)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=1),
            open=first_candle_close,
            high=first_candle_close + 1,
            low=first_candle_close - 1,
            close=first_candle_close,
            volume=1000.0
        ),
        # Промежуточная свеча для плавного перехода
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=2),
            open=first_candle_close,
            high=first_candle_close + 0.5,
            low=90.0,
            close=95.0,
            volume=1000.0
        ),
        # Свеча с просадкой (вход)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=3),
            open=95.0,
            high=95.0,
            low=entry_price_target - 0.5,  # Вход
            close=76.0,
            volume=1000.0
        ),
        # Свеча с TP (выход)
        Candle(
            timestamp=sample_signal.timestamp + timedelta(minutes=4),
            open=entry_price_target,
            high=tp_price + 1,  # TP сработает
            low=entry_price_target - 1,
            close=entry_price_target + 1,
            volume=1000.0
        ),
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = rrd_strategy.on_signal(data)
    
    # Проверяем, что стратегия работает
    assert result.entry_price is not None
    assert result.exit_price is not None
    assert result.reason == "tp"
    
    # КРИТИЧНО: проверяем, что reset-флаги НЕ установлены
    assert "triggered_reset" not in result.meta, \
        "RRDStrategy не должен устанавливать triggered_reset в meta"
    assert "closed_by_reset" not in result.meta, \
        "RRDStrategy не должен устанавливать closed_by_reset in meta"
    
    # Проверяем, что meta существует и может содержать другие поля
    assert isinstance(result.meta, dict)


def test_runner_strategy_does_not_set_reset_flags(runner_strategy, sample_signal):
    """Проверяет, что RunnerStrategy не устанавливает reset-флаги в meta"""
    # Создаём несколько свечей для Runner стратегии
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=100.0 + i * 2,
            high=101.0 + i * 2,
            low=99.0 + i * 2,
            close=100.0 + i * 2,
            volume=2000.0
        )
        for i in range(5)
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    # Проверяем, что стратегия работает
    assert result.entry_price is not None
    assert result.exit_price is not None
    assert result.reason == "timeout"
    
    # КРИТИЧНО: проверяем, что reset-флаги НЕ установлены
    assert "triggered_reset" not in result.meta, \
        "RunnerStrategy не должен устанавливать triggered_reset в meta"
    assert "closed_by_reset" not in result.meta, \
        "RunnerStrategy не должен устанавливать closed_by_reset в meta"
    
    # Проверяем, что meta существует и может содержать другие поля
    assert isinstance(result.meta, dict)


def test_reset_flags_appear_only_in_portfolio_positions():
    """
    Интеграционный тест: проверяет, что reset-флаги появляются только в Position.meta
    после прогонки через PortfolioEngine.
    
    Сценарий:
    - 2-3 сделки с ростом x2
    - PortfolioEngine с runner_reset_enabled=True
    - Ожидаем: у одной позиции triggered_reset=True, у других closed_by_reset=True
    """
    from backtester.domain.portfolio import (
        FeeModel,
        PortfolioConfig,
        PortfolioEngine
    )
    from backtester.domain.models import StrategyOutput
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=True,
        runner_reset_multiple=2.0  # x2
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаём 3 сделки, открывающиеся одновременно
    trades = []
    for i in range(3):
        entry_time = base_time + timedelta(minutes=i * 5)
        exit_time = entry_time + timedelta(hours=2)
        
        # Первая сделка достигает x2 (триггер reset)
        # Остальные - обычные сделки
        if i == 0:
            exit_price = 2.0  # x2 от entry_price=1.0
            pnl = 1.0  # 100% прибыль
        else:
            exit_price = 1.05  # 5% прибыль
            pnl = 0.05
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=exit_price,
            pnl=pnl,
            reason="tp",
            meta={}  # КРИТИЧНО: стратегия не должна устанавливать reset-флаги
        )
        
        trades.append({
            "signal_id": f"reset_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Прогоняем через PortfolioEngine
    portfolio_result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверяем, что все позиции закрыты
    assert len(portfolio_result.positions) == 3
    assert all(p.status == "closed" for p in portfolio_result.positions)
    
    # Находим триггерную позицию (первая)
    trigger_position = next((p for p in portfolio_result.positions if p.signal_id == "reset_signal_1"), None)
    assert trigger_position is not None, "Триггерная позиция должна быть найдена"
    
    # Проверяем, что триггерная позиция имеет метку triggered_reset
    assert trigger_position.meta is not None, "Position.meta не должен быть None"
    assert trigger_position.meta.get("triggered_reset") == True, \
        "Триггерная позиция должна иметь triggered_reset=True в Position.meta"
    assert trigger_position.meta.get("closed_by_reset") != True, \
        "Триггерная позиция не должна иметь closed_by_reset=True"
    
    # Проверяем, что остальные позиции имеют метку closed_by_reset
    other_positions = [p for p in portfolio_result.positions if p.signal_id != "reset_signal_1"]
    assert len(other_positions) == 2, "Должно быть 2 другие позиции"
    
    for pos in other_positions:
        assert pos.meta is not None, f"Position.meta для {pos.signal_id} не должен быть None"
        assert pos.meta.get("closed_by_reset") == True, \
            f"Позиция {pos.signal_id} должна иметь closed_by_reset=True в Position.meta"
        assert pos.meta.get("triggered_reset") != True, \
            f"Позиция {pos.signal_id} не должна иметь triggered_reset=True"







