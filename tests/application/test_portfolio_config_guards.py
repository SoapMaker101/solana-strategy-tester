"""
Guard tests for PortfolioConfig parsing contract.

These tests ensure that 0 ≠ None and parsing logic remains stable.
"""
import pytest
from backtester.domain.portfolio import PortfolioConfig, FeeModel
from backtester.application.runner import BacktestRunner


def test_parse_bool_zero_is_false():
    """Guard: _parse_bool(0) → False (not None)."""
    runner = BacktestRunner(
        signal_loader=None,  # Not used in this test
        price_loader=None,  # Not used in this test
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    assert runner._parse_bool(0) is False
    assert runner._parse_bool(0.0) is False


def test_parse_bool_one_is_true():
    """Guard: _parse_bool(1) → True."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    assert runner._parse_bool(1) is True
    assert runner._parse_bool(1.0) is True


def test_parse_bool_false_string():
    """Guard: _parse_bool("false") → False."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    assert runner._parse_bool("false") is False
    assert runner._parse_bool("False") is False
    assert runner._parse_bool("0") is False


def test_parse_bool_true_string():
    """Guard: _parse_bool("true") → True."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    assert runner._parse_bool("true") is True
    assert runner._parse_bool("True") is True
    assert runner._parse_bool("1") is True


def test_parse_bool_none_uses_default():
    """Guard: _parse_bool(None) → default."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    assert runner._parse_bool(None, default=False) is False
    assert runner._parse_bool(None, default=True) is True


def test_parse_int_optional_zero_is_zero():
    """Guard: _parse_int_optional(0) → 0 (not None)."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    result = runner._parse_int_optional(0)
    assert result == 0
    assert result is not None


def test_parse_int_optional_string_zero_is_zero():
    """Guard: _parse_int_optional("0") → 0 (not None)."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    result = runner._parse_int_optional("0")
    assert result == 0
    assert result is not None


def test_parse_int_optional_none_is_none():
    """Guard: _parse_int_optional(None) → None."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    result = runner._parse_int_optional(None)
    assert result is None


def test_parse_int_optional_empty_string_is_none():
    """Guard: _parse_int_optional("") → None."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    result = runner._parse_int_optional("")
    assert result is None


def test_parse_int_optional_string_number():
    """Guard: _parse_int_optional("4320") → 4320."""
    runner = BacktestRunner(
        signal_loader=None,
        price_loader=None,
        reporter=None,
        strategies=[],
        global_config={},
    )
    
    result = runner._parse_int_optional("4320")
    assert result == 4320
    assert result is not None

