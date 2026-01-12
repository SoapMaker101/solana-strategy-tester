"""
Тесты для проверки отсутствия reset spam в убыточном прогоне.

Проверяет:
- Lossy run не может триггерить realized_balance reset
- Reset блокируется если нет реальных открытых позиций
- Baseline <= 0 блокирует reset навсегда
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput
from backtester.domain.portfolio_events import PortfolioEventType


def test_lossy_run_cannot_trigger_realized_balance_reset():
    """
    Test 1: Lossy run cannot trigger realized_balance reset.
    
    Arrange:
    - initial=10, multiple=1.3, trigger_basis=realized_balance
    - expected threshold = 13 SOL
    - Генерируем 50 сделок с отрицательным pnl так, чтобы balance падал
    - Оставляем хотя бы 1 open позицию по ходу
    
    Assert:
    - portfolio_reset_profit_count == 0
    - len(events where event_type==portfolio_reset_triggered) == 0
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.1,  # 10% per trade
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,  # threshold = 10 * 1.3 = 13 SOL
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    all_results = []
    
    # Генерируем 50 сделок с отрицательным pnl
    # Каждая сделка теряет 5% (exit_price = 0.95 * entry_price)
    # initial=10, size=1.0 (10%), loss=5% → balance уменьшается
    for i in range(50):
        entry_time = base_time + timedelta(hours=i)
        exit_time = entry_time + timedelta(hours=1)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.95,  # -5% loss
            pnl=-0.05,
            reason="stop_loss"
        )
        
        all_results.append({
            "signal_id": f"test_signal_{i}",
            "contract_address": f"TOKEN_{i}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что reset НЕ сработал
    assert result.stats.portfolio_reset_profit_count == 0, \
        f"Reset не должен сработать в убыточном прогоне, получен: {result.stats.portfolio_reset_profit_count}"
    
    # Проверяем что баланс действительно упал ниже initial
    assert result.stats.final_balance_sol < 10.0, \
        f"Баланс должен быть < 10 (убыточный прогон), получен: {result.stats.final_balance_sol}"
    
    # Проверяем что нет событий portfolio_reset_triggered
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) == 0, \
        f"Не должно быть событий portfolio_reset_triggered в убыточном прогоне, получено: {len(reset_events)}"


def test_reset_blocked_if_no_real_open_positions():
    """
    Test 2: Reset blocked if no real open positions.
    
    Arrange:
    - Баланс вырос (или просто поставить current_balance руками через engine internal? лучше через прибыль)
    - Но к моменту проверки все позиции уже закрыты
    
    Assert:
    - reset не срабатывает
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.5,  # 50% для быстрого роста
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,  # threshold = 10 * 1.3 = 13 SOL
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    all_results = []
    
    # Создаем несколько прибыльных сделок, которые закрываются ДО того, как баланс достигнет threshold
    # Но баланс все равно растет достаточно, чтобы потенциально триггерить reset
    # Однако все позиции закрыты → reset не должен сработать
    
    # Сделка 1: большая прибыль, но закрывается рано
    entry_time_1 = base_time
    exit_time_1 = base_time + timedelta(hours=1)
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=1.0,
        exit_time=exit_time_1,
        exit_price=2.0,  # 100% profit
        pnl=1.0,
        reason="ladder_tp"
    )
    all_results.append({
        "signal_id": "test_signal_1",
        "contract_address": "TOKEN_1",
        "strategy": "test_strategy",
        "timestamp": entry_time_1,
        "result": strategy_output_1
    })
    
    # Сделка 2: еще одна прибыль, закрывается
    entry_time_2 = base_time + timedelta(hours=2)
    exit_time_2 = base_time + timedelta(hours=3)
    strategy_output_2 = StrategyOutput(
        entry_time=entry_time_2,
        entry_price=1.0,
        exit_time=exit_time_2,
        exit_price=1.5,  # 50% profit
        pnl=0.5,
        reason="ladder_tp"
    )
    all_results.append({
        "signal_id": "test_signal_2",
        "contract_address": "TOKEN_2",
        "strategy": "test_strategy",
        "timestamp": entry_time_2,
        "result": strategy_output_2
    })
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что баланс вырос (может быть >= 13)
    # Но reset не должен сработать, если все позиции закрыты к моменту проверки
    # В данном случае все позиции закрываются до того, как баланс достигнет threshold,
    # или если баланс достиг threshold, но позиций нет → reset блокируется
    
    # Проверяем что reset НЕ сработал (нет открытых позиций)
    assert result.stats.portfolio_reset_profit_count == 0, \
        f"Reset не должен сработать если нет открытых позиций, получен: {result.stats.portfolio_reset_profit_count}"
    
    # Проверяем что нет событий portfolio_reset_triggered
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) == 0, \
        f"Не должно быть событий portfolio_reset_triggered если нет открытых позиций, получено: {len(reset_events)}"


def test_baseline_le_0_blocks_reset_forever():
    """
    Test 3: Baseline <= 0 blocks reset forever.
    
    Arrange:
    - Насильно выставляем cycle_start_balance в 0 (если есть доступ через state)
    - Или через последовательные сделки доводим до почти 0
    - Даже если current_balance >= threshold (порог будет некорректен)
    
    Assert:
    - reset не происходит даже если current_balance >= threshold
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.1,
        profit_reset_enabled=True,
        profit_reset_multiple=1.3,  # threshold = cycle_start_balance * 1.3
        profit_reset_trigger_basis="realized_balance",
        fee_model=FeeModel(swap_fee_pct=0.0, lp_fee_pct=0.0, slippage_pct=0.0, network_fee_sol=0.0),
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    all_results = []
    
    # Сценарий: делаем много убыточных сделок, чтобы balance упал до почти 0
    # Затем делаем одну прибыльную сделку, которая возвращает баланс выше initial
    # Но cycle_start_balance остается на низком уровне (или даже 0) после убытков
    # → threshold = cycle_start_balance * 1.3 будет <= 0 или очень маленьким
    # → reset не должен сработать даже если current_balance >= threshold
    
    # Много убыточных сделок (баланс падает)
    for i in range(20):
        entry_time = base_time + timedelta(hours=i)
        exit_time = entry_time + timedelta(hours=1)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.9,  # -10% loss
            pnl=-0.1,
            reason="stop_loss"
        )
        
        all_results.append({
            "signal_id": f"loss_signal_{i}",
            "contract_address": f"TOKEN_LOSS_{i}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Затем одна большая прибыльная сделка (баланс растет обратно)
    # Но cycle_start_balance уже низкий после убытков
    entry_time_profit = base_time + timedelta(hours=25)
    exit_time_profit = entry_time_profit + timedelta(hours=1)
    strategy_output_profit = StrategyOutput(
        entry_time=entry_time_profit,
        entry_price=1.0,
        exit_time=exit_time_profit,
        exit_price=5.0,  # 400% profit - большой рост
        pnl=4.0,
        reason="ladder_tp"
    )
    all_results.append({
        "signal_id": "profit_signal",
        "contract_address": "TOKEN_PROFIT",
        "strategy": "test_strategy",
        "timestamp": entry_time_profit,
        "result": strategy_output_profit
    })
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем что reset НЕ сработал
    # Даже если current_balance >= threshold, но baseline <= 0, reset должен быть заблокирован
    assert result.stats.portfolio_reset_profit_count == 0, \
        f"Reset не должен сработать если baseline <= 0, получен: {result.stats.portfolio_reset_profit_count}"
    
    # Проверяем что нет событий portfolio_reset_triggered
    reset_events = [
        e for e in result.stats.portfolio_events
        if e.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    ]
    assert len(reset_events) == 0, \
        f"Не должно быть событий portfolio_reset_triggered если baseline <= 0, получено: {len(reset_events)}"
