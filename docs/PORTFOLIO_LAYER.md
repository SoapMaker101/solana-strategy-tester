# Портфельный слой

## Обзор

Портфельный слой реализован поверх существующих стратегий (RR, RRD, Runner) и обеспечивает:

> **Дата реализации:** Phase 4 (2025-01-XX)  
> **Цель:** Реалистичная симуляция торговли с учетом комиссий, проскальзывания и портфельных ограничений

## История изменений

### Phase 4: Реализация портфельного слоя

#### Созданные файлы

1. **`backtester/domain/portfolio.py`** (новый файл, ~295 строк)
   - Полная реализация портфельного движка
   - Модели: `FeeModel`, `PortfolioConfig`, `PortfolioStats`, `PortfolioResult`
   - Класс `PortfolioEngine` с методом `simulate()`

2. **`docs/PORTFOLIO_LAYER.md`** (новый файл)
   - Полная документация портфельного слоя
   - Примеры использования и конфигурации

#### Измененные файлы

1. **`backtester/domain/position.py`**
   - **Изменение:** `meta: Dict[str, Any] = None` → `meta: Dict[str, Any] = field(default_factory=dict)`
   - **Причина:** Упрощение работы с метаданными, безопасное добавление полей без проверки на None
   - **Использование:** Портфельный движок добавляет в `meta` информацию о стратегии, комиссиях, PnL

2. **`backtester/application/runner.py`**
   - **Добавлено:**
     - Импорты портфельных классов
     - Атрибут `self.portfolio_results: Dict[str, PortfolioResult]`
     - Метод `_build_portfolio_config()` - парсинг конфигурации из YAML
     - Метод `run_portfolio()` - запуск портфельной симуляции
   - **Причина:** Интеграция портфельного слоя в основной процесс бэктестинга
   - **Результат:** Автоматический запуск портфельной симуляции после выполнения стратегий

3. **`backtester/infrastructure/reporter.py`**
   - **Добавлено:**
     - Метод `save_portfolio_results()` - сохранение портфельных результатов в CSV/JSON
     - Метод `plot_portfolio_equity_curve()` - построение графика equity curve
   - **Причина:** Полная отчетность по портфелю
   - **Результат:** Автоматическое сохранение equity curve, позиций и статистики

4. **`config/backtest_example.yaml`**
   - **Добавлено:**
     - Секция `backtest` с `start_at` и `end_at`
     - Секция `portfolio` с настройками баланса, аллокации, лимитов
     - Секция `fee` с комиссиями и проскальзыванием
   - **Причина:** Централизованная конфигурация портфеля
   - **Результат:** Гибкая настройка портфеля через YAML

5. **`main.py`**
   - **Добавлено:**
     - Вызов `runner.run_portfolio()` после `runner.run()`
     - Вывод информации о портфельной симуляции
     - Автоматическое сохранение портфельных результатов
   - **Причина:** Интеграция в основной workflow
   - **Результат:** Портфельная симуляция запускается автоматически

#### Детальное описание изменений

##### 1. Модель комиссий и Execution Profiles (FeeModel + ExecutionModel)

**Файлы:** `backtester/domain/portfolio.py`, `backtester/domain/execution_model.py`

**Что делает:**
- Моделирует реальные издержки торговли на Solana
- Учитывает комиссии swap (0.3%), LP (0.1%), проскальзывание, сетевые комиссии (0.0005 SOL)
- Поддерживает **execution profiles** с reason-based slippage multipliers

**Execution Profiles:**

Система поддерживает разные профили исполнения для более реалистичного моделирования:

- **`realistic`** (по умолчанию): Базовое проскальзывание 3%, разные multipliers для разных типов выхода
  - Entry: 3% (1.0x)
  - Exit TP: 2.1% (0.7x) - меньше slippage при прибыльном выходе
  - Exit SL: 3.6% (1.2x) - больше slippage при стоп-лоссе (паника)
  - Exit Timeout: 0.9% (0.3x) - минимальный slippage при плановом выходе
  - Exit Manual: 1.5% (0.5x)

