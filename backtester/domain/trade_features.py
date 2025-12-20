"""
Утилиты для расчета фичей сделки (trade features).
Фичи включают market cap proxy, объёмы и волатильность вокруг точки входа.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import statistics

from .models import Signal, Candle


def get_total_supply(signal: Signal, default: float = 1_000_000_000.0) -> float:
    """
    Извлекает total_supply из Signal.extra, возвращает default если отсутствует.
    
    :param signal: Сигнал для извлечения supply
    :param default: Значение по умолчанию (1 миллиард)
    :return: Total supply токена
    """
    if signal.extra and "total_supply" in signal.extra:
        supply = signal.extra["total_supply"]
        # Преобразуем в float, если нужно
        return float(supply)
    return default


def calc_mcap_proxy(price: float, supply: float) -> float:
    """
    Вычисляет proxy для market cap: price * supply.
    
    :param price: Цена токена
    :param supply: Общее количество токенов в обращении
    :return: Market cap proxy (price * supply)
    """
    return price * supply


def calc_window_features(
    candles: List[Candle],
    entry_time: datetime,
    entry_price: float,
    windows_min: tuple[int, ...] = (5, 15, 60),
) -> Dict[str, Any]:
    """
    Вычисляет фичи объёма и волатильности для окон до точки входа.
    Важно: окна берутся ДО entry_time, чтобы избежать data leakage.
    
    :param candles: Список свечей (должны быть отсортированы по времени)
    :param entry_time: Время входа в позицию
    :param entry_price: Цена входа (используется для нормализации range_pct)
    :param windows_min: Кортеж с размерами окон в минутах (5, 15, 60)
    :return: Словарь с фичами для каждого окна
    """
    features: Dict[str, Any] = {}
    
    # Фильтруем свечи до входа (строго до entry_time, чтобы не подглядывать)
    candles_before_entry = [
        c for c in candles
        if c.timestamp < entry_time
    ]
    
    # Сортируем по времени (на случай, если не были отсортированы)
    candles_before_entry.sort(key=lambda c: c.timestamp)
    
    if not candles_before_entry:
        # Если нет свечей до входа, заполняем нулями
        for w in windows_min:
            features[f"vol_sum_{w}m"] = 0.0
            features[f"range_pct_{w}m"] = 0.0
            features[f"volat_{w}m"] = 0.0
        return features
    
    # Для каждого окна вычисляем фичи
    for w in windows_min:
        window_start = entry_time - timedelta(minutes=w)
        window_candles = [
            c for c in candles_before_entry
            if c.timestamp >= window_start
        ]
        
        if not window_candles:
            features[f"vol_sum_{w}m"] = 0.0
            features[f"range_pct_{w}m"] = 0.0
            features[f"volat_{w}m"] = 0.0
            continue
        
        # vol_sum_{w}m: сумма объёмов за окно
        vol_sum = sum(c.volume for c in window_candles)
        features[f"vol_sum_{w}m"] = vol_sum
        
        # range_pct_{w}m: (max_high - min_low) / entry_price
        max_high = max(c.high for c in window_candles)
        min_low = min(c.low for c in window_candles)
        if entry_price > 0:
            range_pct = (max_high - min_low) / entry_price
        else:
            range_pct = 0.0
        features[f"range_pct_{w}m"] = range_pct
        
        # volat_{w}m: стандартное отклонение доходностей (returns)
        # Вычисляем returns между последовательными свечами
        if len(window_candles) < 2:
            features[f"volat_{w}m"] = 0.0
        else:
            returns = []
            for i in range(1, len(window_candles)):
                prev_close = window_candles[i - 1].close
                curr_close = window_candles[i].close
                if prev_close > 0:
                    ret = (curr_close - prev_close) / prev_close
                    returns.append(ret)
            
            if len(returns) < 2:
                features[f"volat_{w}m"] = 0.0
            else:
                volat = statistics.stdev(returns) if len(returns) > 1 else 0.0
                # Возвращаем волатильность в абсолютных единицах (можно умножить на 100 для процентов)
                features[f"volat_{w}m"] = volat
    
    return features


def calc_trade_mcap_features(
    entry_price: Optional[float],
    exit_price: Optional[float],
    total_supply: float,
) -> Dict[str, Any]:
    """
    Вычисляет market cap proxy на входе и выходе, а также изменение.
    
    :param entry_price: Цена входа
    :param exit_price: Цена выхода (может быть None)
    :param total_supply: Общее количество токенов
    :return: Словарь с entry_mcap_proxy, exit_mcap_proxy, mcap_change_pct, total_supply_used
    """
    features: Dict[str, Any] = {
        "total_supply_used": total_supply,
    }
    
    if entry_price is not None:
        entry_mcap = calc_mcap_proxy(entry_price, total_supply)
        features["entry_mcap_proxy"] = entry_mcap
        
        if exit_price is not None:
            exit_mcap = calc_mcap_proxy(exit_price, total_supply)
            features["exit_mcap_proxy"] = exit_mcap
            
            # mcap_change_pct: изменение market cap в процентах
            if entry_mcap > 0:
                mcap_change_pct = (exit_mcap - entry_mcap) / entry_mcap
            else:
                mcap_change_pct = 0.0
            features["mcap_change_pct"] = mcap_change_pct
    
    return features















