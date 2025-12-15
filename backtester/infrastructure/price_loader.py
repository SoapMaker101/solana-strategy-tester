from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Callable, TypeVar
import os
import time
import requests
from requests.exceptions import RequestException, HTTPError
import pandas as pd
import threading
from collections import deque

from ..domain.models import Candle  # Импорт структуры свечи

T = TypeVar('T')


def _format_datetime(dt: Optional[datetime]) -> str:
    """
    Форматирует datetime для вывода в логах.
    Использует strftime для гарантированного правильного формата YYYY-MM-DD HH:MM:SS.
    """
    if dt is None:
        return "None"
    # Используем strftime для гарантированного формата YYYY-MM-DD HH:MM:SS
    # Если есть timezone, добавляем его
    if dt.tzinfo is not None:
        return dt.strftime("%Y-%m-%d %H:%M:%S%z")
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class RateLimitExceededError(RuntimeError):
    """Исключение, выбрасываемое при превышении rate limit в fail-fast режиме."""
    pass


class RateLimiter:
    """
    Thread-safe rate limiter с использованием sliding window алгоритма.
    Ограничивает количество запросов в заданном временном окне.
    """
    
    def __init__(self, max_calls: int = 30, period_seconds: int = 60):
        """
        :param max_calls: Максимальное количество запросов
        :param period_seconds: Период времени в секундах
        """
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._lock = threading.Lock()
        self._timestamps = deque()  # Хранит timestamps последних запросов
        self._blocked_events = 0
        self._total_wait_time = 0.0
    
    def acquire(self, cost: int = 1) -> None:
        """
        Получает разрешение на выполнение запроса.
        Если лимит исчерпан, ждёт до освобождения слота.
        
        :param cost: Стоимость запроса (по умолчанию 1)
        """
        while True:
            with self._lock:
                now = time.time()
                
                # Удаляем старые timestamps (старше period_seconds)
                while self._timestamps and self._timestamps[0] < now - self.period_seconds:
                    self._timestamps.popleft()
                
                # Проверяем, можем ли выполнить запрос
                if len(self._timestamps) + cost <= self.max_calls:
                    # Можем выполнить - добавляем timestamps
                    for _ in range(cost):
                        self._timestamps.append(now)
                    return
                
                # Лимит исчерпан - нужно ждать
                self._blocked_events += 1
                # Вычисляем время до освобождения самого старого слота
                oldest_ts = self._timestamps[0]
                wait_time = (oldest_ts + self.period_seconds) - now + 0.1  # +0.1 для безопасности
                wait_time = max(0.0, wait_time)
            
            # Sleep вне lock, чтобы другие потоки могли войти
            if wait_time > 0:
                try:
                    print(f"[RL ⏳] Waiting {wait_time:.2f}s (limit {self.max_calls}/{self.period_seconds}s) before request...")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    # Fallback для систем с проблемами кодировки
                    print(f"[RL] Waiting {wait_time:.2f}s (limit {self.max_calls}/{self.period_seconds}s) before request...")
                with self._lock:
                    self._total_wait_time += wait_time
                time.sleep(wait_time)
            
            # После ожидания цикл повторится и снова проверит лимит
    
    def get_stats(self) -> dict:
        """Возвращает статистику по rate limiter."""
        with self._lock:
            return {
                "blocked_events": self._blocked_events,
                "total_wait_time_seconds": self._total_wait_time,
            }