- **`stress`**: Базовое проскальзывание 10% для stress-testing low-cap токенов
  - Используется для проверки устойчивости стратегий к экстремальным условиям

- **`custom`**: Пользовательский профиль (определяется в YAML)

**Legacy режим:**
Если в конфиге указан только `slippage_pct` без `profiles`, используется legacy режим:
- Одинаковое проскальзывание для всех событий (вход/выход)
- Выдается предупреждение о миграции на profiles

**Формула применения slippage:**
```
effective_entry_price = raw_entry_price * (1 + slippage_entry)
effective_exit_price = raw_exit_price * (1 - slippage_exit)
```

**Формула применения fees:**
```
notional_after_fees = notional * (1 - swap_fee_pct - lp_fee_pct)
```

**Зачем нужно:**
- Реалистичная оценка прибыльности стратегий
- Разные slippage для разных сценариев выхода (TP vs SL vs timeout)
- Возможность stress-testing без влияния на основной анализ (Stage A/B используют realistic)
- Обратная совместимость с legacy конфигами

##### 2. Портфельный движок (PortfolioEngine)

**Файл:** `backtester/domain/portfolio.py`

**Что делает:**
- Принимает результаты стратегий (StrategyOutput)
- Применяет портфельные ограничения
- Рассчитывает размер позиций
- Применяет комиссии
- Ведет учет баланса и equity curve

**Логика работы:**
1. Фильтрует сделки по стратегии и backtest window
2. Сортирует по entry_time
3. Последовательно обрабатывает сделки:
   - Закрывает позиции, у которых exit_time <= entry_time новой
   - Проверяет лимиты (количество позиций, экспозиция)
   - Рассчитывает размер позиции (fixed/dynamic)
   - Применяет комиссии к PnL
   - Создает Position и добавляет в открытые
4. Закрывает все оставшиеся позиции
5. Рассчитывает финальную статистику

**Зачем нужно:**
- Управление капиталом на уровне портфеля
- Реалистичная симуляция с учетом ограничений
- Генерация equity curve для анализа

##### 3. Интеграция в Runner

**Файл:** `backtester/application/runner.py`

**Что делает:**
- Парсит конфигурацию портфеля из YAML
- Запускает портфельную симуляцию для каждой стратегии
- Сохраняет результаты

**Метод `_build_portfolio_config()`:**
- Парсит секцию `backtest` (start_at, end_at)
- Парсит секцию `portfolio` (баланс, режим, лимиты)
- Парсит секцию `fee` (комиссии)
- Создает объекты `FeeModel` и `PortfolioConfig`

**Метод `run_portfolio()`:**
- Получает уникальные имена стратегий
- Для каждой стратегии запускает `PortfolioEngine.simulate()`
- Сохраняет результаты в `self.portfolio_results`
- Выводит краткую статистику

**Зачем нужно:**
- Автоматическая интеграция портфельного слоя
- Работает со всеми стратегиями без изменений
- Централизованная конфигурация

##### 4. Отчетность портфеля

**Файл:** `backtester/infrastructure/reporter.py`

**Что делает:**
- Сохраняет портфельные результаты в различных форматах
- Строит графики equity curve

**Метод `save_portfolio_results()`:**
- Сохраняет equity curve в CSV
- Сохраняет позиции в CSV (с метаданными: strategy, raw_pnl_pct, fee_pct, pnl_sol)
- Сохраняет статистику в JSON
- Вызывает построение графика

**Метод `plot_portfolio_equity_curve()`:**
- Строит временную серию баланса
- Добавляет линию финального баланса
- Сохраняет в PNG

**Зачем нужно:**
- Полная отчетность по портфелю
- Визуализация динамики баланса
- Детальная информация для анализа

##### 5. Конфигурация

**Файл:** `config/backtest_example.yaml`

**Что добавлено:**

