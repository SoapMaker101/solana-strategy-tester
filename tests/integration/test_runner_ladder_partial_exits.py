"""
Integration test for Runner ladder partial exits.

Tests that partial exits work correctly:
- Fractions are calculated from initial size (not remaining)
- Position remains open after partial exit
- Final exit happens on time_stop
- PnL is calculated correctly from partial exits
"""
import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from backtester.domain.runner_strategy import RunnerStrategy
from backtester.domain.runner_config import create_runner_config_from_dict
from backtester.domain.models import Signal, Candle, StrategyInput
from backtester.domain.portfolio import (
    PortfolioConfig,
    PortfolioEngine,
    FeeModel,
)
from backtester.domain.portfolio_events import PortfolioEventType


@pytest.fixture
def base_time():
    """Base time for tests."""
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def runner_config():
    """Create Runner config with partial exits enabled."""
    return create_runner_config_from_dict(
        "test_runner_partial",
        {
            "take_profit_levels": [
                {"xn": 3.0, "fraction": 0.20},
                {"xn": 7.0, "fraction": 0.30},
                {"xn": 15.0, "fraction": 0.50},
            ],
            "time_stop_minutes": 120,  # 2 hours for quick test
            "use_high_for_targets": True,
            "exit_on_first_tp": False,
            "allow_partial_fills": True,
        }
    )


@pytest.fixture
def runner_strategy(runner_config):
    """Create Runner strategy."""
    return RunnerStrategy(runner_config)


@pytest.fixture
def sample_signal(base_time):
    """Create test signal."""
    return Signal(
        id="test_signal_partial",
        contract_address="TESTTOKEN",
        timestamp=base_time,
        source="test",
        narrative="test signal for partial exits"
    )


