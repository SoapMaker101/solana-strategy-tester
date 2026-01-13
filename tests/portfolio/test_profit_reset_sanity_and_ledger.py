"""
Тесты для profit reset sanity checks и ledger.

Проверяет:
- profit_reset_multiple парсится правильно и не спамит reset
- profit_reset_multiple <= 1.0 отключает reset
- reset_id уникален и добавлен в meta
- marker position_id уникален на каждый reset
- anti-spam guard предотвращает множественные reset на одном timestamp
"""
import pytest
from datetime import datetime, timezone, timedelta
import math

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput
from backtester.domain.portfolio_events import PortfolioEventType


def test_profit_reset_multiple_float_parsed_correctly_no_spam():
    """
    Тест: profit_reset_multiple парсится правильно и не спамит reset.
    
    Arrange:
    - initial=10
    - profit_reset_multiple=1.3
    - сценарий без роста до 13 (можно через минимальный synthetic run)
    
    Assert:
    - reset_count == 0
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.01,
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    # Создаем позицию с небольшим profit, чтобы НЕ достигнуть порога 13
    # initial=10, size=0.1, profit=10% → balance = 10 - 0.1 + 0.1*1.1 = 10.01 < 13
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.1,  # 10% profit
        pnl=0.1,
        reason="ladder_tp"
    )
    
    all_results = [{
        "signal_id": "test_signal_1",
        "contract_address": "TESTTOKEN",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что reset НЕ сработал (balance < 13)
    assert result.stats.portfolio_reset_profit_count == 0, \
        f"Reset не должен сработать при balance < 13 (multiple=1.3), получен: {result.stats.portfolio_reset_profit_count}"
    
    # Проверяем что баланс действительно < 13
    assert result.stats.final_balance_sol < 13.0, \
        f"Баланс должен быть < 13, получен: {result.stats.final_balance_sol}"


def test_profit_reset_multiple_le_1_disables_reset():
    """
    Тест: profit_reset_multiple <= 1.0 отключает reset.
    
    Arrange:
    - multiple=1.0 и multiple=0.9
    - сценарий с большим profit (должен триггерить reset при валидном multiple)
    
    Assert:
    - reset не срабатывает вообще (или явно disabled)
    """
    # Тест 1: multiple=1.0
    config_1 = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,  # 50% для быстрого роста
        profit_reset_enabled=True,
        profit_reset_multiple=1.0,  # <= 1.0 - должен быть disabled
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine_1 = PortfolioEngine(config_1)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    # Создаем позицию с большим profit
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=2.0,  # 100% profit
        pnl=1.0,
        reason="ladder_tp"
    )
    
    all_results = [{
        "signal_id": "test_signal_1",
        "contract_address": "TESTTOKEN",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result_1 = engine_1.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что reset НЕ сработал (multiple=1.0 disabled)
    assert result_1.stats.portfolio_reset_profit_count == 0, \
        f"Reset не должен сработать при multiple=1.0 (disabled), получен: {result_1.stats.portfolio_reset_profit_count}"
    
    # Проверяем что resolved_profit_reset_enabled возвращает False
    assert not config_1.resolved_profit_reset_enabled(), \
        "resolved_profit_reset_enabled должен быть False при multiple=1.0"
    
    # Тест 2: multiple=0.9
    config_2 = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,
        profit_reset_enabled=True,
        profit_reset_multiple=0.9,  # < 1.0 - должен быть disabled
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine_2 = PortfolioEngine(config_2)
    result_2 = engine_2.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что reset НЕ сработал (multiple=0.9 disabled)
    assert result_2.stats.portfolio_reset_profit_count == 0, \
        f"Reset не должен сработать при multiple=0.9 (disabled), получен: {result_2.stats.portfolio_reset_profit_count}"
    
    # Проверяем что resolved_profit_reset_enabled возвращает False
    assert not config_2.resolved_profit_reset_enabled(), \
        "resolved_profit_reset_enabled должен быть False при multiple=0.9"


def test_profit_reset_emits_reset_id_and_unique_marker_position_id():
    """
    Тест: reset_id уникален и marker position_id уникален на каждый reset.
    
    Arrange:
    - прогон, где reset срабатывает 2 раза (с открытыми позициями)
    
    Assert:
    - reset_id существует в каждом portfolio_reset_triggered
    - reset_id различаются
    - marker position_id различаются
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,  # 50% для быстрого роста
        max_exposure=1.0,  # Разрешаем 100% exposure для открытия двух позиций одновременно
        profit_reset_enabled=True,
        profit_reset_multiple=1.2,  # Снижаем порог до 1.2x (12 SOL) чтобы гарантировать срабатывание
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    # Первая сделка: trigger первый reset, закрывается раньше
    entry_time_1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time_1 = entry_time_1 + timedelta(hours=1)
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=1.0,
        exit_time=exit_time_1,
        exit_price=2.5,  # 150% profit для гарантированного превышения порога
        pnl=1.5,
        reason="ladder_tp"
    )
    
    # Вторая сделка: открывается одновременно, остается открытой для первого reset
    entry_time_2 = entry_time_1
    exit_time_2 = entry_time_1 + timedelta(hours=3)
    strategy_output_2 = StrategyOutput(
        entry_time=entry_time_2,
        entry_price=1.0,
        exit_time=exit_time_2,
        exit_price=1.5,
        pnl=0.5,
        reason="ladder_tp"
    )
    
    # Третья сделка: открывается после первого reset, остается открытой для второго reset
    entry_time_3 = exit_time_1 + timedelta(hours=1)  # После первого reset
    exit_time_3 = entry_time_3 + timedelta(hours=3)  # Закрывается позже (после второго reset)
    strategy_output_3 = StrategyOutput(
        entry_time=entry_time_3,
        entry_price=1.0,
        exit_time=exit_time_3,
        exit_price=1.5,
        pnl=0.5,
        reason="ladder_tp"
    )
    
    # Четвертая сделка: trigger второй reset, закрывается раньше третьей
    # После первого reset balance = 20.0, порог = 20.0 * 1.2 = 24.0
    # Нужно чтобы balance после четвертой сделки >= 24.0
    entry_time_4 = exit_time_1 + timedelta(hours=1)  # После первого reset (14:00)
    exit_time_4 = entry_time_4 + timedelta(hours=1)  # Закрывается раньше третьей (15:00)
    strategy_output_4 = StrategyOutput(
        entry_time=entry_time_4,
        entry_price=1.0,
        exit_time=exit_time_4,
        exit_price=3.0,  # 200% profit для гарантированного превышения порога 24.0
        pnl=2.0,
        reason="ladder_tp"
    )
    
    all_results = [
        {
            "signal_id": "test_signal_1",
            "contract_address": "TESTTOKEN1",
            "strategy": "test_strategy",
            "timestamp": entry_time_1,
            "result": strategy_output_1
        },
        {
            "signal_id": "test_signal_2",
            "contract_address": "TESTTOKEN2",
            "strategy": "test_strategy",
            "timestamp": entry_time_2,
            "result": strategy_output_2
        },
        {
            "signal_id": "test_signal_3",
            "contract_address": "TESTTOKEN3",
            "strategy": "test_strategy",
            "timestamp": entry_time_3,
            "result": strategy_output_3
        },
        {
            "signal_id": "test_signal_4",
            "contract_address": "TESTTOKEN4",
            "strategy": "test_strategy",
            "timestamp": entry_time_4,
            "result": strategy_output_4
        }
    ]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что было 2 reset'а
    assert result.stats.portfolio_reset_profit_count == 2, (
        f"Должно быть 2 reset'а (после первой и третьей сделок, когда есть открытые позиции), "
        f"получено: {result.stats.portfolio_reset_profit_count}"
    )
    
    # Находим reset события
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) == 2, (
        f"Должно быть 2 portfolio_reset_triggered события, получено: {len(reset_events)}"
    )
    
    # Проверяем что reset_id существует и различаются
    reset_id_1 = reset_events[0].meta.get("reset_id")
    reset_id_2 = reset_events[1].meta.get("reset_id")
    assert reset_id_1 is not None, "Первый reset должен иметь reset_id"
    assert reset_id_2 is not None, "Второй reset должен иметь reset_id"
    assert reset_id_1 != reset_id_2, (
        f"reset_id должны различаться: {reset_id_1} vs {reset_id_2}"
    )
    
    # Проверяем что position_id различаются (marker для каждого reset уникален)
    position_id_1 = reset_events[0].position_id
    position_id_2 = reset_events[1].position_id
    assert position_id_1 != position_id_2, (
        f"position_id marker'ов должны различаться: {position_id_1} vs {position_id_2}"
    )
    
    # Проверяем что marker позиции имеют reset_id в meta
    marker_positions = [
        p for p in result.positions
        if p.meta and p.meta.get("marker", False)
    ]
    assert len(marker_positions) >= 2, (
        f"Должно быть хотя бы 2 marker позиции, получено: {len(marker_positions)}"
    )
    
    marker_reset_ids = [
        p.meta.get("reset_id") for p in marker_positions
        if p.meta.get("reset_id") is not None
    ]
    assert len(marker_reset_ids) >= 2, (
        f"Должно быть хотя бы 2 marker с reset_id, получено: {len(marker_reset_ids)}"
    )
    assert len(set(marker_reset_ids)) >= 2, \
        "Marker reset_id должны быть уникальными"


