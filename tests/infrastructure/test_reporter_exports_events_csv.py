"""
Unit tests for Reporter portfolio_events.csv export (v1.9).
"""
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import json
import pytest

from backtester.infrastructure.reporter import Reporter
from backtester.domain.portfolio import (
    PortfolioResult,
    PortfolioStats,
)
from backtester.domain.portfolio_events import PortfolioEvent, PortfolioEventType


def test_reporter_exports_events_csv():
    """
    Test that Reporter exports portfolio_events.csv with correct schema.
    
    Checks:
    - File exists after export
    - CSV contains expected columns
    - Events are correctly serialized
    - meta_json is valid JSON
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        # Create a mock portfolio result with events
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Create events
        events = [
            PortfolioEvent(
                timestamp=base_time,
                strategy="test_strategy",
                signal_id="sig1",
                contract_address="CONTRACT1",
                event_type=PortfolioEventType.ATTEMPT_ACCEPTED_OPEN,
                reason=None,
                result=None,
                meta={"open_positions": 1},
            ),
            PortfolioEvent(
                timestamp=base_time,
                strategy="test_strategy",
                signal_id="sig2",
                contract_address="CONTRACT2",
                event_type=PortfolioEventType.ATTEMPT_REJECTED_CAPACITY,
                reason="capacity_full",
                result=None,
                meta={"blocked_by_capacity": True},
            ),
            PortfolioEvent(
                timestamp=base_time,
                strategy="test_strategy",
                signal_id="sig1",
                contract_address="CONTRACT1",
                event_type=PortfolioEventType.CAPACITY_PRUNE_TRIGGERED,
                reason=None,
                result=None,
                meta={
                    "candidates_count": 2,
                    "closed_count": 1,
                    "blocked_ratio": 0.5,
                },
            ),
        ]
        
        # Create portfolio stats with events
        stats = PortfolioStats(
            final_balance_sol=100.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            trades_executed=1,
            trades_skipped_by_risk=0,
        )
        stats.portfolio_events = events
        
        # Create portfolio result
        portfolio_result = PortfolioResult(
            equity_curve=[],
            positions=[],
            stats=stats,
        )
        
        # Export events
        portfolio_results = {"test_strategy": portfolio_result}
        reporter.save_portfolio_events_table(portfolio_results)
        
        # Check file exists
        events_path = Path(tmpdir) / "portfolio_events.csv"
        assert events_path.exists(), f"portfolio_events.csv should exist at {events_path}"
        
        # Read and verify CSV
        import pandas as pd
        df = pd.read_csv(events_path)
        
        # Check columns
        expected_columns = [
            "timestamp",
            "event_type",
            "strategy",
            "signal_id",
            "contract_address",
            "position_id",
            "meta_json",
        ]
        assert list(df.columns) == expected_columns, \
            f"Expected columns {expected_columns}, got {list(df.columns)}"
        
        # Check row count
        assert len(df) == 3, f"Expected 3 events, got {len(df)}"
        
        # Check first event
        first_row = df.iloc[0]
        assert first_row["event_type"] == PortfolioEventType.ATTEMPT_ACCEPTED_OPEN.value
        assert first_row["strategy"] == "test_strategy"
        assert first_row["signal_id"] == "sig1"
        assert first_row["contract_address"] == "CONTRACT1"
        
        # Check meta_json is valid JSON
        meta_json = first_row["meta_json"]
        assert isinstance(meta_json, str), "meta_json should be a string"
        meta_dict = json.loads(meta_json)
        assert isinstance(meta_dict, dict), "meta_json should parse to dict"
        assert meta_dict.get("open_positions") == 1
        
        # Check second event (ATTEMPT_REJECTED_CAPACITY)
        second_row = df.iloc[1]
        assert second_row["event_type"] == PortfolioEventType.ATTEMPT_REJECTED_CAPACITY.value
        assert second_row["signal_id"] == "sig2"
        meta_dict_2 = json.loads(second_row["meta_json"])
        assert meta_dict_2.get("blocked_by_capacity") is True
        
        # Check third event (CAPACITY_PRUNE_TRIGGERED)
        third_row = df.iloc[2]
        assert third_row["event_type"] == PortfolioEventType.CAPACITY_PRUNE_TRIGGERED.value
        meta_dict_3 = json.loads(third_row["meta_json"])
        assert meta_dict_3.get("candidates_count") == 2
        assert meta_dict_3.get("closed_count") == 1
        assert meta_dict_3.get("blocked_ratio") == 0.5


def test_reporter_exports_events_csv_empty():
    """
    Test that Reporter handles empty events gracefully.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        # Create portfolio result with no events
        stats = PortfolioStats(
            final_balance_sol=100.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            trades_executed=0,
            trades_skipped_by_risk=0,
        )
        stats.portfolio_events = []
        
        portfolio_result = PortfolioResult(
            equity_curve=[],
            positions=[],
            stats=stats,
        )
        
        # Export events (should not fail)
        portfolio_results = {"test_strategy": portfolio_result}
        reporter.save_portfolio_events_table(portfolio_results)
        
        # Check file exists (even if empty)
        events_path = Path(tmpdir) / "portfolio_events.csv"
        assert events_path.exists(), "portfolio_events.csv should exist even with no events"
        
        # Read and verify CSV has correct columns
        import pandas as pd
        df = pd.read_csv(events_path)
        
        expected_columns = [
            "timestamp",
            "event_type",
            "strategy",
            "signal_id",
            "contract_address",
            "position_id",
            "meta_json",
        ]
        assert list(df.columns) == expected_columns
        assert len(df) == 0, "Should have 0 rows for empty events"

