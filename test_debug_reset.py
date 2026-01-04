#!/usr/bin/env python
"""Temporary debug script to understand reset behavior"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone, timedelta
from backtester.domain.portfolio import PortfolioConfig, PortfolioEngine, FeeModel
from backtester.domain.models import StrategyOutput

initial_balance = 10.0

config = PortfolioConfig(
    initial_balance_sol=initial_balance,
    allocation_mode="dynamic",
    percent_per_trade=0.2,
    max_exposure=1.0,
    max_open_positions=10,
    fee_model=FeeModel(
        swap_fee_pct=0.003,
        lp_fee_pct=0.001,
        slippage_pct=0.0,
        network_fee_sol=0.0005
    ),
    runner_reset_enabled=True,
    runner_reset_multiple=2.0
)

engine = PortfolioEngine(config)

base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

entry_time_1 = base_time
exit_time_1 = base_time + timedelta(hours=1)

strategy_output_1 = StrategyOutput(
    entry_time=entry_time_1,
    entry_price=100.0,
    exit_time=exit_time_1,
    exit_price=300.0,
    pnl=2.0,
    reason="tp",
    meta={}
)

entry_time_2 = exit_time_1 + timedelta(minutes=5)
exit_time_2 = entry_time_2 + timedelta(hours=1)

strategy_output_2 = StrategyOutput(
    entry_time=entry_time_2,
    entry_price=100.0,
    exit_time=exit_time_2,
    exit_price=200.0,
    pnl=1.0,
    reason="tp",
    meta={}
)

all_results = [
    {
        "signal_id": "trade_1",
        "contract_address": "TOKEN1",
        "strategy": "test_strategy",
        "timestamp": entry_time_1,
        "result": strategy_output_1
    },
    {
        "signal_id": "trade_2",
        "contract_address": "TOKEN2",
        "strategy": "test_strategy",
        "timestamp": entry_time_2,
        "result": strategy_output_2
    }
]

result = engine.simulate(all_results, strategy_name="test_strategy")

print(f"\nReset count: {result.stats.reset_count}")
print(f"Positions count: {len(result.positions)}")
for i, pos in enumerate(result.positions):
    print(f"  Position {i}: signal_id={pos.signal_id}, closed_by_reset={pos.meta.get('closed_by_reset', False)}, "
          f"triggered_portfolio_reset={pos.meta.get('triggered_portfolio_reset', False)}")
    
reset_positions = [p for p in result.positions if p.meta.get("closed_by_reset", False)]
print(f"\nReset positions count: {len(reset_positions)}")






















