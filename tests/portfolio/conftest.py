"""
Общие фикстуры для тестов портфельного слоя.
"""
import pytest
from datetime import datetime, timezone
from backtester.domain.portfolio import PortfolioConfig, FeeModel


@pytest.fixture
def fee_model():
    """Создает модель комиссий с дефолтными значениями."""
    return FeeModel()


@pytest.fixture
def portfolio_config(fee_model):
    """Создает конфигурацию портфеля с дефолтными значениями."""
    return PortfolioConfig(fee_model=fee_model)


@pytest.fixture
def custom_portfolio_config():
    """Создает конфигурацию портфеля с кастомными значениями."""
    fee_model = FeeModel(
        swap_fee_pct=0.002,
        lp_fee_pct=0.0005,
        slippage_pct=0.05,
        network_fee_sol=0.0001
    )
    return PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.15,
        max_exposure=0.6,
        max_open_positions=5,
        fee_model=fee_model,
        backtest_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        backtest_end=datetime(2024, 12, 31, tzinfo=timezone.utc),
        profit_reset_enabled=False
    )




























