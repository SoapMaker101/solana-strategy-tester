"""
Unit tests for PortfolioEvent constructor contract (v2.0).
"""
from datetime import datetime, timezone

from backtester.domain.portfolio_events import PortfolioEvent, PortfolioEventType


def test_portfolio_event_constructor_with_all_fields():
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    event = PortfolioEvent(
        timestamp=base_time,
        strategy="test_strategy",
        signal_id="sig1",
        contract_address="CONTRACT1",
        position_id="pos-123",
        event_type=PortfolioEventType.POSITION_OPENED,
        reason=None,
        meta={"size": 1.0},
    )

    assert event.timestamp == base_time
    assert event.strategy == "test_strategy"
    assert event.signal_id == "sig1"
    assert event.contract_address == "CONTRACT1"
    assert event.position_id == "pos-123"
    assert event.event_type == PortfolioEventType.POSITION_OPENED
    assert event.reason is None
    assert isinstance(event.meta, dict)


def test_portfolio_event_reset_triggered():
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    event = PortfolioEvent(
        timestamp=base_time,
        strategy="runner",
        signal_id="sig-reset",
        contract_address="CONTRACT1",
        position_id="pos-reset",
        event_type=PortfolioEventType.PORTFOLIO_RESET_TRIGGERED,
        reason="profit_reset",
        meta={"closed_positions_count": 3},
    )

    assert event.event_type == PortfolioEventType.PORTFOLIO_RESET_TRIGGERED
    assert event.reason == "profit_reset"
    assert event.meta["closed_positions_count"] == 3