def test_profit_reset_guard_prevents_multiple_resets_same_timestamp():
    """
    Тест: anti-spam guard предотвращает множественные reset на одном timestamp.
    
    Arrange:
    - создать сценарий где balance >= threshold и есть открытые позиции
    
    Assert:
    - reset-count увеличился максимум на 1 на каждом timestamp
    - нет спама (сотни reset'ов)
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,  # 50% для быстрого роста
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем сценарий с открытой позицией для trigger reset
    entry_time_1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time_1 = entry_time_1 + timedelta(hours=1)
    
    # Первая сделка: большая прибыль, закрывается раньше
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=1.0,
        exit_time=exit_time_1,
        exit_price=2.0,  # 100% profit
        pnl=1.0,
        reason="ladder_tp"
    )
    
    # Вторая сделка: остается открытой для trigger reset
    entry_time_2 = entry_time_1
    exit_time_2 = entry_time_1 + timedelta(hours=3)
    
    strategy_output_2 = StrategyOutput(
        entry_time=entry_time_2,
        entry_price=1.0,
        exit_time=exit_time_2,
        exit_price=1.5,
        pnl=0.5,
        reason="ladder_tp"
    )
    
    all_results = [
        {
            "signal_id": "test_signal_1",
            "contract_address": "TESTTOKEN1",
            "strategy": "test_strategy",
            "timestamp": entry_time_1,
            "result": strategy_output_1
        },
        {
            "signal_id": "test_signal_2",
            "contract_address": "TESTTOKEN2",
            "strategy": "test_strategy",
            "timestamp": entry_time_2,
            "result": strategy_output_2
        }
    ]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что количество reset'ов разумное (не спам сотнями)
    assert result.stats.portfolio_reset_profit_count <= 1, (
        f"Количество reset'ов должно быть <= 1 (не спам), "
        f"получено: {result.stats.portfolio_reset_profit_count}"
    )
    
    # Проверяем что количество portfolio_reset_triggered событий разумное
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) <= 1, (
        f"Количество portfolio_reset_triggered событий должно быть <= 1, "
        f"получено: {len(reset_events)}"
    )
    
    # Проверяем что все reset события имеют разное время (если их больше 1, что не должно быть)
    if reset_events:
        reset_timestamps = [e.timestamp for e in reset_events]
        assert len(set(reset_timestamps)) == len(reset_timestamps), \
            "Все reset события должны иметь разное время"
        
        # Проверяем что нет reset'ов с closed_positions_count=0
        for reset_event in reset_events:
            closed_count = reset_event.meta.get("closed_positions_count", 0)
            assert closed_count > 0, (
                f"Reset событие не должно иметь closed_positions_count=0 "
                f"(Guard B должен предотвратить reset без позиций), "
                f"reset_id={reset_event.meta.get('reset_id')}"
            )


def test_profit_reset_config_c_scenario_no_spam():
    """
    Тест: имитирует сценарий конфига C - убыточный результат не должен триггерить reset.
    
    Сценарий:
    - initial=10, profit_reset_multiple=1.3
    - multiple убыточных сделок, итоговый balance ~ 1.24 (убыток)
    
    Assert:
    - reset_count == 0 (reset не должен сработать при убытке)
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed_then_dynamic_after_profit_reset",
        percent_per_trade=0.01,  # 1% как в конфиге C
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем несколько убыточных сделок
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    all_results = []
    
    # Несколько убыточных сделок, которые уменьшают баланс
    for i in range(5):
        entry_time = base_time + timedelta(hours=i*2)
        exit_time = entry_time + timedelta(hours=1)
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.8,  # -20% убыток
            pnl=-0.2,
            reason="stop_loss"
        )
        all_results.append({
            "signal_id": f"test_signal_{i}",
            "contract_address": f"TESTTOKEN{i}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что баланс действительно уменьшился (убыток)
    assert result.stats.final_balance_sol < 10.0, \
        f"Баланс должен быть < 10 (убыток), получен: {result.stats.final_balance_sol}"
    
    # Проверяем что reset НЕ сработал (убыточный результат не должен триггерить reset)
    # Порог = 10 * 1.3 = 13, баланс < 13, поэтому reset не должен сработать
    assert result.stats.portfolio_reset_profit_count == 0, (
        f"Reset не должен сработать при убыточном результате (balance < 13), "
        f"получен: {result.stats.portfolio_reset_profit_count} reset'ов"
    )
    
    # Проверяем что нет portfolio_reset_triggered событий
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) == 0, \
        f"Не должно быть portfolio_reset_triggered событий при убытке, получено: {len(reset_events)}"


def test_profit_reset_multiple_float_type():
    """
    Тест: profit_reset_multiple правильно парсится как float.
    
    Проверяет что:
    - profit_reset_multiple может быть int (конвертируется в float)
    - profit_reset_multiple может быть float
    - profit_reset_multiple валидируется (<= 1.0 disabled)
    """
    import math
    
    # Тест 1: int конвертируется в float
    config_1 = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_enabled=True,
        profit_reset_multiple=2,  # int
    )
    multiple_1 = config_1.resolved_profit_reset_multiple()
    assert multiple_1 == 2.0, \
        f"profit_reset_multiple=2 (int) должен быть 2.0 (float), получен: {multiple_1}"
    assert isinstance(multiple_1, float), \
        f"profit_reset_multiple должен быть float, получен: {type(multiple_1)}"
    
    # Тест 2: float остается float
    config_2 = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,  # float
    )
    multiple_2 = config_2.resolved_profit_reset_multiple()
    assert multiple_2 == 1.3, \
        f"profit_reset_multiple=1.3 должен быть 1.3, получен: {multiple_2}"
    assert isinstance(multiple_2, float), \
        f"profit_reset_multiple должен быть float, получен: {type(multiple_2)}"
    
    # Тест 3: <= 1.0 disabled
    config_3 = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_enabled=True,
        profit_reset_multiple=1.0,  # <= 1.0
    )
    multiple_3 = config_3.resolved_profit_reset_multiple()
    assert multiple_3 is None, \
        f"profit_reset_multiple=1.0 должен вернуть None (disabled), получен: {multiple_3}"
    assert not config_3.resolved_profit_reset_enabled(), \
        "resolved_profit_reset_enabled должен быть False при multiple=1.0"
    
    # Тест 4: невалидное значение (inf, nan) disabled
    config_4 = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_enabled=True,
        profit_reset_multiple=float('inf'),  # inf
    )
    multiple_4 = config_4.resolved_profit_reset_multiple()
    assert multiple_4 is None, \
        f"profit_reset_multiple=inf должен вернуть None (disabled), получен: {multiple_4}"
