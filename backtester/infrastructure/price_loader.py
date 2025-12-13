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
        Выбирает пул с наибольшей ликвидностью (reserve_in_usd).
        """
        pools_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{contract_address}/pools"
        print(f"🔍 Fetching pools for token: {contract_address}")
        r = requests.get(pools_url, headers=headers)
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
            print(f"⚠️ No reserve_in_usd found, using first pool")
        
        pool_id_raw = best_pool["attributes"]["address"]
        pool_name = best_pool["attributes"].get("name", "Unknown")
        reserve = best_pool["attributes"].get("reserve_in_usd", "N/A")
        
        # Убеждаемся, что pool_id - это строка и не изменяется
        pool_id = str(pool_id_raw).strip()
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: убеждаемся, что pool_id не содержит опечаток
        # Проверяем на наличие подозрительных паттернов (например, двойных букв)
        if pool_id.count('dd') > 0 and 'Rpddp' in pool_id:
            print(f"⚠️ WARNING: Detected suspicious pattern 'Rpddp' in pool_id: {pool_id}")
            print(f"   This might be a typo - expected 'Rpdp' (single 'd')")
            # НЕ исправляем автоматически, только предупреждаем
        
        # Проверяем корректность pool_id
        if not pool_id or len(pool_id) != 44:
            print(f"⚠️ Warning: Invalid pool_id format: {pool_id} (length: {len(pool_id) if pool_id else 0})")
            print(f"   Raw pool_id: {repr(pool_id_raw)}")
        
        # Логируем для отладки с проверкой
        print(f"✅ Selected pool: {pool_id} ({pool_name}), reserve: {reserve} USD")
        print(f"   🔍 Pool ID verification: {pool_id} (type: {type(pool_id)}, length: {len(pool_id)})")
        
        # Дополнительная проверка: выводим все пулы для отладки
        if len(pools) > 1:
            print(f"   📋 Available pools ({len(pools)} total):")
            for i, p in enumerate(pools[:3]):  # Показываем первые 3
                p_addr = p.get("attributes", {}).get("address", "N/A")
                p_reserve = p.get("attributes", {}).get("reserve_in_usd", "N/A")
                marker = " ← SELECTED" if p_addr == pool_id else ""
                print(f"      {i+1}. {p_addr} (reserve: {p_reserve}){marker}")
        
        return pool_id

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    def _fetch_ohlcv_batch(self, pool_id: str, tf_endpoint: str, aggregate: Optional[str], 
                           before_ts: int, headers: dict) -> List:
        """
        Получает батч свечей OHLCV с retry-логикой.
        """
        # Нормализуем pool_id (убираем пробелы, проверяем формат)
        pool_id = str(pool_id).strip()
        
        # Проверяем, что pool_id не изменился
        if len(pool_id) != 44:  # Solana addresses are 44 characters
            print(f"⚠️ Warning: pool_id length is {len(pool_id)}, expected 44")
            print(f"   Pool ID received: {repr(pool_id)}")
        
        query = f"limit=1000&before_timestamp={before_ts}"
        if aggregate:
            query += f"&aggregate={aggregate}"

        # Проверяем, что pool_id не был изменен (защита от багов)
        if 'dd' in pool_id and pool_id.count('dd') > pool_id.count('dp'):
            print(f"⚠️ WARNING: Suspicious pool_id detected: {pool_id}")
            print(f"   This might indicate a bug in pool_id handling")
        
        ohlcv_url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_id}/ohlcv/{tf_endpoint}?{query}"
        print(f"⬅️ Fetching: {ohlcv_url}")
        print(f"   🔍 Pool ID in URL: {pool_id} (length: {len(pool_id)}, hex: {pool_id.encode('utf-8').hex()[:20]}...)")  # Дополнительное логирование для отладки
        res = requests.get(ohlcv_url, headers=headers)
        
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
            print(f"⚠️ Unexpected response structure: {response_data}")
            return []
        
        return response_data["data"]["attributes"].get("ohlcv_list", [])

    def load_prices(self, contract_address: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Candle]:
        """
        Основной метод. Загружает свечи из API GeckoTerminal с умным кешированием.
        
        Логика работы:
        1. Проверяет наличие кеша
        2. Если кеш покрывает нужный диапазон полностью - использует только кеш
        3. Если диапазон не покрыт - дозагружает недостающие данные через API
        4. Сохраняет обновленный кеш
        
        :param contract_address: Адрес контракта токена
        :param start_time: Начало временного диапазона (опционально)
        :param end_time: Конец временного диапазона (опционально)
        :return: Список свечей в указанном диапазоне
        """
        cache_path = self._get_cache_path(contract_address)
        cached_candles: Optional[List[Candle]] = None
        
        # Проверяем наличие кеша
        if cache_path.exists():
            cached_candles = self._load_from_cache(cache_path)
        
        # Если кеш есть, проверяем покрытие диапазона
        if cached_candles and len(cached_candles) > 0:
            cached_candles.sort(key=lambda c: c.timestamp)
            cache_min = cached_candles[0].timestamp
            cache_max = cached_candles[-1].timestamp
            
            # Проверяем, покрывает ли кеш нужный диапазон
            covers_start = (start_time is None) or (cache_min <= start_time)
            covers_end = (end_time is None) or (cache_max >= end_time)
            
            if covers_start and covers_end:
                # Кеш полностью покрывает диапазон - используем только его
                filtered = [
                    c for c in cached_candles
                    if (start_time is None or c.timestamp >= start_time) and
                       (end_time is None or c.timestamp <= end_time)
                ]
                print(f"[CACHE ✅] Using cached candles for {contract_address} ({len(filtered)} candles, range: {cache_min} to {cache_max})")
                return filtered
            else:
                # Диапазон не покрыт полностью - перезагружаем полностью
                missing_info = []
                if not covers_start:
                    missing_info.append(f"start (cache: {cache_min}, needed: {start_time})")
                if not covers_end:
                    missing_info.append(f"end (cache: {cache_max}, needed: {end_time})")
                print(f"[CACHE ⚠️] Incomplete coverage for {contract_address} (missing: {', '.join(missing_info)}), reloading from API")
        else:
            # Кеша нет - загружаем все с нуля
            print(f"[CACHE ❌] No cache found, loading from API for {contract_address}")
        
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
            
            # Сохраняем оригинальный pool_id для проверки (не должен изменяться)
            original_pool_id = pool_id
            print(f"🔍 Received pool_id in load_prices: {pool_id} (length: {len(pool_id)})")  # Дополнительное логирование

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
                print(f"⚠️ Warning: Requested timestamp is more than 6 months ago. GeckoTerminal API may not have data.")
                print(f"   Requested: {before_ts} ({datetime.fromtimestamp(before_ts, tz=timezone.utc)})")
                print(f"   Limit: {six_months_ago} ({datetime.fromtimestamp(six_months_ago, tz=timezone.utc)})")
            
            seen = set()        # для исключения дубликатов

            # Загружаем свечи батчами по 1000 штук, двигаясь в прошлое
            while True:
                # Проверяем, что pool_id не изменился
                if pool_id != original_pool_id:
                    print(f"⚠️ WARNING: pool_id changed from {original_pool_id} to {pool_id}!")
                    pool_id = original_pool_id  # Восстанавливаем оригинальный
                
                # Получаем батч свечей с retry
                try:
                    candles_raw = self._fetch_ohlcv_batch(pool_id, tf_endpoint, aggregate, before_ts, headers)
                except HTTPError as e:
                    # Если 404 - пул не найден или нет данных для этого таймфрейма
                    if e.response and e.response.status_code == 404:
                        print(f"❌ Pool {pool_id} returned 404. Possible reasons:")
                        print(f"   1. Pool was removed or deactivated")
                        print(f"   2. Pool has no trading history")
                        print(f"   3. Requested timeframe ({self.timeframe}) is not available")
                        print(f"   4. Timestamp {before_ts} is too far in the past/future")
                        # Пытаемся использовать кеш, если есть
                        if cached_candles:
                            print(f"⚠️ Falling back to cached candles due to 404 error")
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
                    print(f"⚠️ All candles in batch were duplicates, stopping fetch")
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
                    print(f"⚠️ Empty batch but non-empty response, stopping to avoid infinite loop")
                    break

            candles.sort(key=lambda c: c.timestamp)  # сортировка по времени
            print(f"📦 Total candles fetched: {len(candles)}")
            
            # Сохраняем обновленный кеш
            self._save_to_cache(cache_path, candles)

        except HTTPError as e:
            # Детальная обработка HTTP ошибок
            if e.response and e.response.status_code == 404:
                print(f"❌ HTTP 404: Pool or OHLCV data not found for {contract_address}")
                print(f"   URL: {e.response.url if hasattr(e.response, 'url') else 'N/A'}")
            else:
                print(f"❌ HTTP Error loading candles for {contract_address}: {e}")
            
            # В случае ошибки API, пытаемся вернуть кеш, если он есть
            if cached_candles:
                print(f"⚠️ Falling back to cached candles due to API error")
                return [
                    c for c in cached_candles
                    if (start_time is None or c.timestamp >= start_time) and
                       (end_time is None or c.timestamp <= end_time)
                ]
            return []
        except Exception as e:
            print(f"❌ Error loading candles for {contract_address}: {e}")
            import traceback
            traceback.print_exc()
            # В случае ошибки API, пытаемся вернуть кеш, если он есть
            if cached_candles:
                print(f"⚠️ Falling back to cached candles due to API error")
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
