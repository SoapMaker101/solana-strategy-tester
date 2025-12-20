"""
Тесты для гибкой схемы CsvSignalLoader.

Проверяет:
- Необязательные поля source и narrative
- Автоматический сбор дополнительных колонок в extra
- Совместимость с extra_json
- Приоритет колонок над extra_json
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from tempfile import NamedTemporaryFile
import json

from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.domain.models import Signal


@pytest.fixture
def temp_csv_file():
    """Создает временный CSV файл для тестов"""
    with NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        yield f.name
    # Удаляем файл после теста
    Path(f.name).unlink(missing_ok=True)


def test_load_signals_without_narrative_and_source(temp_csv_file):
    """Тест: CSV без narrative и source успешно грузится и ставит дефолты"""
    # Создаем CSV только с обязательными полями
    csv_content = """id,contract_address,timestamp
test1,TESTTOKEN,2024-01-01T12:00:00Z
test2,TESTTOKEN2,2024-01-01T13:00:00Z"""
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 2
    assert signals[0].id == "test1"
    assert signals[0].contract_address == "TESTTOKEN"
    assert signals[0].source == "unknown"
    assert signals[0].narrative == ""
    assert signals[0].extra == {}
    
    assert signals[1].id == "test2"
    assert signals[1].source == "unknown"
    assert signals[1].narrative == ""


def test_load_signals_with_extra_columns(temp_csv_file):
    """Тест: Доп. колонки (twitter_url, launch, pinned_earlier) попадают в Signal.extra"""
    csv_content = """id,contract_address,timestamp,source,twitter_url,launch,pinned_earlier
test1,TESTTOKEN,2024-01-01T12:00:00Z,tg:123,https://x.com/test,true,Pumpfun
test2,TESTTOKEN2,2024-01-01T13:00:00Z,tg:456,https://x.com/test2,false,Bonk"""
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 2
    
    # Проверяем первый сигнал
    assert signals[0].id == "test1"
    assert signals[0].source == "tg:123"
    assert "twitter_url" in signals[0].extra
    assert signals[0].extra["twitter_url"] == "https://x.com/test"
    assert signals[0].extra["launch"] == True  # pandas читает булевы значения
    assert signals[0].extra["pinned_earlier"] == "Pumpfun"
    
    # Проверяем второй сигнал
    assert signals[1].id == "test2"
    assert signals[1].extra["twitter_url"] == "https://x.com/test2"
    assert signals[1].extra["launch"] == False  # pandas читает булевы значения


def test_load_signals_with_extra_json(temp_csv_file):
    """Тест: extra_json продолжает работать"""
    extra_data = {"key1": "value1", "key2": 42}
    csv_content = f"""id,contract_address,timestamp,source,extra_json
test1,TESTTOKEN,2024-01-01T12:00:00Z,tg:123,"{json.dumps(extra_data).replace('"', '""')}"
test2,TESTTOKEN2,2024-01-01T13:00:00Z,tg:456,"{json.dumps({"key3": "value3"}).replace('"', '""')}" """
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 2
    assert signals[0].extra == extra_data
    assert signals[1].extra == {"key3": "value3"}


def test_load_signals_extra_columns_override_extra_json(temp_csv_file):
    """Тест: Приоритет колонок над extra_json (колонка перезаписывает значение из extra_json)"""
    # В extra_json есть ключ "twitter_url", но он также есть как колонка
    # Колонка должна иметь приоритет
    extra_json_data = {"twitter_url": "from_json", "other_key": "from_json"}
    csv_content = f"""id,contract_address,timestamp,source,twitter_url,extra_json
test1,TESTTOKEN,2024-01-01T12:00:00Z,tg:123,from_column,"{json.dumps(extra_json_data).replace('"', '""')}" """
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 1
    # twitter_url должен быть из колонки, а не из extra_json
    assert signals[0].extra["twitter_url"] == "from_column"
    # other_key должен остаться из extra_json
    assert signals[0].extra["other_key"] == "from_json"


def test_load_signals_skip_nan_values(temp_csv_file):
    """Тест: NaN значения в дополнительных колонках пропускаются"""
    csv_content = """id,contract_address,timestamp,source,twitter_url,launch
test1,TESTTOKEN,2024-01-01T12:00:00Z,tg:123,https://x.com/test,
test2,TESTTOKEN2,2024-01-01T13:00:00Z,tg:456,,true"""
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 2
    
    # Первый сигнал: launch пустой (NaN), должен быть пропущен
    assert "twitter_url" in signals[0].extra
    assert signals[0].extra["twitter_url"] == "https://x.com/test"
    assert "launch" not in signals[0].extra  # NaN должен быть пропущен
    
    # Второй сигнал: twitter_url пустой (NaN), должен быть пропущен
    assert "twitter_url" not in signals[1].extra  # NaN должен быть пропущен
    assert "launch" in signals[1].extra
    assert signals[1].extra["launch"] == True  # pandas читает булевы значения (в CSV указано "true")


def test_load_signals_missing_required_column(temp_csv_file):
    """Тест: Отсутствие обязательной колонки вызывает ошибку"""
    csv_content = """id,contract_address
test1,TESTTOKEN"""
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    with pytest.raises(ValueError, match="Missing required column 'timestamp'"):
        loader.load_signals()


def test_load_signals_timestamp_parsing(temp_csv_file):
    """Тест: Таймстемп корректно парсится в UTC"""
    csv_content = """id,contract_address,timestamp
test1,TESTTOKEN,2024-01-01T12:00:00Z
test2,TESTTOKEN2,2024-01-01T13:00:00+00:00"""
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 2
    assert isinstance(signals[0].timestamp, datetime)
    assert signals[0].timestamp.tzinfo == timezone.utc
    assert signals[0].timestamp.year == 2024
    assert signals[0].timestamp.month == 1
    assert signals[0].timestamp.day == 1
    assert signals[0].timestamp.hour == 12


def test_load_signals_combined_scenario(temp_csv_file):
    """Тест: Комплексный сценарий - все возможности вместе"""
    extra_json_data = {"from_json": "value", "overridden": "old"}
    csv_content = f"""id,contract_address,timestamp,source,narrative,twitter_url,launch,extra_json
test1,TESTTOKEN,2024-01-01T12:00:00Z,tg:123,Test narrative,https://x.com/test,true,"{json.dumps(extra_json_data).replace('"', '""')}"
test2,TESTTOKEN2,2024-01-01T13:00:00Z,tg:456,Another narrative,https://x.com/test2,false,"{json.dumps({"from_json": "value2"}).replace('"', '""')}" """
    
    Path(temp_csv_file).write_text(csv_content, encoding='utf-8')
    
    loader = CsvSignalLoader(temp_csv_file)
    signals = loader.load_signals()
    
    assert len(signals) == 2
    
    # Первый сигнал
    assert signals[0].id == "test1"
    assert signals[0].source == "tg:123"
    assert signals[0].narrative == "Test narrative"
    assert "twitter_url" in signals[0].extra
    assert signals[0].extra["twitter_url"] == "https://x.com/test"
    assert "launch" in signals[0].extra
    assert signals[0].extra["launch"] == True  # pandas читает булевы значения
    assert "from_json" in signals[0].extra
    assert signals[0].extra["from_json"] == "value"
    # Если бы была колонка "overridden", она бы перезаписала значение из extra_json
    
    # Второй сигнал
    assert signals[1].id == "test2"
    assert signals[1].source == "tg:456"
    assert signals[1].narrative == "Another narrative"
    assert signals[1].extra["twitter_url"] == "https://x.com/test2"
    assert signals[1].extra["launch"] == False  # pandas читает булевы значения














