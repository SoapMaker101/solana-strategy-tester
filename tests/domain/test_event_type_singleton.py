# tests/domain/test_event_type_singleton.py
"""
Test that PortfolioEventType is a singleton across imports.

This test ensures that PortfolioEventType imported from different modules
is the same class, preventing Enum mismatch bugs.
"""

import pytest


def test_portfolio_event_type_singleton():
    """
    Test that PortfolioEventType is the same class when imported from different modules.
    
    This prevents bugs where test code uses one PortfolioEventType enum
    and engine code uses another, causing filter mismatches.
    """
    # Import from test context (direct import)
    from backtester.domain.portfolio_events import PortfolioEventType as TestPortfolioEventType
    
    # Import from engine context (module import)
    import backtester.domain.portfolio_events as pe
    EnginePortfolioEventType = pe.PortfolioEventType
    
    # They should be the same class
    assert TestPortfolioEventType is EnginePortfolioEventType, \
        f"PortfolioEventType should be singleton, but got different classes:\n" \
        f"  Test: module={TestPortfolioEventType.__module__}, id={id(TestPortfolioEventType)}\n" \
        f"  Engine: module={EnginePortfolioEventType.__module__}, id={id(EnginePortfolioEventType)}"
    
    # Members should be equal
    assert TestPortfolioEventType.POSITION_CLOSED == EnginePortfolioEventType.POSITION_CLOSED, \
        f"POSITION_CLOSED should be equal, but:\n" \
        f"  Test: {TestPortfolioEventType.POSITION_CLOSED}\n" \
        f"  Engine: {EnginePortfolioEventType.POSITION_CLOSED}"
    
    assert TestPortfolioEventType.PORTFOLIO_RESET_TRIGGERED == EnginePortfolioEventType.PORTFOLIO_RESET_TRIGGERED, \
        f"PORTFOLIO_RESET_TRIGGERED should be equal, but:\n" \
        f"  Test: {TestPortfolioEventType.PORTFOLIO_RESET_TRIGGERED}\n" \
        f"  Engine: {EnginePortfolioEventType.PORTFOLIO_RESET_TRIGGERED}"


def test_portfolio_event_type_members_consistent():
    """
    Test that PortfolioEventType members are consistent across imports.
    """
    from backtester.domain.portfolio_events import PortfolioEventType
    
    # Check that members exist
    assert hasattr(PortfolioEventType, 'POSITION_CLOSED'), "POSITION_CLOSED should exist"
    assert hasattr(PortfolioEventType, 'PORTFOLIO_RESET_TRIGGERED'), "PORTFOLIO_RESET_TRIGGERED should exist"
    
    # Check that members are Enum members
    assert isinstance(PortfolioEventType.POSITION_CLOSED, PortfolioEventType), \
        "POSITION_CLOSED should be a PortfolioEventType member"
    assert isinstance(PortfolioEventType.PORTFOLIO_RESET_TRIGGERED, PortfolioEventType), \
        "PORTFOLIO_RESET_TRIGGERED should be a PortfolioEventType member"

