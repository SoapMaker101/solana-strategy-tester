# Полный список модулей и скриптов Runner

**Версия:** 2.0  
**Дата:** 2025-01-XX

---

## 📦 Core Domain Layer (Основная логика)

### Конфигурация и модели
- **`backtester/domain/runner_config.py`**
  - `RunnerTakeProfitLevel` (dataclass) — уровень TP с `xn` и `fraction`
  - `RunnerConfig` (dataclass) — конфигурация Runner стратегии
  - `create_runner_config_from_dict()` — парсинг из YAML

### Core логика Runner Ladder
- **`backtester/domain/runner_ladder.py`**
  - `RunnerTradeResult` (dataclass) — результат симуляции одной сделки
  - `RunnerLadderEngine` (class) — независимый движок симуляции
  - `RunnerLadderEngine.simulate()` (static method) — статический метод симуляции

### Strategy интеграция
- **`backtester/domain/runner_strategy.py`**
  - `RunnerStrategy` (class) — реализация интерфейса `Strategy`
  - `RunnerStrategy.on_signal()` — обработка сигнала
  - `RunnerStrategy._candles_to_dataframe()` — конвертация свечей
  - `RunnerStrategy._ladder_result_to_strategy_output()` — конвертация результата

### Portfolio интеграция
- **`backtester/domain/portfolio.py`** (частично)
  - `PortfolioEngine._process_runner_partial_exits()` — обработка частичных выходов
  - Portfolio-level reset логика (в методе `simulate()`)
  - Поддержка Runner метаданных в `Position.meta`
  - `PortfolioStats` — расширен с полями: `reset_count`, `last_reset_time`, `cycle_start_equity`, `equity_peak_in_cycle`

---

## 🔬 Research Layer (Исследовательские модули)

### XN Analysis (теоретический анализ потенциала)
- **`backtester/research/xn_analysis/xn_analyzer.py`**
  - `XNAnalyzer` (class) — анализ максимального потенциала роста сигналов
  - `XNAnalyzer.analyze_signal()` — анализ одного сигнала

- **`backtester/research/xn_analysis/xn_models.py`**
  - `XNAnalysisConfig` (dataclass) — конфигурация XN-анализа
  - `XNSignalResult` (dataclass) — результат анализа одного сигнала

- **`backtester/research/xn_analysis/xn_runner.py`**
  - CLI скрипт для запуска XN-анализа
  - Генерация `xn_per_signal.csv` и `xn_summary.csv`
  - `main()` — точка входа CLI

- **`backtester/research/xn_analysis/__init__.py`**
  - Экспорт публичных классов и функций

### Stage A/B интеграция
- **`backtester/research/strategy_stability.py`** (частично)
  - `calculate_runner_metrics()` — вычисление Runner-метрик из trades CSV
  - `is_runner_strategy()` — определение типа стратегии
  - Интеграция Runner метрик в `build_stability_table()`

- **`backtester/research/window_aggregator.py`** (частично)
  - Агрегация сделок по временным окнам
  - Поддержка Runner стратегий в агрегации

- **`backtester/research/run_stage_a.py`**
  - CLI скрипт для запуска Stage A
  - Генерация `strategy_stability.csv` с Runner метриками
  - `main()` — точка входа CLI

---

## 🎯 Decision Layer (Критерии отбора)

### Selection Criteria
- **`backtester/decision/selection_rules.py`**
  - `SelectionCriteria` (dataclass) — расширенный dataclass с Runner критериями
  - `DEFAULT_CRITERIA` — критерии для RR/RRD стратегий
  - `DEFAULT_RUNNER_CRITERIA` — критерии для Runner стратегий (baseline)

### Strategy Selector
- **`backtester/decision/strategy_selector.py`**
  - `is_runner_strategy()` — определение типа стратегии
  - `check_strategy_criteria()` — условная проверка критериев
  - `select_strategies()` — применение критериев отбора
  - `load_stability_csv()` — загрузка stability CSV
  - `save_selection_table()` — сохранение таблицы отбора
  - `generate_selection_table_from_stability()` — генерация таблицы отбора

- **`backtester/decision/run_stage_b.py`**
  - CLI скрипт для запуска Stage B
  - Отбор стратегий по Runner критериям
  - `format_selection_summary()` — форматирование вывода
  - `main()` — точка входа CLI

---

## 🧪 Tests (Тесты)

### Domain тесты
- **`tests/domain/test_runner_ladder.py`**
  - Unit-тесты для `RunnerLadderEngine`
  - Тесты частичных выходов, time stop, сортировки уровней

