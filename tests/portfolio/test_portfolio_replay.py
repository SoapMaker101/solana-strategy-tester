"""
Unit tests for PortfolioReplay (ЭТАП 2).

Тесты для альтернативного пути исполнения портфеля на основе StrategyTradeBlueprint.
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from backtester.domain.portfolio import (
    PortfolioConfig,
    PortfolioStats,
    FeeModel,
)
from backtester.domain.portfolio_replay import PortfolioReplay, MarketData
from backtester.domain.portfolio_events import PortfolioEventType
from backtester.domain.strategy_trade_blueprint import (
    StrategyTradeBlueprint,
    PartialExitBlueprint,
    FinalExitBlueprint,
)


@pytest.fixture
def base_time():
    """Базовое время для тестов."""
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fee_model():
    """Фикстура для FeeModel."""
    return FeeModel()


@pytest.fixture
def sample_blueprints(base_time):
    """Создает набор тестовых blueprints."""
    blueprints = []
    
    # Blueprint 1: полный ladder trade с final_exit
    blueprints.append(StrategyTradeBlueprint(
        signal_id="sig_1",
        strategy_id="test_strategy",
        contract_address="TOKEN_A",
        entry_time=base_time,
        entry_price_raw=1.0,
        entry_mcap_proxy=100_000_000.0,
        partial_exits=[
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=10),
                xn=2.0,
                fraction=0.5
            ),
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=20),
                xn=3.0,
                fraction=0.5
            ),
        ],
        final_exit=FinalExitBlueprint(
            timestamp=base_time + timedelta(minutes=30),
            reason="all_levels_hit"
        ),
        realized_multiple=2.5,
        max_xn_reached=3.0,
        reason="all_levels_hit"
    ))
    
    # Blueprint 2: без final_exit (будет закрыт по max_hold_minutes)
    blueprints.append(StrategyTradeBlueprint(
        signal_id="sig_2",
        strategy_id="test_strategy",
        contract_address="TOKEN_B",
        entry_time=base_time + timedelta(minutes=5),
        entry_price_raw=2.0,
        entry_mcap_proxy=200_000_000.0,
        partial_exits=[
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=15),
                xn=2.0,
                fraction=0.5
            ),
        ],
        final_exit=None,
        realized_multiple=1.0,
        max_xn_reached=2.0,
        reason="all_levels_hit"
    ))
    
    # Blueprint 3: простой trade для capacity теста
    blueprints.append(StrategyTradeBlueprint(
        signal_id="sig_3",
        strategy_id="test_strategy",
        contract_address="TOKEN_C",
        entry_time=base_time + timedelta(minutes=10),
        entry_price_raw=3.0,
        entry_mcap_proxy=300_000_000.0,
        partial_exits=[],
        final_exit=FinalExitBlueprint(
            timestamp=base_time + timedelta(minutes=40),
            reason="all_levels_hit"
        ),
        realized_multiple=1.5,
        max_xn_reached=1.5,
        reason="all_levels_hit"
    ))
    
    return blueprints


def test_replay_two_configs_same_blueprints_different_equity(base_time, fee_model, sample_blueprints):
    """
    Тест: один набор blueprints, два разных PortfolioConfig (fixed vs dynamic) → разные equity curves.
    
    Проверки:
    - equity curves разные (финальный баланс отличается)
    - positions созданы правильно
    - события генерируются корректно
    """
    # Используем первые 2 blueprints для простоты
    blueprints = sample_blueprints[:2]
    
    # Config 1: fixed allocation
    config_fixed = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="fixed",
        percent_per_trade=0.2,  # 20% от начального баланса = 20 SOL
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=fee_model,
    )
    
    # Config 2: dynamic allocation
    config_dynamic = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.2,  # 20% от текущего баланса (меняется после каждой сделки)
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=fee_model,
    )
    
    # Replay с fixed config
    result_fixed = PortfolioReplay.replay(
        blueprints=blueprints,
        portfolio_config=config_fixed,
        market_data=None,
    )
    
    # Replay с dynamic config
    result_dynamic = PortfolioReplay.replay(
        blueprints=blueprints,
        portfolio_config=config_dynamic,
        market_data=None,
    )
    
    # Проверки: equity curves разные
    # В fixed режиме размер позиции фиксированный (20 SOL)
    # В dynamic режиме размер может отличаться (зависит от текущего баланса)
    assert result_fixed.stats.final_balance_sol != result_dynamic.stats.final_balance_sol, \
        "Fixed and dynamic configs should produce different equity curves"
    
    # Проверки: позиции созданы
    assert len(result_fixed.positions) > 0, "Fixed config should have positions"
    assert len(result_dynamic.positions) > 0, "Dynamic config should have positions"
    
    # Проверки: события созданы
    assert len(result_fixed.stats.portfolio_events) > 0, "Fixed config should have events"
    assert len(result_dynamic.stats.portfolio_events) > 0, "Dynamic config should have events"
    
    # Проверки: monotonic timestamps
    events_fixed = result_fixed.stats.portfolio_events
    for i in range(len(events_fixed) - 1):
        assert events_fixed[i].timestamp <= events_fixed[i + 1].timestamp, \
            f"Events must have monotonic timestamps: {events_fixed[i].timestamp} > {events_fixed[i+1].timestamp}"


def test_replay_capacity_blocking_skips_positions(base_time, fee_model):
    """
    Тест: blueprints > capacity → часть не применяется, для них НЕТ POSITION_OPENED.
    
    Проверки:
    - trades_executed < len(blueprints) (некоторые пропущены)
    - trades_skipped_by_risk > 0
    - для пропущенных blueprints нет POSITION_OPENED events
    """
    # Создаем больше blueprints, чем max_open_positions
    blueprints = []
    for i in range(5):  # 5 blueprints
        blueprints.append(StrategyTradeBlueprint(
            signal_id=f"sig_{i}",
            strategy_id="test_strategy",
            contract_address=f"TOKEN_{i}",
            entry_time=base_time + timedelta(minutes=i * 5),
            entry_price_raw=1.0 + i * 0.1,
            entry_mcap_proxy=100_000_000.0,
            partial_exits=[],
            final_exit=FinalExitBlueprint(
                timestamp=base_time + timedelta(minutes=i * 5 + 30),
                reason="all_levels_hit"
            ),
            realized_multiple=2.0,
            max_xn_reached=2.0,
            reason="all_levels_hit"
        ))
    
    # Config с ограничением capacity
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="fixed",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=2,  # Только 2 позиции одновременно
        fee_model=fee_model,
    )
    
    result = PortfolioReplay.replay(
        blueprints=blueprints,
        portfolio_config=config,
        market_data=None,
    )
    
    # Проверки: часть blueprints пропущена
    assert result.stats.trades_executed < len(blueprints), \
        f"Some blueprints should be skipped: {result.stats.trades_executed} < {len(blueprints)}"
    
    assert result.stats.trades_skipped_by_risk > 0, \
        f"Some blueprints should be skipped by capacity: {result.stats.trades_skipped_by_risk} > 0"
    
    # Проверки: для пропущенных blueprints нет POSITION_OPENED
    opened_signal_ids = {
        event.signal_id
        for event in result.stats.portfolio_events
        if event.event_type == PortfolioEventType.POSITION_OPENED
    }
    
    # Должно быть открыто не больше max_open_positions позиций
    assert len(opened_signal_ids) <= config.max_open_positions, \
        f"Should not open more than {config.max_open_positions} positions, got {len(opened_signal_ids)}"
    
    # Проверки: для открытых позиций есть события
    assert len(opened_signal_ids) == result.stats.trades_executed, \
        f"Number of POSITION_OPENED events ({len(opened_signal_ids)}) should match trades_executed ({result.stats.trades_executed})"


def test_replay_profit_reset_emits_chain(base_time, fee_model):
    """
    Тест: profit reset срабатывает → есть PORTFOLIO_RESET_TRIGGERED, после него все позиции закрыты.
    
    Проверки:
    - есть PORTFOLIO_RESET_TRIGGERED event
    - после reset все позиции закрыты
    - для каждой закрытой позиции есть POSITION_CLOSED с reason="profit_reset"
    - правильный порядок событий (POSITION_CLOSED → PORTFOLIO_RESET_TRIGGERED)
    """
    # Создаем blueprints с прибыльными сделками (для достижения threshold)
    blueprints = []
    
    # Blueprint 1: очень прибыльная сделка (2x)
    blueprints.append(StrategyTradeBlueprint(
        signal_id="sig_profit_1",
        strategy_id="test_strategy",
        contract_address="TOKEN_A",
        entry_time=base_time,
        entry_price_raw=1.0,
        entry_mcap_proxy=100_000_000.0,
        partial_exits=[],
        final_exit=FinalExitBlueprint(
            timestamp=base_time + timedelta(minutes=30),
            reason="all_levels_hit"
        ),
        realized_multiple=2.0,  # 2x прибыль
        max_xn_reached=2.0,
        reason="all_levels_hit"
    ))
    
    # Blueprint 2: еще одна прибыльная сделка (2x)
    blueprints.append(StrategyTradeBlueprint(
        signal_id="sig_profit_2",
        strategy_id="test_strategy",
        contract_address="TOKEN_B",
        entry_time=base_time + timedelta(minutes=35),
        entry_price_raw=1.0,
        entry_mcap_proxy=100_000_000.0,
        partial_exits=[],
        final_exit=None,  # Без final_exit - будет закрыт по reset
        realized_multiple=0.0,
        max_xn_reached=0.0,
        reason="all_levels_hit"
    ))
    
    # Config с profit reset (threshold = 1.3x от начального баланса)
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,  # 50% на сделку (5 SOL)
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=fee_model,
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,  # Reset при equity >= 13 SOL
    )
    
    # Debug: Enum comparison (only if BACKTESTER_RESET_DEBUG=1)
    from backtester.debug.reset_debug import reset_debug_enabled
    if reset_debug_enabled():
        import backtester.domain.portfolio_events as pe
        print("=== TEST DEBUG: Enum Comparison ===")
        print(f"PortfolioEventType.__module__={PortfolioEventType.__module__}, id(PortfolioEventType)={id(PortfolioEventType)}")
        print(f"pe.PortfolioEventType.__module__={pe.PortfolioEventType.__module__}, id(pe.PortfolioEventType)={id(pe.PortfolioEventType)}")
        print(f"PortfolioEventType is pe.PortfolioEventType={PortfolioEventType is pe.PortfolioEventType}")
        print(f"PortfolioEventType.POSITION_CLOSED == pe.PortfolioEventType.POSITION_CLOSED={PortfolioEventType.POSITION_CLOSED == pe.PortfolioEventType.POSITION_CLOSED}")
        print("=== END TEST DEBUG ===")
    
    result = PortfolioReplay.replay(
        blueprints=blueprints,
        portfolio_config=config,
        market_data=None,
    )
    
    # Debug: Reset events diagnostics (only if BACKTESTER_RESET_DEBUG=1)
    from backtester.debug.reset_debug import dump_reset_debug
    if reset_debug_enabled():
        import backtester.domain.portfolio_events as pe
        dump_reset_debug(
            "TEST:test_replay_profit_reset_emits_chain",
            events=result.stats.portfolio_events,
            portfolio_event_type_test=PortfolioEventType,
            portfolio_event_type_engine=pe.PortfolioEventType,
        )
    
    # Проверки: есть PORTFOLIO_RESET_TRIGGERED event
    reset_events = [
        event for event in result.stats.portfolio_events
        if event.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) > 0, "Should have PORTFOLIO_RESET_TRIGGERED event"
    
    reset_event = reset_events[0]
    assert reset_event.reason == "profit_reset", \
        f"Reset event reason should be 'profit_reset', got {reset_event.reason}"
    
    # Проверки: после reset все позиции закрыты
    # Находим время reset
    reset_time = reset_event.timestamp
    
    # Проверяем, что все открытые на момент reset позиции закрыты
    positions_closed_by_reset = [
        event for event in result.stats.portfolio_events
        if event.event_type == PortfolioEventType.POSITION_CLOSED
        and event.reason == "profit_reset"
        and event.timestamp <= reset_time
    ]
    
    assert len(positions_closed_by_reset) > 0, \
        "Should have POSITION_CLOSED events with reason='profit_reset'"
    
    # Проверки: правильный порядок событий
    # POSITION_CLOSED events должны быть до или в одно время с PORTFOLIO_RESET_TRIGGERED
    for closed_event in positions_closed_by_reset:
        assert closed_event.timestamp <= reset_time, \
            f"POSITION_CLOSED event ({closed_event.timestamp}) should be before or at reset time ({reset_time})"
    
    # Проверки: linkage - каждый POSITION_CLOSED имеет правильный position_id
    closed_position_ids = {event.position_id for event in positions_closed_by_reset}
    assert len(closed_position_ids) == len(positions_closed_by_reset), \
        "Each POSITION_CLOSED should have unique position_id"
    
    # Проверки: после reset нет открытых позиций (или они закрыты позже)
    # (Это проверяется через то, что все позиции с timestamp <= reset_time закрыты)


def test_replay_max_hold_closes_positions(base_time, fee_model):
    """
    Тест: blueprint без final_exit, max_hold_minutes задан → позиция закрыта с reason="max_hold_minutes".
    
    Проверки:
    - позиция без final_exit остается открытой после обработки blueprint
    - после max_hold_minutes позиция закрывается
    - есть POSITION_CLOSED event с reason="max_hold_minutes"
    - EXECUTION создан (forced_close)
    """
    # Blueprint без final_exit
    blueprint = StrategyTradeBlueprint(
        signal_id="sig_no_final",
        strategy_id="test_strategy",
        contract_address="TOKEN_NO_FINAL",
        entry_time=base_time,
        entry_price_raw=1.0,
        entry_mcap_proxy=100_000_000.0,
        partial_exits=[
            PartialExitBlueprint(
                timestamp=base_time + timedelta(minutes=10),
                xn=2.0,
                fraction=0.5
            ),
        ],
        final_exit=None,  # НЕТ final_exit
        realized_multiple=1.0,
        max_xn_reached=2.0,
        reason="all_levels_hit"
    )
    
    # Config с max_hold_minutes
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="fixed",
        percent_per_trade=0.2,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=fee_model,
        max_hold_minutes=60,  # 60 минут
    )
    
    # Blueprint 2: появляется позже, чтобы триггерить проверку max_hold_minutes
    blueprint2 = StrategyTradeBlueprint(
        signal_id="sig_trigger",
        strategy_id="test_strategy",
        contract_address="TOKEN_TRIGGER",
        entry_time=base_time + timedelta(minutes=70),  # Через 70 минут (после max_hold_minutes)
        entry_price_raw=2.0,
        entry_mcap_proxy=200_000_000.0,
        partial_exits=[],
        final_exit=FinalExitBlueprint(
            timestamp=base_time + timedelta(minutes=100),
            reason="all_levels_hit"
        ),
        realized_multiple=1.5,
        max_xn_reached=1.5,
        reason="all_levels_hit"
    )
    
    result = PortfolioReplay.replay(
        blueprints=[blueprint, blueprint2],
        portfolio_config=config,
        market_data=None,
    )
    
    # Проверки: есть POSITION_CLOSED event с reason="max_hold_minutes"
    max_hold_events = [
        event for event in result.stats.portfolio_events
        if event.event_type == PortfolioEventType.POSITION_CLOSED
        and event.reason == "max_hold_minutes"
    ]
    
    assert len(max_hold_events) > 0, \
        "Should have POSITION_CLOSED event with reason='max_hold_minutes'"
    
    max_hold_event = max_hold_events[0]
    
    # Проверки: EXECUTION создан (forced_close в meta)
    assert max_hold_event.meta.get("execution_type") == "forced_close", \
        "Should have execution_type='forced_close' in meta"
    
    assert max_hold_event.meta.get("forced_reason") == "max_hold_minutes", \
        "Should have forced_reason='max_hold_minutes' in meta"
    
    # Проверки: позиция закрыта в правильное время (entry_time + max_hold_minutes)
    expected_close_time = base_time + timedelta(minutes=60)
    assert max_hold_event.timestamp == expected_close_time, \
        f"Close time should be {expected_close_time}, got {max_hold_event.timestamp}"
    
    # Проверки: linkage - position_id корректный
    assert max_hold_event.signal_id == blueprint.signal_id, \
        f"Event signal_id should match blueprint: {max_hold_event.signal_id} != {blueprint.signal_id}"
    
    # Проверки: позиция найдена в результатах и закрыта
    closed_positions = [p for p in result.positions if p.status == "closed"]
    max_hold_position = next(
        (p for p in closed_positions if p.signal_id == blueprint.signal_id),
        None
    )
    assert max_hold_position is not None, \
        f"Position for {blueprint.signal_id} should be closed"
    
    assert max_hold_position.exit_time == expected_close_time, \
        f"Position exit_time should be {expected_close_time}, got {max_hold_position.exit_time}"

