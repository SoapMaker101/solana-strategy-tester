"""
Smoke tests для портфельного слоя.

Проверяет базовую функциональность:
- Импорт модулей
- Создание экземпляров классов
- Минимальный replay run
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine,
)
from backtester.domain.portfolio_replay import PortfolioReplay
from backtester.domain.strategy_trade_blueprint import (
    StrategyTradeBlueprint,
    FinalExitBlueprint,
)


def test_import_modules():
    """Проверяет, что основные модули можно импортировать."""
    from backtester.domain.portfolio import PortfolioConfig, FeeModel, PortfolioEngine
    from backtester.domain.portfolio_replay import PortfolioReplay
    from backtester.domain.strategy_trade_blueprint import StrategyTradeBlueprint
    
    # Проверка, что классы доступны
    assert PortfolioConfig is not None
    assert FeeModel is not None
    assert PortfolioEngine is not None
    assert PortfolioReplay is not None
    assert StrategyTradeBlueprint is not None


def test_basic_instantiation():
    """Проверяет базовое создание основных классов."""
    # FeeModel
    fee_model = FeeModel()
    assert fee_model is not None
    
    # PortfolioConfig
    config = PortfolioConfig()
    assert config is not None
    assert isinstance(config.fee_model, FeeModel)
    
    # PortfolioEngine
    engine = PortfolioEngine(config)
    assert engine is not None
    assert engine.config == config


def test_minimal_replay_run():
    """Проверяет минимальный replay run с одним blueprint."""
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем минимальный blueprint
    blueprint = StrategyTradeBlueprint(
        signal_id="smoke_test_signal",
        strategy_id="test_strategy",
        contract_address="TOKEN_TEST",
        entry_time=base_time,
        entry_price_raw=100.0,
        entry_mcap_proxy=None,
        partial_exits=[],
        final_exit=FinalExitBlueprint(
            timestamp=base_time + timedelta(hours=1),
            reason="all_levels_hit"
        ),
        realized_multiple=1.0,
        max_xn_reached=1.0,
        reason="all_levels_hit"
    )
    
    # Создаем минимальный конфиг
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="fixed",
        percent_per_trade=0.1,
        fee_model=FeeModel(),
    )
    
    # Запускаем replay
    result = PortfolioReplay.replay(
        blueprints=[blueprint],
        portfolio_config=config,
        market_data=None
    )
    
    # Базовые проверки: replay не упал и вернул результат
    assert result is not None
    assert result.stats is not None
    assert len(result.positions) == 1, "Должна быть создана одна позиция"



