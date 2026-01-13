"""
Тесты для проверки, что profit_reset_trigger_basis отражается в событиях portfolio_reset_triggered.
"""
import pytest
import json
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput
from backtester.domain.portfolio_events import PortfolioEventType


def test_profit_reset_realized_balance_reflected_in_events():
    """
    Тест: при profit_reset_trigger_basis="realized_balance" в событиях записывается trigger_basis="realized_balance".
    
    Arrange:
    - initial=10, multiple=1.2 → порог = 12 SOL
    - trigger_basis="realized_balance"
    - создаем сценарий гарантирующий reset
    
    Assert:
    - есть portfolio_reset_triggered событие
    - в meta_json события trigger_basis="realized_balance"
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,  # 50% на сделку для гарантированного превышения порога
        max_exposure=1.0,
        profit_reset_enabled=True,
        profit_reset_multiple=1.2,  # Порог 12 SOL
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),  # Без комиссий
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=1)
    
    # Создаем позицию с большой прибылью, которая гарантированно превысит порог
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=3.0,  # 200% profit → balance станет 10 + 5*2 = 20 SOL (порог 12)
        pnl=2.0,
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
    
    # Проверяем что reset сработал
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) > 0, "Должно быть хотя бы одно portfolio_reset_triggered событие"
    
    # Проверяем trigger_basis в meta
    for event in reset_events:
        assert event.meta is not None, "Meta должно быть заполнено"
        trigger_basis = event.meta.get("trigger_basis")
        assert trigger_basis == "realized_balance", \
            f"trigger_basis должен быть 'realized_balance', получен '{trigger_basis}'"
        
        # Проверяем что не equity_peak
        assert trigger_basis != "equity_peak", \
            "trigger_basis НЕ должен быть 'equity_peak' при конфиге 'realized_balance'"


def test_profit_reset_equity_peak_reflected_in_events():
    """
    Тест: при profit_reset_trigger_basis="equity_peak" в событиях записывается trigger_basis="equity_peak".
    
    Arrange:
    - initial=10, multiple=1.2 → порог = 12 SOL
    - trigger_basis="equity_peak"
    - создаем сценарий гарантирующий reset
    
    Assert:
    - есть portfolio_reset_triggered событие
    - в meta_json события trigger_basis="equity_peak"
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,
        max_exposure=1.0,
        profit_reset_enabled=True,
        profit_reset_multiple=1.2,
        profit_reset_trigger_basis="equity_peak",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=1)
    
    # Создаем позицию с большой прибылью
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=3.0,  # 200% profit
        pnl=2.0,
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
    
    # Проверяем что reset сработал
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) > 0, "Должно быть хотя бы одно portfolio_reset_triggered событие"
    
    # Проверяем trigger_basis в meta
    for event in reset_events:
        assert event.meta is not None, "Meta должно быть заполнено"
        trigger_basis = event.meta.get("trigger_basis")
        assert trigger_basis == "equity_peak", \
            f"trigger_basis должен быть 'equity_peak', получен '{trigger_basis}'"
