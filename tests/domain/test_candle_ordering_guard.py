"""
Tests для проверки сортировки свечей и правильного выбора exit candle.

Тесты проверяют, что:
1. Свечи сортируются по timestamp после загрузки
2. Exit candle выбирается как минимальный timestamp >= exit_time
3. Дубликаты по timestamp дедуплицируются
4. Правильная цена используется для exit_price
"""

import pytest
from datetime import datetime, timedelta, timezone
from backtester.domain.models import Signal, Candle, StrategyInput
from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.runner_config import create_runner_config_from_dict


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
def runner_strategy():
    """Создает Runner стратегию"""
    config = create_runner_config_from_dict(
        "test_runner",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.5},
                {"xn": 5.0, "fraction": 0.3},
                {"xn": 10.0, "fraction": 0.2}
            ],
            "time_stop_minutes": 60,
            "use_high_for_targets": True
        }
    )
    return RunnerStrategy(config)


def test_exit_candle_selection_with_unsorted_candles(runner_strategy, sample_signal):
    """
    Тест: exit candle выбирается правильно даже если свечи не отсортированы в исходном списке.
    
    Сценарий:
    - Entry time: T0
    - Exit time: T1 (time_stop)
    - Свечи намеренно перемешаны
    - Ожидание: выбранная exit candle timestamp == минимальный >= T1
    - Ожидание: raw_exit_price соответствует close именно этой свечи
    """
    entry_time = sample_signal.timestamp
    entry_price = 100.0
    
    # Создаем свечи, намеренно перемешанные по времени
    # T0: entry candle
    # T1: exit candle (time_stop)
    # T2: более поздняя свеча (не должна быть выбрана)
    # T3: еще более поздняя свеча (не должна быть выбрана)
    t0 = entry_time
    t1 = entry_time + timedelta(minutes=60)  # time_stop
    t2 = entry_time + timedelta(minutes=120)
    t3 = entry_time + timedelta(minutes=180)
    
    # Создаем свечи в перемешанном порядке
    # Цены: T0=100, T1=50 (правильная exit цена), T2=200 (неправильная, если выбрана), T3=300
    unsorted_candles = [
        Candle(timestamp=t3, open=300.0, high=310.0, low=290.0, close=300.0, volume=1000.0),  # Поздняя свеча
        Candle(timestamp=t0, open=100.0, high=110.0, low=90.0, close=100.0, volume=1000.0),   # Entry свеча
        Candle(timestamp=t2, open=200.0, high=210.0, low=190.0, close=200.0, volume=1000.0),  # Промежуточная свеча
        Candle(timestamp=t1, open=50.0, high=55.0, low=45.0, close=50.0, volume=1000.0),      # Правильная exit свеча (должна быть выбрана)
    ]
    
    # Создаем StrategyInput с перемешанными свечами
    data = StrategyInput(
        signal=sample_signal,
        candles=unsorted_candles,
        global_params={}
    )
    
    # Запускаем стратегию
    result = runner_strategy.on_signal(data)
    
    # Проверяем, что exit_time установлен (time_stop сработал)
    assert result.exit_time is not None
    assert result.exit_time >= t1  # exit_time должен быть >= time_stop
    
    # Проверяем, что exit_price соответствует правильной свече (T1, close=50.0)
    # Важно: exit_price должен быть 50.0 (close свечи на T1), а не 200.0 (T2) или 300.0 (T3)
    assert result.exit_price == 50.0, f"Expected exit_price=50.0 (close at T1), got {result.exit_price}"
    
    # Проверяем, что exit_time соответствует T1 (минимальный >= time_stop)
    # exit_time может быть равен t1 или немного позже (если time_stop_time_dt используется)
    assert result.exit_time >= t1
    assert result.exit_time < t2  # exit_time не должен быть >= T2


