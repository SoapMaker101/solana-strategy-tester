# backtester/research/signal_quality/feature_extractor.py
"""
Модуль для извлечения признаков из сигналов.

Вычисляет:
- entry_price: цена входа (на момент сигнала или t+1m)
- market_cap_proxy: прокси market cap (entry_price × 1_000_000_000)
- max_xn: максимальный множитель цены в окне анализа
- time_to_xn: время до достижения уровней (2x, 3x, 5x, 7x, 10x)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ...domain.models import Candle, Signal
from ...infrastructure.price_loader import CsvPriceLoader
from ...infrastructure.signal_loader import CsvSignalLoader


def load_signals(path: str | Path) -> pd.DataFrame:
    """
    Загружает сигналы из CSV файла и возвращает DataFrame.
    
    :param path: Путь к CSV файлу с сигналами
    :return: DataFrame с колонками id, contract_address, timestamp, source, narrative
    """
    loader = CsvSignalLoader(str(path))
    signals = loader.load_signals()
    
    # Преобразуем в DataFrame
    data = []
    for sig in signals:
        data.append({
            "id": sig.id,
            "contract_address": sig.contract_address,
            "timestamp": sig.timestamp,
            "source": sig.source,
            "narrative": sig.narrative,
        })
    
    return pd.DataFrame(data)


def load_candles(contract: str, timeframe: str, candles_dir: str) -> List[Candle]:
    """
    Загружает свечи для контракта.
    
    :param contract: Адрес контракта
    :param timeframe: Таймфрейм ("1m", "5m", "15m")
    :param candles_dir: Базовая директория со свечами
    :return: Список свечей Candle
    """
    loader = CsvPriceLoader(candles_dir=candles_dir, timeframe=timeframe)
    return loader.load_prices(contract_address=contract)


def get_entry_price(
    candles: List[Candle],
    signal_ts: datetime,
    mode: str = "t+1m"
) -> Optional[float]:
    """
    Получает цену входа для сигнала.
    
    Логика:
    - mode="t+1m": ищет свечу с timestamp >= signal_ts + 1 минута (или ближайшую следующую)
    - mode="t": ищет свечу на момент сигнала (timestamp >= signal_ts)
    - fallback: если нет свечи для t+1m, пробует "t"
    - если всё равно нет — возвращает None
    
    :param candles: Список свечей (должен быть отсортирован по timestamp)
    :param signal_ts: Время сигнала
    :param mode: Режим поиска ("t+1m" или "t")
    :return: Цена входа (close цена свечи) или None
    """
    if not candles:
        return None
    
    # Сортируем свечи по timestamp (на всякий случай)
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    
    target_time = signal_ts
    if mode == "t+1m":
        target_time = signal_ts + timedelta(minutes=1)
    
    # Ищем первую свечу с timestamp >= target_time
    for candle in sorted_candles:
        if candle.timestamp >= target_time:
            return candle.close
    
    # Если не нашли для t+1m, пробуем fallback на "t"
    if mode == "t+1m":
        return get_entry_price(candles, signal_ts, mode="t")
    
    return None


def compute_market_cap_proxy(entry_price: float, supply: float = 1_000_000_000) -> float:
    """
    Вычисляет прокси market cap.
    
    Формула: market_cap_proxy = entry_price × supply
    
    :param entry_price: Цена входа
    :param supply: Предполагаемый supply (по умолчанию 1 млрд)
    :return: Прокси market cap
    """
    if entry_price is None or entry_price <= 0:
        return 0.0
    return entry_price * supply


def compute_max_xn(
    candles: List[Candle],
    entry_price: float,
    entry_time: datetime,
    horizon_minutes: int,
    use_high: bool = True
) -> Tuple[float, Dict[str, Optional[int]]]:
    """
    Вычисляет максимальный множитель цены (max_xn) и время до достижения уровней.
    
    :param candles: Список свечей (должен быть отсортирован по timestamp)
    :param entry_price: Цена входа
    :param entry_time: Время входа
    :param horizon_minutes: Горизонт анализа в минутах
    :param use_high: Если True, использует high цену, иначе close
    :return: (max_xn, time_to_levels_dict)
        - max_xn: максимальный множитель (max(price/entry_price))
        - time_to_levels_dict: словарь {level: minutes} для уровней 2x, 3x, 5x, 7x, 10x
    """
    if not candles or entry_price <= 0:
        return 0.0, {}
    
    # Сортируем свечи по timestamp
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    
    # Определяем окно анализа
    end_time = entry_time + timedelta(minutes=horizon_minutes)
    
    # Фильтруем свечи в окне
    window_candles = [
        c for c in sorted_candles
        if entry_time <= c.timestamp <= end_time
    ]
    
    if not window_candles:
        return 0.0, {}
    
    # Вычисляем max_xn
    max_xn = 0.0
    price_key = "high" if use_high else "close"
    
    for candle in window_candles:
        price = candle.high if use_high else candle.close
        if price > 0:
            xn = price / entry_price
            if xn > max_xn:
                max_xn = xn
    
    # Вычисляем время до достижения уровней
    levels = [2.0, 3.0, 5.0, 7.0, 10.0]
    time_to_levels: Dict[str, Optional[int]] = {}
    
    for level in levels:
        target_price = entry_price * level
        time_to_level = None
        
        for candle in window_candles:
            price = candle.high if use_high else candle.close
            if price >= target_price:
                # Вычисляем разницу в минутах
                delta = candle.timestamp - entry_time
                time_to_level = int(delta.total_seconds() / 60)
                break
        
        time_to_levels[f"time_to_{int(level)}x_minutes"] = time_to_level
    
    return max_xn, time_to_levels


def extract_signal_features(
    signals_df: pd.DataFrame,
    candles_dir: str,
    timeframe: str = "1m",
    entry_mode: str = "t+1m",
    horizon_days: int = 14,
    use_high: bool = True
) -> pd.DataFrame:
    """
    Извлекает признаки для всех сигналов.
    
    :param signals_df: DataFrame с сигналами (колонки: id, contract_address, timestamp)
    :param candles_dir: Базовая директория со свечами
    :param timeframe: Таймфрейм свечей
    :param entry_mode: Режим поиска entry_price ("t+1m" или "t")
    :param horizon_days: Горизонт анализа в днях
    :param use_high: Использовать high цену для max_xn
    :return: DataFrame с признаками сигналов
    """
    horizon_minutes = horizon_days * 24 * 60
    
    results = []
    
    for idx, row in signals_df.iterrows():
        signal_id = signals_df.at[idx, "id"]
        contract = str(signals_df.at[idx, "contract_address"])
        # Convert timestamp to datetime, handling both datetime and string types
        ts_value = signals_df.at[idx, "timestamp"]
        if isinstance(ts_value, datetime):
            signal_ts: datetime = ts_value
        else:
            try:
                ts = pd.Timestamp(ts_value)
                # Check if timestamp is NaT
                if ts is pd.NaT:
                    # Skip rows with invalid timestamps
                    results.append({
                        "signal_id": signal_id,
                        "contract_address": contract,
                        "timestamp": None,
                        "entry_time": None,
                        "entry_price": None,
                        "market_cap_proxy": None,
                        "max_xn": None,
                        "time_to_2x_minutes": None,
                        "time_to_3x_minutes": None,
                        "time_to_5x_minutes": None,
                        "time_to_7x_minutes": None,
                        "time_to_10x_minutes": None,
                        "lived_minutes": None,
                        "status": "invalid_timestamp",
                        "error_message": "Invalid timestamp value"
                    })
                    continue
                dt = ts.to_pydatetime()
                # Ensure we have a valid datetime (to_pydatetime can return NaT in some edge cases)
                if dt is pd.NaT or not isinstance(dt, datetime):
                    results.append({
                        "signal_id": signal_id,
                        "contract_address": contract,
                        "timestamp": None,
                        "entry_time": None,
                        "entry_price": None,
                        "market_cap_proxy": None,
                        "max_xn": None,
                        "time_to_2x_minutes": None,
                        "time_to_3x_minutes": None,
                        "time_to_5x_minutes": None,
                        "time_to_7x_minutes": None,
                        "time_to_10x_minutes": None,
                        "lived_minutes": None,
                        "status": "invalid_timestamp",
                        "error_message": "Invalid timestamp value"
                    })
                    continue
                signal_ts = dt
            except (ValueError, TypeError):
                # Skip rows with invalid timestamps
                results.append({
                    "signal_id": signal_id,
                    "contract_address": contract,
                    "timestamp": None,
                    "entry_time": None,
                    "entry_price": None,
                    "market_cap_proxy": None,
                    "max_xn": None,
                    "time_to_2x_minutes": None,
                    "time_to_3x_minutes": None,
                    "time_to_5x_minutes": None,
                    "time_to_7x_minutes": None,
                    "time_to_10x_minutes": None,
                    "lived_minutes": None,
                    "status": "invalid_timestamp",
                    "error_message": "Invalid timestamp value"
                })
                continue
        
        # Загружаем свечи
        try:
            candles = load_candles(contract, timeframe, candles_dir)
        except Exception as e:
            results.append({
                "signal_id": signal_id,
                "contract_address": contract,
                "timestamp": signal_ts,
                "entry_time": None,
                "entry_price": None,
                "market_cap_proxy": None,
                "max_xn": None,
                "time_to_2x_minutes": None,
                "time_to_3x_minutes": None,
                "time_to_5x_minutes": None,
                "time_to_7x_minutes": None,
                "time_to_10x_minutes": None,
                "lived_minutes": None,
                "status": "error",
                "error_message": str(e)
            })
            continue
        
        if not candles:
            results.append({
                "signal_id": signal_id,
                "contract_address": contract,
                "timestamp": signal_ts,
                "entry_time": None,
                "entry_price": None,
                "market_cap_proxy": None,
                "max_xn": None,
                "time_to_2x_minutes": None,
                "time_to_3x_minutes": None,
                "time_to_5x_minutes": None,
                "time_to_7x_minutes": None,
                "time_to_10x_minutes": None,
                "lived_minutes": None,
                "status": "no_candles",
                "error_message": None
            })
            continue
        
        # Получаем entry_price
        entry_price = get_entry_price(candles, signal_ts, mode=entry_mode)
        
        if entry_price is None:
            results.append({
                "signal_id": signal_id,
                "contract_address": contract,
                "timestamp": signal_ts,
                "entry_time": None,
                "entry_price": None,
                "market_cap_proxy": None,
                "max_xn": None,
                "time_to_2x_minutes": None,
                "time_to_3x_minutes": None,
                "time_to_5x_minutes": None,
                "time_to_7x_minutes": None,
                "time_to_10x_minutes": None,
                "lived_minutes": None,
                "status": "no_entry",
                "error_message": None
            })
            continue
        
        # Вычисляем entry_time (время свечи, которую использовали для entry_price)
        entry_time = signal_ts
        if entry_mode == "t+1m":
            target_time = signal_ts + timedelta(minutes=1)
        else:
            target_time = signal_ts
        
        sorted_candles = sorted(candles, key=lambda c: c.timestamp)
        for candle in sorted_candles:
            if candle.timestamp >= target_time:
                entry_time = candle.timestamp
                break
        
        # Вычисляем market_cap_proxy
        market_cap_proxy = compute_market_cap_proxy(entry_price)
        
        # Вычисляем max_xn и time_to_xn
        max_xn, time_to_levels = compute_max_xn(
            candles, entry_price, entry_time, horizon_minutes, use_high
        )
        
        # Вычисляем lived_minutes (сколько минут есть свечей после entry)
        last_candle_time = max(c.timestamp for c in candles)
        if last_candle_time > entry_time:
            delta = last_candle_time - entry_time
            lived_minutes = int(delta.total_seconds() / 60)
        else:
            lived_minutes = 0
        
        results.append({
            "signal_id": signal_id,
            "contract_address": contract,
            "timestamp": signal_ts,
            "entry_time": entry_time,
            "entry_price": entry_price,
            "market_cap_proxy": market_cap_proxy,
            "max_xn": max_xn,
            "time_to_2x_minutes": time_to_levels.get("time_to_2x_minutes"),
            "time_to_3x_minutes": time_to_levels.get("time_to_3x_minutes"),
            "time_to_5x_minutes": time_to_levels.get("time_to_5x_minutes"),
            "time_to_7x_minutes": time_to_levels.get("time_to_7x_minutes"),
            "time_to_10x_minutes": time_to_levels.get("time_to_10x_minutes"),
            "lived_minutes": lived_minutes,
            "status": "ok",
            "error_message": None
        })
    
    return pd.DataFrame(results)









