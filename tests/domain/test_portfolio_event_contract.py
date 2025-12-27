"""
Unit tests for PortfolioEvent constructor contract (v1.9).

Ensures that PortfolioEvent can be created with keyword arguments
as used in portfolio.py, and that pyright/basedpyright correctly
resolves the dataclass constructor.
"""
from datetime import datetime, timezone
from backtester.domain.portfolio_events import PortfolioEvent, PortfolioEventType
from backtester.domain.models import StrategyOutput


def test_portfolio_event_constructor_with_all_fields():
    """
    Test that PortfolioEvent can be created with all keyword arguments
    used in portfolio.py.
    
    This test ensures the dataclass contract is correct for pyright/basedpyright.
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Create event with all fields (as used in portfolio.py)
    event = PortfolioEvent(
        timestamp=base_time,
        strategy="test_strategy",
        signal_id="sig1",
        contract_address="CONTRACT1",
        event_type=PortfolioEventType.ATTEMPT_ACCEPTED_OPEN,
        reason="position_opened",
        result=None,
        meta={"open_positions": 1},
    )
    
    # Verify all fields are accessible
    assert event.timestamp == base_time
    assert event.strategy == "test_strategy"
    assert event.signal_id == "sig1"
    assert event.contract_address == "CONTRACT1"
    assert event.event_type == PortfolioEventType.ATTEMPT_ACCEPTED_OPEN
    assert event.reason == "position_opened"
    assert event.result is None
    assert isinstance(event.meta, dict)
    assert event.meta["open_positions"] == 1


def test_portfolio_event_constructor_with_optional_fields():
    """
    Test that PortfolioEvent can be created with optional fields (None/defaults).
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Create event without optional fields (reason, result)
    event = PortfolioEvent(
        timestamp=base_time,
        strategy="test_strategy",
        signal_id="sig2",
        contract_address="CONTRACT2",
        event_type=PortfolioEventType.ATTEMPT_RECEIVED,
        # reason=None (default)
        # result=None (default)
        # meta={} (default)
    )
    
    # Verify defaults
    assert event.reason is None
    assert event.result is None
    assert isinstance(event.meta, dict)
    assert len(event.meta) == 0


def test_portfolio_event_constructor_with_result():
    """
    Test PortfolioEvent with StrategyOutput result (as used for attempts).
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    result = StrategyOutput(
        entry_time=base_time,
        entry_price=1.0,
        exit_time=base_time,
        exit_price=1.1,
        pnl=0.1,
        reason="tp",
        meta={},
    )
    
    event = PortfolioEvent(
        timestamp=base_time,
        strategy="test_strategy",
        signal_id="sig3",
        contract_address="CONTRACT3",
        event_type=PortfolioEventType.ATTEMPT_ACCEPTED_OPEN,
        result=result,
        reason="position_opened",
        meta={"size": 10.0},
    )
    
    assert event.result is not None
    assert event.result.entry_price == 1.0
    assert event.result.exit_price == 1.1


def test_portfolio_event_constructor_with_rejected_event():
    """
    Test PortfolioEvent for rejected events (as used for ATTEMPT_REJECTED_*).
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent(
        timestamp=base_time,
        strategy="test_strategy",
        signal_id="sig4",
        contract_address="CONTRACT4",
        event_type=PortfolioEventType.ATTEMPT_REJECTED_CAPACITY,
        reason="max_open_positions",
        result=None,
        meta={"open_positions": 10, "max_open_positions": 10},
    )
    
    assert event.event_type == PortfolioEventType.ATTEMPT_REJECTED_CAPACITY
    assert event.reason == "max_open_positions"
    assert event.meta["open_positions"] == 10


def test_portfolio_event_constructor_with_close_event():
    """
    Test PortfolioEvent for close events (EXECUTED_CLOSE, CLOSED_BY_*).
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent(
        timestamp=base_time,
        strategy="test_strategy",
        signal_id="sig5",
        contract_address="CONTRACT5",
        event_type=PortfolioEventType.EXECUTED_CLOSE,
        reason="tp",
        meta={
            "entry_time": base_time.isoformat(),
            "exit_time": base_time.isoformat(),
            "pnl_pct": 0.15,
            "pnl_sol": 1.5,
        },
    )
    
    assert event.event_type == PortfolioEventType.EXECUTED_CLOSE
    assert event.reason == "tp"
    assert event.meta["pnl_pct"] == 0.15


def test_portfolio_event_constructor_with_trigger_event():
    """
    Test PortfolioEvent for trigger events (CAPACITY_PRUNE_TRIGGERED, etc.).
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Trigger events may have empty signal_id/contract_address
    event = PortfolioEvent(
        timestamp=base_time,
        strategy="portfolio",
        signal_id="",
        contract_address="",
        event_type=PortfolioEventType.CAPACITY_PRUNE_TRIGGERED,
        reason="capacity_pressure",
        meta={
            "candidates_count": 5,
            "closed_count": 2,
            "blocked_ratio": 0.5,
        },
    )
    
    assert event.event_type == PortfolioEventType.CAPACITY_PRUNE_TRIGGERED
    assert event.strategy == "portfolio"
    assert event.signal_id == ""
    assert event.meta["candidates_count"] == 5

