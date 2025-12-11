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

from ..domain.models import Candle  # Импорт структуры свечи

T = TypeVar('T')


def retry_on_failure(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    retryable_status_codes: tuple = (429, 500, 502, 503, 504)
) -> Callable:
    """
    Декоратор для повторных попыток при неудачных API запросах.
    
    :param max_retries: Максимальное количество попыток
    :param backoff_factor: Множитель для экспоненциальной задержки
    :param retryable_status_codes: Коды статусов HTTP, при которых стоит повторять запрос
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except HTTPError as e:
                    # Проверяем, стоит ли повторять запрос
                    if e.response.status_code in retryable_status_codes:
                        last_exception = e
                        if attempt < max_retries - 1:
                            wait_time = backoff_factor ** attempt
                            print(f"⚠️ API request failed (status {e.response.status_code}), retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                    else:
                        # Неповторяемая ошибка - пробрасываем сразу
                        raise
                except RequestException as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt
                        print(f"⚠️ API request failed ({type(e).__name__}), retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise
            
            # Если все попытки исчерпаны
            if last_exception:
                print(f"❌ API request failed after {max_retries} attempts")
                raise last_exception
            
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
            print(f"⚠️ {error_msg}")
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
        for row in df.itertuples(index=False):
            candle = Candle(
                timestamp=row.timestamp.to_pydatetime(),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
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
        retry_backoff_factor: float = 2.0
    ):
        # Папка для кеша, целевой таймфрейм, допустимая свежесть кеша
        self.cache_dir = Path(cache_dir)
        self.timeframe = timeframe
        self.max_cache_age_days = max_cache_age_days
        self.strict_validation = strict_validation
        self.max_retries = max_retries
        self.retry_backoff_factor = retry_backoff_factor

    def _get_cache_path(self, contract_address: str) -> Path:
        """
        Возвращает путь до кешированного CSV-файла.
        """
        return self.cache_dir / f"{contract_address}_{self.timeframe}.csv"

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
            return [
                Candle(
                    timestamp=row.timestamp.to_pydatetime(),
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                ) for row in df.itertuples(index=False)
            ]
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
            print(f"📅 Saved {len(candles)} candles to cache: {path}")
        except Exception as e:
            print(f"⚠️ Failed to save cache: {e}")

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    def _fetch_pool_id(self, contract_address: str, headers: dict) -> str:
        """
        Получает идентификатор пула по адресу контракта с retry-логикой.
        """
        pools_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{contract_address}/pools"
        r = requests.get(pools_url, headers=headers)
        r.raise_for_status()
        return r.json()["data"][0]["attributes"]["address"]

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    def _fetch_ohlcv_batch(self, pool_id: str, tf_endpoint: str, aggregate: Optional[str], 
                           before_ts: int, headers: dict) -> List:
        """
        Получает батч свечей OHLCV с retry-логикой.
        """
        query = f"limit=1000&before_timestamp={before_ts}"
        if aggregate:
            query += f"&aggregate={aggregate}"

        ohlcv_url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_id}/ohlcv/{tf_endpoint}?{query}"
        print(f"⬅️ Fetching: {ohlcv_url}")
        res = requests.get(ohlcv_url, headers=headers)
        res.raise_for_status()
        return res.json()["data"]["attributes"].get("ohlcv_list", [])

    def load_prices(self, contract_address: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Candle]:
        """
        Основной метод. Загружает свечи из API GeckoTerminal вглубь истории через пагинацию.
        Сохраняет результат в кеш. Возвращает только свечи в нужном диапазоне.
        """
        cache_path = self._get_cache_path(contract_address)
        candles: List[Candle] = []
        now_ts = int(datetime.now(timezone.utc).timestamp())  # текущий момент

        try:
            headers = {"User-Agent": "Mozilla/5.0 GeckoLoader"}
            tf_map = {"1m": ("minute", None), "15m": ("minute", "15")}
            tf_endpoint, aggregate = tf_map[self.timeframe]

            # Получаем идентификатор пула (pool_id) по адресу контракта с retry
            pool_id = self._fetch_pool_id(contract_address, headers)

            before_ts = now_ts  # начнем выгрузку с настоящего времени
            seen = set()        # для исключения дубликатов

            # Загружаем свечи батчами по 1000 штук, двигаясь в прошлое
            while True:
                # Получаем батч свечей с retry
                candles_raw = self._fetch_ohlcv_batch(pool_id, tf_endpoint, aggregate, before_ts, headers)
                
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

                # Прерываем, если достигли нужной начальной даты
                if start_time and batch and batch[-1].timestamp <= start_time:
                    break

                # Продвигаемся дальше в прошлое
                if batch:
                    before_ts = int(batch[-1].timestamp.timestamp())

            candles.sort(key=lambda c: c.timestamp)  # сортировка по времени
            print(f"📦 Total candles fetched: {len(candles)}")
            self._save_to_cache(cache_path, candles)

        except Exception as e:
            print(f"❌ Error loading candles for {contract_address}: {e}")

        # Возвращаем свечи, соответствующие указанному временному окну
        return [
            c for c in candles
            if (start_time is None or c.timestamp >= start_time) and
               (end_time is None or c.timestamp <= end_time)
        ]
