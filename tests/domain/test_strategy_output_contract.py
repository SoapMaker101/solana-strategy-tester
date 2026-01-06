"""
Guard tests for StrategyOutput contract.

These tests ensure that legacy API remains stable and canonical_reason
is automatically computed correctly.
"""
import pytest
from datetime import datetime, timezone

from backtester.domain.models import StrategyOutput


def test_strategy_output_legacy_tp_maps_to_ladder_tp():
    """Guard: StrategyOutput(reason="tp") → canonical_reason == "ladder_tp"."""
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=110.0,
        pnl=0.10,
        reason="tp",
    )
    
    assert output.reason == "tp"
    assert output.canonical_reason == "ladder_tp"


def test_strategy_output_legacy_sl_maps_to_stop_loss():
    """Guard: StrategyOutput(reason="sl") → canonical_reason == "stop_loss"."""
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=90.0,
        pnl=-0.10,
        reason="sl",
    )
    
    assert output.reason == "sl"
    assert output.canonical_reason == "stop_loss"


def test_strategy_output_legacy_timeout_maps_to_time_stop():
    """Guard: StrategyOutput(reason="timeout") → canonical_reason == "time_stop"."""
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=100.0,
        pnl=0.0,
        reason="timeout",
    )
    
    assert output.reason == "timeout"
    assert output.canonical_reason == "time_stop"


def test_strategy_output_canonical_ladder_tp_remains_ladder_tp():
    """Guard: StrategyOutput(reason="ladder_tp") → canonical_reason == "ladder_tp"."""
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=110.0,
        pnl=0.10,
        reason="ladder_tp",
    )
    
    assert output.reason == "ladder_tp"
    assert output.canonical_reason == "ladder_tp"


def test_strategy_output_meta_ladder_reason_has_priority():
    """Guard: meta["ladder_reason"] has priority over reason mapping."""
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=110.0,
        pnl=0.10,
        reason="tp",  # Legacy reason
        meta={"ladder_reason": "time_stop"},  # But meta says time_stop
    )
    
    assert output.reason == "tp"
    assert output.canonical_reason == "time_stop"  # meta has priority


def test_strategy_output_canonical_reason_optional():
    """Guard: canonical_reason is Optional and can be None initially."""
    # This test ensures that canonical_reason is computed in __post_init__
    # and is not required in constructor
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=110.0,
        pnl=0.10,
        reason="tp",
        # canonical_reason not provided - should be computed
    )
    
    assert output.canonical_reason is not None
    assert output.canonical_reason == "ladder_tp"


def test_strategy_output_explicit_canonical_reason_respected():
    """Guard: If canonical_reason is explicitly provided, it's not overridden."""
    output = StrategyOutput(
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=110.0,
        pnl=0.10,
        reason="tp",
        canonical_reason="manual_close",  # Explicitly set
    )
    
    assert output.reason == "tp"
    assert output.canonical_reason == "manual_close"  # Explicit value respected