def retry_on_failure(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    retryable_status_codes: tuple = (429, 500, 502, 503, 504),
    on_429_mode: Optional[str] = None
) -> Callable:
    """
    Декоратор для повторных попыток при неудачных API запросах.
    
    :param max_retries: Максимальное количество попыток
    :param backoff_factor: Множитель для экспоненциальной задержки
    :param retryable_status_codes: Коды статусов HTTP, при которых стоит повторять запрос
    :param on_429_mode: Режим обработки 429: "wait" (ждать) или "fail" (выбросить исключение).
                        Если None, пытается прочитать из self.on_429_mode (для GeckoTerminalPriceLoader)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            # Пытаемся получить on_429_mode из self, если не передан явно
            mode = on_429_mode
            if mode is None and args and hasattr(args[0], 'on_429_mode'):
                mode = args[0].on_429_mode
            if mode is None:
                mode = "wait"  # По умолчанию
            
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except HTTPError as e:
                    # Специальная обработка 429
                    if e.response.status_code == 429:
                        if mode == "fail":
                            print(f"[429 ❌] Rate limit exceeded, failing fast (on_429=fail)")
                            # Обновляем счётчик failures если есть self
                            if args and hasattr(args[0], '_rate_limit_failures'):
                                args[0]._rate_limit_failures += 1
                            raise RateLimitExceededError(f"Rate limit exceeded: {e}")
                        
                        # Режим wait - обрабатываем Retry-After
                        last_exception = e
                        if attempt < max_retries - 1:
                            # Пытаемся получить Retry-After из заголовка
                            retry_after = e.response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    wait_time = float(retry_after)
                                except (ValueError, TypeError):
                                    wait_time = max(2.1, backoff_factor ** attempt)
                            else:
                                # Нет Retry-After - используем безопасную задержку
                                wait_time = max(2.0, backoff_factor ** attempt)
                            
                            print(f"[429 ⏳] Rate limit exceeded, waiting {wait_time:.2f}s (Retry-After: {retry_after if retry_after else 'N/A'})... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                    
                    # Проверяем, стоит ли повторять запрос для других кодов
                    elif e.response.status_code in retryable_status_codes:
                        last_exception = e
                        if attempt < max_retries - 1:
                            wait_time = backoff_factor ** attempt
                            print(f"[WARNING] API request failed (status {e.response.status_code}), retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                    else:
                        # Неповторяемая ошибка - пробрасываем сразу
                        raise
                except RequestException as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt
                        print(f"[WARNING] API request failed ({type(e).__name__}), retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise
            
            # Если все попытки исчерпаны
            if last_exception:
                print(f"[ERROR] API request failed after {max_retries} attempts")
                raise last_exception
            
            # Этот код не должен достигнуться, но нужен для типизации
            raise RuntimeError("Unexpected end of retry loop")
            
        return wrapper
    return decorator


def validate_candle(candle: Candle, strict_validation: bool = False) -> bool:
    """
    Проверяет корректность данных свечи.
    
    Проверки:
    - Все цены должны быть положительными
    - high >= low
    - high >= open и high >= close
    - low <= open и low <= close
    - volume >= 0
    
    :param candle: Свеча для валидации
    :param strict_validation: Если True, выбрасывает исключение при некорректных данных
    :return: True если свеча корректна, False иначе
    """
    issues = []
    
    # Проверка положительных цен
    if candle.open <= 0:
        issues.append(f"open price must be positive, got {candle.open}")
    if candle.high <= 0:
        issues.append(f"high price must be positive, got {candle.high}")
    if candle.low <= 0:
        issues.append(f"low price must be positive, got {candle.low}")
    if candle.close <= 0:
        issues.append(f"close price must be positive, got {candle.close}")
    
    # Проверка логики OHLC
    if candle.high < candle.low:
        issues.append(f"high ({candle.high}) must be >= low ({candle.low})")
    if candle.high < candle.open:
        issues.append(f"high ({candle.high}) must be >= open ({candle.open})")
    if candle.high < candle.close:
        issues.append(f"high ({candle.high}) must be >= close ({candle.close})")
    if candle.low > candle.open:
        issues.append(f"low ({candle.low}) must be <= open ({candle.open})")
    if candle.low > candle.close:
        issues.append(f"low ({candle.low}) must be <= close ({candle.close})")
    
    # Проверка объема
    if candle.volume < 0:
        issues.append(f"volume must be non-negative, got {candle.volume}")
    
    if issues:
        error_msg = f"Invalid candle at {candle.timestamp}: {'; '.join(issues)}"
        if strict_validation:
            raise ValueError(error_msg)
        else:
            print(f"[WARNING] {error_msg}")
        return False
    
    return True


# Абстрактный базовый класс загрузчиков цен
class PriceLoader(ABC):
    @abstractmethod
    def load_prices(
        self,
        contract_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """
        Абстрактный метод, который должен быть реализован в потомках.
        Возвращает список свечей Candle для заданного контракта и периода времени.
        """
        raise NotImplementedError


# Загрузчик свечей из локального CSV-файла
class CsvPriceLoader(PriceLoader):
    def __init__(self, candles_dir: str, timeframe: str = "1m", strict_validation: bool = False):
        # Инициализация пути к папке с файлами и заданного таймфрейма (1m или 15m)
        self.candles_dir = Path(candles_dir)
        self.timeframe = timeframe
        self.strict_validation = strict_validation

    def _build_path(self, contract_address: str) -> Path:
        """
        Строит путь до CSV-файла по контракту и таймфрейму.
        """
        filename = f"{contract_address}_{self.timeframe}.csv"
        return self.candles_dir / filename

    def load_prices(self, contract_address: str, start_time=None, end_time=None) -> List[Candle]:
        """
        Загружает свечи из локального CSV-файла, фильтрует по диапазону времени.
        """
        path = self._build_path(contract_address)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")

        # Фильтрация по времени (если указано)
        if start_time is not None:
            df = df[df["timestamp"] >= start_time]
        if end_time is not None:
            df = df[df["timestamp"] <= end_time]

        # Преобразуем строки в объекты Candle с валидацией
        candles = []
        for row in df.itertuples(index=False):  # type: ignore[attr-defined]
            candle = Candle(
                timestamp=row.timestamp.to_pydatetime(),  # type: ignore[attr-defined]
                open=row.open,  # type: ignore[attr-defined]
                high=row.high,  # type: ignore[attr-defined]
                low=row.low,  # type: ignore[attr-defined]
                close=row.close,  # type: ignore[attr-defined]
                volume=row.volume,  # type: ignore[attr-defined]
            )
            if validate_candle(candle, strict_validation=self.strict_validation):
                candles.append(candle)
        
        return candles


# Загрузчик свечей с API GeckoTerminal с кешированием и историческим бэктрекингом
class GeckoTerminalPriceLoader(PriceLoader):
    def __init__(
        self, 
        cache_dir: str = "data/candles/cached", 
        timeframe: str = "1m", 
        max_cache_age_days: int = 2, 
        strict_validation: bool = False,
        max_retries: int = 3,
        retry_backoff_factor: float = 2.0,
        rate_limit_config: Optional[dict] = None,
        prefer_cache_if_exists: bool = True
    ):
        # Папка для кеша, целевой таймфрейм, допустимая свежесть кеша
        self.cache_dir = Path(cache_dir)
        self.timeframe = timeframe
        self.max_cache_age_days = max_cache_age_days
        self.strict_validation = strict_validation
        self.max_retries = max_retries
        self.retry_backoff_factor = retry_backoff_factor
        self.prefer_cache_if_exists = prefer_cache_if_exists
        
        # Настройки rate limit
        rate_limit_config = rate_limit_config or {}
        self.rate_limit_enabled = rate_limit_config.get("enabled", True)
        self.rate_limit_max_calls = rate_limit_config.get("max_calls_per_minute", 30)
        self.on_429_mode = rate_limit_config.get("on_429", "wait")  # "wait" или "fail"
        
        # Создаём rate limiter если включен
        if self.rate_limit_enabled:
            self.rate_limiter = RateLimiter(
                max_calls=self.rate_limit_max_calls,
                period_seconds=60
            )
        else:
            self.rate_limiter = None
        
        # Метрики
        self._total_requests = 0
        self._total_429_responses = 0
        self._rate_limit_failures = 0

    def _get_cache_paths(self, contract_address: str) -> List[Path]:
        """
        Возвращает список возможных путей к кэшу в порядке приоритета.
        
        Поддерживает два формата:
        1. Новый формат: cache_dir/{timeframe}/{contract}.csv (приоритет)
        2. Старый формат: cache_dir/{contract}_{timeframe}.csv (backward compatible)
        
        :param contract_address: Адрес контракта
        :return: Список путей в порядке приоритета
        """
        paths = []
        
        # Новый формат: cache_dir/{timeframe}/{contract}.csv
        timeframe_dir = self.cache_dir / self.timeframe
        paths.append(timeframe_dir / f"{contract_address}.csv")
        
        # Старый формат: cache_dir/{contract}_{timeframe}.csv
        paths.append(self.cache_dir / f"{contract_address}_{self.timeframe}.csv")
        
        return paths

    def _get_cache_path(self, contract_address: str) -> Path:
        """
        Возвращает путь до кешированного CSV-файла (новый формат).
        Структура: cache_dir/timeframe/contract.csv
        
        Папка timeframe создается автоматически при сохранении.
        """
        timeframe_dir = self.cache_dir / self.timeframe
        return timeframe_dir / f"{contract_address}.csv"

    def _is_cache_fresh(self, path: Path) -> bool:
        """
        Проверяет, не устарел ли кеш. 
        Возвращает True, если последний таймштамп файла не старше max_cache_age_days.
        """
        if not path.exists():
            return False
        try:
            df = pd.read_csv(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            last_ts = df["timestamp"].max()
            age = datetime.now(timezone.utc) - last_ts
            return age <= timedelta(days=self.max_cache_age_days)
        except Exception:
            return False

    def _load_from_cache(self, path: Path) -> Optional[List[Candle]]:
        """
        Загружает свечи из кеша. Возвращает None в случае ошибки.
        """
        try:
            df = pd.read_csv(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            candles = []
            for row in df.itertuples(index=False):  # type: ignore[attr-defined]
                candles.append(Candle(
                    timestamp=row.timestamp.to_pydatetime(),  # type: ignore[attr-defined]
                    open=row.open,  # type: ignore[attr-defined]
                    high=row.high,  # type: ignore[attr-defined]
                    low=row.low,  # type: ignore[attr-defined]
                    close=row.close,  # type: ignore[attr-defined]
                    volume=row.volume,  # type: ignore[attr-defined]
                ))
            return candles
        except Exception as e:
            print(f"⚠️ Failed to load cache from {path}: {e}")
            return None

    def _save_to_cache(self, path: Path, candles: List[Candle]):
        """
        Сохраняет свечи в кешированный CSV-файл.
        """
        try:
            os.makedirs(path.parent, exist_ok=True)
            df = pd.DataFrame([{
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            } for c in candles])
            df.to_csv(path, index=False)
            print(f"[cache] Saved {len(candles)} candles to cache: {path}")
        except Exception as e:
            print(f"[WARNING] Failed to save cache: {e}")

    def _http_get(self, url: str, headers: dict) -> requests.Response:
        """
        Единая точка отправки HTTP запросов с rate limiting.
        
        :param url: URL для запроса
        :param headers: HTTP заголовки
        :return: Response объект
        """
        # Применяем rate limiter если включен
        if self.rate_limiter:
            self.rate_limiter.acquire()
        
        self._total_requests += 1
        print(f"[HTTP] GET {url}")
        
        try:
            response = requests.get(url, headers=headers)
            
            # Отслеживаем 429 ответы
            if response.status_code == 429:
                self._total_429_responses += 1
                print(f"[429] Rate limit response received (total: {self._total_429_responses})")
            
            return response
        except Exception as e:
            print(f"[HTTP ERROR] Request failed: {e}")
            raise

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    def _fetch_pool_id(self, contract_address: str, headers: dict) -> str:
        """
        Получает идентификатор пула по адресу контракта с retry-логикой.
        Выбирает пул с наибольшей ликвидностью (reserve_in_usd).
        """
        pools_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{contract_address}/pools"
        print(f"[fetch] Fetching pools for token: {contract_address}")
        r = self._http_get(pools_url, headers)
        r.raise_for_status()
        
        data = r.json()
        pools = data.get("data", [])
        
        if not pools:
            raise ValueError(f"No pools found for token {contract_address}")
        
        # Выбираем пул с наибольшей ликвидностью (reserve_in_usd)
        # Если reserve_in_usd нет, берем первый пул
        best_pool = None
        max_reserve = 0.0
        
        for pool in pools:
            attrs = pool.get("attributes", {})
            reserve_str = attrs.get("reserve_in_usd")
            if reserve_str:
                try:
                    reserve = float(reserve_str)
                    if reserve > max_reserve:
                        max_reserve = reserve
                        best_pool = pool
                except (ValueError, TypeError):
                    pass
        
        # Если не нашли пул с reserve_in_usd, берем первый
        if best_pool is None:
            best_pool = pools[0]
            print(f"[WARNING] No reserve_in_usd found, using first pool")
        
        pool_id_raw = best_pool["attributes"]["address"]
        pool_name = best_pool["attributes"].get("name", "Unknown")
        reserve = best_pool["attributes"].get("reserve_in_usd", "N/A")
        
        # Убеждаемся, что pool_id - это строка
        pool_id = str(pool_id_raw).strip()
        
        # Проверяем корректность pool_id (Solana addresses могут быть 43-44 символа)
        if not pool_id or len(pool_id) < 43 or len(pool_id) > 44:
            print(f"[WARNING] Warning: Invalid pool_id format: {pool_id} (length: {len(pool_id) if pool_id else 0})")
            print(f"   Raw pool_id: {repr(pool_id_raw)}")
            print(f"   Expected length: 43-44 characters (Solana address)")
        
        print(f"[OK] Selected pool: {pool_id} ({pool_name}), reserve: {reserve} USD")
        
        return pool_id

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    def _fetch_ohlcv_batch(self, pool_id: str, tf_endpoint: str, aggregate: Optional[str], 
                           before_ts: int, headers: dict) -> List:
        """
        Получает батч свечей OHLCV с retry-логикой.
        """
        # Нормализуем pool_id (убираем пробелы)
        pool_id = str(pool_id).strip()
        
        # Проверяем, что pool_id имеет правильную длину (Solana addresses могут быть 43-44 символа)
        if len(pool_id) < 43 or len(pool_id) > 44:
            print(f"[WARNING] Warning: pool_id length is {len(pool_id)}, expected 43-44")
            print(f"   Pool ID received: {repr(pool_id)}")
        
        query = f"limit=1000&before_timestamp={before_ts}"
        if aggregate:
            query += f"&aggregate={aggregate}"
        
        ohlcv_url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_id}/ohlcv/{tf_endpoint}?{query}"
        print(f"[fetch] Fetching: {ohlcv_url}")
        res = self._http_get(ohlcv_url, headers)
        
        # Проверяем статус ответа
        if res.status_code == 404:
            error_data = res.json() if res.content else {}
            error_msg = error_data.get("errors", [{}])[0].get("title", "Not Found") if error_data.get("errors") else "Not Found"
            raise HTTPError(
                f"Pool {pool_id} not found or has no OHLCV data for timeframe {tf_endpoint} (aggregate={aggregate}). "
                f"Error: {error_msg}. "
                f"This usually means: 1) Pool was removed/deactivated, 2) Pool has no trading history, "
                f"3) Requested timeframe is not available for this pool.",
                response=res
            )
        
        res.raise_for_status()
        response_data = res.json()
        
        # Проверяем структуру ответа
        if "data" not in response_data:
            print(f"[WARNING] Unexpected response structure: {response_data}")
            return []
        
        return response_data["data"]["attributes"].get("ohlcv_list", [])

    def load_prices(self, contract_address: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Candle]:
        """
        Основной метод. Загружает свечи из API GeckoTerminal с умным кешированием.
        
        Логика работы:
        1. Проверяет наличие кеша (поддерживает новый и старый формат)
        2. Если prefer_cache_if_exists=True и кеш найден - использует только кеш (cache-only режим)
        3. Если prefer_cache_if_exists=False - проверяет покрытие диапазона и дозагружает при необходимости
        4. Сохраняет обновленный кеш в новом формате
        
        :param contract_address: Адрес контракта токена
        :param start_time: Начало временного диапазона (опционально)
        :param end_time: Конец временного диапазона (опционально)
        :return: Список свечей в указанном диапазоне
        """
        # Ищем кэш в обоих форматах
        cache_paths = self._get_cache_paths(contract_address)
        cache_path: Optional[Path] = None
        cached_candles: Optional[List[Candle]] = None
        is_legacy_format = False
        
        # Пытаемся найти существующий кэш
        for path in cache_paths:
            if path.exists():
                cache_path = path
                # Определяем, это старый формат или новый
                is_legacy_format = (path == cache_paths[1])  # Второй путь - старый формат
                cached_candles = self._load_from_cache(path)
                if cached_candles is not None:
                    break
        
        # Если кеш найден и успешно загружен
        if cached_candles and len(cached_candles) > 0:
            cached_candles.sort(key=lambda c: c.timestamp)
            cache_min = cached_candles[0].timestamp
            cache_max = cached_candles[-1].timestamp
            
            # Если включен режим prefer_cache_if_exists - используем кэш без API запросов
            if self.prefer_cache_if_exists:
                filtered = [
                    c for c in cached_candles
                    if (start_time is None or c.timestamp >= start_time) and
                       (end_time is None or c.timestamp <= end_time)
                ]
                
                # Проверяем покрытие диапазона для логирования
                covers_start = (start_time is None) or (cache_min <= start_time)
                covers_end = (end_time is None) or (cache_max >= end_time)
                
                if covers_start and covers_end:
                    print(f"[CACHE OK] cache-hit (cache-only) {contract_address} path={cache_path}")
                else:
                    missing_info = []
                    if not covers_start:
                        missing_info.append(f"start (have: {_format_datetime(cache_min)}, need: {_format_datetime(start_time)})")
                    if not covers_end:
                        missing_info.append(f"end (have: {_format_datetime(cache_max)}, need: {_format_datetime(end_time)})")
                    print(f"[CACHE WARNING] cache-hit but incomplete range (cache-only) {contract_address} have={_format_datetime(cache_min)} to {_format_datetime(cache_max)} need={' to '.join(missing_info) if missing_info else 'full range'}")
                
                # Миграция из старого формата в новый (если нужно)
                if is_legacy_format and cache_path:
                    new_cache_path = cache_paths[0]  # Новый формат
                    if not new_cache_path.exists():
                        print(f"[CACHE] Migrating cache from legacy format: {cache_path} -> {new_cache_path}")
                        self._save_to_cache(new_cache_path, cached_candles)
                
                return filtered
            
            # Старая логика: проверяем покрытие диапазона
            covers_start = (start_time is None) or (cache_min <= start_time)
            covers_end = (end_time is None) or (cache_max >= end_time)
            
            if covers_start and covers_end:
                # Кеш полностью покрывает диапазон - используем только его
                filtered = [
                    c for c in cached_candles
                    if (start_time is None or c.timestamp >= start_time) and
                       (end_time is None or c.timestamp <= end_time)
                ]
                print(f"[CACHE OK] Using cached candles for {contract_address} ({len(filtered)} candles, range: {_format_datetime(cache_min)} to {_format_datetime(cache_max)})")
                
                # Миграция из старого формата в новый (если нужно)
                if is_legacy_format and cache_path:
                    new_cache_path = cache_paths[0]  # Новый формат
                    if not new_cache_path.exists():
                        print(f"[CACHE] Migrating cache from legacy format: {cache_path} -> {new_cache_path}")
                        self._save_to_cache(new_cache_path, cached_candles)
                
                return filtered
            else:
                # Диапазон не покрыт полностью - перезагружаем полностью
                missing_info = []
                if not covers_start:
                    missing_info.append(f"start (cache: {_format_datetime(cache_min)}, needed: {_format_datetime(start_time)})")
                if not covers_end:
                    missing_info.append(f"end (cache: {_format_datetime(cache_max)}, needed: {_format_datetime(end_time)})")
                print(f"[CACHE WARNING] Incomplete coverage for {contract_address} (missing: {', '.join(missing_info)}), reloading from API")
        else:
            # Кеша нет - загружаем все с нуля
            print(f"[CACHE ERROR] cache-miss {contract_address} -> API")
        
        # Загружаем свечи через API (полная перезагрузка для простоты)
        # TODO: Оптимизировать - дозагружать только недостающие части
        candles: List[Candle] = []
        now_ts = int(datetime.now(timezone.utc).timestamp())

        try:
            headers = {"User-Agent": "Mozilla/5.0 GeckoLoader"}
            tf_map = {"1m": ("minute", None), "15m": ("minute", "15")}
            tf_endpoint, aggregate = tf_map[self.timeframe]

            # Получаем идентификатор пула (pool_id) по адресу контракта с retry
            pool_id = self._fetch_pool_id(contract_address, headers)
            pool_id = str(pool_id).strip()  # Нормализуем pool_id

            # Определяем начальный timestamp для загрузки
            # Если указан end_time, используем его, иначе текущее время
            if end_time:
                before_ts = int(end_time.timestamp())
                # Проверяем, что timestamp не в будущем
                if before_ts > now_ts:
                    print(f"⚠️ Warning: end_time is in the future, using current time instead")
                    before_ts = now_ts
            else:
                before_ts = now_ts
            
            # Проверяем, что timestamp не слишком старый (больше 6 месяцев назад API не возвращает данные)
            six_months_ago = int((datetime.now(timezone.utc) - timedelta(days=180)).timestamp())
            if before_ts < six_months_ago:
                print(f"[WARNING] Warning: Requested timestamp is more than 6 months ago. GeckoTerminal API may not have data.")
                print(f"   Requested: {before_ts} ({datetime.fromtimestamp(before_ts, tz=timezone.utc)})")
                print(f"   Limit: {six_months_ago} ({datetime.fromtimestamp(six_months_ago, tz=timezone.utc)})")
            
            seen = set()        # для исключения дубликатов

            # Загружаем свечи батчами по 1000 штук, двигаясь в прошлое
            while True:
                # Получаем батч свечей с retry
                try:
                    candles_raw = self._fetch_ohlcv_batch(pool_id, tf_endpoint, aggregate, before_ts, headers)
                except HTTPError as e:
                    # Если 404 - пул не найден или нет данных для этого таймфрейма
                    if e.response and e.response.status_code == 404:
                        print(f"[ERROR] Pool {pool_id} returned 404. Possible reasons:")
                        print(f"   1. Pool was removed or deactivated")
                        print(f"   2. Pool has no trading history")
                        print(f"   3. Requested timeframe ({self.timeframe}) is not available")
                        print(f"   4. Timestamp {before_ts} is too far in the past/future")
                        # Пытаемся использовать кеш, если есть
                        if cached_candles:
                            print(f"[WARNING] Falling back to cached candles due to 404 error")
                            return [
                                c for c in cached_candles
                                if (start_time is None or c.timestamp >= start_time) and
                                   (end_time is None or c.timestamp <= end_time)
                            ]
                        raise
                    else:
                        raise
                
                if not candles_raw:
                    break  # данных больше нет

                # Преобразуем в объекты Candle и исключаем дубли
                # Формат GeckoTerminal API: [timestamp, open, high, low, close, volume]
                batch = []
                for row in candles_raw:
                    if row[0] not in seen:
                        candle = Candle(
                            timestamp=datetime.utcfromtimestamp(row[0]).replace(tzinfo=timezone.utc),
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[5]),
                        )
                        if validate_candle(candle, strict_validation=self.strict_validation):
                            batch.append(candle)
                seen.update(row[0] for row in candles_raw)
                candles.extend(batch)

                # Если получили непустой ответ, но все свечи уже были в seen (дубликаты),
                # значит мы достигли конца данных - прерываем цикл
                if candles_raw and not batch:
                    print(f"[WARNING] All candles in batch were duplicates, stopping fetch")
                    break

                # Прерываем, если достигли нужной начальной даты
                if start_time and batch and batch[-1].timestamp <= start_time:
                    break

                # Продвигаемся дальше в прошлое
                if batch:
                    before_ts = int(batch[-1].timestamp.timestamp())
                else:
                    # Если batch пустой, но candles_raw не пустой (что не должно происходить после проверки выше),
                    # все равно прерываем, чтобы избежать бесконечного цикла
                    print(f"[WARNING] Empty batch but non-empty response, stopping to avoid infinite loop")
                    break

            candles.sort(key=lambda c: c.timestamp)  # сортировка по времени
            print(f"[fetch] Total candles fetched: {len(candles)}")
            
            # Сохраняем обновленный кеш в новом формате
            new_cache_path = self._get_cache_path(contract_address)
            self._save_to_cache(new_cache_path, candles)

        except RateLimitExceededError:
            # Rate limit exceeded в fail-fast режиме - пробрасываем дальше
            raise
        except HTTPError as e:
            # Детальная обработка HTTP ошибок
            if e.response and e.response.status_code == 404:
                print(f"[ERROR] HTTP 404: Pool or OHLCV data not found for {contract_address}")
                print(f"   URL: {e.response.url if hasattr(e.response, 'url') else 'N/A'}")
            else:
                print(f"[ERROR] HTTP Error loading candles for {contract_address}: {e}")
            
            # В случае ошибки API, пытаемся вернуть кеш, если он есть
            if cached_candles:
                print(f"[WARNING] Falling back to cached candles due to API error")
                return [
                    c for c in cached_candles
                    if (start_time is None or c.timestamp >= start_time) and
                       (end_time is None or c.timestamp <= end_time)
                ]
            return []
        except Exception as e:
            print(f"[ERROR] Error loading candles for {contract_address}: {e}")
            import traceback
            traceback.print_exc()
            # В случае ошибки API, пытаемся вернуть кеш, если он есть
            if cached_candles:
                print(f"[WARNING] Falling back to cached candles due to API error")
                return [
                    c for c in cached_candles
                    if (start_time is None or c.timestamp >= start_time) and
                       (end_time is None or c.timestamp <= end_time)
                ]
            return []

        # Возвращаем свечи, соответствующие указанному временному окну
        return [
            c for c in candles
            if (start_time is None or c.timestamp >= start_time) and
               (end_time is None or c.timestamp <= end_time)
        ]
    
    def get_rate_limit_summary(self) -> dict:
        """
        Возвращает summary по rate limit метрикам.
        """
        stats = {
            "total_requests": self._total_requests,
            "http_429": self._total_429_responses,
            "rate_limit_failures": self._rate_limit_failures,
            "mode_on_429": self.on_429_mode,
        }
        
        if self.rate_limiter:
            limiter_stats = self.rate_limiter.get_stats()
            stats.update({
                "requests_blocked_by_rate_limiter": limiter_stats["blocked_events"],
                "total_wait_time_seconds": limiter_stats["total_wait_time_seconds"],
            })
        else:
            stats.update({
                "requests_blocked_by_rate_limiter": 0,
                "total_wait_time_seconds": 0.0,
            })
        
        return stats
