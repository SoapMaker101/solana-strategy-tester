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
        
        # Получаем max_hold_minutes из конфига
        max_hold_minutes = getattr(config, 'max_hold_minutes', None)
        if max_hold_minutes is None:
            max_hold_minutes = 1440  # 24 часа по умолчанию
        
        # Сортируем свечи по времени
        candles_df = candles_df.sort_values('timestamp').reset_index(drop=True)
        
        # Инициализация
        levels_hit: Dict[float, datetime] = {}
        fractions_exited: Dict[float, float] = {}
        remaining_fraction = 1.0
        realized_multiple = 0.0
        
        # Проверяем каждый уровень
        for i, (xn, fraction) in enumerate(zip(levels, fractions)):
            if remaining_fraction <= 0:
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
                    hit_time = candle_time
                    levels_hit[xn] = hit_time.to_pydatetime() if hasattr(hit_time, 'to_pydatetime') else hit_time
                    
                    # Закрываем долю на этом уровне
                    actual_fraction = min(fraction, remaining_fraction)
                    fractions_exited[xn] = actual_fraction
                    remaining_fraction -= actual_fraction
                    realized_multiple += xn * actual_fraction
                    break
            
            if hit_time is None:
                # Уровень не достигнут (либо time_stop, либо цена не достигла)
                break
        
        # Определяем exit_time и exit_price
        exit_time: Optional[datetime] = None
        exit_price: Optional[float] = None
        
        if remaining_fraction <= 0:
            # Все уровни достигнуты
            reason = "all_levels_hit"
            if levels_hit:
                # Берем время последнего достигнутого уровня
                exit_time = max(levels_hit.values())
        else:
            # Не все уровни достигнуты - проверяем time_stop
            reason = "time_stop"
            if max_hold_minutes:
                # Вычисляем время time_stop
                time_stop_time = entry_time + pd.Timedelta(minutes=max_hold_minutes)
                # Проверяем, не превысили ли мы time_stop
                last_candle_time = pd.to_datetime(candles_df.iloc[-1]['timestamp'])
                if last_candle_time >= time_stop_time:
                    exit_time = time_stop_time
                elif levels_hit:
                    # Если есть достигнутые уровни, используем время последнего
                    exit_time = max(levels_hit.values())
            elif levels_hit:
                # Если нет max_hold_minutes, но есть достигнутые уровни
                exit_time = max(levels_hit.values())
        
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
        
        return RunnerTradeResult(
            entry_time=entry_time,
            entry_price=entry_price,
            exit_time=exit_time.to_pydatetime() if exit_time and hasattr(exit_time, 'to_pydatetime') else exit_time,
            exit_price=exit_price,
            realized_pnl_pct=realized_pnl_pct,
            reason=reason,
            levels_hit=levels_hit,
            fractions_exited=fractions_exited,
            realized_multiple=realized_multiple if realized_multiple > 0 else 1.0,
        )


# Алиас для обратной совместимости
__all__ = ['RunnerLadderEngine', 'RunnerTradeResult']
