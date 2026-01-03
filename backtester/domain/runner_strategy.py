from __future__ import annotations
from typing import List, Literal, Optional, cast

import pandas as pd

from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy
from .runner_ladder import RunnerLadderEngine
from .runner_config import RunnerConfig
from .trade_features import (
    get_total_supply,
    calc_window_features,
    calc_trade_mcap_features,
    calc_mcap_proxy,
)
from .strategy_trade_blueprint import (
    StrategyTradeBlueprint,
    PartialExitBlueprint,
    FinalExitBlueprint,
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
        Blueprint path: strategy intent only, portfolio untouched.
        
        Returns StrategyTradeBlueprint describing strategy intent without portfolio execution.
        Uses the same ladder logic as on_signal but returns blueprint instead of StrategyOutput.
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

        # Если свечей нет — невозможно войти в позицию
        if not candles:
            return StrategyTradeBlueprint(
                signal_id=data.signal.id,
                strategy_id=config.name,
                contract_address=data.signal.contract_address,
                entry_time=signal_time,
                entry_price_raw=0.0,
                entry_mcap_proxy=None,
                partial_exits=[],
                final_exit=None,
                realized_multiple=0.0,
                max_xn_reached=0.0,
                reason="no_entry"
            )

        # Первая доступная свеча после сигнала — вход
        entry_candle = candles[0]
        entry_time = entry_candle.timestamp
        entry_price = entry_candle.close

        # Преобразуем List[Candle] в DataFrame для RunnerLadderEngine
        candles_df = self._candles_to_dataframe(candles)

        # Запускаем симуляцию Runner Ladder (та же логика, что в on_signal)
        ladder_result = RunnerLadderEngine.simulate(
            entry_time=entry_time,
            entry_price=entry_price,
            candles_df=candles_df,
            config=config
        )

        # Вычисляем entry_mcap_proxy
        total_supply = get_total_supply(data.signal)
        entry_mcap_proxy = calc_mcap_proxy(entry_price, total_supply) if entry_price > 0 else None

        # Собираем partial_exits из levels_hit и fractions_exited
        partial_exits: List[PartialExitBlueprint] = []
        for xn in sorted(ladder_result.levels_hit.keys()):
            if xn in ladder_result.fractions_exited and ladder_result.fractions_exited[xn] > 0:
                exit_timestamp = ladder_result.levels_hit[xn]
                fraction = ladder_result.fractions_exited[xn]
                partial_exits.append(
                    PartialExitBlueprint(
                        timestamp=exit_timestamp,
                        xn=xn,
                        fraction=fraction
                    )
                )

        # Создаём final_exit если стратегия сама закрыла позицию
        final_exit: Optional[FinalExitBlueprint] = None
        if ladder_result.exit_time and ladder_result.reason in ("time_stop", "all_levels_hit"):
            final_exit = FinalExitBlueprint(
                timestamp=ladder_result.exit_time,
                reason=ladder_result.reason
            )

        # Вычисляем max_xn_reached (максимальный xn из достигнутых уровней)
        max_xn_reached = max(ladder_result.levels_hit.keys()) if ladder_result.levels_hit else 0.0

        return StrategyTradeBlueprint(
            signal_id=data.signal.id,
            strategy_id=config.name,
            contract_address=data.signal.contract_address,
            entry_time=ladder_result.entry_time,
            entry_price_raw=ladder_result.entry_price,
            entry_mcap_proxy=entry_mcap_proxy,
            partial_exits=partial_exits,
            final_exit=final_exit,
            realized_multiple=ladder_result.realized_multiple,
            max_xn_reached=max_xn_reached,
            reason=ladder_result.reason
        )
