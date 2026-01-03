"""
Unit тесты для парсинга PortfolioConfig из YAML в BacktestRunner.

Проверяет, что метод _build_portfolio_config() корректно парсит
поле max_hold_minutes из YAML конфига.
"""
import pytest
from unittest.mock import Mock

from backtester.application.runner import BacktestRunner


@pytest.fixture
def minimal_runner():
    """Создает минимальный BacktestRunner для тестирования (без реальных файлов)."""
    # Создаем моки для зависимостей
    signal_loader = Mock()
    price_loader = Mock()
    reporter = Mock()
    strategies = [Mock()]
    
    runner = BacktestRunner(
        signal_loader=signal_loader,
        price_loader=price_loader,
        reporter=reporter,
        strategies=strategies,
        global_config={},
    )
    return runner


def test_portfolio_config_defaults_no_max_hold_minutes(minimal_runner):
    """Тест: конфиг без поля max_hold_minutes использует дефолт None."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "allocation_mode": "fixed",
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    # Проверяем дефолт для max_hold_minutes
    assert config.max_hold_minutes is None


def test_portfolio_config_with_max_hold_minutes(minimal_runner):
    """Тест: конфиг с полем max_hold_minutes корректно парсится."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "allocation_mode": "fixed",
            "max_hold_minutes": 4320,
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    # Проверяем, что поле применено
    assert config.max_hold_minutes == 4320


def test_portfolio_config_max_hold_minutes_none(minimal_runner):
    """Тест: max_hold_minutes: null корректно парсится в None."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "max_hold_minutes": None,
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    assert config.max_hold_minutes is None


def test_portfolio_config_max_hold_minutes_zero(minimal_runner):
    """Тест: max_hold_minutes: 0 корректно парсится."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "max_hold_minutes": 0,
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    assert config.max_hold_minutes == 0




def test_portfolio_config_max_hold_minutes_string_int(minimal_runner):
    """Тест: max_hold_minutes как строка "4320" корректно приводится к int."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "max_hold_minutes": "4320",  # YAML может парситься как строка
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    # int("4320") должно работать
    assert config.max_hold_minutes == 4320
    assert isinstance(config.max_hold_minutes, int)


def test_portfolio_config_backward_compatibility(minimal_runner):
    """Тест: старые конфиги без max_hold_minutes работают (обратная совместимость)."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "allocation_mode": "fixed",
            "percent_per_trade": 0.1,
            "max_exposure": 0.5,
            "max_open_positions": 10,
            # Нет max_hold_minutes
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    # Проверяем, что дефолты применены и остальные поля работают
    assert config.max_hold_minutes is None
    assert config.initial_balance_sol == 10.0
    assert config.allocation_mode == "fixed"
    assert config.percent_per_trade == 0.1


def test_portfolio_config_full_example(minimal_runner):
    """Тест: полный пример конфига с max_hold_minutes."""
    minimal_runner.global_config = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "allocation_mode": "dynamic",
            "percent_per_trade": 0.01,
            "max_exposure": 0.95,
            "max_open_positions": 100,
            "profit_reset_enabled": True,
            "profit_reset_multiple": 1.3,
            "max_hold_minutes": 4320,  # 30 дней в минутах
        }
    }
    
    config = minimal_runner._build_portfolio_config()
    
    # Проверяем все поля
    assert config.initial_balance_sol == 10.0
    assert config.allocation_mode == "dynamic"
    assert config.max_hold_minutes == 4320
    assert config.profit_reset_enabled is True
    assert config.profit_reset_multiple == 1.3

