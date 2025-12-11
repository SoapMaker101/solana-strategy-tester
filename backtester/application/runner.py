from __future__ import annotations  # Позволяет использовать аннотации типов для классов, объявленных ниже по коду

from datetime import timedelta
from typing import Any, Dict, List, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

# Импорты компонентов системы
from ..infrastructure.signal_loader import SignalLoader  # Интерфейс загрузки торговых сигналов
from ..infrastructure.price_loader import PriceLoader    # Интерфейс загрузки свечей (цен)
from ..domain.strategy_base import Strategy              # Базовый класс стратегий
from ..domain.models import StrategyInput, StrategyOutput, Signal, Candle  # Общие модели

class BacktestRunner:
    """
    Класс, отвечающий за запуск бэктестов:
    - Загружает сигналы и свечи
    - Применяет стратегии
    - Сохраняет результаты
    """

    def __init__(
        self,
        signal_loader: SignalLoader,        # Объект, загружающий сигналы из CSV, API и т.п.
        price_loader: PriceLoader,          # Объект, загружающий свечи
        reporter: Any,                      # Пока не используется (опциональный отчётчик)
        strategies: Sequence[Strategy],     # Список стратегий для тестирования
        global_config: Dict[str, Any] | None = None,  # Глобальная конфигурация из YAML
        parallel: bool = False,             # Включить параллельную обработку сигналов
        max_workers: int = 4,               # Максимальное количество потоков для параллельной обработки
    ) -> None:
        self.signal_loader = signal_loader
        self.price_loader = price_loader
        self.reporter = reporter
        self.strategies = list(strategies)
        self.global_config = global_config or {}
        self.results: List[Dict[str, Any]] = []
        self.parallel = parallel
        self.max_workers = max_workers

        # Считываем параметры временного окна вокруг сигнала
        data_cfg = self.global_config.get("data", {})
        self.before_minutes = int(data_cfg.get("before_minutes", 60))  # сколько минут до сигнала загружать
        self.after_minutes = int(data_cfg.get("after_minutes", 360))   # сколько минут после сигнала загружать
        
        # Добавляем price_loader в global_params для использования стратегиями
        self.global_config["_price_loader"] = self.price_loader

    def _load_signals(self) -> List[Signal]:
        """
        Загружает сигналы через указанный сигнал-лоадер.
        """
        signals = self.signal_loader.load_signals()
        if not isinstance(signals, list):
            raise ValueError("SignalLoader must return List[Signal]")  # Защита от некорректной реализации
        return signals

    def _process_signal(self, sig: Signal) -> List[Dict[str, Any]]:
        """
        Обрабатывает один сигнал и возвращает результаты для всех стратегий.
        Этот метод может быть вызван параллельно.

        :param sig: Сигнал для обработки
        :return: Список результатов по стратегиям
        """
        results = []
        contract = sig.contract_address
        ts = sig.timestamp

        # Определяем диапазон загрузки свечей вокруг сигнала
        start_time = ts - timedelta(minutes=self.before_minutes)
        end_time = ts + timedelta(minutes=self.after_minutes)

        # Загружаем свечи из ценового лоадера
        candles: List[Candle] = self.price_loader.load_prices(
            contract_address=contract,
            start_time=start_time,
            end_time=end_time,
        )

        # Логируем диагностику по свечам
        if candles:
            print(f"⏱️ Candle range requested: {start_time} to {end_time}")
            print(f"📉 Candles available: {len(candles)}")
            if candles[0].timestamp > ts:
                print(f"⚠️ WARNING: Signal time {ts} is earlier than first candle {candles[0].timestamp}")
        else:
            print(f"⚠️ No candles found for signal at {ts}")

        # Формируем единый объект с входными данными
        data = StrategyInput(
            signal=sig,
            candles=candles,
            global_params=self.global_config,
        )

        # Применяем каждую стратегию к данным
        for strategy in self.strategies:
            try:
                out: StrategyOutput = strategy.on_signal(data)
            except Exception as e:
                # Если ошибка — фиксируем результат с reason="error"
                out = StrategyOutput(
                    entry_time=None,
                    entry_price=None,
                    exit_time=None,
                    exit_price=None,
                    pnl=0.0,
                    reason="error",
                    meta={"exception": str(e)},
                )

            # Добавляем результат в список
            results.append(
                {
                    "signal_id": sig.id,
                    "contract_address": contract,
                    "strategy": strategy.config.name,
                    "timestamp": ts,
                    "result": out,
                }
            )

        return results

    def run(self) -> List[Dict[str, Any]]:
        """
        Основной метод запуска бэктеста.
        Возвращает список словарей с результатами по каждой стратегии и сигналу.
        """
        signals: List[Signal] = self._load_signals()
        
        if self.parallel and len(signals) > 1:
            # Параллельная обработка сигналов
            print(f"🚀 Processing {len(signals)} signals in parallel (max_workers={self.max_workers})")
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Запускаем обработку всех сигналов
                future_to_signal = {executor.submit(self._process_signal, sig): sig for sig in signals}
                
                # Собираем результаты по мере завершения
                for future in as_completed(future_to_signal):
                    sig = future_to_signal[future]
                    try:
                        signal_results = future.result()
                        self.results.extend(signal_results)
                    except Exception as e:
                        print(f"❌ Error processing signal {sig.id}: {e}")
                        # Добавляем ошибку для всех стратегий этого сигнала
                        for strategy in self.strategies:
                            self.results.append({
                                "signal_id": sig.id,
                                "contract_address": sig.contract_address,
                                "strategy": strategy.config.name,
                                "timestamp": sig.timestamp,
                                "result": StrategyOutput(
                                    entry_time=None,
                                    entry_price=None,
                                    exit_time=None,
                                    exit_price=None,
                                    pnl=0.0,
                                    reason="error",
                                    meta={"exception": str(e)},
                                ),
                            })
            
            # Сортируем результаты по signal_id и timestamp для консистентности
            self.results.sort(key=lambda x: (x["signal_id"], x["timestamp"]))
        else:
            # Последовательная обработка сигналов
            if self.parallel:
                print("⚠️ Parallel processing requested but only 1 signal, using sequential mode")
            
            for sig in signals:
                signal_results = self._process_signal(sig)
                self.results.extend(signal_results)

        return self.results
