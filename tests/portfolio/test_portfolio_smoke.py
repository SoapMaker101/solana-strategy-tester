"""
Smoke tests для портфельного слоя.

Проверяет базовую функциональность:
- Импорт модулей
- Создание экземпляров классов
- Базовые операции без реальной симуляции
"""
import pytest
from datetime import datetime, timezone

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine,
    PortfolioStats,
    PortfolioResult
)


def test_import_fee_model():
    """Проверяет, что FeeModel можно импортировать и создать."""
    fee_model = FeeModel()
    assert fee_model is not None
    assert fee_model.swap_fee_pct == 0.003
    assert fee_model.lp_fee_pct == 0.001
    assert fee_model.slippage_pct == 0.10
    assert fee_model.network_fee_sol == 0.0005


def test_fee_model_custom():
    """Проверяет создание FeeModel с кастомными параметрами."""
    fee_model = FeeModel(
        swap_fee_pct=0.002,
        lp_fee_pct=0.0005,
        slippage_pct=0.05,
        network_fee_sol=0.0001
    )
    assert fee_model.swap_fee_pct == 0.002
    assert fee_model.lp_fee_pct == 0.0005


def test_fee_model_effective_fee():
    """Проверяет метод effective_fee_pct."""
    fee_model = FeeModel()
    # Тест с ненулевым номиналом
    fee = fee_model.effective_fee_pct(10.0)
    assert fee > 0
    assert isinstance(fee, float)
    # Тест с нулевым номиналом (должен вернуть 0 или handle gracefully)
    fee_zero = fee_model.effective_fee_pct(0.0)
    assert isinstance(fee_zero, float)


def test_import_portfolio_config():
    """Проверяет, что PortfolioConfig можно импортировать и создать."""
    config = PortfolioConfig()
    assert config is not None
    assert config.initial_balance_sol == 10.0
    assert config.allocation_mode == "dynamic"
    assert config.percent_per_trade == 0.1
    assert config.max_exposure == 0.5
    assert config.max_open_positions == 10
    assert isinstance(config.fee_model, FeeModel)


def test_portfolio_config_custom():
    """Проверяет создание PortfolioConfig с кастомными параметрами."""
    fee_model = FeeModel()
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="fixed",
        percent_per_trade=0.2,
        max_exposure=0.8,
        max_open_positions=20,
        fee_model=fee_model,
        backtest_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        backtest_end=datetime(2024, 12, 31, tzinfo=timezone.utc)
    )
    assert config.initial_balance_sol == 100.0
    assert config.allocation_mode == "fixed"
    assert config.backtest_start is not None
    assert config.backtest_end is not None


def test_import_portfolio_engine():
    """Проверяет, что PortfolioEngine можно импортировать и создать."""
    config = PortfolioConfig()
    engine = PortfolioEngine(config)
    assert engine is not None
    assert engine.config == config


def test_portfolio_engine_with_custom_config():
    """Проверяет создание PortfolioEngine с кастомной конфигурацией."""
    fee_model = FeeModel(swap_fee_pct=0.001)
    config = PortfolioConfig(
        initial_balance_sol=50.0,
        allocation_mode="dynamic",
        fee_model=fee_model
    )
    engine = PortfolioEngine(config)
    assert engine.config.initial_balance_sol == 50.0
    assert engine.config.fee_model.swap_fee_pct == 0.001


def test_portfolio_stats_dataclass():
    """Проверяет создание PortfolioStats."""
    stats = PortfolioStats(
        final_balance_sol=12.5,
        total_return_pct=0.25,
        max_drawdown_pct=-0.15,
        trades_executed=5,
        trades_skipped_by_risk=2
    )
    assert stats.final_balance_sol == 12.5
    assert stats.total_return_pct == 0.25
    assert stats.trades_executed == 5
    assert stats.trades_skipped_by_risk == 2


def test_portfolio_result_dataclass():
    """Проверяет создание PortfolioResult."""
    stats = PortfolioStats(
        final_balance_sol=10.0,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        trades_executed=0,
        trades_skipped_by_risk=0
    )
    result = PortfolioResult(
        equity_curve=[],
        positions=[],
        stats=stats
    )
    assert result.stats == stats
    assert result.equity_curve == []
    assert result.positions == []


def test_fixtures_work(fee_model, portfolio_config):
    """Проверяет, что фикстуры из conftest.py работают."""
    assert fee_model is not None
    assert portfolio_config is not None
    assert portfolio_config.fee_model == fee_model


def test_custom_fixture_work(custom_portfolio_config):
    """Проверяет, что кастомная фикстура работает."""
    assert custom_portfolio_config.initial_balance_sol == 100.0
    assert custom_portfolio_config.max_open_positions == 5
    assert custom_portfolio_config.fee_model.swap_fee_pct == 0.002


