```yaml
backtest:
  start_at: "2024-06-01T00:00:00Z"  # Окно бэктеста
  end_at: "2024-07-01T00:00:00Z"

portfolio:
  initial_balance_sol: 10.0         # Начальный баланс
  allocation_mode: "dynamic"        # Режим аллокации
  percent_per_trade: 0.1            # Доля на сделку
  max_exposure: 0.5                  # Макс. экспозиция
  max_open_positions: 10            # Макс. позиций
  fee:
    swap_fee_pct: 0.003              # Комиссии
    lp_fee_pct: 0.001
    slippage_pct: 0.10
    network_fee_sol: 0.0005
```

**Зачем нужно:**
- Гибкая настройка портфеля
- Легко экспериментировать с параметрами
- Централизованное управление

#### Результаты реализации

После реализации портфельного слоя:

✅ **Реалистичная симуляция:**
- Учитываются все комиссии и проскальзывание
- Применяются портфельные ограничения
- Генерируется equity curve

✅ **Гибкая настройка:**
- Через YAML конфигурацию
- Разные режимы аллокации (fixed/dynamic)
- Настраиваемые лимиты

✅ **Полная отчетность:**
- Equity curve в CSV и PNG
- Детальная информация по позициям
- Статистика портфеля

✅ **Интеграция:**
- Автоматический запуск
- Работает со всеми стратегиями
- Не требует изменений в коде стратегий

---

## Обзор

Портфельный слой реализован поверх существующих стратегий (RR, RRD, Runner) и обеспечивает:

- Единый баланс в SOL
- Динамическое/фиксированное управление размером позиций
- Учет комиссий (swap, LP, network) и проскальзывания (по умолчанию 10%)
- Ограничения портфеля:
  - Максимальная экспозиция (max_exposure)
  - Максимальное количество открытых позиций (max_open_positions)
- Backtest window (ограничение по датам)
- Equity curve (кривая баланса)
- **Portfolio-level reset для Runner:** Закрытие всех позиций при достижении порога equity
- **Runner частичные выходы:** Обработка частичного закрытия позиций на разных уровнях TP

## Архитектура

### Модули

1. **`backtester/domain/portfolio.py`** - основной модуль портфельного движка
   - `FeeModel` - модель комиссий и проскальзывания
   - `PortfolioConfig` - конфигурация портфеля
   - `PortfolioStats` - статистика портфеля
   - `PortfolioResult` - результат портфельной симуляции
   - `PortfolioEngine` - движок портфельной симуляции

2. **`backtester/application/runner.py`** - обновлен для интеграции портфельного слоя
   - Метод `run_portfolio()` - запускает портфельную симуляцию

3. **`backtester/infrastructure/reporter.py`** - обновлен для сохранения портфельных результатов
   - Метод `save_portfolio_results()` - сохраняет портфельные результаты
   - Метод `plot_portfolio_equity_curve()` - строит график equity curve

## Конфигурация

### backtest_example.yaml

```yaml
backtest:
  start_at: "2024-06-01T00:00:00Z"  # Начало окна бэктеста (опционально)
  end_at: "2024-07-01T00:00:00Z"    # Конец окна бэктеста (опционально)

portfolio:
  initial_balance_sol: 10.0       # Начальный баланс в SOL
  allocation_mode: "dynamic"      # "fixed" или "dynamic"
  percent_per_trade: 0.1          # Доля капитала на одну сделку (10%)
  max_exposure: 0.5               # Максимальная экспозиция (50%)
  max_open_positions: 10          # Максимальное количество открытых позиций
  runner_reset_enabled: false     # Portfolio-level reset для Runner (закрытие всех позиций при достижении порога equity)
  runner_reset_multiple: 2.0     # Множитель XN для порога reset (например, 2.0 = x2)
  execution_profile: "realistic"   # Профиль исполнения: "realistic", "stress", или "custom"
  fee:
    swap_fee_pct: 0.003           # Комиссия swap (0.3%)
    lp_fee_pct: 0.001             # Комиссия LP (0.1%)
    network_fee_sol: 0.0005        # Фиксированная комиссия сети в SOL
    
    # Execution profiles с reason-based slippage (рекомендуется)
    profiles:
      realistic:
        base_slippage_pct: 0.03    # 3% базовое проскальзывание
        slippage_multipliers:
          entry: 1.0               # 3% при входе
          exit_tp: 0.7             # 2.1% при выходе по TP
          exit_sl: 1.2             # 3.6% при выходе по SL
          exit_timeout: 0.3        # 0.9% при timeout
          exit_manual: 0.5         # 1.5% при ручном выходе
      
      stress:
        base_slippage_pct: 0.10    # 10% для stress-testing
        slippage_multipliers:
          entry: 1.0
          exit_tp: 0.6
          exit_sl: 1.3
          exit_timeout: 0.2
          exit_manual: 0.5
    
    # Legacy режим (если profiles не указаны)
    # slippage_pct: 0.10            # Одинаковое проскальзывание для всех событий
```

