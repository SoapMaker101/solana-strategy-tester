"""
Unit-тест для динамического размера позиций (dynamic allocation).

Проверяет, что в режиме allocation_mode="dynamic" размер позиции
рассчитывается от текущего баланса, а не от начального.
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_dynamic_allocation_scales_position_sizing():
    """
    Тест: dynamic allocation масштабирует размер позиций на основе текущего баланса.
    
    Сценарий:
    - initial_balance = 10 SOL
    - percent_per_trade = 0.5 (50%)
    - allocation_mode = "dynamic"
    - Две сделки последовательно (без пересечения во времени):
      1. Первая сделка прибыльная → баланс растет
      2. Вторая сделка должна иметь размер позиции > первой
         (т.к. баланс выше после прибыльной сделки)
    
    Проверяемые формулы:
    1. Размер первой позиции = initial_balance × percent_per_trade = 10 × 0.5 = 5 SOL
    2. Баланс после открытия первой = 10 - 5 = 5 SOL
    3. После закрытия прибыльной первой сделки баланс растет
    4. Размер второй позиции = новый_баланс × percent_per_trade > 5 SOL
    
    Проверяем:
    - size_2 > size_1 (размер второй позиции больше первой)
    - Итоговый баланс соответствует ожидаемой логике
    """
    initial_balance = 10.0
    percent_per_trade = 0.5  # 50% на сделку
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",  # КЛЮЧЕВОЕ: размер от текущего баланса
        percent_per_trade=percent_per_trade,
        max_exposure=1.0,  # Не ограничиваем экспозицией
        max_open_positions=10,  # Не ограничиваем количеством позиций
        fee_model=FeeModel()
    )
    
    engine = PortfolioEngine(config)
    
    # Первая сделка: прибыльная
    # Используем достаточно большую прибыль, чтобы баланс заметно вырос
    # после учета комиссий (около 20% прибыль после комиссий)
    first_entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    first_exit_time = first_entry_time + timedelta(hours=2)
    
    # Используем большой raw_pnl (30%), чтобы после комиссий ~20% осталось
    first_strategy_output = StrategyOutput(
        entry_time=first_entry_time,
        entry_price=1.0,
        exit_time=first_exit_time,
        exit_price=1.30,  # 30% прибыль
        pnl=0.30,
        reason="tp"
    )
    
    # Вторая сделка: начинается ПОСЛЕ закрытия первой (последовательно, без overlap)
    second_entry_time = first_exit_time + timedelta(hours=1)  # После закрытия первой
    second_exit_time = second_entry_time + timedelta(hours=2)
    
    second_strategy_output = StrategyOutput(
        entry_time=second_entry_time,
        entry_price=1.0,
        exit_time=second_exit_time,
        exit_price=1.05,  # 5% прибыль
        pnl=0.05,
        reason="tp"
    )
    
    all_results = [
        {
            "signal_id": "dynamic_signal_1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": first_entry_time,
            "result": first_strategy_output
        },
        {
            "signal_id": "dynamic_signal_2",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": second_entry_time,
            "result": second_strategy_output
        }
    ]
    
    # Запускаем симуляцию
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: обе сделки выполнены
    assert result.stats.trades_executed == 2, \
        f"Должны быть выполнены обе сделки, получено: {result.stats.trades_executed}"
    
    assert len(result.positions) == 2, \
        f"Должны быть 2 позиции, получено: {len(result.positions)}"
    
    # 2. Находим позиции по signal_id
    position_1 = next((p for p in result.positions if p.signal_id == "dynamic_signal_1"), None)
    position_2 = next((p for p in result.positions if p.signal_id == "dynamic_signal_2"), None)
    
    assert position_1 is not None, "Первая позиция должна быть найдена"
    assert position_2 is not None, "Вторая позиция должна быть найдена"
    
    # 3. Проверка: размер первой позиции соответствует ожиданию
    expected_size_1 = initial_balance * percent_per_trade  # 10.0 * 0.5 = 5.0 SOL
    assert abs(position_1.size - expected_size_1) < 0.01, \
        f"Размер первой позиции должен быть {expected_size_1} SOL, получено: {position_1.size}"
    
    # 4. РАСЧЕТ: баланс после первой сделки
    # Баланс после открытия первой: 10.0 - 5.0 = 5.0 SOL
    balance_after_open_1 = initial_balance - position_1.size
    
    # Комиссии для первой сделки
    fee_model = config.fee_model
    fee_pct_1 = fee_model.effective_fee_pct(position_1.size)
    net_pnl_pct_1 = first_strategy_output.pnl - fee_pct_1  # 0.30 - ~0.2085 = ~0.0915
    
    # Баланс после закрытия первой: 5.0 + 5.0 + 5.0 * net_pnl_pct_1
    trade_pnl_sol_1 = position_1.size * net_pnl_pct_1
    balance_after_close_1 = balance_after_open_1 + position_1.size + trade_pnl_sol_1
    
    # 5. Проверка: баланс вырос после прибыльной первой сделки
    assert balance_after_close_1 > initial_balance, \
        f"Баланс после прибыльной первой сделки должен вырасти: {balance_after_close_1} > {initial_balance}"
    
    # 6. ОЖИДАЕМЫЙ размер второй позиции (в dynamic mode от текущего баланса)
    expected_size_2 = balance_after_close_1 * percent_per_trade
    
    # 7. ГЛАВНАЯ ПРОВЕРКА: размер второй позиции больше первой
    assert position_2.size > position_1.size, \
        f"Размер второй позиции ({position_2.size}) должен быть больше первой ({position_1.size}) " \
        f"в режиме dynamic allocation после прибыльной сделки"
    
    # 8. Проверка: размер второй позиции соответствует ожиданию (в пределах допусков)
    assert abs(position_2.size - expected_size_2) < 0.01, \
        f"Размер второй позиции должен быть {expected_size_2} SOL (50% от нового баланса " \
        f"{balance_after_close_1}), получено: {position_2.size}"
    
    # 9. Проверка: вторая позиция использует текущий баланс (dynamic), а не начальный
    # Если бы был fixed mode, размер был бы такой же (5.0 SOL)
    # В dynamic mode размер должен быть больше из-за роста баланса
    assert position_2.size > expected_size_1, \
        f"В dynamic mode вторая позиция должна быть больше начального размера " \
        f"({expected_size_1} SOL), получено: {position_2.size}"
    
    # 10. Проверка: итоговый баланс соответствует ожидаемой логике
    # Баланс после открытия второй: balance_after_close_1 - position_2.size
    balance_after_open_2 = balance_after_close_1 - position_2.size
    
    # Комиссии для второй сделки
    fee_pct_2 = fee_model.effective_fee_pct(position_2.size)
    net_pnl_pct_2 = second_strategy_output.pnl - fee_pct_2
    
    # Баланс после закрытия второй: balance_after_open_2 + position_2.size + trade_pnl_sol_2
    trade_pnl_sol_2 = position_2.size * net_pnl_pct_2
    expected_final_balance = balance_after_open_2 + position_2.size + trade_pnl_sol_2
    
    assert abs(result.stats.final_balance_sol - expected_final_balance) < 0.01, \
        f"Итоговый баланс должен быть {expected_final_balance} SOL, получено: {result.stats.final_balance_sol}"
    
    # 11. Дополнительная проверка: позиции отсортированы по времени
    assert position_1.entry_time is not None, "entry_time первой позиции не должен быть None"
    assert position_2.entry_time is not None, "entry_time второй позиции не должен быть None"
    assert position_1.entry_time < position_2.entry_time, \
        "Первая позиция должна быть раньше второй по времени"
    
    # 12. Проверка метаданных: размер позиции сохранен в объекте Position
    assert hasattr(position_1, 'size'), "Position должен иметь поле size"
    assert hasattr(position_2, 'size'), "Position должен иметь поле size"
    assert position_1.size > 0, "Размер первой позиции должен быть положительным"
    assert position_2.size > 0, "Размер второй позиции должен быть положительным"


def test_dynamic_allocation_vs_fixed_allocation():
    """
    Тест: сравнивает dynamic и fixed allocation для одной и той же последовательности сделок.
    
    Проверяет, что в dynamic mode размер второй позиции больше, чем в fixed mode
    (после прибыльной первой сделки).
    """
    initial_balance = 10.0
    percent_per_trade = 0.5
    
    # Тест 1: Dynamic allocation
    dynamic_config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=percent_per_trade,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel()
    )
    
    # Тест 2: Fixed allocation (для сравнения)
    fixed_config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="fixed",
        percent_per_trade=percent_per_trade,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel()
    )
    
    # Те же сделки для обоих тестов
    first_entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    first_exit_time = first_entry_time + timedelta(hours=2)
    second_entry_time = first_exit_time + timedelta(hours=1)
    second_exit_time = second_entry_time + timedelta(hours=2)
    
    all_results = [
        {
            "signal_id": "compare_signal_1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": first_entry_time,
            "result": StrategyOutput(
                entry_time=first_entry_time,
                entry_price=1.0,
                exit_time=first_exit_time,
                exit_price=1.30,
                pnl=0.30,
                reason="tp"
            )
        },
        {
            "signal_id": "compare_signal_2",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": second_entry_time,
            "result": StrategyOutput(
                entry_time=second_entry_time,
                entry_price=1.0,
                exit_time=second_exit_time,
                exit_price=1.05,
                pnl=0.05,
                reason="tp"
            )
        }
    ]
    
    # Запускаем симуляцию для dynamic
    dynamic_result = PortfolioEngine(dynamic_config).simulate(all_results, strategy_name="test_strategy")
    dynamic_position_2 = next((p for p in dynamic_result.positions if p.signal_id == "compare_signal_2"), None)
    assert dynamic_position_2 is not None, "Вторая позиция должна быть найдена в dynamic mode"
    
    # Запускаем симуляцию для fixed
    fixed_result = PortfolioEngine(fixed_config).simulate(all_results, strategy_name="test_strategy")
    fixed_position_2 = next((p for p in fixed_result.positions if p.signal_id == "compare_signal_2"), None)
    assert fixed_position_2 is not None, "Вторая позиция должна быть найдена в fixed mode"
    
    # Проверка: в dynamic mode вторая позиция больше, чем в fixed mode
    # (после прибыльной первой сделки баланс вырос)
    assert dynamic_position_2.size > fixed_position_2.size, \
        f"В dynamic mode вторая позиция ({dynamic_position_2.size}) должна быть больше, " \
        f"чем в fixed mode ({fixed_position_2.size}) после прибыльной сделки"
    
    # В fixed mode размер всегда от начального баланса
    expected_fixed_size = initial_balance * percent_per_trade
    assert abs(fixed_position_2.size - expected_fixed_size) < 0.01, \
        f"В fixed mode размер второй позиции должен быть {expected_fixed_size} SOL (от начального баланса)"






