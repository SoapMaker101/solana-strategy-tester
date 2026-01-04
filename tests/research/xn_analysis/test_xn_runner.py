"""
Tests for XN runner candles path resolution
"""
import pytest
import tempfile
from pathlib import Path

from backtester.research.xn_analysis.xn_runner import resolve_candles_path


def test_resolve_candles_path_primary_format():
    """
    Test that resolve_candles_path finds candles in the primary format:
    {base_dir}/cached/{timeframe}/{contract}.csv
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir) / "data" / "candles"
        cached_dir = base_dir / "cached" / "1m"
        cached_dir.mkdir(parents=True, exist_ok=True)
        
        contract = "TESTTOKEN"
        test_file = cached_dir / f"{contract}.csv"
        test_file.write_text("timestamp,open,high,low,close,volume\n")
        
        # Should resolve to the primary format
        resolved = resolve_candles_path(
            contract=contract,
            timeframe="1m",
            base_dir=str(base_dir),
        )
        
        assert resolved is not None
        assert resolved == test_file
        assert resolved.exists()


def test_resolve_candles_path_fallback_formats():
    """
    Test that resolve_candles_path falls back to other formats if primary doesn't exist.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir) / "data" / "candles"
        cached_dir = base_dir / "cached"
        cached_dir.mkdir(parents=True, exist_ok=True)
        
        contract = "TESTTOKEN"
        
        # Test fallback to old format: cached/{contract}_{timeframe}.csv
        old_format_file = cached_dir / f"{contract}_1m.csv"
        old_format_file.write_text("timestamp,open,high,low,close,volume\n")
        
        resolved = resolve_candles_path(
            contract=contract,
            timeframe="1m",
            base_dir=str(base_dir),
        )
        
        assert resolved is not None
        assert resolved == old_format_file
        assert resolved.exists()


def test_resolve_candles_path_not_found():
    """
    Test that resolve_candles_path returns None when no file exists.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir) / "data" / "candles"
        
        resolved = resolve_candles_path(
            contract="NONEXISTENT",
            timeframe="1m",
            base_dir=str(base_dir),
        )
        
        assert resolved is None


def test_resolve_candles_path_priority_order():
    """
    Test that resolve_candles_path checks paths in the correct priority order.
    If multiple formats exist, it should return the highest priority one.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir) / "data" / "candles"
        cached_dir = base_dir / "cached" / "1m"
        cached_dir.mkdir(parents=True, exist_ok=True)
        
        contract = "TESTTOKEN"
        
        # Create files in multiple formats
        primary_file = cached_dir / f"{contract}.csv"
        primary_file.write_text("primary\n")
        
        old_format_file = base_dir / "cached" / f"{contract}_1m.csv"
        old_format_file.write_text("old_format\n")
        
        # Should return primary format (highest priority)
        resolved = resolve_candles_path(
            contract=contract,
            timeframe="1m",
            base_dir=str(base_dir),
        )
        
        assert resolved is not None
        assert resolved == primary_file
        # Verify it's the primary format, not the old format
        assert resolved.read_text() == "primary\n"




























