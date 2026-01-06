"""
Smoke tests for imports to catch import errors early.
"""


def test_import_portfolio_config():
    """Test that PortfolioConfig can be imported without errors."""
    from backtester.domain.portfolio import PortfolioConfig, FeeModel  # noqa: F401


def test_import_portfolio_events():
    """Test that PortfolioEvent can be imported without errors."""
    from backtester.domain.portfolio_events import PortfolioEvent, PortfolioEventType  # noqa: F401


def test_import_models():
    """Test that StrategyOutput can be imported without errors."""
    from backtester.domain.models import StrategyOutput  # noqa: F401










