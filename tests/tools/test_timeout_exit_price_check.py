"""
Tests for timeout exit price check tool.

Тесты проверяют:
1. stored_raw_exit_price соответствует свече на exit_time → ok
2. stored_raw_exit_price соответствует последней свече после exit_time → suspect
3. missing candles file → missing_candles_file
4. no candle after exit_time → no_candle_after_exit_time
"""

import pytest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import pandas as pd

from backtester.tools.check_timeout_exit_price import (
    check_timeout_exit_price,
    check_all_timeout_positions,
    find_candle_at_or_after,
    resolve_candles_file,
    EXIT_PRICE_TOLERANCE_PCT,
)
from backtester.domain.models import Candle


@pytest.fixture
def sample_candles():
    """Создает тестовые свечи с известными ценами."""
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=base_time - timedelta(minutes=10), open=100.0, high=110.0, low=90.0, close=100.0, volume=1000.0),
        Candle(timestamp=base_time, open=100.0, high=110.0, low=90.0, close=100.0, volume=1000.0),  # Entry candle
        Candle(timestamp=base_time + timedelta(minutes=60), open=50.0, high=55.0, low=45.0, close=50.0, volume=1000.0),  # Exit time candle (correct)
        Candle(timestamp=base_time + timedelta(minutes=120), open=200.0, high=210.0, low=190.0, close=200.0, volume=1000.0),  # After exit_time (wrong)
    ]


@pytest.fixture
def temp_candles_dir(sample_candles):
    """Создает временную директорию со свечами."""
    with TemporaryDirectory() as tmpdir:
        candles_dir = Path(tmpdir) / "candles"
        candles_dir.mkdir(parents=True, exist_ok=True)
        
        # Создаём файл свечей для тестового контракта
        contract = "TESTCONTRACT"
        candles_file = candles_dir / f"{contract}_1m.csv"
        
        # Сохраняем свечи в CSV
        df = pd.DataFrame([{
            "timestamp": c.timestamp.isoformat(),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        } for c in sample_candles])
        df.to_csv(candles_file, index=False)
        
        yield candles_dir, contract


def test_find_candle_at_or_after_exact_match(sample_candles):
    """Тест: находит свечу с точным совпадением timestamp."""
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)  # T+60 минут
    
    candle = find_candle_at_or_after(sample_candles, exit_time)
    
    assert candle is not None
    assert candle.timestamp == exit_time
    assert candle.close == 50.0  # Правильная цена на exit_time


def test_find_candle_at_or_after_after_time(sample_candles):
    """Тест: находит первую свечу после exit_time, если точного совпадения нет."""
    # Exit_time между свечами
    exit_time = datetime(2024, 1, 1, 13, 30, 0, tzinfo=timezone.utc)  # Между T+60 и T+120
    
    candle = find_candle_at_or_after(sample_candles, exit_time)
    
    assert candle is not None
    assert candle.timestamp == datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)  # T+120 минут
    assert candle.close == 200.0


def test_find_candle_at_or_after_no_candle(sample_candles):
    """Тест: возвращает None, если нет свечей после exit_time."""
    # Exit_time после всех свечей
    exit_time = datetime(2024, 1, 1, 15, 0, 0, tzinfo=timezone.utc)  # После всех
    
    candle = find_candle_at_or_after(sample_candles, exit_time)
    
    assert candle is None


def test_check_timeout_exit_price_ok(temp_candles_dir, sample_candles):
    """Тест: stored_raw_exit_price совпадает с candle на exit_time → ok."""
    candles_dir, contract = temp_candles_dir
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)  # T+60 минут
    stored_raw_exit_price = 50.0  # Правильная цена на exit_time
    
    result = check_timeout_exit_price(
        position_id="test_pos_1",
        contract_address=contract,
        exit_time=exit_time,
        stored_raw_exit_price=stored_raw_exit_price,
        candles_dir=candles_dir,
        timeframe="1m",
    )
    
    assert result["status"] == "ok"
    assert result["expected_exit_close"] == 50.0
    assert result["abs_diff_pct"] <= EXIT_PRICE_TOLERANCE_PCT


def test_check_timeout_exit_price_suspect(temp_candles_dir, sample_candles):
    """Тест: stored_raw_exit_price соответствует последней свече после exit_time → suspect."""
    candles_dir, contract = temp_candles_dir
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)  # T+60 минут
    stored_raw_exit_price = 200.0  # Неправильная цена (свеча на T+120)
    
    result = check_timeout_exit_price(
        position_id="test_pos_2",
        contract_address=contract,
        exit_time=exit_time,
        stored_raw_exit_price=stored_raw_exit_price,
        candles_dir=candles_dir,
        timeframe="1m",
    )
    
    assert result["status"] == "suspect_exit_price_after_exit_time"
    assert result["expected_exit_close"] == 50.0  # Правильная цена на exit_time
    assert result["abs_diff_pct"] > EXIT_PRICE_TOLERANCE_PCT  # Большая разница


def test_check_timeout_exit_price_missing_candles_file():
    """Тест: missing candles file → missing_candles_file."""
    # Используем несуществующую директорию
    candles_dir = Path("/nonexistent/path/to/candles")
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    
    result = check_timeout_exit_price(
        position_id="test_pos_3",
        contract_address="TESTCONTRACT",
        exit_time=exit_time,
        stored_raw_exit_price=50.0,
        candles_dir=candles_dir,
        timeframe="1m",
    )
    
    assert result["status"] == "missing_candles_file"
    assert result["expected_exit_close"] is None


