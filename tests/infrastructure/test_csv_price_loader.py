"""
Unit tests for CsvPriceLoader.resolve_candles_path method.
Tests path resolution with different directory layouts.
"""
import tempfile
import shutil
from pathlib import Path
import pytest

from backtester.infrastructure.price_loader import CsvPriceLoader


class TestCsvPriceLoaderResolvePath:
    """Tests for CsvPriceLoader.resolve_candles_path method."""
    
    def test_resolve_candles_path_finds_cached_timeframe_format(self):
        """
        Test that resolve_candles_path finds files in cached/{timeframe}/{contract}.csv format.
        This is the primary format used in the project.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = base_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "CONTRACT123"
            csv_file = cached_dir / f"{contract}.csv"
            csv_file.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1.0,1.1,0.9,1.0,1000\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            resolved_path = loader.resolve_candles_path(contract, "1m")
            
            assert resolved_path is not None
            assert resolved_path == csv_file
            assert resolved_path.exists()
    
    def test_resolve_candles_path_priority_order(self):
        """
        Test that resolve_candles_path checks paths in the correct priority order.
        Should prefer cached/{timeframe}/{contract}.csv over legacy formats.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            
            contract = "CONTRACT123"
            
            # Create multiple files in different formats
            # Lower priority: legacy format
            legacy_file = base_dir / f"{contract}_1m.csv"
            legacy_file.parent.mkdir(parents=True, exist_ok=True)
            legacy_file.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1.0,1.1,0.9,1.0,1000\n")
            
            # Higher priority: cached/{timeframe}/{contract}.csv
            cached_dir = base_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            cached_file = cached_dir / f"{contract}.csv"
            cached_file.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,2.0,2.1,1.9,2.0,2000\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            resolved_path = loader.resolve_candles_path(contract, "1m")
            
            # Should find the cached format (higher priority)
            assert resolved_path is not None
            assert resolved_path == cached_file
            assert resolved_path.exists()
    
    def test_resolve_candles_path_legacy_format_fallback(self):
        """
        Test that resolve_candles_path falls back to legacy format if cached format doesn't exist.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            
            contract = "CONTRACT123"
            
            # Only create legacy format file
            legacy_file = base_dir / f"{contract}_1m.csv"
            legacy_file.parent.mkdir(parents=True, exist_ok=True)
            legacy_file.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1.0,1.1,0.9,1.0,1000\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            resolved_path = loader.resolve_candles_path(contract, "1m")
            
            # Should find the legacy format
            assert resolved_path is not None
            assert resolved_path == legacy_file
            assert resolved_path.exists()
    
    def test_resolve_candles_path_returns_none_when_not_found(self):
        """
        Test that resolve_candles_path returns None when no file is found.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            base_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "NONEXISTENT_CONTRACT"
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            resolved_path = loader.resolve_candles_path(contract, "1m")
            
            # Should return None when file doesn't exist
            assert resolved_path is None
    
    def test_resolve_candles_path_custom_base_dir(self):
        """
        Test that resolve_candles_path works with custom base_dir parameter.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_base = Path(tmpdir) / "custom" / "candles"
            cached_dir = custom_base / "cached" / "15m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "CONTRACT456"
            csv_file = cached_dir / f"{contract}.csv"
            csv_file.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1.0,1.1,0.9,1.0,1000\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(custom_base),
                timeframe="15m",
                base_dir=str(custom_base)
            )
            
            resolved_path = loader.resolve_candles_path(contract, "15m", base_dir=str(custom_base))
            
            assert resolved_path is not None
            assert resolved_path == csv_file
            assert resolved_path.exists()


class TestCsvPriceLoaderEmptyCorrupt:
    """Tests for CsvPriceLoader handling empty/corrupt CSV files."""
    
    def test_load_prices_handles_empty_csv_file(self):
        """
        Test that load_prices returns empty list for empty CSV file (0 bytes).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = base_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "EMPTY_CONTRACT"
            csv_file = cached_dir / f"{contract}.csv"
            # Создаем пустой файл
            csv_file.touch()
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            candles = loader.load_prices(contract)
            
            assert candles == []
    
    def test_load_prices_handles_corrupt_csv_file(self):
        """
        Test that load_prices returns empty list for corrupt CSV file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = base_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "CORRUPT_CONTRACT"
            csv_file = cached_dir / f"{contract}.csv"
            # Создаем битый CSV (невалидные данные)
            csv_file.write_text("invalid,csv,data\nbroken,line,without,enough,columns\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            candles = loader.load_prices(contract)
            
            assert candles == []
    
    def test_load_prices_handles_csv_with_missing_columns(self):
        """
        Test that load_prices returns empty list for CSV with missing required columns.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = base_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "MISSING_COLUMNS"
            csv_file = cached_dir / f"{contract}.csv"
            # CSV без обязательных колонок
            csv_file.write_text("timestamp,open\n2024-01-01T00:00:00Z,1.0\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            candles = loader.load_prices(contract)
            
            assert candles == []
    
    def test_load_prices_handles_csv_with_invalid_timestamps(self):
        """
        Test that load_prices returns empty list for CSV with invalid timestamps.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = base_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            contract = "INVALID_TIMESTAMPS"
            csv_file = cached_dir / f"{contract}.csv"
            # CSV с невалидными timestamp
            csv_file.write_text("timestamp,open,high,low,close,volume\ninvalid_date,1.0,1.1,0.9,1.0,1000\n")
            
            loader = CsvPriceLoader(
                candles_dir=str(base_dir),
                timeframe="1m",
                base_dir=str(base_dir)
            )
            
            candles = loader.load_prices(contract)
            
            assert candles == []































