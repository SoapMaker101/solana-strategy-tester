"""
Утилиты для Risk/Reward стратегий.
Содержит общую логику TP/SL, которая используется в RRStrategy и RRDStrategy.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import statistics

from .models import Candle, StrategyOutput


def apply_rr_logic(
    entry_candle: Candle,
    entry_price: float,
    tp_pct: float,
    sl_pct: float,
    max_minutes: int,
    candles_from_entry: List[Candle],
    price_loader: Optional[Any] = None,
    contract_address: Optional[str] = None,
    base_meta: Optional[Dict[str, Any]] = None,
) -> StrategyOutput:
    """
    Применяет общую RR-логику (TP/SL/timeout) после входа в позицию.
    
    :param entry_candle: Свеча, на которой произошел вход
    :param entry_price: Цена входа
    :param tp_pct: Take Profit в долях (например, 0.1 = 10%)
    :param sl_pct: Stop Loss в долях (например, 0.05 = 5%)
    :param max_minutes: Максимальное время удержания позиции в минутах
    :param candles_from_entry: Список свечей, начиная со следующей после входа
    :param price_loader: Опциональный загрузчик свечей для догрузки данных
    :param contract_address: Адрес контракта для догрузки свечей
    :param base_meta: Базовые метаданные, которые будут добавлены к результату
    :return: StrategyOutput с результатом применения RR-логики
    """
    # Рассчитываем цели TP и SL
    tp_price = entry_price * (1 + tp_pct)
    sl_price = entry_price * (1 - sl_pct)
    
    # Инициализация
    all_candles_after_entry = candles_from_entry[:]
    # next_from должен быть после entry_candle, чтобы не загружать саму свечу входа повторно
    next_from = all_candles_after_entry[-1].timestamp + timedelta(minutes=1) if all_candles_after_entry else entry_candle.timestamp + timedelta(minutes=1)
    max_exit_time = entry_candle.timestamp + timedelta(minutes=max_minutes)
    last_valid_candle = entry_candle  # На случай таймаута
    
    # Вычисляем дополнительные метрики
    max_favorable_excursion = 0.0  # Максимальная прибыль до выхода
    max_adverse_excursion = 0.0   # Максимальный убыток до выхода
    
    # Основной цикл проверки TP/SL
    while True:
        for c in all_candles_after_entry:
            # Проверяем ограничение по времени от входа
            minutes_from_entry = (c.timestamp - entry_candle.timestamp).total_seconds() / 60
            if minutes_from_entry > max_minutes:
                # Выход по таймауту (используем предыдущую свечу)
                exit_candle = last_valid_candle
                exit_price = exit_candle.close
                pnl = (exit_price - entry_price) / entry_price
                
                # Формируем метаданные
                meta = _build_rr_meta(
                    entry_candle=entry_candle,
                    exit_candle=exit_candle,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    tp_price=tp_price,
                    sl_price=sl_price,
                    max_favorable_excursion=max_favorable_excursion,
                    max_adverse_excursion=max_adverse_excursion,
                    minutes_from_entry=minutes_from_entry,
                    base_meta=base_meta,
                )
                
                return StrategyOutput(
                    entry_time=entry_candle.timestamp,
                    entry_price=entry_price,
                    exit_time=exit_candle.timestamp,
                    exit_price=exit_price,
                    pnl=pnl,
                    reason="timeout",
                    meta=meta,
                )
            
            # Сохраняем последнюю валидную свечу (в пределах окна)
            last_valid_candle = c
            
            # Обновляем метрики экскурсий (только если еще не вышли)
            current_high_pnl = (c.high - entry_price) / entry_price
            current_low_pnl = (c.low - entry_price) / entry_price
            max_favorable_excursion = max(max_favorable_excursion, current_high_pnl)
            max_adverse_excursion = min(max_adverse_excursion, current_low_pnl)
            
            # Проверка: сработал SL (минимум свечи ниже SL)
            if c.low <= sl_price:
                pnl = (sl_price - entry_price) / entry_price
                minutes_from_entry = (c.timestamp - entry_candle.timestamp).total_seconds() / 60
                
                meta = _build_rr_meta(
                    entry_candle=entry_candle,
                    exit_candle=c,
                    entry_price=entry_price,
                    exit_price=sl_price,
                    tp_price=tp_price,
                    sl_price=sl_price,
                    max_favorable_excursion=max_favorable_excursion,
                    max_adverse_excursion=max_adverse_excursion,
                    minutes_from_entry=minutes_from_entry,
                    base_meta=base_meta,
                )
                
                return StrategyOutput(
                    entry_time=entry_candle.timestamp,
                    entry_price=entry_price,
                    exit_time=c.timestamp,
                    exit_price=sl_price,
                    pnl=pnl,
                    reason="sl",
                    meta=meta,
                )

            # Проверка: сработал TP (максимум свечи выше TP)
            if c.high >= tp_price:
                pnl = (tp_price - entry_price) / entry_price
                minutes_from_entry = (c.timestamp - entry_candle.timestamp).total_seconds() / 60
                
                meta = _build_rr_meta(
                    entry_candle=entry_candle,
                    exit_candle=c,
                    entry_price=entry_price,
                    exit_price=tp_price,
                    tp_price=tp_price,
                    sl_price=sl_price,
                    max_favorable_excursion=max_favorable_excursion,
                    max_adverse_excursion=max_adverse_excursion,
                    minutes_from_entry=minutes_from_entry,
                    base_meta=base_meta,
                )
                
                return StrategyOutput(
                    entry_time=entry_candle.timestamp,
                    entry_price=entry_price,
                    exit_time=c.timestamp,
                    exit_price=tp_price,
                    pnl=pnl,
                    reason="tp",
                    meta=meta,
                )
        
        # Проверка максимального времени выхода
        if all_candles_after_entry and all_candles_after_entry[-1].timestamp >= max_exit_time:
            break
        
        # Если нет загрузчика — прекращаем цикл
        if not price_loader or not contract_address:
            break
        
        # Догружаем свечи для проверки TP/SL
        new = price_loader.load_prices(contract_address, start_time=next_from, end_time=max_exit_time)
        if not new:
            break  # Нечего загружать
        
        # Добавляем новые свечи
        all_candles_after_entry.extend(new)
        all_candles_after_entry.sort(key=lambda c: c.timestamp)
        next_from = new[-1].timestamp + timedelta(minutes=1)

    # Если ни TP, ни SL не сработали (таймаут)
    # Выход по последней свече в пределах окна
    exit_candle = last_valid_candle
    exit_price = exit_candle.close
    pnl = (exit_price - entry_price) / entry_price
    minutes_from_entry = (exit_candle.timestamp - entry_candle.timestamp).total_seconds() / 60
    
    meta = _build_rr_meta(
        entry_candle=entry_candle,
        exit_candle=exit_candle,
        entry_price=entry_price,
        exit_price=exit_price,
        tp_price=tp_price,
        sl_price=sl_price,
        max_favorable_excursion=max_favorable_excursion,
        max_adverse_excursion=max_adverse_excursion,
        minutes_from_entry=minutes_from_entry,
        base_meta=base_meta,
    )
    
    return StrategyOutput(
        entry_time=entry_candle.timestamp,
        entry_price=entry_price,
        exit_time=exit_candle.timestamp,
        exit_price=exit_price,
        pnl=pnl,
        reason="timeout",
        meta=meta,
    )


def _build_rr_meta(
    entry_candle: Candle,
    exit_candle: Candle,
    entry_price: float,
    exit_price: float,
    tp_price: float,
    sl_price: float,
    max_favorable_excursion: float,
    max_adverse_excursion: float,
    minutes_from_entry: float,
    base_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Формирует метаданные для StrategyOutput с дополнительными метриками.
    """
    meta = base_meta.copy() if base_meta else {}
    
    # Базовые метрики
    meta.update({
        "tp_price": tp_price,
        "sl_price": sl_price,
        "minutes_in_market": minutes_from_entry,
        "max_favorable_excursion": max_favorable_excursion,
        "max_adverse_excursion": max_adverse_excursion,
    })
    
    return meta


