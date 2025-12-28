"""
Unit tests for PortfolioEngine event mapping from StrategyOutput (v1.9).

Tests that PortfolioEngine correctly maps StrategyOutput.reason and meta.detail
to PortfolioEventType for skipped attempts (no_candles, corrupt_candles).
"""
from datetime import datetime, timezone
from backtester.domain.portfolio import PortfolioEngine, PortfolioConfig
from backtester.domain.models import StrategyOutput
from backtester.domain.portfolio_events import PortfolioEventType
from tests.helpers.events import count_event


def test_portfolio_engine_maps_no_candles_to_rejected_no_candles():
    """
    Test that PortfolioEngine emits ATTEMPT_REJECTED_NO_CANDLES
    when StrategyOutput has entry_time=None, reason="no_entry", meta.detail="no_candles".
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        max_open_positions=10,
        capacity_reset_mode="prune",
    )
    engine = PortfolioEngine(config)
    
    # Создаем attempt с no_candles
    trades = [
        {
            "signal_id": "sig1",
            "contract_address": "CONTRACT1",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "no_candles"},
            ),
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверяем события
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_RECEIVED) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_NO_CANDLES) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_ACCEPTED_OPEN) == 0
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_CAPACITY) == 0


def test_portfolio_engine_maps_corrupt_candles_to_rejected_corrupt():
    """
    Test that PortfolioEngine emits ATTEMPT_REJECTED_CORRUPT_CANDLES
    when StrategyOutput has entry_time=None, reason="no_entry", meta.detail="corrupt_candles".
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        max_open_positions=10,
        capacity_reset_mode="prune",
    )
    engine = PortfolioEngine(config)
    
    # Создаем attempt с corrupt_candles
    trades = [
        {
            "signal_id": "sig1",
            "contract_address": "CONTRACT1",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "corrupt_candles"},
            ),
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверяем события
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_RECEIVED) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_CORRUPT_CANDLES) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_NO_CANDLES) == 0
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_ACCEPTED_OPEN) == 0


def test_portfolio_engine_maps_unknown_detail_to_strategy_no_entry():
    """
    Test that PortfolioEngine emits ATTEMPT_REJECTED_STRATEGY_NO_ENTRY
    when StrategyOutput has entry_time=None but unknown/empty meta.detail.
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        max_open_positions=10,
        capacity_reset_mode="prune",
    )
    engine = PortfolioEngine(config)
    
    # Создаем attempt с неизвестным detail (или без detail)
    trades = [
        {
            "signal_id": "sig1",
            "contract_address": "CONTRACT1",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "unknown_reason"},  # Неизвестный detail
            ),
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверяем события - должно быть ATTEMPT_REJECTED_STRATEGY_NO_ENTRY (неизвестный detail)
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_RECEIVED) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_STRATEGY_NO_ENTRY) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_NO_CANDLES) == 0
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_CORRUPT_CANDLES) == 0


def test_portfolio_engine_maps_empty_detail_to_strategy_no_entry():
    """
    Test that PortfolioEngine emits ATTEMPT_REJECTED_STRATEGY_NO_ENTRY
    when StrategyOutput has entry_time=None but no meta.detail (empty).
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        max_open_positions=10,
        capacity_reset_mode="prune",
    )
    engine = PortfolioEngine(config)
    
    # Создаем attempt без detail
    trades = [
        {
            "signal_id": "sig1",
            "contract_address": "CONTRACT1",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={},  # Пустой meta, нет detail
            ),
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверяем события - должно быть ATTEMPT_REJECTED_STRATEGY_NO_ENTRY (пустой detail)
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_RECEIVED) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_STRATEGY_NO_ENTRY) == 1
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_NO_CANDLES) == 0
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_CORRUPT_CANDLES) == 0


def test_portfolio_engine_no_candles_not_in_capacity_window():
    """
    Test that ATTEMPT_REJECTED_NO_CANDLES events do NOT participate
    in capacity pressure / blocked_ratio calculation.
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        max_open_positions=2,
        capacity_reset_mode="prune",
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_open_ratio_threshold=1.0,
        capacity_max_blocked_ratio=0.2,
    )
    engine = PortfolioEngine(config)
    
    # Создаем много attempts с no_candles (не должны влиять на capacity)
    trades = []
    for i in range(20):
        trades.append({
            "signal_id": f"sig{i}",
            "contract_address": f"CONTRACT{i}",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "no_candles"},
            ),
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверяем события
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_NO_CANDLES) == 20
    
    # Проверяем, что capacity events НЕ появились (no_candles не считаются blocked_by_capacity)
    assert count_event(result.stats, PortfolioEventType.ATTEMPT_REJECTED_CAPACITY) == 0
    assert count_event(result.stats, PortfolioEventType.CAPACITY_PRUNE_TRIGGERED) == 0

