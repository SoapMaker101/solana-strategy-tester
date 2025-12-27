from __future__ import annotations
from datetime import timedelta
from typing import List
from .models import StrategyInput, StrategyOutput, Candle
from .strategy_base import Strategy
from .rr_utils import (
    apply_rr_logic,
    check_candle_quality,
    calculate_volatility_around_entry,
    calculate_signal_to_entry_delay,
    warn_once,
)
from .trade_features import (
    get_total_supply,
    calc_window_features,
    calc_trade_mcap_features,
)

# RRDStrategy — стратегия с отложенным входом по drawdown
# ⚠️ LEGACY: С декабря 2025 стратегия RRD признана неэффективной и исключена из пайплайна.
# Остается только для обратной совместимости. Новые разработки должны использовать RUNNER стратегии.
class RRDStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        # Уровень просадки (drawdown), при котором предполагается вход (в процентах)
        self.drawdown_entry_pct = float(config.params.get("drawdown_entry_pct", 25)) / 100.0
        # Уровень прибыли для фиксации TP (в процентах)
        self.tp_pct = float(config.params.get("tp_pct", 20)) / 100.0
        # Уровень потерь для фиксации SL (в процентах)
        self.sl_pct = float(config.params.get("sl_pct", 10)) / 100.0
        # Максимальное время удержания позиции после входа (в минутах)
        self.max_minutes = int(config.params.get("max_minutes", 43200))  # 30 дней по умолчанию
        # Максимальное время ожидания входа с момента сигнала (в минутах)
        self.entry_wait_minutes = int(config.params.get("entry_wait_minutes", 360))  # 6 часов по умолчанию
        # Максимальный скачок цены для проверки качества свечей
        self.max_price_jump_pct = float(config.params.get("max_price_jump_pct", 0.5))  # 0.5% по умолчанию

    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        signal_time = data.signal.timestamp
        
        # 2.1. Подготовка свечей
        # Сортируем свечи по времени и выделяем свечи не раньше времени сигнала
        candles: List[Candle] = sorted(
            [c for c in data.candles if c.timestamp >= signal_time],
            key=lambda c: c.timestamp
        )

        # Если после сигнала вообще нет свечей → возвращаем no_entry
        if len(candles) == 0:
            return StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": "no candles after signal (rrd)"}
            )

        # 2.2. Определение цены входа (drawdown)
        # Берем первую свечу после сигнала как базовую
        first_candle = candles[0]
        
        # Проверка: первая свеча позже сигнала (возможна задержка/перерыв)
        if first_candle.timestamp > signal_time:
            delta_sec = int((first_candle.timestamp - signal_time).total_seconds())
            key = f"first_candle_after_signal|{data.signal.id}|{data.signal.contract_address}|RRD"
            warn_once(
                key,
                f"Signal at {signal_time}, first candle at {first_candle.timestamp} (delta_sec={delta_sec}s)"
            )
        
        # Проверка качества первой свечи
        is_valid, error_msg = check_candle_quality(
            first_candle,
            previous_candle=None,
            max_price_jump_pct=self.max_price_jump_pct
        )
        
        if not is_valid:
            return StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry",
                meta={"detail": f"first candle quality check failed: {error_msg}"}
            )
        
        # Рассчитываем целевую цену входа
        entry_price_target = first_candle.close * (1 - self.drawdown_entry_pct)

        # 2.3. Окно ожидания входа
        # Рассчитываем дедлайн входа
        entry_deadline_ts = signal_time + timedelta(minutes=self.entry_wait_minutes)
        
        # Ищем точку входа: свечу, где low <= entry_price_target
        entry_candle = None
        entry_idx = None
        
        # Глобальные параметры для догрузки свечей (если нужно)
        loader = data.global_params.get("_price_loader")
        contract = data.signal.contract_address
        all_candles = candles[:]
        next_from = all_candles[-1].timestamp + timedelta(minutes=1) if all_candles else signal_time
        
        # Цикл поиска входа (с возможной догрузкой свечей)
        previous_candle = None
        while entry_candle is None:
            # Проходим по всем свечам после сигнала
            for idx, c in enumerate(all_candles):
                # Если свеча выходит за дедлайн входа — прерываем поиск
                if c.timestamp > entry_deadline_ts:
                    break
                
                # Проверка качества свечи
                is_valid, error_msg = check_candle_quality(
                    c,
                    previous_candle=previous_candle,
                    max_price_jump_pct=self.max_price_jump_pct
                )
                
                # Пропускаем аномальные свечи с предупреждением
                if not is_valid:
                    key = f"anomalous_candle|{data.signal.id}|{data.signal.contract_address}|RRD"
                    warn_once(
                        key,
                        f"Skipping anomalous candle at {c.timestamp}: {error_msg}"
                    )
                    previous_candle = c
                    continue
                
                # Если low свечи <= entry_price_target — вход найден
                if c.low <= entry_price_target:
                    entry_candle = c
                    entry_idx = idx
                    break
                
                previous_candle = c
            
            # Если вход найден — выходим из цикла поиска
            if entry_candle is not None:
                break
            
            # Проверка: все ли свечи проверены до дедлайна
            if all_candles and all_candles[-1].timestamp >= entry_deadline_ts:
                # Вход не найден до дедлайна
                return StrategyOutput(
                    entry_time=None,
                    entry_price=None,
                    exit_time=None,
                    exit_price=None,
                    pnl=0.0,
                    reason="no_entry",
                    meta={
                        "detail": f"entry_price_target {entry_price_target:.4f} not reached within {self.entry_wait_minutes} minutes",
                        "entry_price_target": entry_price_target,
                        "drawdown_pct": self.drawdown_entry_pct,
                        "entry_wait_minutes": self.entry_wait_minutes,
                        "first_candle_close": first_candle.close,
                    }
                )
            
            # Если нет загрузчика — прекращаем поиск
            if not loader:
                return StrategyOutput(
                    entry_time=None,
                    entry_price=None,
                    exit_time=None,
                    exit_price=None,
                    pnl=0.0,
                    reason="no_entry",
                    meta={
                        "detail": "no loader available for additional candles",
                        "entry_price_target": entry_price_target,
                        "drawdown_pct": self.drawdown_entry_pct,
                        "entry_wait_minutes": self.entry_wait_minutes,
                    }
                )
            
            # Догружаем свечи для поиска входа (до дедлайна)
            new = loader.load_prices(contract, start_time=next_from, end_time=entry_deadline_ts)
            if not new:
                # Больше данных нет — вход не найден
                return StrategyOutput(
                    entry_time=None,
                    entry_price=None,
                    exit_time=None,
                    exit_price=None,
                    pnl=0.0,
                    reason="no_entry",
                    meta={
                        "detail": "no more candles available, entry_price_target not reached",
                        "entry_price_target": entry_price_target,
                        "drawdown_pct": self.drawdown_entry_pct,
                        "entry_wait_minutes": self.entry_wait_minutes,
                    }
                )
            
            # Добавляем новые свечи
            all_candles.extend(new)
            all_candles.sort(key=lambda c: c.timestamp)
            next_from = new[-1].timestamp + timedelta(minutes=1)

        # 2.4. После входа — применяем RR-логику через общий хелпер
        # Входная цена: считаем, что лимитка исполнилась по целевой цене
        entry_price = entry_price_target
        
        # Вычисляем дополнительные метрики
        signal_to_entry_delay = calculate_signal_to_entry_delay(signal_time, entry_candle.timestamp)
        volatility_around_entry = calculate_volatility_around_entry(all_candles, entry_candle)
        
        # Вычисляем trade features
        # Для window features нужны все candles (используем all_candles, они уже содержат все доступные)
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
            "entry_price_target": entry_price_target,
            "drawdown_pct": self.drawdown_entry_pct,
            "entry_wait_minutes": self.entry_wait_minutes,
            "entry_idx": entry_idx,
            "signal_to_entry_delay_minutes": signal_to_entry_delay,
            "volatility_around_entry": volatility_around_entry,
        }
        # Добавляем trade features
        base_meta.update(window_features)
        base_meta.update(mcap_features)

        # Свечи после входа (начиная со следующей)
        if entry_idx is not None:
            start_check_idx = entry_idx + 1
        else:
            start_check_idx = 0
        candles_from_entry = all_candles[start_check_idx:] if start_check_idx < len(all_candles) else []

        # Применяем общую RR-логику
        result = apply_rr_logic(
            entry_candle=entry_candle,
            entry_price=entry_price,
            tp_pct=self.tp_pct,
            sl_pct=self.sl_pct,
            max_minutes=self.max_minutes,
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
        
        # Добавляем exit_idx в мета (если его еще нет)
        if "exit_idx" not in result.meta and result.exit_time:
            # Находим индекс свечи выхода
            for idx, c in enumerate(all_candles):
                if c.timestamp == result.exit_time:
                    result.meta["exit_idx"] = idx
                    break
        
        return result