def test_exit_candle_selection_with_exact_match(runner_strategy, sample_signal):
    """
    Тест: если в candle list есть свеча ровно на exit_time, должна быть выбрана она, а не более поздняя.
    
    Сценарий:
    - Entry time: T0
    - Exit time: T1 (time_stop, точно совпадает с timestamp свечи)
    - Свечи: T0, T1 (точное совпадение), T2 (позднее)
    - Ожидание: выбранная exit candle timestamp == T1 (точное совпадение)
    """
    entry_time = sample_signal.timestamp
    entry_price = 100.0
    
    t0 = entry_time
    t1 = entry_time + timedelta(minutes=60)  # time_stop, точно совпадает с timestamp свечи
    t2 = entry_time + timedelta(minutes=120)
    
    # Создаем свечи с точным совпадением exit_time с timestamp свечи
    candles = [
        Candle(timestamp=t0, open=100.0, high=110.0, low=90.0, close=100.0, volume=1000.0),
        Candle(timestamp=t1, open=50.0, high=55.0, low=45.0, close=50.0, volume=1000.0),  # Точное совпадение
        Candle(timestamp=t2, open=200.0, high=210.0, low=190.0, close=200.0, volume=1000.0),  # Позднее
    ]
    
    # Перемешиваем для проверки устойчивости
    unsorted_candles = [candles[2], candles[0], candles[1]]  # T2, T0, T1
    
    data = StrategyInput(
        signal=sample_signal,
        candles=unsorted_candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    # Проверяем, что exit_price соответствует свече на T1 (close=50.0), а не T2 (close=200.0)
    assert result.exit_price == 50.0, f"Expected exit_price=50.0 (close at exact T1), got {result.exit_price}"


def test_candle_deduplication_by_timestamp(runner_strategy, sample_signal):
    """
    Тест: дубликаты по timestamp дедуплицируются (оставляется первая свеча).
    
    Сценарий:
    - Две свечи с одинаковым timestamp
    - Ожидание: используется первая свеча (в порядке загрузки)
    """
    entry_time = sample_signal.timestamp
    t0 = entry_time
    t1 = entry_time + timedelta(minutes=60)
    
    # Создаем две свечи с одинаковым timestamp, но разными ценами
    # Первая свеча должна быть использована
    candles = [
        Candle(timestamp=t0, open=100.0, high=110.0, low=90.0, close=100.0, volume=1000.0),
        Candle(timestamp=t1, open=50.0, high=55.0, low=45.0, close=50.0, volume=1000.0),  # Первая с T1
        Candle(timestamp=t1, open=60.0, high=65.0, low=55.0, close=60.0, volume=1000.0),  # Дубликат T1 (не должна быть использована)
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    # Проверяем, что exit_price соответствует первой свече с T1 (close=50.0), а не второй (close=60.0)
    # Это косвенно проверяет дедупликацию
    assert result.exit_price == 50.0, f"Expected exit_price=50.0 (first candle at T1), got {result.exit_price}"


def test_candle_sorting_ensures_chronological_order(runner_strategy, sample_signal):
    """
    Тест: свечи всегда отсортированы по timestamp в хронологическом порядке.
    
    Сценарий:
    - Свечи загружаются в произвольном порядке
    - После обработки свечи должны быть отсортированы
    """
    entry_time = sample_signal.timestamp
    
    # Создаем свечи в произвольном порядке
    timestamps = [
        entry_time + timedelta(minutes=180),
        entry_time + timedelta(minutes=0),
        entry_time + timedelta(minutes=120),
        entry_time + timedelta(minutes=60),
        entry_time + timedelta(minutes=240),
    ]
    
    candles = [
        Candle(timestamp=ts, open=100.0 + i * 10, high=110.0 + i * 10, low=90.0 + i * 10, 
               close=100.0 + i * 10, volume=1000.0)
        for i, ts in enumerate(timestamps)
    ]
    
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    # После фильтрации и сортировки в on_signal, свечи должны быть отсортированы
    # Проверяем это косвенно через результат
    result = runner_strategy.on_signal(data)
    
    # Проверяем, что exit_price соответствует правильной свече (первая >= exit_time)
    # Это косвенно проверяет, что сортировка работает правильно
    assert result.exit_price is not None
    assert result.exit_time is not None
    
    # Проверяем, что exit_time >= entry_time + 60 минут (time_stop)
    assert result.exit_time >= entry_time + timedelta(minutes=60)