def check_candle_quality(
    candle: Candle,
    previous_candle: Optional[Candle] = None,
    max_price_jump_pct: float = 0.5,  # Максимальный скачок цены за 1 минуту в процентах
) -> Tuple[bool, Optional[str]]:
    """
    Проверяет качество свечи и возвращает (is_valid, error_message).
    
    :param candle: Свеча для проверки
    :param previous_candle: Предыдущая свеча (для проверки скачков цены)
    :param max_price_jump_pct: Максимальный допустимый скачок цены за 1 минуту в процентах
    :return: (is_valid, error_message)
    """
    # Проверка 1: volume > 0
    if candle.volume <= 0:
        return False, f"volume must be > 0, got {candle.volume}"
    
    # Проверка 2: high >= low
    if candle.high < candle.low:
        return False, f"high ({candle.high}) must be >= low ({candle.low})"
    
    # Проверка 3: high >= open и high >= close
    if candle.high < candle.open:
        return False, f"high ({candle.high}) must be >= open ({candle.open})"
    if candle.high < candle.close:
        return False, f"high ({candle.high}) must be >= close ({candle.close})"
    
    # Проверка 4: low <= open и low <= close
    if candle.low > candle.open:
        return False, f"low ({candle.low}) must be <= open ({candle.open})"
    if candle.low > candle.close:
        return False, f"low ({candle.low}) must be <= close ({candle.close})"
    
    # Проверка 5: Проверка скачков цены (если есть предыдущая свеча)
    if previous_candle is not None:
        # Проверяем скачок между close предыдущей и open текущей
        if previous_candle.close > 0:
            price_jump_pct = abs(candle.open - previous_candle.close) / previous_candle.close * 100
            if price_jump_pct > max_price_jump_pct:
                return False, f"price jump too large: {price_jump_pct:.2f}% (max {max_price_jump_pct}%)"
    
    return True, None


