"""
Unit tests for RunnerStrategy blueprint functionality (Этап 1)
"""
import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.runner_config import create_runner_config_from_dict
from backtester.domain.models import Signal, Candle, StrategyInput
from backtester.domain.strategy_trade_blueprint import StrategyTradeBlueprint


@pytest.fixture
def runner_strategy():
    """Создает Runner стратегию с несколькими уровнями для теста blueprint"""
    config = create_runner_config_from_dict(
        "test_runner",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.3},
                {"xn": 5.0, "fraction": 0.4},
                {"xn": 10.0, "fraction": 0.3},
            ],
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
        narrative="test signal",
        extra={"total_supply": 1_000_000_000.0}  # Для вычисления mcap_proxy
    )


def test_strategy_blueprint_generated_basic(runner_strategy, sample_signal):
    """
    Тест базовой генерации blueprint (Этап 1).
    
    Проверки согласно PIPE изменений.md:
    - возвращается blueprint
    - entry_time и entry_price_raw валидны
    - partial_exits отсортированы по времени
    - realized_multiple = Σ(fraction * xn)
    """
    entry_price = 100.0
    
    # Создаем свечи с постепенным ростом, достигающим уровней 2x, 5x, 10x
    # Уровень 2x достигается на минуте 1 (high = 200)
    # Уровень 5x достигается на минуте 2 (high = 500)
    # Уровень 10x достигается на минуте 3 (high = 1000)
    candles = []
    base_time = sample_signal.timestamp
    
    # Минута 0: вход по close = 100
    candles.append(Candle(
        timestamp=base_time + timedelta(minutes=0),
        open=entry_price,
        high=entry_price + 5,
        low=entry_price - 5,
        close=entry_price,
        volume=1000.0
    ))
    
    # Минута 1: достигаем 2x (high = 200), закрываем 30%
    candles.append(Candle(
        timestamp=base_time + timedelta(minutes=1),
        open=150.0,
        high=200.0,  # Достигаем уровня 2x
        low=140.0,
        close=180.0,
        volume=1000.0
    ))
    
    # Минута 2: достигаем 5x (high = 500), закрываем 40%
    candles.append(Candle(
        timestamp=base_time + timedelta(minutes=2),
        open=300.0,
        high=500.0,  # Достигаем уровня 5x
        low=280.0,
        close=450.0,
        volume=1000.0
    ))
    
    # Минута 3: достигаем 10x (high = 1000), закрываем оставшиеся 30%
    candles.append(Candle(
        timestamp=base_time + timedelta(minutes=3),
        open=700.0,
        high=1000.0,  # Достигаем уровня 10x
        low=680.0,
        close=950.0,
        volume=1000.0
    ))
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    # Вызываем on_signal_blueprint
    blueprint = runner_strategy.on_signal_blueprint(data)
    
    # Проверка 1: возвращается StrategyTradeBlueprint
    assert isinstance(blueprint, StrategyTradeBlueprint)
    
    # Проверка 2: entry_time не None
    assert blueprint.entry_time is not None
    assert isinstance(blueprint.entry_time, datetime)
    
    # Проверка 3: entry_price_raw > 0
    assert blueprint.entry_price_raw > 0
    assert blueprint.entry_price_raw == pytest.approx(entry_price, rel=1e-6)
    
    # Проверка 4: partial_exits отсортированы по времени
    assert len(blueprint.partial_exits) == 3  # Должно быть 3 частичных выхода
    
    # Проверяем, что timestamps идут в возрастающем порядке
    for i in range(len(blueprint.partial_exits) - 1):
        current_time = blueprint.partial_exits[i].timestamp
        next_time = blueprint.partial_exits[i + 1].timestamp
        assert current_time <= next_time, f"partial_exits[{i}].timestamp ({current_time}) > partial_exits[{i+1}].timestamp ({next_time})"
    
    # Проверяем, что уровни соответствуют ожидаемым (2x, 5x, 10x) и в правильном порядке
    assert blueprint.partial_exits[0].xn == pytest.approx(2.0, rel=1e-6)
    assert blueprint.partial_exits[0].fraction == pytest.approx(0.3, rel=1e-6)
    assert blueprint.partial_exits[1].xn == pytest.approx(5.0, rel=1e-6)
    assert blueprint.partial_exits[1].fraction == pytest.approx(0.4, rel=1e-6)
    assert blueprint.partial_exits[2].xn == pytest.approx(10.0, rel=1e-6)
    assert blueprint.partial_exits[2].fraction == pytest.approx(0.3, rel=1e-6)
    
    # Проверка 5: realized_multiple = Σ(fraction * xn) с допуском
    expected_realized_multiple = (
        0.3 * 2.0 +   # 30% на уровне 2x
        0.4 * 5.0 +   # 40% на уровне 5x
        0.3 * 10.0    # 30% на уровне 10x
    )
    # expected = 0.6 + 2.0 + 3.0 = 5.6
    
    assert blueprint.realized_multiple == pytest.approx(expected_realized_multiple, rel=1e-6), \
        f"realized_multiple ({blueprint.realized_multiple}) != expected ({expected_realized_multiple})"
    
    # Дополнительные проверки для полноты
    assert blueprint.signal_id == sample_signal.id
    assert blueprint.strategy_id == "test_runner"
    assert blueprint.contract_address == sample_signal.contract_address
    assert blueprint.reason == "all_levels_hit"
    assert blueprint.final_exit is not None  # Позиция полностью закрыта
    assert blueprint.max_xn_reached == pytest.approx(10.0, rel=1e-6)  # Максимальный достигнутый уровень

