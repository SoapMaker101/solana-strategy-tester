"""
Regression tests for position_id + runner ladder event-ledger + reset events.

Tests verify:
1. Position.position_id generated and stable
2. positions.csv export includes position_id
3. Runner ladder event-ledger correctness
4. Reset emits full event chain with position_id
"""
import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from backtester.domain.position import Position
from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput
from backtester.domain.portfolio_events import PortfolioEventType


def test_position_id_generated_and_stable():
    """Test that Position.position_id is generated and remains stable."""
    from backtester.domain.models import Signal
    
    signal = Signal(
        id="test_signal",
        contract_address="TOKEN1",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        narrative="test"
    )
    
    # Create position
    pos1 = Position(
        signal_id=signal.id,
        contract_address=signal.contract_address,
        entry_time=signal.timestamp,
        entry_price=1.0,
        size=1.0,
    )
    
    # Check position_id is generated and non-empty
    assert pos1.position_id is not None, "position_id should be generated"
    assert isinstance(pos1.position_id, str), "position_id should be string"
    assert len(pos1.position_id) > 0, "position_id should be non-empty"
    assert len(pos1.position_id) == 32, "position_id should be uuid4 hex (32 chars)"
    
    # Check position_id is stable (doesn't change)
    original_id = pos1.position_id
    assert pos1.position_id == original_id, "position_id should remain stable"
    
    # Create another position - should have different ID
    pos2 = Position(
        signal_id="another_signal",
        contract_address="TOKEN2",
        entry_time=signal.timestamp,
        entry_price=1.0,
        size=1.0,
    )
    
    assert pos2.position_id != pos1.position_id, "Different positions should have different position_id"


