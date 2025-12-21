# backtester/research/xn_analysis/xn_models.py
# Data models for XN analysis

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional


@dataclass
class XNAnalysisConfig:
    """
    Configuration for XN analysis.
    """
    holding_days: int = 90  # Default: 90 days holding period
    xn_levels: List[float] = field(default_factory=lambda: [2, 3, 4, 5, 10, 20, 50, 100])  # XN levels to track
    price_timeframe: str = "1m"  # Price timeframe: "1m" | "5m" | "15m"
    price_source: str = "high"  # Price source: "high" (important: use HIGH, not close)
    
    def __post_init__(self):
        """Validate configuration."""
        if self.holding_days <= 0:
            raise ValueError("holding_days must be positive")
        
        if not isinstance(self.xn_levels, list) or len(self.xn_levels) == 0:
            raise ValueError("xn_levels must be a non-empty list")
        elif not all(isinstance(x, (int, float)) and x > 0 for x in self.xn_levels):
            raise ValueError("xn_levels must contain only positive numbers")
        
        if self.price_timeframe not in ["1m", "5m", "15m"]:
            raise ValueError(f"price_timeframe must be one of ['1m', '5m', '15m'], got {self.price_timeframe}")
        
        if self.price_source != "high":
            raise ValueError(f"price_source must be 'high', got {self.price_source}")
        
        # Sort xn_levels for consistency
        self.xn_levels = sorted(self.xn_levels)


@dataclass
class XNSignalResult:
    """
    Result of XN analysis for a single signal.
    """
    signal_id: str
    contract_address: str
    entry_time: datetime
    entry_price: float
    
    # Maximum price reached during holding period
    max_price: float
    
    # Maximum XN achieved (calculated as max_price / entry_price)
    max_xn: float
    
    # Time to reach each XN level (in minutes from entry_time) or None if not reached
    # Key = XN level, Value = minutes to reach or None
    time_to_xn: Dict[float, Optional[int]]
    
    def __post_init__(self):
        """Validate result data."""
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be positive, got {self.entry_price}")
        if self.max_price < 0:
            raise ValueError(f"max_price must be non-negative, got {self.max_price}")
        if self.max_xn < 0:
            raise ValueError(f"max_xn must be non-negative, got {self.max_xn}")
        
        # Validate time_to_xn structure
        if not isinstance(self.time_to_xn, dict):
            raise ValueError("time_to_xn must be a dictionary")
        for xn_level, time_minutes in self.time_to_xn.items():
            if not isinstance(xn_level, (int, float)):
                raise ValueError(f"XN level must be a number, got {type(xn_level)}")
            if time_minutes is not None and (not isinstance(time_minutes, int) or time_minutes < 0):
                raise ValueError(f"time_minutes must be None or non-negative int, got {time_minutes}")


@dataclass
class XNSummaryStats:
    """
    Summary statistics for a specific XN level across multiple signals.
    """
    xn_level: float  # XN level (e.g., 2.0, 3.0, 5.0, etc.)
    reached_count: int  # Number of signals that reached this XN level
    reached_pct: float  # Percentage of signals that reached this level (0-100)
    median_time_minutes: Optional[float]  # Median time to reach XN (in minutes), None if not reached
    p90_time_minutes: Optional[float]  # 90th percentile time to reach XN (in minutes), None if not reached
    
    def __post_init__(self):
        """Validate statistics data."""
        if self.xn_level <= 0:
            raise ValueError(f"xn_level must be positive, got {self.xn_level}")
        if self.reached_count < 0:
            raise ValueError(f"reached_count must be non-negative, got {self.reached_count}")
        if not 0 <= self.reached_pct <= 100:
            raise ValueError(f"reached_pct must be between 0 and 100, got {self.reached_pct}")
        if self.median_time_minutes is not None and self.median_time_minutes < 0:
            raise ValueError(f"median_time_minutes must be None or non-negative, got {self.median_time_minutes}")
        if self.p90_time_minutes is not None and self.p90_time_minutes < 0:
            raise ValueError(f"p90_time_minutes must be None or non-negative, got {self.p90_time_minutes}")











