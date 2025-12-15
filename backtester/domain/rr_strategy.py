from __future__ import annotations
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy
from .rr_utils import apply_rr_logic, check_candle_quality, calculate_volatility_around_entry, calculate_signal_to_entry_delay, warn_once
from .trade_features import (
    get_total_supply,
    calc_window_features,
    calc_trade_mcap_features,
)

# Стратегия RR (Risk/Reward) — базовая реализация трейда с TP и SL
class RRStrategy(Strategy):
    def __init__(self, config) -> None:
        super().__init__(config)
        # Установка параметров TP и SL из конфигурации (в долях, например 0.1 = 10%)
        self.tp_pct = float(config.params.get("tp_pct", 10)) / 100.0
        self.sl_pct = float(config.params.get("sl_pct", 10)) / 100.0
        # Максимальный скачок цены для проверки качества свечей
        self.max_price_jump_pct = float(config.params.get("max_price_jump_pct", 0.5))  # 0.5% по умолчанию

    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        signal_time = data.signal.timestamp

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

        # Первая доступная свеча после сигнала
        first_available = candles[0]

        # Проверка: первая свеча позже сигнала (возможна задержка/перерыв)
        if first_available.timestamp > signal_time:
            delta_sec = int((first_available.timestamp - signal_time).total_seconds())
            key = f"rr_first_candle_after_signal|{data.signal.id}|{data.signal.contract_address}"
            warn_once(
                data.global_params,
                key,
                f"[WARN] (dedup): Signal at {signal_time}, first candle at {first_available.timestamp} (delta_sec={delta_sec}s)"
            )

        # Проверка качества свечи входа
        is_valid, error_msg = check_candle_quality(
            first_available,
            previous_candle=None,
            max_price_jump_pct=self.max_price_jump_pct
        )
        
        if not is_valid:
            return StrategyOutput(
                entry_time=None, entry_price=None,
                exit_time=None, exit_price=None,
                pnl=0.0, reason="no_entry",
                meta={"detail": f"entry candle quality check failed: {error_msg}"}
            )

        # Вход по закрытию первой свечи
        entry_candle = first_available
        entry_price = entry_candle.close

        # Вычисляем дополнительные метрики
        signal_to_entry_delay = calculate_signal_to_entry_delay(signal_time, entry_candle.timestamp)
        volatility_around_entry = calculate_volatility_around_entry(candles, entry_candle)

        # Вычисляем trade features
        # Для window features нужны все candles (не только после signal_time)
        all_candles = sorted(data.candles, key=lambda c: c.timestamp)
        window_features = calc_window_features(
            candles=all_candles,
            entry_time=entry_candle.timestamp,
            entry_price=entry_price,
        )
        
        # Вычисляем mcap features
        total_supply = get_total_supply(data.signal)
        mcap_features = calc_trade_mcap_features(
            entry_price=entry_price,
            exit_price=None,  # Будет добавлено после выхода в apply_rr_logic
            total_supply=total_supply,
        )

        # Базовые метаданные
        base_meta = {
            "signal_to_entry_delay_minutes": signal_to_entry_delay,
            "volatility_around_entry": volatility_around_entry,
        }
        # Добавляем trade features
        base_meta.update(window_features)
        base_meta.update(mcap_features)

        # Глобальные параметры
        loader = data.global_params.get("_price_loader")
        contract = data.signal.contract_address
        max_minutes = int(data.global_params.get("max_minutes", 43200))  # 30 дней по умолчанию

        # Свечи после входа (начиная со следующей)
        candles_from_entry = candles[1:] if len(candles) > 1 else []

        # Применяем общую RR-логику
        result = apply_rr_logic(
            entry_candle=entry_candle,
            entry_price=entry_price,
            tp_pct=self.tp_pct,
            sl_pct=self.sl_pct,
            max_minutes=max_minutes,
            candles_from_entry=candles_from_entry,
            price_loader=loader,
            contract_address=contract,
            base_meta=base_meta,
        )
        
        # Добавляем exit mcap features (если есть exit_price)
        if result.exit_price is not None:
            exit_mcap_features = calc_trade_mcap_features(
                entry_price=entry_price,
                exit_price=result.exit_price,
                total_supply=total_supply,
            )
            # Обновляем только exit_mcap_proxy и mcap_change_pct (total_supply_used уже есть)
            if "exit_mcap_proxy" in exit_mcap_features:
                result.meta["exit_mcap_proxy"] = exit_mcap_features["exit_mcap_proxy"]
            if "mcap_change_pct" in exit_mcap_features:
                result.meta["mcap_change_pct"] = exit_mcap_features["mcap_change_pct"]
        
        return result