def calculate_volatility_around_entry(
    candles: List[Candle],
    entry_candle: Candle,
    window_minutes: int = 60,
) -> float:
    """
    Вычисляет волатильность вокруг точки входа.
    
    :param candles: Список свечей
    :param entry_candle: Свеча входа
    :param window_minutes: Окно для расчета волатильности (минуты до и после входа)
    :return: Волатильность (стандартное отклонение доходностей в процентах)
    """
    if not candles:
        return 0.0
    
    # Фильтруем свечи в окне вокруг входа
    window_start = entry_candle.timestamp - timedelta(minutes=window_minutes)
    window_end = entry_candle.timestamp + timedelta(minutes=window_minutes)
    
    window_candles = [
        c for c in candles
        if window_start <= c.timestamp <= window_end
    ]
    
    if len(window_candles) < 2:
        return 0.0
    
    # Сортируем по времени
    window_candles.sort(key=lambda c: c.timestamp)
    
    # Вычисляем доходности (returns)
    returns = []
    for i in range(1, len(window_candles)):
        if window_candles[i-1].close > 0:
            ret = (window_candles[i].close - window_candles[i-1].close) / window_candles[i-1].close
            returns.append(ret)
    
    if len(returns) < 2:
        return 0.0
    
    # Вычисляем стандартное отклонение доходностей
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0.0
    
    return volatility * 100  # Возвращаем в процентах


def calculate_signal_to_entry_delay(
    signal_time: datetime,
    entry_time: datetime,
) -> float:
    """
    Вычисляет задержку между сигналом и входом в минутах.
    
    :param signal_time: Время сигнала
    :param entry_time: Время входа
    :return: Задержка в минутах
    """
    if entry_time is None:
        return 0.0
    
    delay = (entry_time - signal_time).total_seconds() / 60
    return max(0.0, delay)

