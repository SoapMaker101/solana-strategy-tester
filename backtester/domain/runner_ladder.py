"""
Runner Ladder Engine - симуляция лестницы тейк-профитов для Runner стратегии.

Симулирует частичное закрытие позиций на разных уровнях прибыли (например, 2x, 5x, 10x).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from .runner_config import RunnerConfig
from ..utils.typing_utils import as_utc_datetime


@dataclass
class RunnerTradeResult:
    """Результат симуляции Runner Ladder."""
    
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    realized_pnl_pct: float  # PnL в процентах (например, 150.0 = 150%)
    reason: str  # "all_levels_hit", "time_stop", "no_data"
    levels_hit: Dict[float, datetime]  # {xn: timestamp} - когда был достигнут каждый уровень
    fractions_exited: Dict[float, float]  # {xn: fraction} - какая доля закрыта на каждом уровне
    realized_multiple: float  # Реализованный множитель (сумма xn * fraction)


class RunnerLadderEngine:
    """
    Движок для симуляции Runner Ladder стратегии.
    
    Симулирует частичное закрытие позиций на разных уровнях прибыли.
    """
    
    @staticmethod
    def simulate(
        entry_time: datetime,
        entry_price: float,
        candles_df: pd.DataFrame,
        config: RunnerConfig,
    ) -> RunnerTradeResult:
        """
        Симулирует Runner Ladder стратегию.
        
        Args:
            entry_time: Время входа в позицию
            entry_price: Цена входа
            candles_df: DataFrame со свечами (колонки: timestamp, open, high, low, close, volume)
            config: Конфигурация Runner стратегии
            
        Returns:
            RunnerTradeResult с результатами симуляции
        """
        if candles_df.empty:
            return RunnerTradeResult(
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=None,
                exit_price=None,
                realized_pnl_pct=0.0,
                reason="no_data",
                levels_hit={},
                fractions_exited={},
                realized_multiple=1.0,
            )
        
        # Получаем уровни из конфига
        if hasattr(config, 'take_profit_levels') and config.take_profit_levels:
            levels = [level.xn for level in config.take_profit_levels]
            fractions = [level.fraction for level in config.take_profit_levels]
        else:
            # Fallback: используем стандартные уровни
            levels = [2.0, 5.0, 10.0]
            fraction_per_level = 1.0 / len(levels)
            fractions = [fraction_per_level] * len(levels)
        
        # Получаем max_hold_minutes из конфига (time_stop_minutes или max_hold_minutes)
        max_hold_minutes = getattr(config, 'time_stop_minutes', None)
        if max_hold_minutes is None:
            max_hold_minutes = getattr(config, 'max_hold_minutes', None)
        if max_hold_minutes is None:
            max_hold_minutes = 432000  # 30 дней по умолчанию
        
        # Получаем exit_on_first_tp и allow_partial_fills из конфига
        exit_on_first_tp = getattr(config, 'exit_on_first_tp', False)
        allow_partial_fills = getattr(config, 'allow_partial_fills', True)
        
        # Сортируем свечи по времени
        candles_df = candles_df.sort_values('timestamp').reset_index(drop=True)
        
        # Инициализация
        levels_hit: Dict[float, datetime] = {}
        fractions_exited: Dict[float, float] = {}
        realized_multiple = 0.0
        
        # Отслеживаем, сколько уже закрыто от initial size (для проверки, не превысили ли мы 1.0)
        total_fraction_exited = 0.0
        
        # Проверяем каждый уровень
        for i, (xn, fraction) in enumerate(zip(levels, fractions)):
            # Проверяем, не превысили ли мы 1.0 (100% от initial size)
            if total_fraction_exited >= 1.0:
                break
            
            # Если exit_on_first_tp=True и уже достигнут первый уровень, закрываем всё
            if exit_on_first_tp and i > 0 and levels_hit:
                # Первый уровень уже достигнут, закрываем всё на нём
                break
            
            # Если allow_partial_fills=False, не делаем частичных выходов
            # В этом случае закрываем всё на первом достигнутом уровне
            if not allow_partial_fills and levels_hit:
                # Уже достигнут хотя бы один уровень, закрываем всё на нём
                break
            
            # Ищем первую свечу, где high >= entry_price * xn
            target_price = entry_price * xn
            hit_time: Optional[datetime] = None
            
            for _, row in candles_df.iterrows():
                candle_time = pd.to_datetime(row['timestamp'])
                
                # Проверка max_hold_minutes (если превышен до достижения уровня)
                if max_hold_minutes:
                    hold_minutes = (candle_time - entry_time).total_seconds() / 60
                    if hold_minutes > max_hold_minutes:
                        # Time stop сработал до достижения этого уровня
                        break
                
                # Проверяем, достигнут ли уровень
                if row['high'] >= target_price:
                    hit_time_raw = candle_time
                    # Нормализуем к pd.Timestamp, затем к datetime
                    hit_time_ts = as_utc_datetime(hit_time_raw)
                    if hit_time_ts is not None:
                        hit_time = hit_time_ts.to_pydatetime() if isinstance(hit_time_ts, pd.Timestamp) else hit_time_ts
                        levels_hit[xn] = hit_time
                    
                    # Вычисляем долю для закрытия (от initial size)
                    # Если exit_on_first_tp=True, закрываем всё на первом уровне
                    if exit_on_first_tp and i == 0:
                        # Закрываем всё на первом уровне
                        actual_fraction = 1.0 - total_fraction_exited
                        fractions_exited[xn] = actual_fraction
                        total_fraction_exited = 1.0
                        realized_multiple += xn * actual_fraction
                    elif not allow_partial_fills:
                        # Если allow_partial_fills=False, закрываем всё на первом достигнутом уровне
                        actual_fraction = 1.0 - total_fraction_exited
                        fractions_exited[xn] = actual_fraction
                        total_fraction_exited = 1.0
                        realized_multiple += xn * actual_fraction
                    else:
                        # Частичный выход: закрываем fraction от initial size
                        # Ограничиваем, чтобы не превысить 1.0
                        actual_fraction = min(fraction, 1.0 - total_fraction_exited)
                        if actual_fraction > 0:
                            fractions_exited[xn] = actual_fraction
                            total_fraction_exited += actual_fraction
                            realized_multiple += xn * actual_fraction
                    break
            
            if hit_time is None:
                # Уровень не достигнут (либо time_stop, либо цена не достигла)
                # Продолжаем проверять следующие уровни, если позиция не закрыта полностью
                if total_fraction_exited >= 1.0:
                    break
                continue
            
            # Если exit_on_first_tp=True и достигнут первый уровень, прекращаем обработку
            if exit_on_first_tp and i == 0:
                break
            
            # Если allow_partial_fills=False и достигнут уровень, прекращаем обработку
            if not allow_partial_fills:
                break
        
        # Определяем exit_time и exit_price
        exit_time: Optional[datetime] = None
        exit_price: Optional[float] = None
        
        # Главное правило:
        # - Если позиция закрыта полностью на уровнях (total_fraction_exited >= 1.0) → reason = "ladder_tp"
        # - Если позиция закрыта частично или не закрыта → reason = "time_stop" (остаток закрывается по time_stop)
        has_levels_hit = bool(levels_hit)
        is_fully_closed = total_fraction_exited >= 1.0
        
        if is_fully_closed and has_levels_hit:
            # Позиция полностью закрыта на уровнях - это ladder take profit
            reason = "ladder_tp"
            # Берем время последнего достигнутого уровня
            exit_times = list(levels_hit.values())
            if exit_times:
                exit_time = max(exit_times)
            else:
                exit_time = None
        else:
            # Позиция не закрыта полностью или ни один уровень не достигнут - проверяем time_stop
            reason = "time_stop"
            if max_hold_minutes:
                # Вычисляем время time_stop
                time_stop_time = entry_time + pd.Timedelta(minutes=max_hold_minutes)
                # Проверяем, не превысили ли мы time_stop
                last_candle_time_raw = pd.to_datetime(candles_df.iloc[-1]['timestamp'])
                last_candle_time_ts = as_utc_datetime(last_candle_time_raw)
                if last_candle_time_ts is not None and isinstance(last_candle_time_ts, pd.Timestamp):
                    last_candle_time = last_candle_time_ts.to_pydatetime()
                    # Нормализуем time_stop_time через as_utc_datetime для гарантии datetime|None (NaT -> None)
                    # В runtime time_stop_time всегда pd.Timestamp (результат entry_time + Timedelta),
                    # но basedpyright не может это гарантировать, поэтому нормализуем
                    time_stop_ts = as_utc_datetime(time_stop_time)
                    if time_stop_ts is not None and isinstance(time_stop_ts, pd.Timestamp):
                        time_stop_dt = time_stop_ts.to_pydatetime()
                        if last_candle_time >= time_stop_dt:
                            exit_time = time_stop_dt
                        else:
                            # Данные закончились до time_stop - закрываемся по последней свече
                            exit_time = last_candle_time
                    else:
                        # time_stop_time был NaT или не pd.Timestamp (не должно быть в runtime) - используем last_candle_time
                        # Эквивалентно оригиналу, где использовалось бы исходное значение, но безопаснее для типизации
                        exit_time = last_candle_time
                else:
                    exit_time = None
            else:
                # Нет max_hold_minutes - закрываемся по последней свече
                last_candle_time_raw = pd.to_datetime(candles_df.iloc[-1]['timestamp'])
                last_candle_time_ts = as_utc_datetime(last_candle_time_raw)
                if last_candle_time_ts is not None and isinstance(last_candle_time_ts, pd.Timestamp):
                    exit_time = last_candle_time_ts.to_pydatetime()
                else:
                    exit_time = None
        
        # Находим цену на момент exit_time
        if exit_time:
            for _, row in candles_df.iterrows():
                if pd.to_datetime(row['timestamp']) >= exit_time:
                    exit_price = float(row['close'])
                    break
            if exit_price is None:
                # Fallback: используем последнюю доступную цену
                exit_price = float(candles_df.iloc[-1]['close'])
        
        # Вычисляем realized_pnl_pct
        if realized_multiple > 0:
            realized_pnl_pct = (realized_multiple - 1.0) * 100.0
        else:
            # Если ни один уровень не достигнут, используем exit_price
            if exit_price:
                realized_pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0
            else:
                realized_pnl_pct = 0.0
        
        # Нормализуем exit_time к datetime
        exit_time_dt: Optional[datetime] = None
        if exit_time is not None:
            if isinstance(exit_time, pd.Timestamp):
                exit_time_dt = exit_time.to_pydatetime()
            elif isinstance(exit_time, datetime):
                exit_time_dt = exit_time
            else:
                exit_time_ts = as_utc_datetime(exit_time)
                if exit_time_ts is not None and isinstance(exit_time_ts, pd.Timestamp):
                    exit_time_dt = exit_time_ts.to_pydatetime()
        
        return RunnerTradeResult(
            entry_time=entry_time,
            entry_price=entry_price,
            exit_time=exit_time_dt,
            exit_price=exit_price,
            realized_pnl_pct=realized_pnl_pct,
            reason=reason,
            levels_hit=levels_hit,
            fractions_exited=fractions_exited,
            realized_multiple=realized_multiple if realized_multiple > 0 else 1.0,
        )


# Алиас для обратной совместимости
__all__ = ['RunnerLadderEngine', 'RunnerTradeResult']
