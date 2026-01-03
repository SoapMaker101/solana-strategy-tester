"""
Unit-тесты для execution profiles.

Проверяет:
- Round-trip сделки без движения цены (realistic и stress профили)
- Правильность применения slippage к ценам
- Корректность расчета fees
"""

import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput
from backtester.domain.execution_model import ExecutionProfileConfig, ExecutionModel


def test_round_trip_realistic_profile():
    """
    Test 1: Round-trip no price move (realistic)
    
    Ожидание: потеря в пределах 2-8% от нотионала
    realistic: base 3%, entry 1.0, exit_timeout 0.3 → exit slippage 0.9%
    round-trip slippage factor ~ (1-0.009)/(1+0.03) ≈ 0.961 → ~-3.9% + fees ~-0.8% => ~-4.7%
    """
    initial_balance = 10.0
    position_size = 0.2  # 2% от баланса
    
    # Создаем realistic профиль
    realistic_profile = ExecutionProfileConfig(
        base_slippage_pct=0.03,  # 3%
        slippage_multipliers={
            "entry": 1.0,
            "exit_tp": 0.7,
            "exit_sl": 1.2,
            "exit_timeout": 0.3,
            "exit_manual": 0.5,
        }
    )
    
    fee_model = FeeModel(
        swap_fee_pct=0.003,
        lp_fee_pct=0.001,
        slippage_pct=None,  # Используем profiles
        network_fee_sol=0.0005,
        profiles={"realistic": realistic_profile}
    )
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="fixed",
        percent_per_trade=0.02,  # 2% на сделку
        max_exposure=0.8,
        max_open_positions=10,
        fee_model=fee_model,
        execution_profile="realistic"
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем сделку без движения цены
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.0,  # Нет движения цены
        pnl=0.0,
        reason="max_hold_minutes"
    )
    
    all_results = [{
        "signal_id": "test_signal_1",
        "contract_address": "TESTTOKEN123",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверки
    assert result.stats.trades_executed == 1
    assert len(result.positions) == 1
    
    pos = result.positions[0]
    
    # Проверяем RAW цены (должны совпадать со StrategyOutput)
    assert pos.entry_price == 1.0, f"entry_price должен быть RAW ценой (1.0), получено: {pos.entry_price}"
    assert pos.exit_price == 1.0, f"exit_price должен быть RAW ценой (1.0), получено: {pos.exit_price}"
    
    # Проверяем исполненные цены (с slippage)
    assert "exec_entry_price" in pos.meta
    assert "exec_exit_price" in pos.meta
    exec_entry_price = pos.meta["exec_entry_price"]
    exec_exit_price = pos.meta["exec_exit_price"]
    
    # Entry slippage увеличивает цену (для long: платим больше)
    assert exec_entry_price > 1.0, f"exec_entry_price должен быть больше raw (1.0), получено: {exec_entry_price}"
    
    # Exit slippage уменьшает цену (для long: получаем меньше)
    assert exec_exit_price < 1.0, f"exec_exit_price должен быть меньше raw (1.0), получено: {exec_exit_price}"
    
    # Проверяем метаданные
    assert "slippage_entry_pct" in pos.meta
    assert "slippage_exit_pct" in pos.meta
    assert "execution_profile" in pos.meta
    assert pos.meta["execution_profile"] == "realistic"
    
    # Проверяем что потери в разумных пределах
    # Потери считаем от размера позиции, а не от общего баланса
    final_balance = result.stats.final_balance_sol
    total_loss = initial_balance - final_balance
    position_size = initial_balance * config.percent_per_trade  # 10.0 * 0.02 = 0.2 SOL
    loss_pct_of_position = total_loss / position_size if position_size > 0 else 0.0
    
    # Ожидаем потери от 2% до 10% от размера позиции (реалистично для round-trip с fees)
    assert 0.02 <= loss_pct_of_position <= 0.10, f"Loss {loss_pct_of_position:.2%} of position outside expected range [2%, 10%]"
    
    # Проверяем что PnL отрицательный (round-trip без движения цены = убыток)
    assert pos.pnl_pct < 0


def test_round_trip_stress_profile():
    """
    Test 2: Round-trip no price move (stress)
    
    Ожидание: потери 10-20% (не 20%+)
    stress: base 10%, entry 1.0, exit_timeout 0.2 → exit slippage 2%
    """
    initial_balance = 10.0
    
    # Создаем stress профиль
    stress_profile = ExecutionProfileConfig(
        base_slippage_pct=0.10,  # 10%
        slippage_multipliers={
            "entry": 1.0,
            "exit_tp": 0.6,
            "exit_sl": 1.3,
            "exit_timeout": 0.2,
            "exit_manual": 0.5,
        }
    )
    
    fee_model = FeeModel(
        swap_fee_pct=0.003,
        lp_fee_pct=0.001,
        slippage_pct=None,
        network_fee_sol=0.0005,
        profiles={"stress": stress_profile}
    )
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="fixed",
        percent_per_trade=0.02,
        max_exposure=0.8,
        max_open_positions=10,
        fee_model=fee_model,
        execution_profile="stress"
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.0,
        pnl=0.0,
        reason="max_hold_minutes"
    )
    
    all_results = [{
        "signal_id": "test_signal_1",
        "contract_address": "TESTTOKEN123",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    assert result.stats.trades_executed == 1
    
    final_balance = result.stats.final_balance_sol
    total_loss = initial_balance - final_balance
    position_size = initial_balance * config.percent_per_trade
    loss_pct_of_position = total_loss / position_size if position_size > 0 else 0.0
    
    # Ожидаем потери от 10% до 20% от размера позиции (stress тест)
    assert 0.10 <= loss_pct_of_position <= 0.20, f"Loss {loss_pct_of_position:.2%} of position outside expected range [10%, 20%]"


def test_slippage_applied_once():
    """
    Test 3: Slippage applied once
    
    Проверяем что slippage применяется ровно один раз на вход и один раз на выход.
    """
    realistic_profile = ExecutionProfileConfig(
        base_slippage_pct=0.03,
        slippage_multipliers={
            "entry": 1.0,
            "exit_tp": 0.7,
            "exit_sl": 1.2,
            "exit_timeout": 0.3,
            "exit_manual": 0.5,
        }
    )
    
    fee_model = FeeModel(
        swap_fee_pct=0.003,
        lp_fee_pct=0.001,
        slippage_pct=None,
        network_fee_sol=0.0005,
        profiles={"realistic": realistic_profile}
    )
    
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.1,
        max_exposure=0.8,
        max_open_positions=10,
        fee_model=fee_model,
        execution_profile="realistic"
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.05,  # 5% прибыль
        pnl=0.05,
        reason="ladder_tp"
    )
    
    all_results = [{
        "signal_id": "test_signal_1",
        "contract_address": "TESTTOKEN123",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    assert result.stats.trades_executed == 1
    pos = result.positions[0]
    
    # Проверяем RAW цены (должны совпадать со StrategyOutput)
    assert pos.entry_price == 1.0, f"entry_price должен быть RAW ценой (1.0), получено: {pos.entry_price}"
    assert pos.exit_price == 1.05, f"exit_price должен быть RAW ценой (1.05), получено: {pos.exit_price}"
    
    # Проверяем исполненные цены (с slippage)
    assert "exec_entry_price" in pos.meta
    assert "exec_exit_price" in pos.meta
    exec_entry_price = pos.meta["exec_entry_price"]
    exec_exit_price = pos.meta["exec_exit_price"]
    
    # Entry slippage увеличивает цену (для long: платим больше)
    assert exec_entry_price > 1.0, f"exec_entry_price должен быть больше raw (1.0), получено: {exec_entry_price}"
    
    # Exit slippage уменьшает цену (для long: получаем меньше)
    assert exec_exit_price < 1.05, f"exec_exit_price должен быть меньше raw (1.05), получено: {exec_exit_price}"
    
    # Проверяем метаданные slippage
    entry_slippage = pos.meta["slippage_entry_pct"]
    exit_slippage = pos.meta["slippage_exit_pct"]
    
    # Entry slippage должен быть ~3% (base * 1.0)
    assert abs(entry_slippage - 0.03) < 0.001, f"entry_slippage должен быть ~0.03, получено: {entry_slippage}"
    
    # Exit slippage для TP должен быть ~2.1% (base * 0.7)
    assert abs(exit_slippage - 0.021) < 0.001, f"exit_slippage должен быть ~0.021, получено: {exit_slippage}"
    
    # Проверяем, что slippage применен один раз:
    # exec_entry_price = raw_entry_price * (1 + entry_slippage)
    expected_exec_entry = 1.0 * (1 + entry_slippage)
    assert abs(exec_entry_price - expected_exec_entry) < 0.0001, \
        f"exec_entry_price должен быть raw * (1 + slippage) = {expected_exec_entry}, получено: {exec_entry_price}"
    
    # exec_exit_price = raw_exit_price * (1 - exit_slippage) для long
    expected_exec_exit = 1.05 * (1 - exit_slippage)
    assert abs(exec_exit_price - expected_exec_exit) < 0.0001, \
        f"exec_exit_price должен быть raw * (1 - slippage) = {expected_exec_exit}, получено: {exec_exit_price}"


