"""
Тесты для проверки парсинга profit_reset_trigger_basis из YAML конфигурации.
"""
import pytest
import yaml
from pathlib import Path
from backtester.application.runner import BacktestRunner
from backtester.domain.portfolio import PortfolioConfig


def test_yaml_parsing_profit_reset_trigger_basis_realized_balance(tmp_path):
    """Проверяет, что profit_reset_trigger_basis: realized_balance читается из YAML."""
    # Создаем временный YAML файл
    yaml_content = """
portfolio:
  initial_balance_sol: 10.0
  allocation_mode: "dynamic"
  percent_per_trade: 0.1
  profit_reset_enabled: true
  profit_reset_multiple: 1.3
  profit_reset_trigger_basis: "realized_balance"
"""
    yaml_path = tmp_path / "test_config.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    
    # Загружаем YAML
    with yaml_path.open("r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f) or {}
    
    # Создаем PortfolioConfig через BacktestRunner (как в реальном прогоне)
    runner = BacktestRunner(
        signal_loader=None,  # Не используется в этом тесте
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config=config_dict,
    )
    
    portfolio_config = runner._build_portfolio_config()
    
    # Проверяем, что profit_reset_trigger_basis прочитан
    assert portfolio_config.profit_reset_trigger_basis == "realized_balance"
    
    # Проверяем resolved метод
    assert portfolio_config.resolved_profit_reset_trigger_basis() == "realized_balance"


def test_yaml_parsing_profit_reset_trigger_basis_equity_peak(tmp_path):
    """Проверяет, что profit_reset_trigger_basis: equity_peak читается из YAML."""
    # Создаем временный YAML файл
    yaml_content = """
portfolio:
  initial_balance_sol: 10.0
  allocation_mode: "dynamic"
  percent_per_trade: 0.1
  profit_reset_enabled: true
  profit_reset_multiple: 1.3
  profit_reset_trigger_basis: "equity_peak"
"""
    yaml_path = tmp_path / "test_config.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    
    # Загружаем YAML
    with yaml_path.open("r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f) or {}
    
    # Создаем PortfolioConfig
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config=config_dict,
    )
    
    portfolio_config = runner._build_portfolio_config()
    
    # Проверяем, что profit_reset_trigger_basis прочитан
    assert portfolio_config.profit_reset_trigger_basis == "equity_peak"
    assert portfolio_config.resolved_profit_reset_trigger_basis() == "equity_peak"


def test_yaml_parsing_profit_reset_trigger_basis_default():
    """Проверяет, что дефолт equity_peak применяется если поле отсутствует в YAML."""
    # Создаем конфиг без profit_reset_trigger_basis
    config_dict = {
        "portfolio": {
            "initial_balance_sol": 10.0,
            "allocation_mode": "dynamic",
            "percent_per_trade": 0.1,
        }
    }
    
    # Создаем PortfolioConfig
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config=config_dict,
    )
    
    portfolio_config = runner._build_portfolio_config()
    
    # Проверяем, что дефолт equity_peak применяется
    assert portfolio_config.profit_reset_trigger_basis == "equity_peak"
    assert portfolio_config.resolved_profit_reset_trigger_basis() == "equity_peak"


def test_resolved_profit_reset_trigger_basis_validation():
    """Проверяет валидацию resolved_profit_reset_trigger_basis с невалидным значением."""
    # Создаем PortfolioConfig с невалидным значением
    portfolio_config = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_trigger_basis="invalid_value",  # Невалидное значение
    )
    
    # Проверяем, что resolved метод возвращает equity_peak (fallback)
    assert portfolio_config.resolved_profit_reset_trigger_basis() == "equity_peak"


def test_resolved_profit_reset_trigger_basis_valid_values():
    """Проверяет, что resolved метод возвращает валидные значения."""
    # Тестируем equity_peak
    config1 = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_trigger_basis="equity_peak",
    )
    assert config1.resolved_profit_reset_trigger_basis() == "equity_peak"
    
    # Тестируем realized_balance
    config2 = PortfolioConfig(
        initial_balance_sol=10.0,
        profit_reset_trigger_basis="realized_balance",
    )
    assert config2.resolved_profit_reset_trigger_basis() == "realized_balance"
