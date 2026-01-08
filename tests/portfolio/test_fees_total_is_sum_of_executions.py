"""
Test that fees_total_sol equals sum of fees from executions.

TASK 3: fees_total_sol должен быть суммой fees по executions позиции.
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
from backtester.infrastructure.reporter import Reporter
import pandas as pd
import tempfile
import os


@pytest.fixture
def base_time():
    """Base time for tests."""
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def runner_config():
    """Create Runner config with partial exits enabled."""
    return create_runner_config_from_dict(
        "test_runner_fees",
        {
            "take_profit_levels": [
                {"xn": 3.0, "fraction": 0.20},
                {"xn": 7.0, "fraction": 0.30},
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
        id="test_signal_fees",
        contract_address="TESTTOKEN",
        timestamp=base_time,
        source="test",
        narrative="test signal for fees accounting"
    )


def test_fees_total_equals_sum_of_executions(
    runner_strategy, sample_signal, base_time
):
    """
    Test that fees_total_sol in portfolio_positions.csv equals
    sum of fees_sol from portfolio_executions.csv for the same position.
    
    Scenario:
    - Entry fee (network_fee)
    - Partial exit fee (swap + LP + network_fee)
    - Final exit fee (swap + LP + network_fee)
    
    Expected:
    - fees_total_sol == sum(fees_sol from all executions)
    """
    entry_price = 100.0
    
    # Create candles:
    # 1. Entry at 100
    # 2. Price reaches 3x (300) - first TP level
    # 3. Time stop triggers after 120 minutes
    
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
    
    # Run portfolio simulation
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
            "strategy": "test_runner_fees",
            "timestamp": base_time,
            "result": result
        }
    ]
    
    portfolio_result = engine.simulate(trades, strategy_name="test_runner_fees")
    
    # Find the position
    position = next(
        (p for p in portfolio_result.positions if p.signal_id == sample_signal.id),
        None
    )
    assert position is not None, "Position should exist"
    
    # Get fees_total_sol from position meta
    fees_total_sol_from_position = position.meta.get("fees_total_sol", 0.0)
    
    # Calculate sum of fees from partial_exits (executions)
    fees_from_partial_exits = sum(
        exit.get("fees_sol", 0.0) + exit.get("network_fee_sol", 0.0)
        for exit in position.meta.get("partial_exits", [])
    )
    
    # Add network_fee at entry
    network_fee_entry = position.meta.get("network_fee_sol", 0.0)
    # Subtract network_fee from exits (if already included)
    network_fee_exits_total = sum(
        exit.get("network_fee_sol", 0.0)
        for exit in position.meta.get("partial_exits", [])
    )
    network_fee_entry_only = network_fee_entry - network_fee_exits_total
    if network_fee_entry_only < 0:
        network_fee_entry_only = 0.0
    
    fees_total_from_executions = fees_from_partial_exits + network_fee_entry_only
    
    # Verify that fees_total_sol equals sum of fees from executions
    assert abs(fees_total_sol_from_position - fees_total_from_executions) < 1e-6, \
        f"fees_total_sol ({fees_total_sol_from_position}) should equal sum of fees from executions ({fees_total_from_executions})"
    
    # Also verify using Reporter (CSV export)
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        portfolio_results = {"test_runner_fees": portfolio_result}
        
        # Save CSV files
        reporter.save_portfolio_positions_table(portfolio_results)
        reporter.save_portfolio_executions_table(portfolio_results)
        
        # Load CSV files
        positions_path = os.path.join(tmpdir, "portfolio_positions.csv")
        executions_path = os.path.join(tmpdir, "portfolio_executions.csv")
        
        if os.path.exists(positions_path) and os.path.exists(executions_path):
            positions_df = pd.read_csv(positions_path)
            executions_df = pd.read_csv(executions_path)
            
            # Find position in CSV
            position_row = positions_df[positions_df["position_id"] == position.position_id]
            if not position_row.empty:
                fees_total_from_csv = float(position_row.iloc[0]["fees_total_sol"])
                
                # Sum fees from executions CSV
                position_executions = executions_df[executions_df["position_id"] == position.position_id]
                fees_sum_from_executions_csv = float(position_executions["fees_sol"].sum())
                
                # Verify
                assert abs(fees_total_from_csv - fees_sum_from_executions_csv) < 1e-6, \
                    f"fees_total_sol in CSV ({fees_total_from_csv}) should equal sum of fees_sol from executions CSV ({fees_sum_from_executions_csv})"