### Параметры

- **initial_balance_sol**: Начальный баланс портфеля в SOL
- **allocation_mode**: 
  - `"fixed"` - размер позиции рассчитывается от начального баланса
  - `"dynamic"` - размер позиции рассчитывается от текущего баланса
- **percent_per_trade**: Доля капитала на одну сделку (0.1 = 10%)
- **max_exposure**: Максимальная доля капитала в открытых позициях (0.5 = 50%)
- **max_open_positions**: Максимальное количество одновременно открытых позиций
- **execution_profile**: Профиль исполнения (`"realistic"`, `"stress"`, или `"custom"`)
  - `"realistic"` (по умолчанию): Базовое проскальзывание 3% с разными multipliers
  - `"stress"`: Базовое проскальзывание 10% для stress-testing
  - `"custom"`: Пользовательский профиль из `fee.profiles`
- **fee**: Модель комиссий
  - `swap_fee_pct`: Комиссия swap (в долях, 0.003 = 0.3%)
  - `lp_fee_pct`: Комиссия LP (в долях, 0.001 = 0.1%)
  - `network_fee_sol`: Фиксированная комиссия сети в SOL (0.0005 SOL)
  - `profiles`: Execution profiles с reason-based slippage (рекомендуется)
    - `realistic`: Профиль для обычного анализа (3% базовое slippage)
    - `stress`: Профиль для stress-testing (10% базовое slippage)
    - `custom`: Пользовательский профиль
  - `slippage_pct`: Legacy режим (если profiles не указаны, одинаковое slippage для всех событий)

## Использование

### Базовое использование

После запуска стратегий через `runner.run()`, вызовите `runner.run_portfolio()`:

```python
from backtester.application.runner import BacktestRunner
from backtester.domain.portfolio import PortfolioConfig, PortfolioEngine

# ... настройка runner ...

# Запуск стратегий
results = runner.run()

# Запуск портфельной симуляции
portfolio_results = runner.run_portfolio()

# Получение результатов для конкретной стратегии
portfolio_result = portfolio_results["RR_10_20"]
print(f"Final balance: {portfolio_result.stats.final_balance_sol} SOL")
print(f"Total return: {portfolio_result.stats.total_return_pct:.2%}")
```

### Программная настройка портфеля

```python
from backtester.domain.portfolio import PortfolioConfig, PortfolioEngine, FeeModel

fee_model = FeeModel(
    swap_fee_pct=0.003,
    lp_fee_pct=0.001,
    slippage_pct=0.10,
    network_fee_sol=0.0005,
)

portfolio_config = PortfolioConfig(
    initial_balance_sol=10.0,
    allocation_mode="dynamic",
    percent_per_trade=0.1,
    max_exposure=0.5,
    max_open_positions=10,
    fee_model=fee_model,
    backtest_start=datetime(2024, 6, 1),
    backtest_end=datetime(2024, 7, 1),
)

engine = PortfolioEngine(portfolio_config)
portfolio_result = engine.simulate(all_results, strategy_name="RR_10_20")
```

## Результаты

### PortfolioResult

Содержит:

- **equity_curve**: Список точек `{"timestamp": datetime, "balance": float}` - кривая баланса
- **positions**: Список закрытых позиций (`Position` объекты)
- **stats**: Статистика портфеля (`PortfolioStats`)

