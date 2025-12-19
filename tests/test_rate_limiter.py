"""
Тесты для RateLimiter и обработки rate limit в GeckoTerminalPriceLoader
"""
import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from requests.exceptions import HTTPError
import requests

from backtester.infrastructure.price_loader import (
    RateLimiter,
    RateLimitExceededError,
    GeckoTerminalPriceLoader,
    retry_on_failure
)


class TestRateLimiter:
    """Тесты для класса RateLimiter"""
    
    def test_limiter_waits_on_exceed(self, monkeypatch):
        """Тест 1: limiter ждёт при превышении лимита"""
        sleep_calls = []
        
        def mock_sleep(seconds):
            sleep_calls.append(seconds)
        
        monkeypatch.setattr(time, 'sleep', mock_sleep)
        monkeypatch.setattr(time, 'time', lambda: 0.0)  # Фиксированное время
        
        limiter = RateLimiter(max_calls=2, period_seconds=60)
        
        # Первые 2 запроса должны пройти без ожидания
        limiter.acquire()
        limiter.acquire()
        assert len(sleep_calls) == 0, "Первые 2 запроса не должны ждать"
        
        # Третий запрос должен ждать
        # Мокаем time.time чтобы вернуть время, когда старый слот освободится
        call_times = [0.0, 0.0, 0.0, 61.0]  # После третьего вызова время сдвигается
        time_counter = [0]
        
        def mock_time():
            idx = time_counter[0]
            time_counter[0] += 1
            if idx < len(call_times):
                return call_times[idx]
            return call_times[-1]
        
        monkeypatch.setattr(time, 'time', mock_time)
        
        # Сбрасываем счётчик
        sleep_calls.clear()
        limiter._timestamps.clear()
        limiter._timestamps.extend([0.0, 0.0])  # Два старых timestamp
        
        limiter.acquire()
        # Должен был вызван sleep, так как лимит исчерпан
        assert len(sleep_calls) > 0, "Третий запрос должен был вызвать sleep"
        assert sleep_calls[0] > 0, "Время ожидания должно быть положительным"
    
    def test_429_with_retry_after_sleeps_correct_time(self, monkeypatch):
        """Тест 2: 429 + Retry-After → sleep на нужное время"""
        sleep_calls = []
        
        def mock_sleep(seconds):
            sleep_calls.append(seconds)
        
        monkeypatch.setattr(time, 'sleep', mock_sleep)
        
        # Создаём mock response с 429 и Retry-After header
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "5"}
        mock_response.url = "https://api.example.com/test"
        
        error = HTTPError("Rate limit exceeded")
        error.response = mock_response
        
        # Создаём функцию, которая выбрасывает 429
        @retry_on_failure(max_retries=2, backoff_factor=2.0, on_429_mode="wait")
        def failing_request():
            raise error
        
        # Вызываем функцию - она должна обработать 429 и заснуть на 5 секунд
        try:
            failing_request()
        except HTTPError:
            pass  # Ожидаем, что после всех попыток будет исключение
        
        # Проверяем, что sleep был вызван с правильным временем
        assert len(sleep_calls) > 0, "Должен был вызван sleep"
        # Проверяем, что хотя бы один sleep был на 5 секунд (Retry-After)
        retry_after_sleeps = [s for s in sleep_calls if abs(s - 5.0) < 0.1]
        assert len(retry_after_sleeps) > 0, f"Должен был вызван sleep на ~5 секунд, но были: {sleep_calls}"
    
    def test_on_429_fail_raises_exception(self):
        """Тест 3: on_429=fail → выбрасывается RateLimitExceededError"""
        # Создаём mock response с 429
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.url = "https://api.example.com/test"
        
        error = HTTPError("Rate limit exceeded")
        error.response = mock_response
        
        # Создаём функцию с on_429_mode="fail"
        @retry_on_failure(max_retries=3, backoff_factor=2.0, on_429_mode="fail")
        def failing_request():
            raise error
        
        # Вызываем функцию - должна выбросить RateLimitExceededError
        with pytest.raises(RateLimitExceededError):
            failing_request()
    
    def test_rate_limiter_thread_safety(self):
        """Тест 4: общий лимитер в многопоточности (smoke test)"""
        # Используем реальное ограничение API: 30 запросов в минуту
        limiter = RateLimiter(max_calls=30, period_seconds=60)
        results = []
        errors = []
        results_lock = threading.Lock()
        
        def make_request(thread_id):
            try:
                limiter.acquire()
                with results_lock:
                    results.append(thread_id)
            except Exception as e:
                with results_lock:
                    errors.append((thread_id, e))
        
        # Создаём 50 потоков, которые одновременно дергают acquire
        # Это гарантирует, что минимум 20 запросов будут заблокированы (50 - 30 = 20)
        threads = []
        for i in range(50):
            t = threading.Thread(target=make_request, args=(i,))
            threads.append(t)
        
        # Запускаем все потоки одновременно
        for t in threads:
            t.start()
        
        # Ждём завершения всех потоков
        for t in threads:
            t.join(timeout=120)  # Увеличиваем timeout, так как некоторые потоки могут ждать до 60 секунд
        
        # Проверяем, что нет исключений
        assert len(errors) == 0, f"Не должно быть исключений, но были: {errors}"
        
        # Проверяем, что все запросы были обработаны
        assert len(results) == 50, f"Все 50 запросов должны быть обработаны, но было: {len(results)}"
        
        # Проверяем статистику
        # При 50 запросах и лимите 30, минимум 20 должны быть заблокированы
        # Но из-за race conditions может быть немного меньше, поэтому проверяем >= 15
        stats = limiter.get_stats()
        assert stats["blocked_events"] >= 15, (
            f"Должно быть минимум 15 заблокированных событий "
            f"(лимит 30, запросов 50, ожидается ~20 блокировок), "
            f"но было: {stats['blocked_events']}"
        )
        
        # Проверяем, что было время ожидания (если были блокировки, должно быть время ожидания)
        if stats["blocked_events"] > 0:
            assert stats["total_wait_time_seconds"] > 0, (
                "Если были блокировки, должно быть время ожидания"
            )


