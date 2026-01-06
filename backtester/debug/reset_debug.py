# backtester/debug/reset_debug.py
"""
Debug utilities for reset event diagnostics.

Usage:
    Set environment variable BACKTESTER_RESET_DEBUG=1 to enable debug output.
"""

import os
from typing import List, Optional, Any
from datetime import datetime

from ..domain.portfolio_events import PortfolioEventType


def reset_debug_enabled() -> bool:
    """
    Check if reset debug is enabled via environment variable.
    
    Returns:
        True if BACKTESTER_RESET_DEBUG=1, False otherwise
    """
    return os.getenv("BACKTESTER_RESET_DEBUG") == "1"


def dump_reset_debug(
    component: str,
    *,
    events: List[Any],
    portfolio_event_type_test: Optional[type] = None,
    portfolio_event_type_engine: Optional[type] = None,
) -> None:
    """
    Dump reset debug information.
    
    Args:
        component: Component name (e.g., "PortfolioEngine", "TEST:test_name")
        events: List of portfolio events
        portfolio_event_type_test: PortfolioEventType class from test import (optional)
        portfolio_event_type_engine: PortfolioEventType class from engine import (optional)
    """
    if not reset_debug_enabled():
        return
    
    print(f"=== RESET DEBUG {component} ===")
    
    # Enum comparison diagnostics
    if portfolio_event_type_test is not None and portfolio_event_type_engine is not None:
        test_module = portfolio_event_type_test.__module__
        test_id = id(portfolio_event_type_test)
        engine_module = portfolio_event_type_engine.__module__
        engine_id = id(portfolio_event_type_engine)
        
        same_class = portfolio_event_type_test is portfolio_event_type_engine
        same_member = (
            portfolio_event_type_test.POSITION_CLOSED == portfolio_event_type_engine.POSITION_CLOSED
            if hasattr(portfolio_event_type_test, 'POSITION_CLOSED') and hasattr(portfolio_event_type_engine, 'POSITION_CLOSED')
            else None
        )
        
        print(f"Enum(TEST) module={test_module} id={test_id}")
        print(f"Enum(ENGINE) module={engine_module} id={engine_id}")
        print(f"SAME_CLASS={same_class} SAME_MEMBER={same_member}")
    
    # Filter events: only POSITION_CLOSED and PORTFOLIO_RESET_TRIGGERED
    reset_events = [
        e for e in events
        if hasattr(e, 'event_type') and e.event_type in (
            PortfolioEventType.POSITION_CLOSED,
            PortfolioEventType.PORTFOLIO_RESET_TRIGGERED,
        )
    ]
    
    # Self-check: filter same as in test
    position_closed_events = [
        e for e in events
        if hasattr(e, 'event_type') and hasattr(e, 'reason')
        and e.event_type == PortfolioEventType.POSITION_CLOSED
        and e.reason == "profit_reset"
    ]
    print(f"SELF_CHECK closed_profit_reset={len(position_closed_events)}")
    
    # Event details
    for i, e in enumerate(reset_events):
        event_type_repr = repr(e.event_type) if hasattr(e, 'event_type') else 'N/A'
        event_type_class = type(e.event_type).__name__ if hasattr(e, 'event_type') else 'N/A'
        reason_repr = repr(e.reason) if hasattr(e, 'reason') else 'N/A'
        ts_iso = e.timestamp.isoformat() if hasattr(e, 'timestamp') and e.timestamp else 'N/A'
        pos_id = e.position_id if hasattr(e, 'position_id') else 'N/A'
        
        print(f"EVENT {i}: event_type={event_type_repr} event_type_class={event_type_class} reason={reason_repr} ts={ts_iso} pos={pos_id}")
    
    # Statistics
    print(f"LEN portfolio_events={len(events)}")
    
    # Unique event_type classes and modules
    event_type_classes = set()
    event_type_modules = set()
    for e in events:
        if hasattr(e, 'event_type'):
            event_type_classes.add(type(e.event_type).__name__)
            if hasattr(e.event_type, '__class__'):
                event_type_modules.add(e.event_type.__class__.__module__)
    
    print(f"UNIQUE event_type_classes={event_type_classes}")
    print(f"UNIQUE event_type_modules={event_type_modules}")
    
    print("=== END RESET DEBUG ===")