### PortfolioStats

- **final_balance_sol**: Финальный баланс в SOL
- **total_return_pct**: Общая доходность в долях
- **max_drawdown_pct**: Максимальная просадка в долях
- **trades_executed**: Количество исполненных сделок
- **trades_skipped_by_risk**: Количество пропущенных сделок из-за лимитов

### Сохраненные файлы

После запуска портфельной симуляции создаются следующие файлы:

- `{strategy_name}_equity_curve.csv` - кривая баланса
- `{strategy_name}_portfolio_positions.csv` - все портфельные позиции
- `{strategy_name}_portfolio_stats.json` - статистика портфеля
- `{strategy_name}_portfolio_equity.png` - график equity curve

## Логика работы

1. **Фильтрация сделок**: Отбираются только сделки с валидными entry_time и exit_time в пределах backtest window
2. **Сортировка**: Сделки сортируются по entry_time
3. **Закрытие позиций**: Перед открытием новой позиции закрываются все позиции, у которых exit_time <= entry_time новой
4. **Проверка лимитов**: 
   - Проверяется количество открытых позиций
   - Проверяется текущая экспозиция
5. **Расчет размера позиции**: На основе allocation_mode и percent_per_trade
6. **Применение комиссий**: Из PnL вычитаются комиссии и проскальзывание
7. **Обновление баланса**: Баланс обновляется при закрытии позиций

## Комиссии и Execution Profiles

### Применение slippage

Slippage применяется к ценам входа и выхода на основе execution profile:

```
effective_entry_price = raw_entry_price * (1 + slippage_entry)
effective_exit_price = raw_exit_price * (1 - slippage_exit)
```

Где `slippage_entry` и `slippage_exit` зависят от:
- Базового проскальзывания (`base_slippage_pct`)
- Multiplier для типа события (`slippage_multipliers[event]`)

### Применение fees

Fees (swap + LP) применяются к нотионалу при входе и выходе:

```
notional_after_fees = notional * (1 - swap_fee_pct - lp_fee_pct)
```

Network fee вычитается отдельно из баланса (при входе и выходе).

### Рекомендуемый workflow

1. **Stage A/B (поиск альфы)**: Используйте `execution_profile: "realistic"`
   - Реалистичные условия для поиска прибыльных стратегий
   - Не фильтрует стратегии слишком агрессивно

2. **Stress testing**: Используйте `execution_profile: "stress"` для топ-N стратегий
   - Проверка устойчивости к экстремальным условиям
   - Фильтрация стратегий, которые работают только в идеальных условиях

3. **CLI переопределение**: `--execution-profile realistic|stress`
   - Переопределяет YAML конфиг для быстрого переключения

## Примеры

### Фиксированный размер позиции

```yaml
portfolio:
  allocation_mode: "fixed"
  percent_per_trade: 0.1  # 10% от начального баланса на каждую сделку
```

### Динамический размер позиции

```yaml
portfolio:
  allocation_mode: "dynamic"
  percent_per_trade: 0.1  # 10% от текущего баланса на каждую сделку
```

### Ограничение экспозиции

```yaml
portfolio:
  max_exposure: 0.5  # Максимум 50% капитала в открытых позициях
  max_open_positions: 5  # Максимум 5 открытых позиций одновременно
```

## Будущие улучшения

- [x] **Portfolio-level reset для Runner** (реализовано)
  - Закрытие всех позиций при достижении порога: `equity >= cycle_start_equity * runner_reset_multiple`
  - Обновление `cycle_start_equity` после reset
  - Отслеживание метрик: `reset_count`, `last_reset_time`, `equity_peak_in_cycle`
- [x] **Runner частичные выходы** (реализовано)
  - Обработка частичного закрытия позиций на разных уровнях TP
  - Применение slippage и fees к каждому частичному выходу
  - Уменьшение `open_notional` и увеличение `balance`
- [ ] Более сложные модели комиссий
- [ ] Учет частичного закрытия позиций
- [ ] Портфельная оптимизация











