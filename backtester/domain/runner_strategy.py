from __future__ import annotations
from typing import List, Literal, cast, Optional

import pandas as pd

from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy
from .runner_ladder import RunnerLadderEngine
from .runner_config import RunnerConfig
from .strategy_trade_blueprint import (
    StrategyTradeBlueprint,
    PartialExitBlueprint,
    FinalExitBlueprint,
)
from .trade_features import (
    get_total_supply,
    calc_window_features,
    calc_trade_mcap_features,
)


class RunnerStrategy(Strategy):
    """
    Runner стратегия с лестницей тейк-профитов.
    
    Использует RunnerLadderEngine для симуляции частичного закрытия позиций
    на разных уровнях прибыли (например, 2x, 5x, 10x).
    """

    def __init__(self, config) -> None:
        super().__init__(config)
        # Проверяем, что конфиг является RunnerConfig
        if not isinstance(config, RunnerConfig):
            raise ValueError(f"RunnerStrategy requires RunnerConfig, got {type(config)}")

    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        signal_time = data.signal.timestamp
        
        # Проверяем, что config является RunnerConfig
        if not isinstance(self.config, RunnerConfig):
            raise ValueError(f"RunnerStrategy requires RunnerConfig, got {type(self.config)}")
        config = self.config

        # Отбираем свечи, начиная с момента сигнала (или позже)
        candles: List[Candle] = sorted(
            [c for c in data.candles if c.timestamp >= signal_time],
            key=lambda c: c.timestamp
        )

        # Если свечей нет — невозможно войти в позицию
        if not candles:
            return StrategyOutput(
                entry_time=None, entry_price=None,
                exit_time=None, exit_price=None,
                pnl=0.0, reason="no_entry",
                canonical_reason="no_entry",
                meta={"detail": "no candles after signal"}
            )

        # Первая доступная свеча после сигнала — вход
        entry_candle = candles[0]
        entry_time = entry_candle.timestamp
        entry_price = entry_candle.close

        # Преобразуем List[Candle] в DataFrame для RunnerLadderEngine
        candles_df = self._candles_to_dataframe(candles)

        # Запускаем симуляцию Runner Ladder
        ladder_result = RunnerLadderEngine.simulate(
            entry_time=entry_time,
            entry_price=entry_price,
            candles_df=candles_df,
            config=config
        )

        # Преобразуем RunnerTradeResult в StrategyOutput
        return self._ladder_result_to_strategy_output(
            ladder_result=ladder_result,
            data=data,
            entry_candle=entry_candle,
            candles=candles
        )

    def _candles_to_dataframe(self, candles: List[Candle]) -> pd.DataFrame:
        """
        Преобразует List[Candle] в DataFrame для RunnerLadderEngine.
        
        Важно: гарантирует сортировку по timestamp для правильного выбора exit candle.
        Свечи уже отсортированы в on_signal (строка 45-48), но для дополнительной гарантии
        сортируем DataFrame перед возвратом.
        """
        candles_data = []
        for candle in candles:
            candles_data.append({
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume
            })
        df = pd.DataFrame(candles_data)
        # Гарантируем сортировку по timestamp (ascending) для правильного выбора exit candle
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def _ladder_result_to_strategy_output(
        self,
        ladder_result,
        data: StrategyInput,
        entry_candle: Candle,
        candles: List[Candle]
    ) -> StrategyOutput:
        """Преобразует RunnerTradeResult в StrategyOutput."""
        # config уже проверен в on_signal, используем cast для типизации
        config = cast(RunnerConfig, self.config)

        # BC FIX: Определяем reason (legacy) и canonical_reason на основе ladder_result.reason
        # RunnerLadderEngine теперь возвращает ladder_reason в поле reason для BC
        # ladder_reason отражает финальную причину закрытия позиции:
        # - "ladder_tp" если позиция закрылась полностью через ladder TP ИЛИ данные закончились до time_stop с достигнутыми уровнями
        # - "time_stop" если финальный exit произошёл по time_stop (позиция не закрылась полностью на уровнях)
        has_levels_hit = bool(ladder_result.levels_hit)
        
        # ladder_result.reason теперь содержит ladder_reason (для BC)
        ladder_reason = ladder_result.reason
        
        if ladder_reason == "ladder_tp":
            # Позиция закрылась через ladder TP (полностью или частично, но не по time_stop) - это take profit (BC)
            reason_legacy = "tp"  # Legacy: "tp"
            reason_canon = "ladder_tp"  # Канон: "ladder_tp"
        elif ladder_reason == "time_stop":
            # Финальный exit произошёл по time_stop (позиция не закрылась полностью на уровнях)
            reason_legacy = "timeout"  # Legacy: "timeout"
            reason_canon = "time_stop"  # Канон: "time_stop"
        elif ladder_reason == "stop_loss":
            reason_legacy = "sl"  # Legacy: "sl"
            reason_canon = "stop_loss"  # Канон: "stop_loss"
        elif ladder_reason in ("no_data", "no_entry"):
            reason_legacy = "no_entry"
            reason_canon = "no_entry"
        else:
            # Fallback для обратной совместимости (если engine вернул "all_levels_hit")
            if ladder_reason == "all_levels_hit" or has_levels_hit:
                reason_legacy = "tp"
                reason_canon = "ladder_tp"
            else:
                reason_legacy = "error"
                reason_canon = "error"

        # Находим свечу на момент exit_time для получения рыночной цены закрытия
        # exit_price должен быть market close, а НЕ синтетика entry * realized_multiple
        exit_price = entry_candle.close  # Fallback на entry price если не найдена свеча
        
        # Всегда выбираем свечу на момент exit_time (если он установлен)
        # Это важно для time_stop и ladder_tp случаев
        if ladder_result.exit_time:
            # Ищем свечу на момент exit_time (минимальный timestamp >= exit_time)
            # Важно: выбираем свечу с минимальным timestamp >= exit_time (первая свеча на момент или после закрытия)
            # Свечи уже отсортированы по timestamp (в runner.py и в on_signal), поэтому можно использовать min()
            # Но для дополнительной гарантии, находим min() для защиты от несортированных данных
            matching_candles = [c for c in candles if c.timestamp >= ladder_result.exit_time]
            if matching_candles:
                # Выбираем свечу с минимальным timestamp >= exit_time
                exit_candle = min(matching_candles, key=lambda c: c.timestamp)
                exit_price = exit_candle.close  # Market close цена на момент закрытия
            else:
                # Если не нашли свечу >= exit_time, берем последнюю доступную (fallback)
                if candles:
                    exit_price = candles[-1].close
        elif not has_levels_hit:
            # Если exit_time не установлен и уровни не достигнуты - закрываемся по последней доступной свече
            # Это edge case (данные закончились до time_stop)
            if candles:
                exit_price = candles[-1].close

        # PnL уже рассчитан в ladder_result.realized_pnl_pct (в процентах)
        # Преобразуем в десятичную форму
        pnl = ladder_result.realized_pnl_pct / 100.0

        # Вычисляем trade features
        all_candles = sorted(data.candles, key=lambda c: c.timestamp)
        window_features = calc_window_features(
            candles=all_candles,
            entry_time=entry_candle.timestamp,
            entry_price=entry_candle.close,
        )
        
        # Вычисляем mcap features
        total_supply = get_total_supply(data.signal)
        mcap_features = calc_trade_mcap_features(
            entry_price=entry_candle.close,
            exit_price=exit_price,
            total_supply=total_supply,
        )

        # Явная переменная для цены входа
        entry_price_raw = float(entry_candle.close)
        
        # Вычисляем realized_multiple
        if not has_levels_hit:
            # Ни один уровень не достигнут - считаем multiple по последней цене
            realized_multiple = float(exit_price) / entry_price_raw
        else:
            # Уровни достигнуты - используем значение из ladder_result
            realized_multiple = ladder_result.realized_multiple if ladder_result.realized_multiple > 0 else 1.0
        
        # Формируем meta с данными из RunnerTradeResult
        # Гарантируем обязательные ключи
        # FIX 1: time_stop_triggered должен срабатывать даже если был hit TP
        # Используем поле time_stop_triggered из RunnerTradeResult (сохранено отдельно)
        time_stop_triggered = ladder_result.time_stop_triggered
        
        meta = {
            # Данные из RunnerTradeResult
            "levels_hit": {str(k): v.isoformat() for k, v in ladder_result.levels_hit.items()} if ladder_result.levels_hit else {},
            "fractions_exited": {str(k): v for k, v in ladder_result.fractions_exited.items()} if ladder_result.fractions_exited else {},
            "realized_multiple": realized_multiple,
            # time_stop_triggered = True если reason == "time_stop" (даже если были partial exits)
            "time_stop_triggered": time_stop_triggered,
            # Дополнительная информация
            "runner_ladder": True,
            "entry_idx": 0,
            # BC FIX: Сохраняем канонический reason для ladder (ladder_tp/time_stop вместо tp/timeout)
            # ladder_reason всегда содержит точное значение из ladder_result.reason
            "ladder_reason": ladder_reason,  # "ladder_tp" или "time_stop" или "no_entry"
        }
        
        # Добавляем trade features
        meta.update(window_features)
        meta.update(mcap_features)

        return StrategyOutput(
            entry_time=ladder_result.entry_time,
            entry_price=ladder_result.entry_price,
            exit_time=ladder_result.exit_time,
            exit_price=exit_price,  # Market close цена, НЕ синтетика
            pnl=pnl,
            reason=reason_legacy,  # Legacy: "tp"|"timeout"|"sl"|"no_entry"|"error"
            canonical_reason=reason_canon,  # Канон: "ladder_tp"|"time_stop"|"stop_loss"|"no_entry"|"error"
            meta=meta
        )

    def on_signal_blueprint(self, data: StrategyInput) -> StrategyTradeBlueprint:
        """
        Генерирует StrategyTradeBlueprint для сигнала.
        
        Этот метод описывает намерение стратегии без портфеля и денег.
        Возвращает blueprint с partial exits и final exit на основе достижения уровней.
        
        :param data: StrategyInput с сигналом и свечами
        :return: StrategyTradeBlueprint с информацией о входах/выходах
        """
        signal_time = data.signal.timestamp
        
        # Проверяем, что config является RunnerConfig
        if not isinstance(self.config, RunnerConfig):
            raise ValueError(f"RunnerStrategy requires RunnerConfig, got {type(self.config)}")
        config = self.config
        
        # Отбираем свечи, начиная с момента сигнала (или позже)
        candles: List[Candle] = sorted(
            [c for c in data.candles if c.timestamp >= signal_time],
            key=lambda c: c.timestamp
        )
        
        # Если свечей нет — возвращаем blueprint с no_entry
        if not candles:
            return StrategyTradeBlueprint(
                signal_id=data.signal.id,
                strategy_id=config.name,
                contract_address=data.signal.contract_address,
                entry_time=signal_time,  # Используем signal timestamp как fallback
                entry_price_raw=0.0,
                entry_mcap_proxy=None,
                partial_exits=[],
                final_exit=None,
                realized_multiple=1.0,
                max_xn_reached=0.0,
                reason="no_entry",
            )
        
        # Первая доступная свеча после сигнала — вход
        entry_candle = candles[0]
        entry_time = entry_candle.timestamp
        entry_price_raw = entry_candle.close
        
        # Получаем уровни из конфига
        levels = config.take_profit_levels
        if not levels:
            # Если уровней нет, возвращаем blueprint без exits
            return StrategyTradeBlueprint(
                signal_id=data.signal.id,
                strategy_id=config.name,
                contract_address=data.signal.contract_address,
                entry_time=entry_time,
                entry_price_raw=entry_price_raw,
                entry_mcap_proxy=None,
                partial_exits=[],
                final_exit=None,
                realized_multiple=1.0,
                max_xn_reached=1.0,
                reason="no_entry",
            )
        
        # Сортируем уровни по xn (от меньшего к большему)
        sorted_levels = sorted(levels, key=lambda l: l.xn)
        
        # Проходим по свечам и проверяем достижение уровней
        partial_exits: List[PartialExitBlueprint] = []
        max_xn_reached = 1.0  # Минимум 1.0 (entry price)
        final_exit: Optional[FinalExitBlueprint] = None
        reason = "no_entry"
        
        # Отслеживаем, какие уровни уже достигнуты
        levels_hit = set()
        
        for candle in candles:
            # Проверяем достижение каждого уровня
            for level in sorted_levels:
                if level.xn in levels_hit:
                    continue  # Уровень уже достигнут
                
                # Проверяем, достигнут ли уровень (используем high если use_high_for_targets, иначе close)
                price_to_check = candle.high if config.use_high_for_targets else candle.close
                if price_to_check >= entry_price_raw * level.xn:
                    # Уровень достигнут
                    levels_hit.add(level.xn)
                    max_xn_reached = max(max_xn_reached, level.xn)
                    
                    # Создаем partial exit для этого уровня
                    partial_exits.append(PartialExitBlueprint(
                        timestamp=candle.timestamp,
                        xn=level.xn,
                        fraction=level.fraction,
                    ))
        
        # Проверяем, достигнут ли последний уровень (это будет final exit)
        if sorted_levels and sorted_levels[-1].xn in levels_hit:
            # Все уровни достигнуты, создаем final exit
            last_level = sorted_levels[-1]
            # Находим свечу, где был достигнут последний уровень
            final_exit_candle = None
            for candle in candles:
                price_to_check = candle.high if config.use_high_for_targets else candle.close
                if price_to_check >= entry_price_raw * last_level.xn:
                    final_exit_candle = candle
                    break
            
            if final_exit_candle:
                final_exit = FinalExitBlueprint(
                    timestamp=final_exit_candle.timestamp,
                    reason="all_levels_hit",
                )
                reason = "all_levels_hit"
        
        # Рассчитываем realized_multiple: Σ(fraction * xn) по всем partial_exits
        # В тесте все уровни (включая последний) должны быть в partial_exits
        realized_multiple = 0.0
        for partial_exit in partial_exits:
            realized_multiple += partial_exit.fraction * partial_exit.xn
        
        # Если нет partial exits и нет final exit, realized_multiple = 1.0
        if not partial_exits and not final_exit:
            realized_multiple = 1.0
        
        # Вычисляем entry_mcap_proxy (если доступно)
        entry_mcap_proxy = None
        total_supply = get_total_supply(data.signal)
        if total_supply is not None:
            entry_mcap_proxy = entry_price_raw * total_supply
        
        # Сортируем partial_exits по времени (на всякий случай)
        partial_exits = sorted(partial_exits, key=lambda pe: pe.timestamp)
        
        return StrategyTradeBlueprint(
            signal_id=data.signal.id,
            strategy_id=config.name,
            contract_address=data.signal.contract_address,
            entry_time=entry_time,
            entry_price_raw=entry_price_raw,
            entry_mcap_proxy=entry_mcap_proxy,
            partial_exits=partial_exits,
            final_exit=final_exit,
            realized_multiple=realized_multiple,
            max_xn_reached=max_xn_reached,
            reason=reason,
        )
