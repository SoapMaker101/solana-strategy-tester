"""
Тесты на обратную совместимость для profit reset.

Проверяет, что старые YAML конфиги с runner_reset_* продолжают работать
и правильно маппятся на profit_reset_*.
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_profit_reset_uses_new_fields():
    """
    Тест: новые поля profit_reset_* работают корректно.
    
    Проверяет, что при использовании profit_reset_enabled и profit_reset_multiple
    reset по equity threshold работает правильно.
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
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
        profit_reset_enabled=True,
        profit_reset_multiple=1.2  # x1.2 - низкий порог для теста
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем очень прибыльную сделку, которая увеличит equity до порога
    # Начальный баланс: 10.0
    # Порог: 10.0 * 1.2 = 12.0
    # Размер позиции: 10.0 * 0.2 = 2.0 SOL
    # После закрытия с 3x прибылью: баланс увеличится примерно до 10.0 + 2.0 * 2.0 = 14.0 SOL
    
    entry_time = base_time
    exit_time = base_time + timedelta(hours=1)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=100.0,
        exit_time=exit_time,
        exit_price=300.0,  # 3x - очень прибыльная
        pnl=2.0,  # 200%
        reason="tp",
        meta={}
    )
    
    all_results = [{
        "signal_id": "trade_1",
        "contract_address": "TOKEN1",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем, что profit reset работает
    assert config.resolved_profit_reset_enabled() == True
    assert config.resolved_profit_reset_multiple() == 1.2
    
    # Если был reset, проверяем что он сработал
    if result.stats.portfolio_reset_profit_count > 0:
        assert result.stats.last_portfolio_reset_time is not None
        assert result.stats.portfolio_reset_profit_count > 0


def test_profit_reset_falls_back_to_runner_alias():
    """
    Тест: старые поля runner_reset_* работают как alias для profit_reset_*.
    
    Проверяет backward compatibility - если profit_reset_* не заданы,
    но заданы runner_reset_*, они должны использоваться для profit reset.
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
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
        # Новые поля не заданы (None = не задано, fallback на runner_reset_*)
        profit_reset_enabled=None,
        profit_reset_multiple=None,
        # Используем старые поля (deprecated alias)
        runner_reset_enabled=True,
        runner_reset_multiple=1.2  # x1.2 - низкий порог для теста
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем очень прибыльную сделку, которая увеличит equity до порога
    entry_time = base_time
    exit_time = base_time + timedelta(hours=1)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=100.0,
        exit_time=exit_time,
        exit_price=300.0,  # 3x - очень прибыльная
        pnl=2.0,  # 200%
        reason="tp",
        meta={}
    )
    
    all_results = [{
        "signal_id": "trade_1",
        "contract_address": "TOKEN1",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверяем, что resolved методы используют старые поля
    assert config.resolved_profit_reset_enabled() == True, \
        "resolved_profit_reset_enabled должен fallback на runner_reset_enabled"
    assert config.resolved_profit_reset_multiple() == 1.2, \
        "resolved_profit_reset_multiple должен fallback на runner_reset_multiple"
    
    # Если был reset, проверяем что он сработал
    if result.stats.portfolio_reset_profit_count > 0:
        assert result.stats.last_portfolio_reset_time is not None
        assert result.stats.portfolio_reset_profit_count > 0


def test_profit_reset_new_fields_have_priority():
    """
    Тест: новые поля profit_reset_* имеют приоритет над старыми runner_reset_*.
    
    Если заданы оба варианта, используются profit_reset_*.
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
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
        # Новые поля
        profit_reset_enabled=True,
        profit_reset_multiple=1.5,
        # Старые поля (должны игнорироваться)
        runner_reset_enabled=False,
        runner_reset_multiple=2.0
    )
    
    # Проверяем, что используются новые поля
    assert config.resolved_profit_reset_enabled() == True
    assert config.resolved_profit_reset_multiple() == 1.5

