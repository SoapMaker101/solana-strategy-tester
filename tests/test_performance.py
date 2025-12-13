"""
Тесты производительности BacktestRunner при разных настройках parallel.

Цель: определить узкие места при обработке большого количества сигналов —
CPU или API rate limit.

Сценарии тестирования:
1. Последовательный режим (parallel=False)
2. Параллельный режим на 4 потока (parallel=True, max_workers=4)
3. Параллельный режим на 10 потоков (parallel=True, max_workers=10)

Метрики:
- Общее время выполнения
- Количество успешных vs. упавших сигналов
- Количество retry при запросах
- Среднее время обработки одного сигнала
"""

import sys
from pathlib import Path
import io
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict

# Добавляем корень проекта в sys.path для корректных импортов
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Настройка кодировки вывода для Windows (поддержка эмодзи)
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except AttributeError:
        pass

from backtester.application.runner import BacktestRunner
from backtester.infrastructure.signal_loader import CsvSignalLoader
from backtester.infrastructure.price_loader import GeckoTerminalPriceLoader
from backtester.infrastructure.reporter import Reporter
from backtester.domain.strategy_base import StrategyConfig
from backtester.domain.rr_strategy import RRStrategy
from backtester.domain.models import StrategyOutput


class PerformanceTester:
    """
    Класс для тестирования производительности BacktestRunner.
    
    Измеряет:
    - Время выполнения
    - Количество успешных/неуспешных сигналов
    - Статистику по причинам выхода
    - Среднее время на сигнал
    """
    
    def __init__(self, signals_path: str = "signals/test_signals.csv", enable_file_logging: bool = True):
        """
        Инициализация тестовой среды.
        
        :param signals_path: Путь к CSV-файлу с тестовыми сигналами
        :param enable_file_logging: Включить логирование в файл
        """
        self.signals_path = signals_path
        self.enable_file_logging = enable_file_logging
        self.log_file = None
        
        # Базовая конфигурация для тестов
        self.base_config = {
            "data": {
                "loader": "gecko",
                "candles_dir": "data/candles/cached",
                "timeframe": "1m",
                "before_minutes": 60,
                "after_minutes": 360,
            },
            "portfolio": {
                "initial_balance_sol": 10.0,
                "allocation_mode": "dynamic",
                "percent_per_trade": 0.1,
                "max_exposure": 0.5,
                "max_open_positions": 10,
                "fee": {
                    "swap_fee_pct": 0.003,
                    "lp_fee_pct": 0.001,
                    "slippage_pct": 0.10,
                    "network_fee_sol": 0.0005,
                },
            },
            "report": {
                "output_dir": "output/reports",
            },
        }
        
        # Простая стратегия для тестов
        self.test_strategy = RRStrategy(StrategyConfig(
            name="TEST_RR",
            type="RR",
            params={
                "tp_pct": 10,  # 10% TP
                "sl_pct": 5,   # 5% SL
                "max_minutes": 43200,  # 30 дней
            }
        ))
        
        # Настройка логирования в файл
        if self.enable_file_logging:
            log_dir = Path("output/logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = log_dir / f"performance_test_{timestamp}.log"
            self.log_file = open(log_path, "w", encoding="utf-8")
            self.log(f"📝 Логирование инициализировано: {log_path}")
    
    def log(self, message: str, level: str = "INFO"):
        """
        Логирует сообщение с временной меткой.
        
        :param message: Текст сообщения
        :param level: Уровень логирования (INFO, DEBUG, WARNING, ERROR)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_message = f"[{timestamp}] [{level}] {message}"
        
        # Вывод в консоль
        print(log_message)
        
        # Запись в файл
        if self.log_file:
            self.log_file.write(log_message + "\n")
            self.log_file.flush()
    
    def __del__(self):
        """Закрывает файл лога при уничтожении объекта."""
        if self.log_file:
            self.log_file.close()
    
    def _analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Анализирует результаты бэктеста и возвращает статистику.
        
        :param results: Список результатов от BacktestRunner.run()
        :return: Словарь со статистикой
        """
        stats = {
            "total": len(results),
            "successful": 0,
            "errors": 0,
            "no_entry": 0,
            "tp": 0,
            "sl": 0,
            "timeout": 0,
        }
        
        reason_counts = defaultdict(int)
        
        for result in results:
            output: StrategyOutput = result.get("result")
            if not isinstance(output, StrategyOutput):
                stats["errors"] += 1
                continue
            
            reason = output.reason
            reason_counts[reason] += 1
            
            if reason == "error":
                stats["errors"] += 1
            elif reason == "no_entry":
                stats["no_entry"] += 1
            else:
                stats["successful"] += 1
                if reason == "tp":
                    stats["tp"] += 1
                elif reason == "sl":
                    stats["sl"] += 1
                elif reason == "timeout":
                    stats["timeout"] += 1
        
        return {
            "counts": stats,
            "reason_distribution": dict(reason_counts),
        }
    
    def run_test(
        self,
        test_name: str,
        parallel: bool,
        max_workers: int = 1,
    ) -> Dict[str, Any]:
        """
        Запускает один тест производительности.
        
        :param test_name: Название теста
        :param parallel: Включить параллельную обработку
        :param max_workers: Количество потоков для параллельной обработки
        :return: Словарь с результатами теста
        """
        self.log(f"\n{'='*70}")
        self.log(f"🧪 ТЕСТ: {test_name}")
        self.log(f"{'='*70}")
        self.log(f"Параметры:")
        self.log(f"  - parallel: {parallel}")
        self.log(f"  - max_workers: {max_workers}")
        self.log(f"  - signals file: {self.signals_path}")
        self.log(f"  - timeframe: {self.base_config['data']['timeframe']}")
        self.log("")
        
        # Проверяем наличие файла сигналов
        self.log(f"🔍 ШАГ 1: Проверка наличия файла сигналов: {self.signals_path}")
        signals_file = Path(self.signals_path)
        if not signals_file.exists():
            error_msg = f"❌ Файл сигналов не найден: {self.signals_path}"
            self.log(error_msg, "ERROR")
            return {
                "test_name": test_name,
                "parallel": parallel,
                "max_workers": max_workers,
                "success": False,
                "error": error_msg,
                "execution_time": 0.0,
                "signals_count": 0,
                "stats": {},
            }
        self.log(f"✅ Файл сигналов найден: {signals_file.absolute()}")
        
        # Инициализация компонентов
        try:
            self.log(f"🔍 ШАГ 2: Инициализация CsvSignalLoader")
            self.log(f"   Команда: CsvSignalLoader(path='{self.signals_path}')")
            signal_loader = CsvSignalLoader(self.signals_path)
            
            self.log(f"🔍 ШАГ 3: Загрузка сигналов из файла")
            self.log(f"   Команда: signal_loader.load_signals()")
            signals = signal_loader.load_signals()
            signals_count = len(signals)
            
            if signals_count == 0:
                error_msg = "❌ Файл сигналов пуст"
                self.log(error_msg, "ERROR")
                return {
                    "test_name": test_name,
                    "parallel": parallel,
                    "max_workers": max_workers,
                    "success": False,
                    "error": error_msg,
                    "execution_time": 0.0,
                    "signals_count": 0,
                    "stats": {},
                }
            
            self.log(f"✅ Загружено сигналов: {signals_count}")
            
            self.log(f"🔍 ШАГ 4: Инициализация GeckoTerminalPriceLoader")
            self.log(f"   Команда: GeckoTerminalPriceLoader(")
            self.log(f"     cache_dir='{self.base_config['data']['candles_dir']}',")
            self.log(f"     timeframe='{self.base_config['data']['timeframe']}',")
            self.log(f"     max_cache_age_days=7")
            self.log(f"   )")
            price_loader = GeckoTerminalPriceLoader(
                cache_dir=self.base_config["data"]["candles_dir"],
                timeframe=self.base_config["data"]["timeframe"],
                max_cache_age_days=7,  # Кеш действителен 7 дней
            )
            self.log(f"✅ PriceLoader инициализирован")
            
            self.log(f"🔍 ШАГ 5: Инициализация Reporter")
            self.log(f"   Команда: Reporter(output_dir='{self.base_config['report']['output_dir']}')")
            reporter = Reporter(output_dir=self.base_config["report"]["output_dir"])
            self.log(f"✅ Reporter инициализирован")
            
            # Создание runner
            self.log(f"🔍 ШАГ 6: Создание BacktestRunner")
            self.log(f"   Команда: BacktestRunner(")
            self.log(f"     signal_loader=signal_loader,")
            self.log(f"     price_loader=price_loader,")
            self.log(f"     reporter=reporter,")
            self.log(f"     strategies=[{self.test_strategy.config.name}],")
            self.log(f"     global_config=base_config,")
            self.log(f"     parallel={parallel},")
            self.log(f"     max_workers={max_workers}")
            self.log(f"   )")
            runner = BacktestRunner(
                signal_loader=signal_loader,
                price_loader=price_loader,
                reporter=reporter,
                strategies=[self.test_strategy],
                global_config=self.base_config,
                parallel=parallel,
                max_workers=max_workers,
            )
            self.log(f"✅ BacktestRunner создан")
            
            # Запуск и замер времени
            self.log(f"🔍 ШАГ 7: Запуск бэктеста")
            self.log(f"   Команда: runner.run()")
            self.log(f"   Режим: {'ПАРАЛЛЕЛЬНЫЙ' if parallel else 'ПОСЛЕДОВАТЕЛЬНЫЙ'}")
            if parallel:
                self.log(f"   Количество потоков: {max_workers}")
            start_time = time.time()
            
            try:
                results = runner.run()
                execution_time = time.time() - start_time
                self.log(f"✅ Бэктест завершен за {execution_time:.2f} сек")
                
                # Анализ результатов
                self.log(f"🔍 ШАГ 8: Анализ результатов")
                self.log(f"   Команда: _analyze_results(results)")
                analysis = self._analyze_results(results)
                stats = analysis["counts"]
                reason_dist = analysis["reason_distribution"]
                self.log(f"✅ Анализ завершен: {stats['successful']} успешных, {stats['errors']} ошибок")
                
                # Среднее время на сигнал
                avg_time_per_signal = execution_time / signals_count if signals_count > 0 else 0.0
                
                # Формируем результат
                test_result = {
                    "test_name": test_name,
                    "parallel": parallel,
                    "max_workers": max_workers,
                    "success": True,
                    "error": None,
                    "execution_time": execution_time,
                    "signals_count": signals_count,
                    "stats": stats,
                    "reason_distribution": reason_dist,
                    "avg_time_per_signal": avg_time_per_signal,
                }
                
                # Вывод результатов
                self.log(f"\n✅ Тест завершен успешно")
                self.log(f"\n📊 МЕТРИКИ:")
                self.log(f"  ⏱️  Время выполнения: {execution_time:.2f} сек")
                self.log(f"  📈 Всего сигналов: {signals_count}")
                self.log(f"  ✅ Успешных результатов: {stats['successful']}")
                self.log(f"  ❌ Ошибок: {stats['errors']}")
                self.log(f"  ⛔ Нет входа: {stats['no_entry']}")
                self.log(f"  ⏱️  Среднее время на сигнал: {avg_time_per_signal:.2f} сек")
                
                if stats['successful'] > 0:
                    self.log(f"\n📊 Распределение по причинам выхода:")
                    self.log(f"  🎯 TP: {stats['tp']}")
                    self.log(f"  🛑 SL: {stats['sl']}")
                    self.log(f"  ⏰ Timeout: {stats['timeout']}")
                
                return test_result
                
            except Exception as e:
                execution_time = time.time() - start_time
                error_msg = str(e)
                self.log(f"\n❌ Тест завершился с ошибкой: {error_msg}", "ERROR")
                import traceback
                traceback_str = traceback.format_exc()
                self.log(traceback_str, "ERROR")
                traceback.print_exc()
                
                return {
                    "test_name": test_name,
                    "parallel": parallel,
                    "max_workers": max_workers,
                    "success": False,
                    "error": error_msg,
                    "execution_time": execution_time,
                    "signals_count": signals_count,
                    "stats": {},
                    "reason_distribution": {},
                    "avg_time_per_signal": 0.0,
                }
                
        except Exception as e:
            error_msg = f"Ошибка инициализации: {str(e)}"
            self.log(f"❌ {error_msg}", "ERROR")
            import traceback
            traceback_str = traceback.format_exc()
            self.log(traceback_str, "ERROR")
            traceback.print_exc()
            
            return {
                "test_name": test_name,
                "parallel": parallel,
                "max_workers": max_workers,
                "success": False,
                "error": error_msg,
                "execution_time": 0.0,
                "signals_count": 0,
                "stats": {},
                "reason_distribution": {},
                "avg_time_per_signal": 0.0,
            }
    
    def run_all_tests(self) -> List[Dict[str, Any]]:
        """
        Запускает все тесты производительности.
        
        :return: Список результатов всех тестов
        """
        self.log("\n" + "="*70)
        self.log("🚀 ЗАПУСК ТЕСТОВ ПРОИЗВОДИТЕЛЬНОСТИ BACKTESTRUNNER")
        self.log("="*70)
        self.log(f"Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        test_results = []
        
        # Тест №1: Последовательный режим
        self.log(f"\n{'='*70}")
        self.log("📋 ТЕСТ №1: Последовательный режим")
        self.log(f"{'='*70}")
        result1 = self.run_test(
            test_name="Тест №1: Последовательный режим",
            parallel=False,
            max_workers=1
        )
        test_results.append(result1)
        
        # Небольшая пауза между тестами
        if result1.get("success"):
            self.log("\n⏸️  Пауза 2 секунды перед следующим тестом...")
            time.sleep(2)
        
        # Тест №2: Параллельный режим (4 потока)
        self.log(f"\n{'='*70}")
        self.log("📋 ТЕСТ №2: Параллельный режим (4 потока)")
        self.log(f"{'='*70}")
        result2 = self.run_test(
            test_name="Тест №2: Параллельный режим (4 потока)",
            parallel=True,
            max_workers=4
        )
        test_results.append(result2)
        
        # Небольшая пауза между тестами
        if result2.get("success"):
            self.log("\n⏸️  Пауза 2 секунды перед следующим тестом...")
            time.sleep(2)
        
        # Тест №3: Параллельный режим (10 потоков)
        self.log(f"\n{'='*70}")
        self.log("📋 ТЕСТ №3: Параллельный режим (10 потоков)")
        self.log(f"{'='*70}")
        result3 = self.run_test(
            test_name="Тест №3: Параллельный режим (10 потоков)",
            parallel=True,
            max_workers=10
        )
        test_results.append(result3)
        
        # Вывод сводной таблицы
        self.log(f"\n{'='*70}")
        self.log("📊 ГЕНЕРАЦИЯ СВОДНОЙ ТАБЛИЦЫ")
        self.log(f"{'='*70}")
        self._print_summary_table(test_results)
        
        self.log(f"\n✅ Все тесты завершены")
        self.log(f"Время окончания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return test_results
    
    def _print_summary_table(self, results: List[Dict[str, Any]]):
        """
        Выводит сводную таблицу результатов всех тестов.
        
        :param results: Список результатов тестов
        """
        self.log("\n" + "="*70)
        self.log("📊 СВОДНАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
        self.log("="*70)
        
        # Заголовок таблицы
        header = f"{'Тест':<45} {'Время (сек)':<12} {'Сигналов':<10} {'Успешных':<10} {'Ошибок':<10} {'Среднее/сигнал':<15}"
        self.log(header)
        self.log("-" * 70)
        
        # Данные
        for result in results:
            test_name = result.get("test_name", "Unknown")
            exec_time = result.get("execution_time", 0.0)
            signals = result.get("signals_count", 0)
            stats = result.get("stats", {})
            successful = stats.get("successful", 0)
            errors = stats.get("errors", 0)
            avg_time = result.get("avg_time_per_signal", 0.0)
            
            status = "✅" if result.get("success", False) else "❌"
            self.log(f"{status} {test_name:<43} {exec_time:<12.2f} {signals:<10} {successful:<10} {errors:<10} {avg_time:<15.2f}")
        
        self.log("=" * 70)
        
        # Сравнение производительности
        successful_results = [r for r in results if r.get("success", False)]
        
        if len(successful_results) >= 2:
            self.log("\n📈 СРАВНЕНИЕ ПРОИЗВОДИТЕЛЬНОСТИ:")
            
            sequential = None
            parallel_4 = None
            parallel_10 = None
            
            for r in successful_results:
                name = r.get("test_name", "")
                if "Последовательный" in name:
                    sequential = r
                elif "4 потока" in name:
                    parallel_4 = r
                elif "10 потоков" in name:
                    parallel_10 = r
            
            if sequential and parallel_4:
                speedup_4 = sequential["execution_time"] / parallel_4["execution_time"]
                efficiency_4 = (speedup_4 / parallel_4["max_workers"]) * 100
                self.log(f"  📊 Параллельный (4 потока) vs Последовательный:")
                self.log(f"     Ускорение: {speedup_4:.2f}x")
                self.log(f"     Эффективность: {efficiency_4:.1f}%")
            
            if sequential and parallel_10:
                speedup_10 = sequential["execution_time"] / parallel_10["execution_time"]
                efficiency_10 = (speedup_10 / parallel_10["max_workers"]) * 100
                self.log(f"  📊 Параллельный (10 потоков) vs Последовательный:")
                self.log(f"     Ускорение: {speedup_10:.2f}x")
                self.log(f"     Эффективность: {efficiency_10:.1f}%")
            
            if parallel_4 and parallel_10:
                ratio = parallel_4["execution_time"] / parallel_10["execution_time"]
                self.log(f"  📊 10 потоков vs 4 потока:")
                self.log(f"     Ускорение: {ratio:.2f}x")
        
        self.log("")


def main():
    """
    Главная функция для запуска тестов производительности.
    """
    # Проверяем наличие файла сигналов
    signals_path = "signals/test_signals.csv"
    if not Path(signals_path).exists():
        print(f"❌ Файл сигналов не найден: {signals_path}")
        print(f"   Создайте файл с тестовыми сигналами для запуска тестов.")
        return
    
    # Создаем тестер и запускаем все тесты
    tester = PerformanceTester(signals_path=signals_path, enable_file_logging=True)
    results = tester.run_all_tests()
    
    # Сохранение результатов в файл
    tester.log(f"\n🔍 ШАГ 9: Сохранение результатов в JSON")
    output_path = Path("output/performance_test_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        tester.log(f"   Команда: json.dump(results, file='{output_path}')")
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        tester.log(f"✅ Результаты сохранены в: {output_path}")
        if tester.log_file:
            tester.log(f"✅ Лог сохранен в: {tester.log_file.name}")
    except Exception as e:
        tester.log(f"⚠️ Не удалось сохранить результаты: {e}", "WARNING")
    
    # Закрываем файл лога
    if tester.log_file:
        tester.log_file.close()
        tester.log_file = None


if __name__ == "__main__":
    main()