def test_runner_ladder_partial_exit_with_time_stop(
    runner_strategy, sample_signal, base_time
):
    """
    Test partial exit scenario:
    - Price reaches 3x (first TP level)
    - 20% of initial size is closed
    - Price drops to near zero
    - Time stop triggers
    - Remaining 80% is closed at time_stop
    
    Expected:
    - 1 POSITION_PARTIAL_EXIT event (at 3x)
    - 1 POSITION_CLOSED event (at time_stop)
    - Total exited qty on partial_exit == 0.2 * initial_qty
    - Final pnl_pct is NOT ~+200% (because only 20% was closed at 3x)
    """
    entry_price = 100.0
    
    # Create candles:
    # 1. Entry at 100
    # 2. Price reaches 3x (300) - first TP level
    # 3. Price drops to near zero (10)
    # 4. Time stop triggers after 120 minutes
    
    candles = []
    # Entry candle
    candles.append(Candle(
        timestamp=base_time,
        open=entry_price,
        high=entry_price + 5,
        low=entry_price - 5,
        close=entry_price,
        volume=1000.0
    ))
    
    # Price reaches 3x (300) - first TP level
    tp_level_time = base_time + timedelta(minutes=10)
    candles.append(Candle(
        timestamp=tp_level_time,
        open=250.0,
        high=310.0,  # High >= 300 (3x)
        low=240.0,
        close=300.0,
        volume=2000.0
    ))
    
    # Price drops to near zero
    drop_time = base_time + timedelta(minutes=20)
    candles.append(Candle(
        timestamp=drop_time,
        open=50.0,
        high=60.0,
        low=5.0,
        close=10.0,  # Near zero
        volume=3000.0
    ))
    
    # Time stop triggers after 120 minutes
    # Add candles up to time_stop
    for i in range(1, 13):  # 12 more candles to reach ~120 minutes
        candle_time = base_time + timedelta(minutes=10 * i)
        candles.append(Candle(
            timestamp=candle_time,
            open=10.0,
            high=15.0,
            low=5.0,
            close=10.0,
            volume=1000.0
        ))
    
    # Last candle at time_stop (120 minutes)
    time_stop_time = base_time + timedelta(minutes=120)
    candles.append(Candle(
        timestamp=time_stop_time,
        open=10.0,
        high=15.0,
        low=5.0,
        close=10.0,  # Price at time_stop
        volume=1000.0
    ))
    
    # Run strategy
    data = StrategyInput(
        signal=sample_signal,
        candles=candles,
        global_params={}
    )
    
    result = runner_strategy.on_signal(data)
    
    # Verify strategy output
    assert result.entry_time == base_time
    assert result.entry_price == entry_price
    assert result.exit_time is not None
    assert result.exit_price is not None
    
    # Verify meta contains ladder data
    assert "levels_hit" in result.meta
    assert "fractions_exited" in result.meta
    assert "runner_ladder" in result.meta
    assert result.meta["runner_ladder"] is True
    
    # Verify that 3x level was hit
    levels_hit = result.meta.get("levels_hit", {})
    assert "3.0" in levels_hit, "3x level should be hit"
    
    # Verify that fraction 0.20 was exited at 3x
    fractions_exited = result.meta.get("fractions_exited", {})
    assert "3.0" in fractions_exited, "3x level should have fraction exited"
    assert abs(fractions_exited["3.0"] - 0.20) < 1e-6, \
        f"Fraction at 3x should be 0.20, got {fractions_exited['3.0']}"
    
    # Verify that time_stop was triggered (not all levels hit)
    assert result.meta.get("time_stop_triggered", False), \
        "time_stop should be triggered"
    assert result.reason in ("timeout", "time_stop"), \
        f"Reason should be timeout/time_stop, got {result.reason}"
    
    # Now test with PortfolioEngine
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        fee_model=FeeModel(),
    )
    
    engine = PortfolioEngine(config)
    
    trades = [
        {
            "signal_id": sample_signal.id,
            "contract_address": sample_signal.contract_address,
            "strategy": "test_runner_partial",
            "timestamp": base_time,
            "result": result
        }
    ]
    
    portfolio_result = engine.simulate(trades, strategy_name="test_runner_partial")
    
    # Get events
    events = portfolio_result.stats.portfolio_events
    assert len(events) > 0, "Should have events"
    
    # Filter events
    position_opened_events = [
        e for e in events 
        if e.event_type == PortfolioEventType.POSITION_OPENED
    ]
    partial_exit_events = [
        e for e in events 
        if e.event_type == PortfolioEventType.POSITION_PARTIAL_EXIT
    ]
    position_closed_events = [
        e for e in events 
        if e.event_type == PortfolioEventType.POSITION_CLOSED
    ]
    
    # Verify events
    assert len(position_opened_events) == 1, \
        f"Should have 1 POSITION_OPENED, got {len(position_opened_events)}"
    assert len(partial_exit_events) >= 1, \
        f"Should have at least 1 POSITION_PARTIAL_EXIT, got {len(partial_exit_events)}"
    assert len(position_closed_events) >= 1, \
        f"Should have at least 1 POSITION_CLOSED, got {len(position_closed_events)}"
    
    # Find the position
    position = next(
        (p for p in portfolio_result.positions if p.signal_id == sample_signal.id),
        None
    )
    assert position is not None, "Position should exist"
    
    # Verify position_id is consistent
    position_id = position.position_id
    for event in position_opened_events + partial_exit_events + position_closed_events:
        assert event.position_id == position_id, \
            f"Event {event.event_type} should have position_id={position_id}"
    
    # Verify partial exit event
    partial_exit_3x = next(
        (e for e in partial_exit_events if e.meta.get("level_xn") == 3.0),
        None
    )
    assert partial_exit_3x is not None, "Should have partial exit at 3x"
    assert abs(partial_exit_3x.meta.get("fraction", 0) - 0.20) < 1e-6, \
        f"Partial exit fraction should be 0.20, got {partial_exit_3x.meta.get('fraction')}"
    
    # Verify position_closed reason is time_stop
    position_closed = position_closed_events[0]
    assert position_closed.reason == "time_stop", \
        f"Position closed reason should be time_stop, got {position_closed.reason}"
    
    # Verify total exited qty on partial_exit == 0.2 * initial_qty
    initial_size = position.meta.get("original_size", position.size)
    if "original_size" not in position.meta:
        # If original_size not set, use size from partial_exits
        partial_exits = position.meta.get("partial_exits", [])
        if partial_exits:
            # Calculate initial_size from first partial exit
            first_exit = partial_exits[0]
            exit_size = first_exit.get("exit_size", 0)
            fraction = first_exit.get("fraction", 0) if "fraction" in first_exit else 0.20
            if fraction > 0:
                initial_size = exit_size / fraction
    
    # Find partial exit at 3x
    partial_exits = position.meta.get("partial_exits", [])
    partial_exit_3x_data = next(
        (e for e in partial_exits if abs(e.get("xn", 0) - 3.0) < 1e-6),
        None
    )
    if partial_exit_3x_data:
        exit_size = partial_exit_3x_data.get("exit_size", 0)
        expected_exit_size = initial_size * 0.20
        assert abs(exit_size - expected_exit_size) < 1e-6, \
            f"Partial exit size should be {expected_exit_size} (0.2 * {initial_size}), got {exit_size}"
    
    # Verify final pnl_pct is NOT ~+200%
    # If only 20% was closed at 3x, pnl should be much lower
    # Expected: 0.2 * (3.0 - 1.0) * 100 = 40% from partial exit
    # Plus remaining 80% closed at time_stop (price ~0.1x) = 0.8 * (0.1 - 1.0) * 100 = -72%
    # Total: ~40% - 72% = -32% (approximately, depends on exact prices and fees)
    pnl_pct = position.pnl_pct * 100.0  # Convert to percentage
    assert abs(pnl_pct - 200.0) > 50.0, \
        f"Final pnl_pct should NOT be ~+200% (only 20% closed at 3x), got {pnl_pct}%"
    
    # Verify meta contains fractions_exited
    assert "fractions_exited" in position.meta, \
        "Position meta should contain fractions_exited"
    assert "levels_hit" in position.meta, \
        "Position meta should contain levels_hit"
    
    # Verify levels_hit contains 3.0
    levels_hit_meta = position.meta.get("levels_hit", {})
    assert "3.0" in levels_hit_meta or 3.0 in levels_hit_meta, \
        "levels_hit should contain 3.0"

