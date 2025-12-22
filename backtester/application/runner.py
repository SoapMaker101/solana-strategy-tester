from __future__ import annotations  # Позволяет использовать аннотации типов для классов, объявленных ниже по коду

from datetime import timedelta, datetime
from typing import Any, Dict, List, Sequence, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import logging

# Импорты компонентов системы
from ..infrastructure.signal_loader import SignalLoader  # Интерфейс загрузки торговых сигналов
from ..infrastructure.price_loader import PriceLoader    # Интерфейс загрузки свечей (цен)
from ..domain.strategy_base import Strategy              # Базовый класс стратегий
from ..domain.models import StrategyInput, StrategyOutput, Signal, Candle  # Общие модели
from ..domain.portfolio import PortfolioConfig, PortfolioEngine, FeeModel, PortfolioResult  # Портфельный слой
from ..domain.execution_model import ExecutionProfileConfig  # Execution profiles
from ..utils.warn_dedup import WarnDedup  # Потокобезопасный класс для дедупликации предупреждений

logger = logging.getLogger(__name__)

# Модульный флаг для warn once о deprecated runner_reset_* ключах
_warned_runner_reset_deprecated = False
_warned_runner_reset_both_specified = False

def _warn_runner_reset_deprecated_once(msg: str) -> None:
    """Выводит предупреждение о deprecated ключах только один раз за прогон."""
    global _warned_runner_reset_deprecated, _warned_runner_reset_both_specified
    if "DEPRECATED" in msg and not _warned_runner_reset_deprecated:
        logger.warning(msg)
        _warned_runner_reset_deprecated = True
    elif "Both profit_reset_*" in msg and not _warned_runner_reset_both_specified:
        logger.warning(msg)
        _warned_runner_reset_both_specified = True

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
        max_workers: int = 1,               # Максимальное количество потоков для параллельной обработки
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
        
        # Создаем потокобезопасный экземпляр WarnDedup для дедупликации предупреждений
        self.warn_dedup = WarnDedup()
        self.global_config["_warn_dedup"] = self.warn_dedup
        
        # Счетчики для статистики обработки сигналов (потокобезопасные)
        self._counters_lock = threading.Lock()
        self.signals_processed = 0
        self.signals_skipped_no_candles = 0
        self.signals_skipped_corrupt_csv = 0
        
        # Портфельные результаты (по стратегиям)
        self.portfolio_results: Dict[str, PortfolioResult] = {}

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
        try:
            candles: List[Candle] = self.price_loader.load_prices(
                contract_address=contract,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as e:
            # Если load_prices поднял исключение (не должно происходить после наших изменений, но на всякий случай)
            print(f"[ERROR] Error loading candles for signal {sig.id}: {e}")
            with self._counters_lock:
                self.signals_skipped_corrupt_csv += 1
            print(f"[signal] skipped: no candles/failed to parse (signal_id={sig.id}, contract={contract})")
            return []

        # Обрабатываем случай пустых свечей
        if not candles:
            with self._counters_lock:
                self.signals_skipped_no_candles += 1
            print(f"[signal] skipped: no candles/failed to parse (signal_id={sig.id}, contract={contract})")
            return []
        
        # Логируем диагностику по свечам
        with self._counters_lock:
            self.signals_processed += 1
        print(f"[time] Candle range requested: {start_time} to {end_time}")
        print(f"[candles] Candles available: {len(candles)}")
        if candles[0].timestamp > ts:
            print(f"[WARNING] WARNING: Signal time {ts} is earlier than first candle {candles[0].timestamp}")

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
            print(f"[processing] Processing {len(signals)} signals in parallel (max_workers={self.max_workers})")
            
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
                        print(f"[ERROR] Error processing signal {sig.id}: {e}")
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
                print("[WARNING] Parallel processing requested but only 1 signal, using sequential mode")
            
            for sig in signals:
                signal_results = self._process_signal(sig)
                self.results.extend(signal_results)

        # Выводим summary по rate limit, если используется GeckoTerminalPriceLoader
        from ..infrastructure.price_loader import GeckoTerminalPriceLoader
        if isinstance(self.price_loader, GeckoTerminalPriceLoader):
            summary = self.price_loader.get_rate_limit_summary()
            if summary.get("total_requests", 0) > 0:
                print("\n" + "="*60)
                print("=== GeckoTerminal Rate Limit Summary ===")
                print("="*60)
                print(f"total_requests: {summary.get('total_requests', 0)}")
                print(f"blocked_events: {summary.get('requests_blocked_by_rate_limiter', 0)}")
                print(f"total_wait_seconds: {summary.get('total_wait_time_seconds', 0):.2f}")
                print(f"http_429: {summary.get('http_429', 0)}")
                print(f"mode_on_429: {summary.get('mode_on_429', 'N/A')}")
                if summary.get('rate_limit_failures', 0) > 0:
                    print(f"rate_limit_failures: {summary.get('rate_limit_failures', 0)}")
                print("="*60)
        
        # Выводим summary по обработке сигналов
        total_signals = len(signals)
        print("\n" + "="*60)
        print("=== Signal Processing Summary ===")
        print("="*60)
        print(f"signals_processed: {self.signals_processed}")
        print(f"signals_skipped_no_candles: {self.signals_skipped_no_candles}")
        print(f"signals_skipped_corrupt_csv: {self.signals_skipped_corrupt_csv}")
        print(f"total_signals: {total_signals}")
        print("="*60)
        
        # Выводим summary по дедупликации предупреждений
        from ..domain.rr_utils import get_warn_summary
        warn_summary = get_warn_summary(top_n=10)
        print(f"\n{warn_summary}")
        
        return self.results

    def _build_portfolio_config(self) -> PortfolioConfig:
        """
        Строит конфигурацию портфеля из global_config.
        """
        portfolio_cfg = self.global_config.get("portfolio", {}) or {}
        backtest_cfg = self.global_config.get("backtest", {}) or {}
        
        # Парсим даты backtest window
        backtest_start: Optional[datetime] = None
        backtest_end: Optional[datetime] = None
        
        if backtest_cfg and backtest_cfg.get("start_at"):
            try:
                backtest_start = datetime.fromisoformat(backtest_cfg["start_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                print(f"[WARNING] Warning: Invalid backtest.start_at format: {backtest_cfg.get('start_at')}, ignoring")
                backtest_start = None
        if backtest_cfg and backtest_cfg.get("end_at"):
            try:
                backtest_end = datetime.fromisoformat(backtest_cfg["end_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                print(f"[WARNING] Warning: Invalid backtest.end_at format: {backtest_cfg.get('end_at')}, ignoring")
                backtest_end = None
        
        # Парсим fee model
        fee_cfg = portfolio_cfg.get("fee", {})
        
        # Парсим execution profiles если есть
        profiles = None
        if "profiles" in fee_cfg:
            profiles_dict = {}
            for profile_name, profile_data in fee_cfg["profiles"].items():
                profiles_dict[profile_name] = ExecutionProfileConfig(
                    base_slippage_pct=float(profile_data.get("base_slippage_pct", 0.03)),
                    slippage_multipliers={
                        "entry": float(profile_data.get("slippage_multipliers", {}).get("entry", 1.0)),
                        "exit_tp": float(profile_data.get("slippage_multipliers", {}).get("exit_tp", 1.0)),
                        "exit_sl": float(profile_data.get("slippage_multipliers", {}).get("exit_sl", 1.0)),
                        "exit_timeout": float(profile_data.get("slippage_multipliers", {}).get("exit_timeout", 1.0)),
                        "exit_manual": float(profile_data.get("slippage_multipliers", {}).get("exit_manual", 1.0)),
                    }
                )
            profiles = profiles_dict
        
        # Legacy slippage_pct (используется если profiles отсутствует)
        slippage_pct = None
        if "slippage_pct" in fee_cfg:
            slippage_pct = float(fee_cfg.get("slippage_pct"))
        
        fee_model = FeeModel(
            swap_fee_pct=float(fee_cfg.get("swap_fee_pct", 0.003)),
            lp_fee_pct=float(fee_cfg.get("lp_fee_pct", 0.001)),
            slippage_pct=slippage_pct,
            network_fee_sol=float(fee_cfg.get("network_fee_sol", 0.0005)),
            profiles=profiles,
        )
        
        # Execution profile (по умолчанию realistic)
        execution_profile = portfolio_cfg.get("execution_profile", "realistic")
        
        # Парсим capacity reset конфигурацию (поддерживаем вложенную структуру)
        capacity_reset_cfg = portfolio_cfg.get("capacity_reset", {})
        if capacity_reset_cfg:
            # Новая вложенная структура
            capacity_reset_enabled = capacity_reset_cfg.get("enabled", True)
            capacity_window_type = capacity_reset_cfg.get("window_type", "time")
            capacity_window_size = capacity_reset_cfg.get("window_size", 7)
            capacity_max_blocked_ratio = float(capacity_reset_cfg.get("max_blocked_ratio", 0.4))
            capacity_max_avg_hold_days = float(capacity_reset_cfg.get("max_avg_hold_days", 10.0))
            
            # Парсим window_size: может быть int, str "7d", или число
            if isinstance(capacity_window_size, str) and capacity_window_size.endswith("d"):
                capacity_window_size = int(capacity_window_size[:-1])
            else:
                capacity_window_size = int(capacity_window_size)
        else:
            # Обратная совместимость: плоская структура
            capacity_reset_enabled = portfolio_cfg.get("capacity_reset_enabled", True)
            capacity_window_type = portfolio_cfg.get("capacity_window_mode", "time")
            capacity_window_size = portfolio_cfg.get("capacity_window_days", 7)
            # Для обратной совместимости используем старые параметры
            blocked_threshold = portfolio_cfg.get("capacity_blocked_signals_threshold", 200)
            max_positions = int(portfolio_cfg.get("max_open_positions", 10))
            # Приблизительно вычисляем max_blocked_ratio из threshold
            capacity_max_blocked_ratio = blocked_threshold / max(100, max_positions * 10) if blocked_threshold else 0.4
            capacity_max_avg_hold_days = float(portfolio_cfg.get("capacity_min_turnover_threshold", 2))
        
        # Загрузка profit reset параметров с поддержкой обратной совместимости
        # Приоритет: profit_reset_* > runner_reset_* (deprecated)
        profit_reset_enabled = portfolio_cfg.get("profit_reset_enabled")
        profit_reset_multiple = portfolio_cfg.get("profit_reset_multiple")
        runner_reset_enabled = portfolio_cfg.get("runner_reset_enabled")
        runner_reset_multiple = portfolio_cfg.get("runner_reset_multiple")
        
        # Определяем финальные значения с fallback на deprecated поля
        final_profit_reset_enabled = profit_reset_enabled if profit_reset_enabled is not None else runner_reset_enabled
        final_profit_reset_multiple = profit_reset_multiple if profit_reset_multiple is not None else runner_reset_multiple
        
        # Выводим предупреждение, если используются старые поля (только один раз за прогон)
        if runner_reset_enabled is not None or runner_reset_multiple is not None:
            if profit_reset_enabled is None and profit_reset_multiple is None:
                # Используются только старые поля
                _warn_runner_reset_deprecated_once(
                    "DEPRECATED: runner_reset_enabled and runner_reset_multiple are renamed to "
                    "profit_reset_enabled and profit_reset_multiple. "
                    "Please update your YAML config. Old keys will be removed in a future version."
                )
            elif profit_reset_enabled is not None or profit_reset_multiple is not None:
                # Оба варианта заданы - новые имеют приоритет
                _warn_runner_reset_deprecated_once(
                    "Both profit_reset_* and runner_reset_* are specified in config. "
                    "Using profit_reset_* values (runner_reset_* ignored)."
                )
        
        return PortfolioConfig(
            initial_balance_sol=float(portfolio_cfg.get("initial_balance_sol", 10.0)),
            allocation_mode=portfolio_cfg.get("allocation_mode", "dynamic"),
            percent_per_trade=float(portfolio_cfg.get("percent_per_trade", 0.1)),
            max_exposure=float(portfolio_cfg.get("max_exposure", 0.5)),
            max_open_positions=int(portfolio_cfg.get("max_open_positions", 10)),
            fee_model=fee_model,
            execution_profile=execution_profile,
            backtest_start=backtest_start,
            backtest_end=backtest_end,
            profit_reset_enabled=final_profit_reset_enabled if final_profit_reset_enabled is not None else False,
            profit_reset_multiple=float(final_profit_reset_multiple) if final_profit_reset_multiple is not None else 2.0,
            runner_reset_enabled=runner_reset_enabled if runner_reset_enabled is not None else False,
            runner_reset_multiple=float(runner_reset_multiple) if runner_reset_multiple is not None else 2.0,
            capacity_reset_enabled=capacity_reset_enabled,
            capacity_window_type=capacity_window_type,
            capacity_window_size=capacity_window_size,
            capacity_max_blocked_ratio=capacity_max_blocked_ratio,
            capacity_max_avg_hold_days=capacity_max_avg_hold_days,
        )

    def run_portfolio(self) -> Dict[str, PortfolioResult]:
        """
        Запускает портфельную симуляцию для всех стратегий.
        Должен вызываться после run().
        
        :return: Словарь {strategy_name: PortfolioResult}
        """
        if not self.results:
            print("[WARNING] No strategy results available. Run run() first.")
            return {}
        
        portfolio_cfg = self._build_portfolio_config()
        engine = PortfolioEngine(portfolio_cfg)
        
        # Получаем уникальные имена стратегий
        strategy_names = sorted({r["strategy"] for r in self.results})
        
        print(f"\n[portfolio] Running portfolio simulation for {len(strategy_names)} strategies...")
        
        for name in strategy_names:
            print(f"  [processing] Processing portfolio for strategy: {name}")
            p_result = engine.simulate(self.results, strategy_name=name)
            self.portfolio_results[name] = p_result
            
            # Выводим краткую статистику
            stats = p_result.stats
            print(f"    [OK] Final balance: {stats.final_balance_sol:.4f} SOL")
            print(f"    [return] Total return: {stats.total_return_pct:.2%}")
            print(f"    [drawdown] Max drawdown: {stats.max_drawdown_pct:.2%}")
            print(f"    [trades] Trades executed: {stats.trades_executed}")
            print(f"    [skipped] Trades skipped: {stats.trades_skipped_by_risk}")
        
        return self.portfolio_results
