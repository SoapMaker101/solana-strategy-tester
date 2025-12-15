"""
Тесты для cache-only режима GeckoTerminalPriceLoader.

Проверяет:
1. Поддержку двух схем именования кэша (новый и старый формат)
2. Режим prefer_cache_if_exists (cache-only)
3. Миграцию из старого формата в новый
4. Логирование
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

from backtester.infrastructure.price_loader import GeckoTerminalPriceLoader
from backtester.domain.models import Candle


class TestGeckoCacheOnly:
    """Тесты для cache-only режима GeckoTerminalPriceLoader"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """Создает временную директорию для кэша"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def sample_candles(self):
        """Создает тестовые свечи"""
        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        return [
            Candle(
                timestamp=base_time + timedelta(minutes=i),
                open=1.0 + i * 0.01,
                high=1.1 + i * 0.01,
                low=0.9 + i * 0.01,
                close=1.05 + i * 0.01,
                volume=1000.0 + i * 100
            )
            for i in range(10)
        ]
    
    def _save_cache_file(self, cache_dir: Path, contract: str, timeframe: str, 
                        candles: list[Candle], use_new_format: bool = True):
        """Сохраняет кэш в указанном формате"""
        if use_new_format:
            # Новый формат: cache_dir/{timeframe}/{contract}.csv
            timeframe_dir = cache_dir / timeframe
            timeframe_dir.mkdir(parents=True, exist_ok=True)
            cache_path = timeframe_dir / f"{contract}.csv"
        else:
            # Старый формат: cache_dir/{contract}_{timeframe}.csv
            cache_path = cache_dir / f"{contract}_{timeframe}.csv"
        
        import pandas as pd
        df = pd.DataFrame([{
            "timestamp": c.timestamp.isoformat(),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        } for c in candles])
        df.to_csv(cache_path, index=False)
        return cache_path
    
    def test_cache_exists_new_format_no_api_call(self, temp_cache_dir, sample_candles):
        """
        Тест 1: Кэш существует в новом формате → load_prices() НЕ вызывает API
        """
        contract = "TestToken123"
        timeframe = "1m"
        
        # Сохраняем кэш в новом формате
        self._save_cache_file(temp_cache_dir, contract, timeframe, sample_candles, use_new_format=True)
        
        # Создаем loader с prefer_cache_if_exists=True
        loader = GeckoTerminalPriceLoader(
            cache_dir=str(temp_cache_dir),
            timeframe=timeframe,
            prefer_cache_if_exists=True
        )
        
        # Мокаем _fetch_pool_id чтобы тест падал, если вызов произошёл
        with patch.object(loader, '_fetch_pool_id', side_effect=AssertionError("API should not be called!")):
            start_time = sample_candles[0].timestamp
            end_time = sample_candles[-1].timestamp
            
            result = loader.load_prices(contract, start_time, end_time)
            
            # Проверяем, что данные загружены из кэша
            assert len(result) == len(sample_candles)
            assert result[0].timestamp == sample_candles[0].timestamp
            assert result[-1].timestamp == sample_candles[-1].timestamp
    
    def test_cache_exists_old_format_no_api_call_with_migration(self, temp_cache_dir, sample_candles):
        """
        Тест 2: Кэш существует в старом формате → кэш читается, API не вызывается,
        при включенной миграции появляется новый файл
        """
        contract = "TestToken456"
        timeframe = "1m"
        
        # Сохраняем кэш в старом формате
        old_cache_path = self._save_cache_file(
            temp_cache_dir, contract, timeframe, sample_candles, use_new_format=False
        )
        
        # Создаем loader с prefer_cache_if_exists=True
        loader = GeckoTerminalPriceLoader(
            cache_dir=str(temp_cache_dir),
            timeframe=timeframe,
            prefer_cache_if_exists=True
        )
        
        # Проверяем, что нового файла ещё нет
        new_cache_path = temp_cache_dir / timeframe / f"{contract}.csv"
        assert not new_cache_path.exists(), "New cache file should not exist before migration"
        
        # Мокаем _fetch_pool_id чтобы тест падал, если вызов произошёл
        with patch.object(loader, '_fetch_pool_id', side_effect=AssertionError("API should not be called!")):
            start_time = sample_candles[0].timestamp
            end_time = sample_candles[-1].timestamp
            
            result = loader.load_prices(contract, start_time, end_time)
            
            # Проверяем, что данные загружены из кэша
            assert len(result) == len(sample_candles)
            
            # Проверяем, что появился новый файл (миграция)
            assert new_cache_path.exists(), "New cache file should be created after migration"
            
            # Проверяем, что старый файл всё ещё существует (не удаляется)
            assert old_cache_path.exists(), "Old cache file should still exist"
    
    def test_cache_miss_api_called(self, temp_cache_dir, sample_candles):
        """
        Тест 3: Кэш отсутствует → API вызывается
        """
        contract = "TestToken789"
        timeframe = "1m"
        
        # Создаем loader
        loader = GeckoTerminalPriceLoader(
            cache_dir=str(temp_cache_dir),
            timeframe=timeframe,
            prefer_cache_if_exists=True
        )
        
        # Мокаем API методы
        mock_pool_id = "MockPoolId1234567890123456789012345678901234"
        mock_ohlcv_data = [
            [int(c.timestamp.timestamp()), c.open, c.high, c.low, c.close, c.volume]
            for c in sample_candles
        ]
        
        with patch.object(loader, '_fetch_pool_id', return_value=mock_pool_id) as mock_fetch_pool:
            with patch.object(loader, '_fetch_ohlcv_batch', return_value=mock_ohlcv_data) as mock_fetch_ohlcv:
                with patch.object(loader, '_http_get') as mock_http:
                    # Настраиваем моки для HTTP запросов
                    mock_response_pool = MagicMock()
                    mock_response_pool.json.return_value = {
                        "data": [{
                            "attributes": {
                                "address": mock_pool_id,
                                "name": "Test Pool",
                                "reserve_in_usd": "1000000"
                            }
                        }]
                    }
                    mock_response_pool.raise_for_status = Mock()
                    
                    mock_response_ohlcv = MagicMock()
                    mock_response_ohlcv.json.return_value = {
                        "data": {
                            "attributes": {
                                "ohlcv_list": mock_ohlcv_data
                            }
                        }
                    }
                    mock_response_ohlcv.raise_for_status = Mock()
                    mock_response_ohlcv.status_code = 200
                    
                    mock_http.side_effect = [mock_response_pool, mock_response_ohlcv]
                    
                    start_time = sample_candles[0].timestamp
                    end_time = sample_candles[-1].timestamp
                    
                    result = loader.load_prices(contract, start_time, end_time)
                    
                    # Проверяем, что API был вызван
                    assert mock_fetch_pool.called, "_fetch_pool_id should be called"
                    assert mock_fetch_ohlcv.called, "_fetch_ohlcv_batch should be called"
                    
                    # Проверяем результат
                    assert len(result) == len(sample_candles)
                    
                    # Проверяем, что кэш был сохранён
                    new_cache_path = temp_cache_dir / timeframe / f"{contract}.csv"
                    assert new_cache_path.exists(), "Cache file should be created after API call"
    
    def test_prefer_cache_false_still_checks_coverage(self, temp_cache_dir, sample_candles):
        """
        Тест 4: prefer_cache_if_exists=False → проверяет покрытие диапазона как раньше
        """
        contract = "TestTokenABC"
        timeframe = "1m"
        
        # Сохраняем кэш с неполным покрытием (только первые 5 свечей)
        partial_candles = sample_candles[:5]
        self._save_cache_file(temp_cache_dir, contract, timeframe, partial_candles, use_new_format=True)
        
        # Создаем loader с prefer_cache_if_exists=False
        loader = GeckoTerminalPriceLoader(
            cache_dir=str(temp_cache_dir),
            timeframe=timeframe,
            prefer_cache_if_exists=False
        )
        
        # Запрашиваем диапазон, который не полностью покрыт кэшем
        start_time = sample_candles[0].timestamp
        end_time = sample_candles[-1].timestamp  # Запрашиваем все 10 свечей, но в кэше только 5
        
        # Мокаем API для дозагрузки
        mock_pool_id = "MockPoolId1234567890123456789012345678901234"
        mock_ohlcv_data = [
            [int(c.timestamp.timestamp()), c.open, c.high, c.low, c.close, c.volume]
            for c in sample_candles[5:]  # Остальные свечи
        ]
        
        with patch.object(loader, '_fetch_pool_id', return_value=mock_pool_id) as mock_fetch_pool:
            with patch.object(loader, '_fetch_ohlcv_batch', return_value=mock_ohlcv_data) as mock_fetch_ohlcv:
                result = loader.load_prices(contract, start_time, end_time)
                
                # При prefer_cache_if_exists=False API должен быть вызван для дозагрузки
                assert mock_fetch_pool.called, "_fetch_pool_id should be called when coverage is incomplete"
                assert mock_fetch_ohlcv.called, "_fetch_ohlcv_batch should be called when coverage is incomplete"
    
    def test_cache_incomplete_range_cache_only_mode(self, temp_cache_dir, sample_candles):
        """
        Тест 5: prefer_cache_if_exists=True с неполным диапазоном → использует кэш без API
        """
        contract = "TestTokenXYZ"
        timeframe = "1m"
        
        # Сохраняем кэш с неполным покрытием
        partial_candles = sample_candles[:5]
        self._save_cache_file(temp_cache_dir, contract, timeframe, partial_candles, use_new_format=True)
        
        # Создаем loader с prefer_cache_if_exists=True
        loader = GeckoTerminalPriceLoader(
            cache_dir=str(temp_cache_dir),
            timeframe=timeframe,
            prefer_cache_if_exists=True
        )
        
        # Запрашиваем диапазон, который не полностью покрыт кэшем
        start_time = sample_candles[0].timestamp
        end_time = sample_candles[-1].timestamp
        
        # Мокаем _fetch_pool_id чтобы тест падал, если вызов произошёл
        with patch.object(loader, '_fetch_pool_id', side_effect=AssertionError("API should not be called in cache-only mode!")):
            result = loader.load_prices(contract, start_time, end_time)
            
            # В cache-only режиме должны вернуться только те свечи, что есть в кэше
            assert len(result) == len(partial_candles)
            assert result[0].timestamp == partial_candles[0].timestamp
            assert result[-1].timestamp == partial_candles[-1].timestamp
    
    def test_get_cache_paths_returns_both_formats(self, temp_cache_dir):
        """
        Тест 6: _get_cache_paths() возвращает оба пути в правильном порядке
        """
        contract = "TestToken123"
        timeframe = "1m"
        
        loader = GeckoTerminalPriceLoader(
            cache_dir=str(temp_cache_dir),
            timeframe=timeframe
        )
        
        paths = loader._get_cache_paths(contract)
        
        assert len(paths) == 2
        
        # Первый путь - новый формат
        assert paths[0] == temp_cache_dir / timeframe / f"{contract}.csv"
        
        # Второй путь - старый формат
        assert paths[1] == temp_cache_dir / f"{contract}_{timeframe}.csv"
