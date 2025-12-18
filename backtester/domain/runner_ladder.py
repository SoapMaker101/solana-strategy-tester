from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Literal

import pandas as pd

from .runner_config import RunnerConfig, RunnerTakeProfitLevel


@dataclass
class RunnerTradeResult:
    """
    Результат симуляции Runner Ladder стратегии.
    
    Attributes:
        entry_time: Время входа в позицию
        entry_price: Цена входа
        exit_time: Финальное время выхода (когда закрыли последнюю долю или time_stop)
        realized_multiple: Итоговый multiple на позицию (например, 3.2x)
        realized_pnl_pct: Реализованная прибыль/убыток в процентах
        levels_hit: Словарь {xn: hit_time} - когда был достигнут каждый уровень
        fractions_exited: Словарь {xn: fraction} - какая доля была закрыта на каждом уровне
        reason: Причина завершения ("time_stop" | "all_levels_hit" | "no_data")
    """
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    realized_multiple: float
    realized_pnl_pct: float
    levels_hit: Dict[float, datetime]
    fractions_exited: Dict[float, float]
    reason: Literal["time_stop", "all_levels_hit", "no_data"]


class RunnerLadderEngine:
    """
    Независимый движок для симуляции Runner Ladder стратегии.
    
    Не зависит от PortfolioEngine и работает только с чистой логикой:
    - Отслеживание уровней тейк-профита
    - Частичное закрытие позиций
    - Обработка time_stop
    """
    
    @staticmethod
    def simulate(
        entry_time: datetime,
        entry_price: float,
        candles_df: pd.DataFrame,
        config: RunnerConfig
    ) -> RunnerTradeResult:
        """
        Симулирует Runner Ladder стратегию на заданных свечах.
        
        Args:
            entry_time: Время входа в позицию
            entry_price: Цена входа
            candles_df: DataFrame со свечами. Должен содержать колонки:
                - timestamp (datetime)
                - open, high, low, close (float)
            config: Конфигурация Runner стратегии
            
        Returns:
            RunnerTradeResult с результатами симуляции
        """
        # Проверка наличия данных
        if candles_df.empty:
            return RunnerTradeResult(
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=entry_time,
                realized_multiple=1.0,
                realized_pnl_pct=0.0,
                levels_hit={},
                fractions_exited={},
                reason="no_data"
            )
        
        # Сортируем свечи по времени
        candles_df = candles_df.sort_values("timestamp").reset_index(drop=True)
        
        # Фильтруем свечи после входа
        candles_after_entry = candles_df[candles_df["timestamp"] >= entry_time].copy()
        
        if candles_after_entry.empty:
            return RunnerTradeResult(
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=entry_time,
                realized_multiple=1.0,
                realized_pnl_pct=0.0,
                levels_hit={},
                fractions_exited={},
                reason="no_data"
            )
        
        # Сортируем уровни по xn возрастанию
        sorted_levels = sorted(config.take_profit_levels, key=lambda x: x.xn)
        
        # Инициализация состояния
        remaining_position = 1.0  # Начальная позиция = 100%
        levels_hit: Dict[float, datetime] = {}
        fractions_exited: Dict[float, float] = {}
        total_realized_value = 0.0  # Суммарная стоимость закрытых долей
        
        # Вычисляем time_stop если задан
        time_stop_time = None
        if config.time_stop_minutes is not None:
            time_stop_time = entry_time + timedelta(minutes=config.time_stop_minutes)
        
        # Проходим по свечам
        for idx in range(len(candles_after_entry)):
            # Используем iloc для получения скалярных значений
            candle_time_val = candles_after_entry.iloc[idx]["timestamp"]
            # Преобразуем в datetime
            candle_time: datetime
            if isinstance(candle_time_val, pd.Timestamp):
                if pd.isna(candle_time_val):  # type: ignore
                    continue
                candle_time_dt = candle_time_val.to_pydatetime()
                # Проверка на NaT после преобразования
                if not isinstance(candle_time_dt, datetime):
                    continue
                candle_time = candle_time_dt
            elif isinstance(candle_time_val, datetime):
                candle_time = candle_time_val
            else:
                # Безопасное преобразование
                try:
                    ts = pd.Timestamp(candle_time_val)
                    if pd.isna(ts):  # type: ignore
                        continue
                    candle_time_dt = ts.to_pydatetime()
                    # Проверка на NaT после преобразования
                    if not isinstance(candle_time_dt, datetime):
                        continue
                    candle_time = candle_time_dt
                except (ValueError, TypeError):
                    # Если не удалось преобразовать, пропускаем свечу
                    continue
            
            # Проверяем time_stop
            if time_stop_time is not None and candle_time >= time_stop_time:
                # Закрываем остаток по close последней доступной свечи
                if remaining_position > 0:
                    exit_price = float(candles_after_entry.iloc[idx]["close"])
                    exit_multiple = exit_price / entry_price
                    total_realized_value += remaining_position * exit_multiple
                    remaining_position = 0.0
                
                return RunnerTradeResult(
                    entry_time=entry_time,
                    entry_price=entry_price,
                    exit_time=candle_time,
                    realized_multiple=total_realized_value,
                    realized_pnl_pct=(total_realized_value - 1.0) * 100.0,
                    levels_hit=levels_hit,
                    fractions_exited=fractions_exited,
                    reason="time_stop"
                )
            
            # Проверяем достижение уровней
            high_val = candles_after_entry.iloc[idx]["high"]
            close_val = candles_after_entry.iloc[idx]["close"]
            price_to_check = float(high_val if config.use_high_for_targets else close_val)
            
            for level in sorted_levels:
                target_price = entry_price * level.xn
                
                # Проверяем, достигнут ли уровень
                if price_to_check >= target_price:
                    # Проверяем, не был ли уже закрыт этот уровень
                    if level.xn not in levels_hit:
                        levels_hit[level.xn] = candle_time  # candle_time уже datetime
                        
                        # Определяем долю для закрытия
                        if config.exit_on_first_tp:
                            # Закрываем всю оставшуюся позицию
                            fraction_to_close = remaining_position
                        else:
                            # Закрываем только fraction этого уровня
                            fraction_to_close = min(level.fraction, remaining_position)
                        
                        if fraction_to_close > 0:
                            # Закрываем долю по цене уровня (target_price)
                            exit_multiple = level.xn
                            total_realized_value += fraction_to_close * exit_multiple
                            remaining_position -= fraction_to_close
                            
                            # Сохраняем информацию о закрытии
                            if level.xn in fractions_exited:
                                fractions_exited[level.xn] += fraction_to_close
                            else:
                                fractions_exited[level.xn] = fraction_to_close
                            
                            # Если позиция полностью закрыта
                            if remaining_position <= 1e-9:  # Учитываем погрешности float
                                return RunnerTradeResult(
                                    entry_time=entry_time,
                                    entry_price=entry_price,
                                    exit_time=candle_time,  # candle_time уже datetime
                                    realized_multiple=total_realized_value,
                                    realized_pnl_pct=(total_realized_value - 1.0) * 100.0,
                                    levels_hit=levels_hit,
                                    fractions_exited=fractions_exited,
                                    reason="all_levels_hit"
                                )
        
        # Если дошли до конца свечей, но позиция не закрыта
        # Закрываем остаток по close последней свечи
        last_timestamp_val = candles_after_entry.iloc[-1]["timestamp"]
        
        # Преобразуем timestamp в datetime
        exit_time_dt: datetime
        if isinstance(last_timestamp_val, pd.Timestamp):
            if pd.isna(last_timestamp_val):  # type: ignore
                exit_time_dt = entry_time
            else:
                dt = last_timestamp_val.to_pydatetime()
                # Проверка на NaT после преобразования
                if not isinstance(dt, datetime):
                    exit_time_dt = entry_time
                else:
                    exit_time_dt = dt
        elif isinstance(last_timestamp_val, datetime):
            exit_time_dt = last_timestamp_val
        else:
            # Безопасное преобразование
            try:
                ts = pd.Timestamp(last_timestamp_val)
                if pd.isna(ts):  # type: ignore
                    exit_time_dt = entry_time
                else:
                    dt = ts.to_pydatetime()
                    if not isinstance(dt, datetime):
                        exit_time_dt = entry_time
                    else:
                        exit_time_dt = dt
            except (ValueError, TypeError):
                # Fallback на entry_time если не удалось преобразовать
                exit_time_dt = entry_time
        
        if remaining_position > 0:
            exit_price = float(candles_after_entry.iloc[-1]["close"])
            exit_multiple = exit_price / entry_price
            total_realized_value += remaining_position * exit_multiple
            
            # Определяем причину: time_stop или просто конец данных
            if time_stop_time is not None and exit_time_dt >= time_stop_time:
                reason: Literal["time_stop", "all_levels_hit", "no_data"] = "time_stop"
            else:
                reason = "all_levels_hit"  # Фактически все уровни пройдены или данных нет
        else:
            reason = "all_levels_hit"
        
        # Финальная проверка типа для exit_time_dt
        if not isinstance(exit_time_dt, datetime):
            exit_time_dt = entry_time
        
        return RunnerTradeResult(
            entry_time=entry_time,
            entry_price=entry_price,
            exit_time=exit_time_dt,
            realized_multiple=total_realized_value,
            realized_pnl_pct=(total_realized_value - 1.0) * 100.0,
            levels_hit=levels_hit,
            fractions_exited=fractions_exited,
            reason=reason
        )



