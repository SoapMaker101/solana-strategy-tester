"""
Unit tests for BacktestRunner handling empty/corrupt candles CSV.
Tests that runner skips signals with empty candles and continues processing.
"""
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from backtester.application.runner import BacktestRunner
from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.infrastructure.price_loader import CsvPriceLoader
from backtester.domain.models import Signal
from backtester.domain.strategy_base import Strategy, StrategyConfig, StrategyInput, StrategyOutput
from backtester.infrastructure.reporter import Reporter


class DummyStrategy(Strategy):
    """Простая стратегия для тестирования."""
    
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        if not data.candles:
            return StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={}
            )
        return StrategyOutput(
            entry_time=data.candles[0].timestamp,
            entry_price=data.candles[0].close,
            exit_time=data.candles[-1].timestamp,
            exit_price=data.candles[-1].close,
            pnl=0.0,
            reason="time_stop",
            meta={}
        )


class TestRunnerEmptyCandles:
    """Tests for BacktestRunner handling empty/corrupt candles."""
    
    def test_runner_skips_signal_with_empty_candles(self):
        """
        Test that runner skips signal when candles CSV is empty and continues processing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Создаем структуру директорий
            signals_dir = Path(tmpdir) / "signals"
            candles_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = candles_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаем сигнал
            signals_file = signals_dir / "test_signals.csv"
            signals_file.parent.mkdir(parents=True, exist_ok=True)
            signals_file.write_text(
                "id,contract_address,timestamp,source,narrative\n"
                "sig1,CONTRACT1,2024-01-01T10:00:00Z,test,test\n"
            )
            
            # Создаем пустой CSV файл для контракта
            contract = "CONTRACT1"
            csv_file = cached_dir / f"{contract}.csv"
            csv_file.touch()  # Пустой файл
            
            # Создаем компоненты
            signal_loader = CsvSignalLoader(str(signals_file))
            price_loader = CsvPriceLoader(
                candles_dir=str(candles_dir),
                timeframe="1m",
                base_dir=str(candles_dir)
            )
            reporter = Reporter(output_dir=str(Path(tmpdir) / "output"))
            
            strategy_config = StrategyConfig(
                name="test_strategy",
                type="RUNNER",
                params={}
            )
            strategy = DummyStrategy(strategy_config)
            
            runner = BacktestRunner(
                signal_loader=signal_loader,
                price_loader=price_loader,
                reporter=reporter,
                strategies=[strategy],
                global_config={
                    "data": {
                        "before_minutes": 60,
                        "after_minutes": 360
                    }
                }
            )
            
            # Запускаем бэктест
            results = runner.run()
            
            # Проверяем, что сигнал был пропущен
            assert runner.signals_skipped_no_candles == 1
            assert runner.signals_processed == 0
            # Результатов не должно быть (сигнал пропущен)
            assert len(results) == 0
    
    def test_runner_skips_signal_with_corrupt_candles(self):
        """
        Test that runner skips signal when candles CSV is corrupt and continues processing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Создаем структуру директорий
            signals_dir = Path(tmpdir) / "signals"
            candles_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = candles_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаем сигнал
            signals_file = signals_dir / "test_signals.csv"
            signals_file.parent.mkdir(parents=True, exist_ok=True)
            signals_file.write_text(
                "id,contract_address,timestamp,source,narrative\n"
                "sig1,CONTRACT1,2024-01-01T10:00:00Z,test,test\n"
            )
            
            # Создаем битый CSV файл
            contract = "CONTRACT1"
            csv_file = cached_dir / f"{contract}.csv"
            csv_file.write_text("invalid,csv,data\nbroken,line\n")
            
            # Создаем компоненты
            signal_loader = CsvSignalLoader(str(signals_file))
            price_loader = CsvPriceLoader(
                candles_dir=str(candles_dir),
                timeframe="1m",
                base_dir=str(candles_dir)
            )
            reporter = Reporter(output_dir=str(Path(tmpdir) / "output"))
            
            strategy_config = StrategyConfig(
                name="test_strategy",
                type="RUNNER",
                params={}
            )
            strategy = DummyStrategy(strategy_config)
            
            runner = BacktestRunner(
                signal_loader=signal_loader,
                price_loader=price_loader,
                reporter=reporter,
                strategies=[strategy],
                global_config={
                    "data": {
                        "before_minutes": 60,
                        "after_minutes": 360
                    }
                }
            )
            
            # Запускаем бэктест
            results = runner.run()
            
            # Проверяем, что сигнал был пропущен
            assert runner.signals_skipped_no_candles == 1
            assert runner.signals_processed == 0
            # Результатов не должно быть (сигнал пропущен)
            assert len(results) == 0
    
    def test_runner_continues_after_skipping_empty_candles(self):
        """
        Test that runner continues processing other signals after skipping one with empty candles.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Создаем структуру директорий
            signals_dir = Path(tmpdir) / "signals"
            candles_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = candles_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаем два сигнала
            signals_file = signals_dir / "test_signals.csv"
            signals_file.parent.mkdir(parents=True, exist_ok=True)
            signals_file.write_text(
                "id,contract_address,timestamp,source,narrative\n"
                "sig1,CONTRACT1,2024-01-01T10:00:00Z,test,test\n"
                "sig2,CONTRACT2,2024-01-01T11:00:00Z,test,test\n"
            )
            
            # CONTRACT1 - пустой файл
            contract1 = "CONTRACT1"
            csv_file1 = cached_dir / f"{contract1}.csv"
            csv_file1.touch()
            
            # CONTRACT2 - валидный CSV
            contract2 = "CONTRACT2"
            csv_file2 = cached_dir / f"{contract2}.csv"
            csv_file2.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T10:00:00Z,1.0,1.1,0.9,1.0,1000\n"
                "2024-01-01T11:00:00Z,1.1,1.2,1.0,1.1,1100\n"
            )
            
            # Создаем компоненты
            signal_loader = CsvSignalLoader(str(signals_file))
            price_loader = CsvPriceLoader(
                candles_dir=str(candles_dir),
                timeframe="1m",
                base_dir=str(candles_dir)
            )
            reporter = Reporter(output_dir=str(Path(tmpdir) / "output"))
            
            strategy_config = StrategyConfig(
                name="test_strategy",
                type="RUNNER",
                params={}
            )
            strategy = DummyStrategy(strategy_config)
            
            runner = BacktestRunner(
                signal_loader=signal_loader,
                price_loader=price_loader,
                reporter=reporter,
                strategies=[strategy],
                global_config={
                    "data": {
                        "before_minutes": 60,
                        "after_minutes": 360
                    }
                }
            )
            
            # Запускаем бэктест
            results = runner.run()
            
            # Проверяем, что один сигнал был пропущен, один обработан
            assert runner.signals_skipped_no_candles == 1
            assert runner.signals_processed == 1
            # Должен быть результат для второго сигнала
            assert len(results) == 1
            assert results[0]["signal_id"] == "sig2"

    def test_runner_includes_skipped_attempts_with_canonical_detail(self):
        """
        Test that runner includes placeholder results when include_skipped_attempts=True
        and uses canonical meta.detail values ("no_candles", "corrupt_candles").
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Создаем структуру директорий
            signals_dir = Path(tmpdir) / "signals"
            candles_dir = Path(tmpdir) / "data" / "candles"
            cached_dir = candles_dir / "cached" / "1m"
            cached_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаем сигнал
            signals_file = signals_dir / "test_signals.csv"
            signals_file.parent.mkdir(parents=True, exist_ok=True)
            signals_file.write_text(
                "id,contract_address,timestamp,source,narrative\n"
                "sig1,CONTRACT1,2024-01-01T10:00:00Z,test,test\n"
            )
            
            # Создаем пустой CSV файл
            contract = "CONTRACT1"
            csv_file = cached_dir / f"{contract}.csv"
            csv_file.touch()  # Пустой файл
            
            # Создаем компоненты
            signal_loader = CsvSignalLoader(str(signals_file))
            price_loader = CsvPriceLoader(
                candles_dir=str(candles_dir),
                timeframe="1m",
                base_dir=str(candles_dir)
            )
            reporter = Reporter(output_dir=str(Path(tmpdir) / "output"))
            
            strategy_config = StrategyConfig(
                name="test_strategy",
                type="RUNNER",
                params={}
            )
            strategy = DummyStrategy(strategy_config)
            
            runner = BacktestRunner(
                signal_loader=signal_loader,
                price_loader=price_loader,
                reporter=reporter,
                strategies=[strategy],
                global_config={
                    "data": {
                        "before_minutes": 60,
                        "after_minutes": 360
                    }
                }
            )
            
            # Запускаем с include_skipped_attempts=True
            results = runner.run(include_skipped_attempts=True)
            
            # Проверяем, что счётчики корректны
            assert runner.signals_skipped_no_candles == 1
            assert runner.signals_processed == 0
            
            # Должен быть placeholder результат
            assert len(results) == 1  # Одна стратегия
            assert results[0]["signal_id"] == "sig1"
            assert results[0]["result"].entry_time is None
            assert results[0]["result"].reason == "no_entry"
            # Проверяем каноническое значение meta.detail
            assert results[0]["result"].meta.get("detail") == "no_candles"





