def test_check_timeout_exit_price_none_candles_dir():
    """Тест: graceful skip если candles_dir=None."""
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    
    result = check_timeout_exit_price(
        position_id="test_pos_4",
        contract_address="TESTCONTRACT",
        exit_time=exit_time,
        stored_raw_exit_price=50.0,
        candles_dir=None,  # Отсутствует
        timeframe="1m",
    )
    
    assert result["status"] == "missing_candles_file"
    assert result["expected_exit_close"] is None


def test_check_timeout_exit_price_no_candle_after_exit_time(temp_candles_dir):
    """Тест: no candle after exit_time → no_candle_after_exit_time."""
    candles_dir, contract = temp_candles_dir
    # Exit_time после всех свечей в файле
    exit_time = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)  # На следующий день
    
    result = check_timeout_exit_price(
        position_id="test_pos_5",
        contract_address=contract,
        exit_time=exit_time,
        stored_raw_exit_price=50.0,
        candles_dir=candles_dir,
        timeframe="1m",
    )
    
    assert result["status"] == "no_candle_after_exit_time"
    assert result["expected_exit_close"] is None


def test_check_all_timeout_positions(temp_candles_dir, sample_candles):
    """Тест: проверка всех timeout позиций из CSV."""
    candles_dir, contract = temp_candles_dir
    
    with TemporaryDirectory() as tmpdir:
        # Создаём временный portfolio_positions.csv
        reports_dir = Path(tmpdir)
        positions_path = reports_dir / "portfolio_positions.csv"
        
        # Создаём тестовые позиции
        positions_data = {
            "position_id": ["pos1", "pos2"],
            "contract_address": [contract, contract],
            "exit_time": [
                datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc).isoformat(),  # Правильное время
                datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc).isoformat(),  # Правильное время
            ],
            "raw_exit_price": [50.0, 200.0],  # pos1: правильная цена, pos2: неправильная
            "reason": ["time_stop", "timeout"],
            "status": ["closed", "closed"],
        }
        df = pd.DataFrame(positions_data)
        df.to_csv(positions_path, index=False)
        
        # Проверяем все позиции
        results_df = check_all_timeout_positions(
            positions_path=positions_path,
            candles_dir=candles_dir,
            timeframe="1m",
        )
        
        assert len(results_df) == 2
        assert results_df[results_df["position_id"] == "pos1"]["status"].iloc[0] == "ok"
        assert results_df[results_df["position_id"] == "pos2"]["status"].iloc[0] == "suspect_exit_price_after_exit_time"


def test_resolve_candles_file(temp_candles_dir):
    """Тест: resolve_candles_file находит файл свечей."""
    candles_dir, contract = temp_candles_dir
    
    # Создаём файл в формате {contract}_{timeframe}.csv
    candles_file = candles_dir / f"{contract}_1m.csv"
    candles_file.touch()
    
    resolved = resolve_candles_file(contract, candles_dir, timeframe="1m")
    
    assert resolved is not None
    assert resolved.exists()
    assert resolved == candles_file


def test_resolve_candles_file_not_found(temp_candles_dir):
    """Тест: resolve_candles_file возвращает None, если файл не найден."""
    candles_dir = temp_candles_dir[0]
    contract = "NONEXISTENT"
    
    resolved = resolve_candles_file(contract, candles_dir, timeframe="1m")
    
    assert resolved is None


def test_check_timeout_exit_price_within_tolerance(temp_candles_dir, sample_candles):
    """Тест: stored_raw_exit_price в пределах tolerance → ok."""
    candles_dir, contract = temp_candles_dir
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    expected_price = 50.0
    # Добавляем небольшую разницу в пределах tolerance (0.5%)
    stored_price = expected_price * (1.0 + EXIT_PRICE_TOLERANCE_PCT / 100.0 * 0.5)
    
    result = check_timeout_exit_price(
        position_id="test_pos_6",
        contract_address=contract,
        exit_time=exit_time,
        stored_raw_exit_price=stored_price,
        candles_dir=candles_dir,
        timeframe="1m",
    )
    
    assert result["status"] == "ok"
    assert result["expected_exit_close"] == expected_price
    assert result["abs_diff_pct"] <= EXIT_PRICE_TOLERANCE_PCT


def test_check_timeout_exit_price_outside_tolerance(temp_candles_dir, sample_candles):
    """Тест: stored_raw_exit_price вне tolerance → suspect."""
    candles_dir, contract = temp_candles_dir
    exit_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    expected_price = 50.0
    # Добавляем большую разницу вне tolerance (2%)
    stored_price = expected_price * (1.0 + EXIT_PRICE_TOLERANCE_PCT / 100.0 * 2.0)
    
    result = check_timeout_exit_price(
        position_id="test_pos_7",
        contract_address=contract,
        exit_time=exit_time,
        stored_raw_exit_price=stored_price,
        candles_dir=candles_dir,
        timeframe="1m",
    )
    
    assert result["status"] == "suspect_exit_price_after_exit_time"
    assert result["expected_exit_close"] == expected_price
    assert result["abs_diff_pct"] > EXIT_PRICE_TOLERANCE_PCT