- **`tests/domain/test_runner_strategy.py`**
  - Unit-тесты для `RunnerStrategy`
  - Проверка интеграции с `RunnerLadderEngine`

### Portfolio тесты
- **`tests/portfolio/test_portfolio_runner_partial_exits.py`**
  - Тесты частичных выходов в портфеле
  - Проверка уменьшения экспозиции, fees, dynamic allocation

- **`tests/portfolio/test_portfolio_runner_reset.py`**
  - Тесты старой логики reset (на уровне позиций)
  - ⚠️ Устарело: заменено на portfolio-level reset

- **`tests/portfolio/test_portfolio_runner_reset_portfolio_level.py`**
  - Тесты portfolio-level reset
  - Проверка закрытия всех позиций при достижении порога equity

### Research тесты
- **`tests/research/xn_analysis/test_xn_analyzer.py`**
  - Тесты XN-анализа

---

## 📝 Configuration & Documentation

### Конфигурация
- **`config/strategies_example.yaml`**
  - Пример конфигурации Runner стратегии с baseline параметрами

- **`docs/runner_config_example.yaml`**
  - Документация по конфигурации Runner

- **`config/backtest_example.yaml`**
  - Параметры portfolio-level reset (`runner_reset_enabled`, `runner_reset_multiple`)

### Документация
- **`docs/XN_RUNNER_RESEARCH.md`**
  - Документация по XN-анализу (research инструмент)

- **`docs/RUNNER_MODULES_REFERENCE.md`**
  - Полный справочник модулей и скриптов Runner

- **`docs/RUNNER_COMPLETE_GUIDE.md`**
  - Полное руководство по Runner стратегии

- **`docs/RUNNER_MODULES_LIST.md`** (этот файл)
  - Список всех модулей и скриптов Runner

- **`backtester/research/Пайплайн реализации Runner.txt`**
  - План реализации Runner (исторический документ)

---

## 🔧 Application Layer (Интеграция)

- **`backtester/application/runner.py`** (частично)
  - `BacktestRunner` — основной оркестратор
  - Загрузка Runner стратегий из YAML
  - Интеграция с PortfolioEngine

- **`main.py`** (частично)
  - CLI точка входа
  - Парсинг Runner конфигурации
  - Генерация `portfolio_summary.csv` с Runner метриками
  - `load_strategies()` — загрузка стратегий (включая Runner)
  - `generate_portfolio_summary()` — генерация portfolio summary с Runner метриками

---

## 📊 Итоговая статистика

### Всего модулей и скриптов: **25**

**По категориям:**
- Core Domain: 4 модуля
- Research: 7 модулей/скриптов
- Decision: 3 модуля/скрипта
- Tests: 5 файлов
- Configuration: 3 файла
- Documentation: 5 файлов
- Application: 2 модуля (частично)

**По типам:**
- Python модули: 15
- CLI скрипты: 3
- Тесты: 5
- Конфигурация: 3
- Документация: 5

---

## 🔗 Связанные модули (не Runner-специфичные, но используемые)

- **`backtester/domain/strategy_base.py`**
  - `StrategyConfig` — базовый класс конфигурации
  - `Strategy` — абстрактный базовый класс стратегии

- **`backtester/domain/models.py`**
  - `StrategyInput`, `StrategyOutput` — модели данных
  - `Candle`, `Signal` — модели данных

- **`backtester/domain/execution_model.py`**
  - `ExecutionModel` — модель исполнения (slippage, fees)
  - Используется для частичных выходов Runner

- **`backtester/domain/position.py`**
  - `Position` — модель позиции
  - Хранит Runner метаданные в `meta`

- **`backtester/infrastructure/reporter.py`**
  - `Reporter` — генерация отчетов
  - Сохранение Runner метаданных в CSV

---

## 📚 Дополнительные ресурсы

- [RUNNER_COMPLETE_GUIDE.md](./RUNNER_COMPLETE_GUIDE.md) — полное руководство
- [RUNNER_MODULES_REFERENCE.md](./RUNNER_MODULES_REFERENCE.md) — справочник модулей
- [XN_RUNNER_RESEARCH.md](./XN_RUNNER_RESEARCH.md) — документация по XN-анализу
- [ARCHITECTURE.md](./ARCHITECTURE.md) — общая архитектура системы
- [PORTFOLIO_LAYER.md](./PORTFOLIO_LAYER.md) — документация портфельного слоя



