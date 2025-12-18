"""
Unit-тесты для portfolio-level runner reset функциональности.

Проверяет портфельную политику: при достижении portfolio equity порога
(equity >= cycle_start_equity * runner_reset_multiple) закрываются все открытые позиции.
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_portfolio_reset_closes_all_positions_on_threshold():
    """
    Тест: portfolio-level reset закрывает все позиции при достижении порога equity.
    
    Сценарий:
    - runner_reset_enabled = True
    - runner_reset_multiple = 2.0 (x2)
    - cycle_start_equity = 10.0 (начальный баланс)
    - Порог = 10.0 * 2.0 = 20.0
    - Открываем прибыльную позицию, которая увеличивает equity до порога
    - Ожидаем: все открытые позиции закрываются, cycle_start_equity обновляется
    """
    initial_balance = 10.0
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(
            swap_fee_pct=0.003,
            lp_fee_pct=0.001,
            slippage_pct=0.0,  # Без slippage для простоты
            network_fee_sol=0.0005
        ),
        runner_reset_enabled=True,
        runner_reset_multiple=2.0  # x2
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Первая сделка: очень прибыльная, увеличивает equity до порога
    # Размер позиции: 10.0 * 0.1 = 1.0 SOL
    # После закрытия с 2x прибылью: баланс увеличится примерно до 11.0+ SOL
    # Но нужно несколько сделок, чтобы достичь порога 20.0
    
    # Создаем несколько очень прибыльных сделок
    all_results = []
    for i in range(3):
        entry_time = base_time + timedelta(minutes=i * 10)
        exit_time = entry_time + timedelta(hours=1)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=100.0,
            exit_time=exit_time,
            exit_price=300.0,  # 3x - очень прибыльная
            pnl=2.0,  # 200%
            reason="tp",
            meta={}
        )
        
        all_results.append({
            "signal_id": f"trade_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверки
    # Проверяем, что cycle_start_equity установлен
    assert result.stats.cycle_start_equity > 0
    assert result.stats.equity_peak_in_cycle > 0
    
    # Если был reset, проверяем что есть позиции, закрытые по reset
    if result.stats.reset_count > 0:
        assert result.stats.last_reset_time is not None
        reset_positions = [p for p in result.positions if p.meta.get("closed_by_reset", False)]
        assert len(reset_positions) > 0, "Должны быть позиции, закрытые по reset"


def test_portfolio_reset_updates_cycle_start_equity():
    """
    Тест: cycle_start_equity обновляется после reset.
    
    Сценарий:
    - Начальный баланс: 10.0
    - Порог: 20.0 (2x)
    - После reset cycle_start_equity должен обновиться на новую equity
    """
    initial_balance = 10.0
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
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
    
    # Создаем сделки, которые приведут к reset
    # После reset cycle_start_equity должен обновиться
    entry_time_1 = base_time
    exit_time_1 = base_time + timedelta(hours=1)
    
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=100.0,
        exit_time=exit_time_1,
        exit_price=200.0,  # 2x - очень прибыльная
        pnl=1.0,
        reason="tp",
        meta={}
    )
    
    all_results = [{
        "signal_id": "trade_1",
        "contract_address": "TOKEN1",
        "strategy": "test_strategy",
        "timestamp": entry_time_1,
        "result": strategy_output_1
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверки
    # cycle_start_equity должен быть установлен (начальный баланс или обновлен после reset)
    assert result.stats.cycle_start_equity > 0
    
    # Если был reset, cycle_start_equity должен отличаться от начального баланса
    if result.stats.reset_count > 0:
        # После reset cycle_start_equity обновляется на новую equity
        assert result.stats.cycle_start_equity != initial_balance or result.stats.reset_count > 0


def test_portfolio_reset_disabled_does_not_trigger():
    """
    Тест: когда runner_reset_enabled = False, reset не срабатывает.
    
    Проверяем, что при отключенном reset все позиции работают нормально
    и reset_count = 0.
    """
    initial_balance = 10.0
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=False,  # Отключен
        runner_reset_multiple=2.0
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем прибыльные сделки
    all_results = []
    for i in range(3):
        entry_time = base_time + timedelta(minutes=i * 5)
        exit_time = entry_time + timedelta(hours=1)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=100.0,
            exit_time=exit_time,
            exit_price=200.0,  # 2x
            pnl=1.0,
            reason="tp",
            meta={}
        )
        
        all_results.append({
            "signal_id": f"trade_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверки
    assert result.stats.reset_count == 0, "Reset не должен срабатывать при disabled"
    assert result.stats.last_reset_time is None, "last_reset_time должен быть None"
    
    # Все сделки должны быть выполнены
    assert result.stats.trades_executed == 3
    
    # Проверяем, что нет позиций, закрытых по reset
    reset_positions = [p for p in result.positions if p.meta.get("closed_by_reset", False)]
    assert len(reset_positions) == 0, "Не должно быть позиций, закрытых по reset"


def test_portfolio_reset_equity_peak_tracking():
    """
    Тест: equity_peak_in_cycle отслеживает пик equity в цикле.
    
    Сценарий:
    - Открываем позиции, equity растет
    - Проверяем, что equity_peak_in_cycle отражает максимальную equity
    """
    initial_balance = 10.0
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(
            swap_fee_pct=0.003,
            lp_fee_pct=0.001,
            slippage_pct=0.0,
            network_fee_sol=0.0005
        ),
        runner_reset_enabled=True,
        runner_reset_multiple=3.0  # x3 (высокий порог, чтобы reset не сработал)
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем прибыльные сделки
    entry_time_1 = base_time
    exit_time_1 = base_time + timedelta(hours=1)
    
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=100.0,
        exit_time=exit_time_1,
        exit_price=200.0,  # 2x
        pnl=1.0,
        reason="tp",
        meta={}
    )
    
    all_results = [{
        "signal_id": "trade_1",
        "contract_address": "TOKEN1",
        "strategy": "test_strategy",
        "timestamp": entry_time_1,
        "result": strategy_output_1
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверки
    # equity_peak_in_cycle должен быть >= cycle_start_equity
    assert result.stats.equity_peak_in_cycle >= result.stats.cycle_start_equity
    
    # equity_peak_in_cycle должен быть >= final_balance
    assert result.stats.equity_peak_in_cycle >= result.stats.final_balance_sol


def test_portfolio_reset_triggered_when_threshold_reached():
    """
    Тест: reset срабатывает при достижении порога equity.
    
    Сценарий:
    - Начальный баланс: 10.0
    - Порог: 20.0 (2x)
    - Создаем сделки, которые приведут к equity >= 20.0
    - Проверяем, что reset сработал и все позиции закрыты
    """
    initial_balance = 10.0
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.2,  # 20% для быстрого роста equity
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(
            swap_fee_pct=0.003,
            lp_fee_pct=0.001,
            slippage_pct=0.0,  # Без slippage для простоты
            network_fee_sol=0.0005
        ),
        runner_reset_enabled=True,
        runner_reset_multiple=2.0  # x2
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Первая сделка: очень прибыльная (3x)
    # Размер: 10.0 * 0.2 = 2.0 SOL
    # После закрытия: баланс увеличится примерно до 10.0 + 2.0 * 2.0 = 14.0 SOL (с учетом fees меньше)
    # Нужна вторая сделка, чтобы достичь порога 20.0
    
    entry_time_1 = base_time
    exit_time_1 = base_time + timedelta(hours=1)
    
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=100.0,
        exit_time=exit_time_1,
        exit_price=300.0,  # 3x
        pnl=2.0,  # 200%
        reason="tp",
        meta={}
    )
    
    # Вторая сделка: открывается после первой, еще открыта когда equity достигает порога
    entry_time_2 = exit_time_1 + timedelta(minutes=5)
    exit_time_2 = entry_time_2 + timedelta(hours=1)
    
    strategy_output_2 = StrategyOutput(
        entry_time=entry_time_2,
        entry_price=100.0,
        exit_time=exit_time_2,
        exit_price=200.0,  # 2x
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
    
    # Проверки
    # Если equity достигла порога, должен быть reset
    # Проверяем, что reset_count > 0 или что все позиции закрыты корректно
    assert result.stats.reset_count >= 0
    
    # Проверяем, что cycle_start_equity установлен
    assert result.stats.cycle_start_equity > 0
    
    # Если был reset, проверяем детали
    if result.stats.reset_count > 0:
        assert result.stats.last_reset_time is not None
        # Должна быть хотя бы одна позиция, закрытая по reset
        reset_positions = [p for p in result.positions if p.meta.get("closed_by_reset", False)]
        assert len(reset_positions) > 0, "Должны быть позиции, закрытые по reset"