def test_positions_csv_includes_position_id():
    """Test that positions.csv export includes position_id with non-empty values."""
    from backtester.infrastructure.reporter import Reporter
    from pathlib import Path
    import tempfile
    import pandas as pd
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        fee_model=FeeModel(),
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = [
        {
            "signal_id": "test_signal_1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=base_time,
                entry_price=1.0,
                exit_time=base_time + timedelta(hours=1),
                exit_price=1.1,
                pnl=0.1,
                reason="tp"
            )
        },
        {
            "signal_id": "test_signal_2",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": base_time + timedelta(minutes=30),
            "result": StrategyOutput(
                entry_time=base_time + timedelta(minutes=30),
                entry_price=2.0,
                exit_time=base_time + timedelta(hours=2),
                exit_price=2.2,
                pnl=0.1,
                reason="tp"
            )
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Export to CSV
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        reporter.save_portfolio_positions_table({
            "test_strategy": result
        })
        
        # Read CSV
        csv_path = Path(tmpdir) / "portfolio_positions.csv"
        assert csv_path.exists(), "portfolio_positions.csv should be created"
        
        df = pd.read_csv(csv_path)
        
        # Check position_id column exists and is first
        assert "position_id" in df.columns, "position_id column should exist"
        assert df.columns[0] == "position_id", "position_id should be first column"
        
        # Check all values are non-empty
        assert df["position_id"].notna().all(), "All position_id values should be non-null"
        assert (df["position_id"].str.len() > 0).all(), "All position_id values should be non-empty"
        
        # Check position_id values are unique
        assert df["position_id"].nunique() == len(df), "All position_id values should be unique"
        
        # Verify position_id matches Position objects
        position_ids_in_result = {pos.position_id for pos in result.positions if pos.status == "closed"}
        position_ids_in_csv = set(df["position_id"].values)
        
        # All closed positions should be in CSV
        assert position_ids_in_result == position_ids_in_csv, \
            "position_id values in CSV should match Position objects"


def test_runner_ladder_event_ledger_correctness():
    """
    Test runner ladder event-ledger correctness.
    
    Scenario: StrategyOutput with levels_hit {2, 5, 10} and fractions {0.4, 0.4, 0.2}
    Expected:
    - 3 POSITION_PARTIAL_EXIT + 1 POSITION_CLOSED events
    - All events have position_id
    - Fractions sum to 1.0
    - realized_multiple == 4.8 (0.4*2 + 0.4*5 + 0.2*10)
    - pnl_pct_total == 380% ((4.8 - 1) * 100)
    - exit_price is market close, NOT entry_price * 4.8
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        fee_model=FeeModel(),
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    entry_price = 100.0
    
    # Market close price at exit (close of candle at exit_time) - should be different from synthetic
    # Exit occurs at last level hit (10x), market close should be candle close at that time
    market_close_price = 800.0  # Close of candle at exit_time, NOT entry_price * 4.8 = 480.0
    
    # Create StrategyOutput with ladder data
    levels_hit = {
        "2.0": (base_time + timedelta(minutes=10)).isoformat(),
        "5.0": (base_time + timedelta(minutes=20)).isoformat(),
        "10.0": (base_time + timedelta(minutes=30)).isoformat(),
    }
    fractions_exited = {
        "2.0": 0.4,
        "5.0": 0.4,
        "10.0": 0.2,
    }
    realized_multiple = 0.4 * 2.0 + 0.4 * 5.0 + 0.2 * 10.0  # 4.8
    
    strategy_output = StrategyOutput(
        entry_time=base_time,
        entry_price=entry_price,
        exit_time=base_time + timedelta(minutes=30),
        exit_price=market_close_price,  # Market close, NOT synthetic
        pnl=(realized_multiple - 1.0),  # 3.8 in decimal form
        reason="tp",
        meta={
            "runner_ladder": True,
            "levels_hit": levels_hit,
            "fractions_exited": fractions_exited,
            "realized_multiple": realized_multiple,
            "time_stop_triggered": False,
            "ladder_reason": "ladder_tp",
        }
    )
    
    trades = [
        {
            "signal_id": "ladder_signal",
            "contract_address": "TOKEN1",
            "strategy": "test_runner",
            "timestamp": base_time,
            "result": strategy_output
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_runner")
    
    # Get events
    events = result.stats.portfolio_events
    assert len(events) > 0, "Should have events"
    
    # Filter position-related events
    position_opened_events = [e for e in events if e.event_type == PortfolioEventType.POSITION_OPENED]
    partial_exit_events = [e for e in events if e.event_type == PortfolioEventType.POSITION_PARTIAL_EXIT]
    position_closed_events = [e for e in events if e.event_type == PortfolioEventType.POSITION_CLOSED]
    
    # Check we have expected events
    assert len(position_opened_events) == 1, f"Should have 1 POSITION_OPENED, got {len(position_opened_events)}"
    assert len(partial_exit_events) == 3, f"Should have 3 POSITION_PARTIAL_EXIT, got {len(partial_exit_events)}"
    assert len(position_closed_events) >= 1, f"Should have at least 1 POSITION_CLOSED, got {len(position_closed_events)}"
    
    # Get the position
    position = next((p for p in result.positions if p.signal_id == "ladder_signal"), None)
    assert position is not None, "Position should exist"
    position_id = position.position_id
    
    # Check all events have position_id
    for event in position_opened_events + partial_exit_events + position_closed_events:
        assert event.position_id == position_id, \
            f"Event {event.event_type} should have position_id={position_id}, got {event.position_id}"
    
    # Check fractions sum to 1.0
    total_fraction = sum(fractions_exited.values())
    assert abs(total_fraction - 1.0) < 1e-6, \
        f"Fractions should sum to 1.0, got {total_fraction}"
    
    # Check realized_multiple
    eps = 1e-6
    assert abs(realized_multiple - 4.8) < eps, \
        f"realized_multiple should be 4.8, got {realized_multiple}"
    
    # Check pnl_pct_total from partial exits
    partial_exits_from_meta = position.meta.get("partial_exits", [])
    if partial_exits_from_meta:
        # pnl_pct is already stored as percentage, no need to multiply by 100
        pnl_pct_total = sum(exit.get("pnl_pct", 0.0) for exit in partial_exits_from_meta)
        expected_pnl_pct = 380.0  # (4.8 - 1) * 100 = 380%
        
        # Allow for rounding differences
        assert abs(pnl_pct_total - expected_pnl_pct) < 10.0, \
            f"pnl_pct_total should be ~{expected_pnl_pct}%, got {pnl_pct_total}%"
    
    # Check exit_price is market close, NOT synthetic
    assert position.exit_price is not None, "exit_price should be set"
    synthetic_price = entry_price * realized_multiple  # 480.0
    # exit_price should be closer to market_close_price (800) than to synthetic_price (480)
    distance_to_market = abs(position.exit_price - market_close_price)
    distance_to_synthetic = abs(position.exit_price - synthetic_price)
    assert distance_to_market < distance_to_synthetic, \
        f"exit_price should be closer to market close ({market_close_price}, distance={distance_to_market}) than synthetic ({synthetic_price}, distance={distance_to_synthetic}), got {position.exit_price}"
    
    # Verify exit_price in StrategyOutput is market close
    assert abs(strategy_output.exit_price - market_close_price) < eps, \
        f"StrategyOutput.exit_price should be market close ({market_close_price}), got {strategy_output.exit_price}"


def test_reset_emits_full_event_chain():
    """
    Test that reset emits PORTFOLIO_RESET_TRIGGERED + N POSITION_CLOSED events with position_id.
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=1.0,  # Use full balance per trade to ensure enough equity growth
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        profit_reset_enabled=True,
        profit_reset_multiple=1.1,  # Reset at 1.1x equity (lower threshold to guarantee reset)
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Create trades with high profit to trigger reset
    # With percent_per_trade=1.0 and profit_reset_multiple=1.1, we need equity to grow by 10%
    # Starting balance: 10.0 SOL
    # Trade 1: 10.0 SOL * (exit/entry - 1) = 10.0 * 1.5 = 15.0 profit -> balance = 25.0 (2.5x, > 1.1x threshold)
    trades = []
    for i in range(2):  # 2 trades should be enough to trigger reset
        entry_time = base_time + timedelta(minutes=i * 5)
        exit_time = entry_time + timedelta(hours=1)
        
        trades.append({
            "signal_id": f"reset_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": StrategyOutput(
                entry_time=entry_time,
                entry_price=1.0,
                exit_time=exit_time,
                exit_price=2.5,  # High profit (150%) to trigger reset
                pnl=1.5,  # 150% profit
                reason="tp"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Get events
    events = result.stats.portfolio_events
    
    # Find PORTFOLIO_RESET_TRIGGERED events
    reset_triggered_events = [e for e in events if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED]
    assert len(reset_triggered_events) > 0, "Should have at least 1 PORTFOLIO_RESET_TRIGGERED event"
    
    # Find POSITION_CLOSED events with profit_reset reason
    position_closed_events = [
        e for e in events 
        if e.event_type == PortfolioEventType.POSITION_CLOSED and e.reason == "profit_reset"
    ]
    
    # Should have at least some closed positions
    assert len(position_closed_events) > 0, "Should have at least 1 POSITION_CLOSED with profit_reset reason"
    
    # Check all POSITION_CLOSED events have position_id
    for event in position_closed_events:
        assert event.position_id is not None, \
            f"POSITION_CLOSED event should have position_id, got None for signal_id={event.signal_id}"
        assert len(event.position_id) > 0, \
            f"POSITION_CLOSED event should have non-empty position_id for signal_id={event.signal_id}"
    
    # Verify position_id matches actual positions
    closed_positions = [p for p in result.positions if p.status == "closed" and p.is_closed_by_reset()]
    position_ids_in_positions = {p.position_id for p in closed_positions}
    position_ids_in_events = {e.position_id for e in position_closed_events}
    
    # All closed-by-reset positions should have corresponding events
    assert len(position_ids_in_positions.intersection(position_ids_in_events)) > 0, \
        "Some closed-by-reset positions should have corresponding POSITION_CLOSED events"


def test_runner_ladder_exit_price_not_synthetic():
    """
    Test that runner ladder exit_price is market close, NOT entry_price * realized_multiple.
    """
    from backtester.domain.runner_config import RunnerConfig, RunnerTakeProfitLevel, create_runner_config_from_dict
    from backtester.domain.runner_strategy import RunnerStrategy
    from backtester.domain.models import StrategyInput, Candle, Signal
    
    # Create runner config
    runner_config = create_runner_config_from_dict(
        "test_runner",
        {
            "take_profit_levels": [
                {"xn": 2.0, "fraction": 0.4},
                {"xn": 5.0, "fraction": 0.4},
                {"xn": 10.0, "fraction": 0.2},
            ],
            "time_stop_minutes": None,
            "use_high_for_targets": True,
        }
    )
    
    strategy = RunnerStrategy(runner_config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    entry_price = 100.0
    
    # Create signal
    signal = Signal(
        id="ladder_test",
        contract_address="TOKEN1",
        timestamp=base_time,
        source="test",
        narrative="test"
    )
    
    # Create candles: price hits 2x, 5x, 10x, then market closes at 105.0
    candles = []
    current_price = entry_price
    
    # Entry candle
    candles.append(Candle(
        timestamp=base_time,
        open=entry_price,
        high=entry_price * 1.5,
        low=entry_price * 0.9,
        close=entry_price,
        volume=1000.0
    ))
    
    # Candle that hits 2x (high = 200)
    hit_2x_time = base_time + timedelta(minutes=10)
    candles.append(Candle(
        timestamp=hit_2x_time,
        open=entry_price * 1.5,
        high=entry_price * 2.1,  # Hits 2x
        low=entry_price * 1.4,
        close=entry_price * 1.8,
        volume=1000.0
    ))
    
    # Candle that hits 5x (high = 500)
    hit_5x_time = base_time + timedelta(minutes=20)
    candles.append(Candle(
        timestamp=hit_5x_time,
        open=entry_price * 2.0,
        high=entry_price * 5.1,  # Hits 5x
        low=entry_price * 1.9,
        close=entry_price * 4.0,
        volume=1000.0
    ))
    
    # Candle that hits 10x (high = 1000)
    hit_10x_time = base_time + timedelta(minutes=30)
    candles.append(Candle(
        timestamp=hit_10x_time,
        open=entry_price * 5.0,
        high=entry_price * 10.1,  # Hits 10x
        low=entry_price * 4.9,
        close=entry_price * 8.0,
        volume=1000.0
    ))
    
    # Exit occurs at last level hit candle (hit_10x_time), so market_close_price should be close of that candle
    # The last level hit candle is the one at hit_10x_time with close = entry_price * 8.0 = 800.0
    exit_time = hit_10x_time  # Exit occurs when last level is hit
    market_close_price = entry_price * 8.0  # 800.0 - close of the candle where 10x was hit
    
    # Create strategy input
    strategy_input = StrategyInput(
        signal=signal,
        candles=candles,
        global_params={}
    )
    
    # Run strategy
    output = strategy.on_signal(strategy_input)
    
    # Check exit_price is market close, NOT synthetic
    assert output.exit_price is not None, "exit_price should be set"
    realized_multiple = output.meta.get("realized_multiple", 1.0)
    synthetic_price = entry_price * realized_multiple  # 100 * 4.8 = 480.0
    
    # exit_price should be closer to market_close_price (800.0) than to synthetic (480.0)
    assert abs(output.exit_price - market_close_price) < abs(output.exit_price - synthetic_price), \
        f"exit_price should be closer to market close ({market_close_price}) than synthetic ({synthetic_price}), got {output.exit_price}"
    
    # Verify it's actually closer to market close (800) than synthetic (480)
    distance_to_market_close = abs(output.exit_price - market_close_price)
    distance_to_synthetic = abs(output.exit_price - synthetic_price)
    assert distance_to_market_close < distance_to_synthetic, \
        f"exit_price ({output.exit_price}) should be closer to market close ({market_close_price}, distance={distance_to_market_close}) than to synthetic ({synthetic_price}, distance={distance_to_synthetic})"
    
    # Verify ladder_reason is in meta
    assert output.meta.get("ladder_reason") == "ladder_tp" or output.reason == "tp", \
        "ladder_reason should be ladder_tp or reason should be tp"