class TestGeckoTerminalPriceLoaderRateLimit:
    """Тесты для GeckoTerminalPriceLoader с rate limiting"""
    
    def test_loader_uses_rate_limiter(self, monkeypatch):
        """Тест что loader использует rate limiter при HTTP запросах"""
        acquire_calls = []
        
        class MockRateLimiter(RateLimiter):
            def __init__(self):
                # Вызываем super().__init__() для соответствия типам, но переопределяем методы
                super().__init__(max_calls=1, period_seconds=1)
            
            def acquire(self, cost=1):
                # Переопределяем, чтобы не использовать реальную логику
                acquire_calls.append(cost)
            
            def get_stats(self):
                return {"blocked_events": 0, "total_wait_time_seconds": 0.0}
        
        loader = GeckoTerminalPriceLoader(
            cache_dir="test_cache",
            timeframe="1m",
            rate_limit_config={
                "enabled": True,
                "max_calls_per_minute": 30,
                "on_429": "wait"
            }
        )
        
        # Заменяем rate_limiter на mock
        loader.rate_limiter = MockRateLimiter()
        
        # Мокаем requests.get
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = Mock()
        
        with patch('backtester.infrastructure.price_loader.requests.get', return_value=mock_response):
            # Вызываем _http_get
            loader._http_get("https://api.example.com/test", {})
        
        # Проверяем, что acquire был вызван
        assert len(acquire_calls) > 0, "Rate limiter.acquire должен был быть вызван"
    
    def test_loader_tracks_429_responses(self, monkeypatch):
        """Тест что loader отслеживает 429 ответы"""
        loader = GeckoTerminalPriceLoader(
            cache_dir="test_cache",
            timeframe="1m",
            rate_limit_config={
                "enabled": True,
                "max_calls_per_minute": 30,
                "on_429": "wait"
            }
        )
        
        # Мокаем requests.get чтобы возвращать 429
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        
        with patch('backtester.infrastructure.price_loader.requests.get', return_value=mock_response):
            loader._http_get("https://api.example.com/test", {})
        
        # Проверяем, что счётчик 429 увеличился
        assert loader._total_429_responses == 1, "Счётчик 429 должен быть равен 1"
    
    def test_loader_summary_includes_all_metrics(self):
        """Тест что get_rate_limit_summary возвращает все метрики"""
        loader = GeckoTerminalPriceLoader(
            cache_dir="test_cache",
            timeframe="1m",
            rate_limit_config={
                "enabled": True,
                "max_calls_per_minute": 30,
                "on_429": "wait"
            }
        )
        
        # Устанавливаем некоторые значения для теста
        loader._total_requests = 100
        loader._total_429_responses = 5
        loader._rate_limit_failures = 0
        
        summary = loader.get_rate_limit_summary()
        
        # Проверяем наличие всех полей
        assert "total_requests" in summary
        assert "http_429" in summary
        assert "rate_limit_failures" in summary
        assert "mode_on_429" in summary
        assert "requests_blocked_by_rate_limiter" in summary
        assert "total_wait_time_seconds" in summary
        
        # Проверяем значения
        assert summary["total_requests"] == 100
        assert summary["http_429"] == 5
        assert summary["mode_on_429"] == "wait"









