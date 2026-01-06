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
        """Преобразует List[Candle] в DataFrame для RunnerLadderEngine."""
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
        return pd.DataFrame(candles_data)

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

        # Находим свечу на момент exit_time для получения рыночной цены закрытия
        # exit_price должен быть market close, а НЕ синтетика entry * realized_multiple
        exit_price = entry_candle.close  # Fallback на entry price если не найдена свеча
        if ladder_result.exit_time:
            # Ищем свечу с timestamp >= exit_time (первая свеча на момент или после закрытия)
            for candle in candles:
                if candle.timestamp >= ladder_result.exit_time:
                    exit_price = candle.close  # Market close цена на момент закрытия
                    break
            else:
                # Если не нашли свечу >= exit_time, берем последнюю доступную
                if candles:
                    exit_price = candles[-1].close

        # PnL уже рассчитан в ladder_result.realized_pnl_pct (в процентах)
        # Преобразуем в десятичную форму
        pnl = ladder_result.realized_pnl_pct / 100.0

        # Преобразуем reason из RunnerTradeResult в StrategyOutput.reason
        # Для ladder используем "ladder_tp" вместо "tp"
        reason_map: dict[str, Literal["ladder_tp", "tp", "sl", "timeout", "no_entry", "error"]] = {
            "time_stop": "timeout",
            "all_levels_hit": "ladder_tp",  # Все уровни достигнуты = ladder take profit
            "no_data": "no_entry"
        }
        reason_str = reason_map.get(ladder_result.reason, "error")
        # StrategyOutput.reason может не поддерживать "ladder_tp", используем "tp" как fallback
        # Но в meta мы сохраним "ladder_tp" для явной идентификации
        reason: Literal["tp", "sl", "timeout", "no_entry", "error"] = cast(
            Literal["tp", "sl", "timeout", "no_entry", "error"], 
            "tp" if reason_str == "ladder_tp" else reason_str
        )

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

        # Формируем meta с данными из RunnerTradeResult
        meta = {
            # Данные из RunnerTradeResult
            "levels_hit": {str(k): v.isoformat() for k, v in ladder_result.levels_hit.items()},
            "fractions_exited": {str(k): v for k, v in ladder_result.fractions_exited.items()},
            "realized_multiple": ladder_result.realized_multiple,
            "time_stop_triggered": ladder_result.reason == "time_stop",
            # Дополнительная информация
            "runner_ladder": True,
            "entry_idx": 0,
            # Сохраняем канонический reason для ladder (ladder_tp вместо tp)
            "ladder_reason": reason_str,  # "ladder_tp" или "timeout" или "no_entry"
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
            reason=reason,  # "tp" для обратной совместимости, но meta["ladder_reason"] содержит "ladder_tp"
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
