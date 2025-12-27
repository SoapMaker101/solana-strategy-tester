"""
Helper functions for working with portfolio events in tests.
"""
from typing import List, Dict
from backtester.domain.portfolio import PortfolioStats
from backtester.domain.portfolio_events import PortfolioEvent, PortfolioEventType


def count_event(stats: PortfolioStats, event_type: PortfolioEventType) -> int:
    """
    Counts events of a specific type in portfolio stats.
    
    Args:
        stats: PortfolioStats containing portfolio_events list
        event_type: The type of event to count
        
    Returns:
        Number of events of the specified type
    """
    if not hasattr(stats, 'portfolio_events') or not stats.portfolio_events:
        return 0
    return sum(1 for e in stats.portfolio_events if e.event_type == event_type)


def events(stats: PortfolioStats, event_type: PortfolioEventType) -> List[PortfolioEvent]:
    """
    Returns all events of a specific type from portfolio stats.
    
    Args:
        stats: PortfolioStats containing portfolio_events list
        event_type: The type of event to filter
        
    Returns:
        List of events of the specified type
    """
    if not hasattr(stats, 'portfolio_events') or not stats.portfolio_events:
        return []
    return [e for e in stats.portfolio_events if e.event_type == event_type]


def counter(stats: PortfolioStats) -> Dict[PortfolioEventType, int]:
    """
    Returns a dictionary with counts for each event type.
    
    Args:
        stats: PortfolioStats containing portfolio_events list
        
    Returns:
        Dictionary mapping event types to their counts
    """
    if not hasattr(stats, 'portfolio_events') or not stats.portfolio_events:
        return {}
    
    result = {}
    for event in stats.portfolio_events:
        event_type = event.event_type
        result[event_type] = result.get(event_type, 0) + 1
    
    return result

