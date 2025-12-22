# Портфельный слой

## Обзор

> **⚠️ ВАЖНО:** С декабря 2025 проект работает только с RUNNER. RR/RRD признаны неэффективными и исключены из пайплайна. Они остаются только как legacy-код для обратной совместимости, но не используются в примерах, документации и research pipeline.

Портфельный слой реализован поверх стратегий Runner и обеспечивает:

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

> **⚠️ ВАЖНО:** С декабря 2025 проект работает только с RUNNER. RR/RRD признаны неэффективными и исключены из пайплайна.

Портфельный слой реализован поверх стратегий Runner и обеспечивает:

- Единый баланс в SOL
- Динамическое/фиксированное управление размером позиций
- Учет комиссий (swap, LP, network) и проскальзывания (по умолчанию 10%)
- Ограничения портфеля:
  - Максимальная экспозиция (max_exposure)
  - Максимальное количество открытых позиций (max_open_positions)
- Backtest window (ограничение по датам)
- Equity curve (кривая баланса)
- **Portfolio-level reset (profit):** Закрытие всех позиций при достижении порога equity (market close)
  - Управляется параметрами `profit_reset_enabled` и `profit_reset_multiple`
  - **DEPRECATED:** Старые параметры `runner_reset_enabled` и `runner_reset_multiple` поддерживаются для обратной совместимости, но помечены как deprecated
- **Capacity reset (v1.6):** Закрытие всех позиций при capacity pressure (портфель заполнен, мало закрытий, много отклонений)
  - Все позиции закрываются через market close (ExecutionModel)
  - Marker позиция исключается из `positions_to_force_close` (архитектурный инвариант) и закрывается отдельно
  - Все закрытые позиции получают `closed_by_reset=True`, `reset_reason="capacity"`
  - Marker дополнительно получает `triggered_portfolio_reset=True`
- **Runner-XN reset:** Закрытие всех позиций при достижении позицией XN уровня
  - Управляется параметрами `runner_reset_enabled` и `runner_reset_multiple` (это отдельный функционал, не связанный с profit reset)
- **Runner частичные выходы:** Обработка частичного закрытия позиций на разных уровнях TP
- **Dual reporting (v1.6):** Positions-level и executions-level таблицы для разных целей анализа

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
  profit_reset_enabled: false    # Profit reset (закрытие всех позиций при росте equity портфеля)
  profit_reset_multiple: 2.0     # Множитель для profit reset (например, 2.0 = x2)
  # DEPRECATED: runner_reset_enabled и runner_reset_multiple - используйте profit_reset_* вместо них
  # Оставлено для обратной совместимости со старыми конфигами
  # Capacity reset (v1.6) - предотвращает "capacity choke"
  capacity_reset:
    enabled: true                 # Включить capacity reset
    window_type: "time"          # Тип окна: "time" (по времени) или "signals" (по количеству сигналов)
    window_size: 7d              # Размер окна: дни (например, "7d" или 7) для time, количество сигналов для signals
    max_blocked_ratio: 0.4       # Максимальная доля отклоненных сигналов за окно (0.4 = 40%)
    max_avg_hold_days: 10.0      # Максимальное среднее время удержания открытых позиций (дни)
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
- **percent_per_trade**: Доля капитала на одну сделку (0.1 = 10%, 0.002 = 0.2%)
  - ⚠️ **Важно:** Используется как доля, не делится на 100 (0.002 = 0.2%, не 2%)
- **max_exposure**: Максимальная доля капитала в открытых позициях (0.5 = 50%)
  - **Формула проверки:** `(total_open_notional + new_size) / (total_capital + new_size) <= max_exposure`
  - **В fixed mode:** `total_capital = initial_balance_sol` (размер позиции рассчитывается от начального баланса)
  - **В dynamic mode:** `total_capital = available_balance + total_open_notional` (размер позиции рассчитывается от текущего баланса)
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
- **trades_executed**: Количество открытых позиций (инкрементируется только при ENTRY, не при partial exits)
- **trades_skipped_by_risk**: Количество пропущенных сделок из-за лимитов

### Сохраненные файлы

После запуска портфельной симуляции создаются следующие файлы:

- `{strategy_name}_equity_curve.csv` - кривая баланса
- `{strategy_name}_portfolio_positions.csv` - все портфельные позиции
- `{strategy_name}_portfolio_stats.json` - статистика портфеля
- `{strategy_name}_portfolio_equity.png` - график equity curve
- `portfolio_positions.csv` - агрегированная таблица всех позиций по всем стратегиям (источник правды для Stage A/B)
- `strategy_summary.csv` - агрегированный summary по всем стратегиям (portfolio-derived)

## Reporting Contract (Источник правды)

### portfolio_positions.csv - единственный источник для Stage A/B

**ВАЖНО:** `portfolio_positions.csv` является единственным источником данных для research pipeline (Stage A и Stage B).

**Обязательные колонки:**
- `strategy` - название стратегии
- `signal_id` - идентификатор сигнала
- `contract_address` - адрес контракта
- `entry_time`, `exit_time` - времена входа/выхода (ISO)
- `status` - статус позиции ("open" или "closed")
- `size` - размер позиции в SOL
- `pnl_sol` - портфельный PnL в SOL (обязательно!)
- `fees_total_sol` - суммарные комиссии в SOL
- `exec_entry_price`, `exec_exit_price` - исполненные цены (с slippage)
- `raw_entry_price`, `raw_exit_price` - сырые цены (без slippage)
- `closed_by_reset` - закрыта ли позиция по reset (bool)
- `triggered_portfolio_reset` - триггернула ли portfolio-level reset (bool)
- `reset_reason` - причина reset ("profit"/"capacity"/"runner"/"manual"/"none")
- `hold_minutes` - длительность удержания позиции в минутах
- `max_xn_reached` - максимальный XN достигнутый (из levels_hit или fallback на цены)
- `hit_x2` - достигнут ли XN >= 2.0 (bool)
- `hit_x5` - достигнут ли XN >= 5.0 (bool)

**Расчет max_xn_reached (приоритет источников):**
1. **Runner truth:** `Position.meta["levels_hit"]` - dict вида {"2.0": "...", "7.0": "..."}
   - `max_xn_reached = max(float(k) for k in levels_hit.keys())`
   - Если ключи не парсятся → warning в логах и fallback
2. **Fallback:** ratio цен
   - Сначала пробуем `raw_exit_price / raw_entry_price`
   - Если raw цены недоступны, пробуем `exec_exit_price / exec_entry_price`
   - Иначе `max_xn_reached = None/NaN`

**Расчет hit flags:**
- `hit_x2 = (max_xn_reached is not None and max_xn_reached >= 2.0)`
- `hit_x5 = (max_xn_reached is not None and max_xn_reached >= 5.0)`
- Если `max_xn_reached is None` → оба `False`

**Reset flags contract:**
- Reset flags (`closed_by_reset`, `triggered_portfolio_reset`, `reset_reason`) появляются **только** в `Position.meta` и только на portfolio уровне
- `StrategyOutput.meta` **НЕ содержит** reset flags
- Reset flags записываются в `portfolio_positions.csv` из `Position.meta`

**Запрещено:**
- Использовать executions-level CSV или strategy output для Stage A/B
- Дублировать строки одной позиции из-за partial close (positions-level = агрегат)
- Использовать `StrategyOutput.pnl` для расчета метрик (используется только `pnl_sol` из portfolio_positions)

### strategy_summary.csv - portfolio-derived summary (Runner-only)

**ВАЖНО:** `strategy_summary.csv` считается **ТОЛЬКО** из `portfolio_positions.csv`, а не из StrategyOutput.

**Обязательные поля (Runner-only):**

**Базовые счетчики:**
- `strategy` - название стратегии
- `total_trades` - количество исполненных позиций (= count rows в portfolio_positions)
- `winning_trades`, `losing_trades`, `winrate` - статистика выигрышных/проигрышных сделок
- `positions_total`, `positions_closed`, `positions_open` - счетчики позиций

**PnL и комиссии:**
- `strategy_total_pnl_sol` - суммарный PnL в SOL
- `fees_total_sol` - суммарные комиссии в SOL
- `pnl_net_sol` - чистый PnL (total - fees)
- `avg_pnl_sol`, `median_pnl_sol` - средний и медианный PnL в SOL
- `best_trade_pnl_sol`, `worst_trade_pnl_sol` - лучшая и худшая сделка в SOL

**Return метрики:**
- `initial_balance_sol`, `final_balance_sol`, `portfolio_return_pct` - return метрики (из portfolio_results)

**Hold метрики:**
- `avg_hold_minutes`, `p50_hold_minutes`, `p90_hold_minutes` - метрики удержания

**Runner hits:**
- `hit_rate_x2`, `hit_rate_x5` - hit rates для Runner стратегий (mean hit_x2/hit_x5)

**Reset counts:**
- `profit_reset_closed_count` - количество позиций закрытых по profit reset (reset_reason == "profit")
- `capacity_reset_closed_count` - количество позиций закрытых по capacity reset (reset_reason == "capacity")
- `closed_by_reset_count` - количество позиций закрытых по reset (closed_by_reset == True)
- `triggered_portfolio_reset_count` - количество позиций триггернувших reset (triggered_portfolio_reset == True)

**Единицы измерения:**
- Все PnL метрики в **SOL** (не в процентах или units)
- Все цены в **SOL** (или нативных единицах токена)
- Все времена в **минутах** или **ISO datetime**

### DEBUG-логирование

Для отладки проблем с лимитами портфеля включите DEBUG-логирование:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Перед каждой проверкой risk-check выводится DEBUG-лог с:
- `balance` - текущий баланс
- `position_size` - желаемый размер позиции
- `open_notional` - сумма открытых позиций
- `total_capital` - общий капитал (зависит от allocation_mode)
- `max_allowed_exposure` - максимально допустимая экспозиция
- `allocation_mode`, `percent_per_trade`, `max_exposure` - параметры конфигурации

## Логика работы

### Event-driven симуляция (Time-aware)

Портфельная симуляция использует **event-driven подход** для корректного моделирования одновременного удержания позиций:

1. **Построение событий**: Для каждой сделки создаются два события:
   - **ENTRY событие** в `entry_time` (открытие позиции)
   - **EXIT событие** в `exit_time` (закрытие позиции)
2. **Сортировка событий**: События сортируются по времени (EXIT перед ENTRY на одном timestamp)
3. **Обработка событий по времени**:
   - На каждом timestamp сначала обрабатываются все **EXIT события** (закрытие позиций)
   - Затем обрабатываются все **ENTRY события** (открытие позиций)
   - После обработки всех событий на timestamp проверяется profit reset
4. **Результат**: Позиции реально держатся открытыми между `entry_time` и `exit_time`, что позволяет:
   - Profit reset корректно закрывать все открытые позиции в момент срабатывания
   - Честно моделировать одновременное удержание позиций
   - Корректно учитывать `max_open_positions` и `max_exposure`

### Детальная логика обработки

1. **Фильтрация сделок**: Отбираются только сделки с валидными entry_time и exit_time в пределах backtest window
2. **Построение событий**: Для каждой сделки создаются ENTRY и EXIT события
3. **Сортировка событий**: События сортируются по времени (EXIT перед ENTRY на одном timestamp)
4. **Обработка EXIT событий**: Закрываются позиции, у которых `exit_time <= current_time`
   - Для Runner стратегий обрабатываются partial exits
   - Позиция остается в `open_positions` до полного закрытия
5. **Обработка ENTRY событий**: Открываются новые позиции
   - Проверяется количество открытых позиций (`max_open_positions`)
   - Проверяется текущая экспозиция (`max_exposure`)
   - **Важно:** В fixed mode `total_capital` = `initial_balance_sol` (размер позиции рассчитывается от начального баланса)
   - В dynamic mode `total_capital` = `available_balance + total_open_notional` (размер позиции рассчитывается от текущего баланса)
   - **Расчет размера позиции**: На основе allocation_mode и percent_per_trade
     - `percent_per_trade` используется как доля (0.002 = 0.2%), не делится на 100
     - Fixed mode: `position_size = initial_balance_sol * percent_per_trade`
     - Dynamic mode: `position_size = current_balance * percent_per_trade`
   - **Инкремент trades_executed**: Счетчик увеличивается только при успешном открытии позиции (ENTRY событие)
6. **Проверка profit reset**: После обработки всех событий на timestamp проверяется profit reset
   - Если `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`, закрываются все открытые позиции
7. **Применение комиссий**: Из PnL вычитаются комиссии и проскальзывание
8. **Обновление баланса**: Баланс обновляется при закрытии позиций и partial exits
9. **DEBUG-логирование**: Перед risk-check выводится DEBUG-лог с балансом, размером позиции, открытым нотионалом и максимально допустимой экспозицией

### Подсчет trades_executed

**Важно:** `trades_executed` инкрементируется только при открытии позиции (ENTRY событие), а не при:
- Partial exits (Runner стратегия)
- Финальном закрытии позиции
- Execution events
- Reset close

**Контракт:**
- Один входной трейд → `trades_executed == 1`
- Partial exits не увеличивают `trades_executed`
- Счетчик увеличивается только при реальном открытии позиции (entry исполнен)

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

### Множество мелких позиций (fixed mode)

Для открытия множества мелких позиций используйте fixed mode с маленьким `percent_per_trade`:

```yaml
portfolio:
  initial_balance_sol: 10.0
  allocation_mode: "fixed"  # Размер позиции от начального баланса
  percent_per_trade: 0.002  # 0.2% от начального баланса на сделку
  max_exposure: 0.9  # 90% максимальная экспозиция
  max_open_positions: 100  # До 100 открытых позиций
```

**Расчет:**
- Размер каждой позиции = `10.0 * 0.002 = 0.02 SOL`
- 100 позиций = `100 * 0.02 = 2.0 SOL`
- Экспозиция = `2.0 / 10.0 = 20% < 90%` ✅

**Важно:** В fixed mode `total_capital` = `initial_balance_sol`, что позволяет открывать много позиций без преждевременного ограничения экспозиции.

## Исправления и улучшения

- [x] **Исправление расчета total_capital в fixed mode** (2025-01-XX)
  - В fixed mode `total_capital` теперь равен `initial_balance_sol` вместо `available_balance + total_open_notional`
  - Это позволяет портфелю открывать много мелких позиций (например, 100 позиций при `percent_per_trade=0.002`)
  - Исправлен баг, из-за которого открывалось только ~10 сделок вместо ожидаемых 100
- [x] **DEBUG-логирование перед risk-check** (2025-01-XX)
  - Добавлен DEBUG-лог с балансом, размером позиции, открытым нотионалом, total_capital и max_allowed_exposure
  - Помогает отлаживать проблемы с лимитами портфеля
- [x] **Portfolio-level reset (profit)** (реализовано)
  - Закрытие всех позиций при достижении порога equity: `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`
  - Закрытие происходит **market close** (по текущей цене через execution_model, не pnl=0)
  - Отслеживание метрик: `portfolio_reset_count`, `portfolio_reset_profit_count`, `last_portfolio_reset_time`
- [x] **Capacity reset (v1.6)** (реализовано)
  - Закрытие всех позиций при capacity pressure (портфель заполнен, много отклоненных сигналов, мало закрытий)
  - Независим от profit reset, имеет собственные счетчики: `portfolio_reset_capacity_count`
  - **Архитектурный инвариант:** marker позиция исключается из `positions_to_force_close` и закрывается отдельно через market close
  - Все закрытые позиции получают `closed_by_reset=True`, `reset_reason="capacity"`; marker дополнительно получает `triggered_portfolio_reset=True`
  - Закрытие происходит **market close** (по текущей цене через execution_model)
  - Триггеры: `open_ratio >= capacity_open_ratio_threshold`, `blocked_window >= capacity_blocked_signals_threshold`, `turnover_window <= capacity_min_turnover_threshold`
- [x] **Runner-XN reset** (реализовано)
  - Закрытие всех позиций при достижении XN позицией: `raw_exit_price / raw_entry_price >= runner_reset_multiple`
  - Reset проверяется **только при закрытии позиции** (exit_time), а не при открытии
  - Проверка выполняется по **raw ценам** из StrategyOutput, а не по исполненным (с slippage)
  - При срабатывании reset все открытые позиции закрываются принудительно с `meta["closed_by_reset"]=True`
  - Отслеживание метрик: `runner_reset_count`, `last_runner_reset_time`, `trades_skipped_by_reset`
  - **Важно:** `Position.entry_price` и `Position.exit_price` содержат raw цены, исполненные цены хранятся в `meta["exec_entry_price"]` и `meta["exec_exit_price"]`
- [x] **Dual reporting (v1.6)** (реализовано)
  - **Positions-level:** `portfolio_positions.csv` - агрегат по signal_id+strategy+contract (для Stage A)
  - **Executions-level:** `portfolio_executions.csv` - каждое событие (entry/partial_exit/final_exit/force_close) отдельной строкой (для дебага)
  - Stage A валидирует формат входных данных (отклоняет executions-level CSV)
- [x] **Runner частичные выходы** (реализовано)
  - Обработка частичного закрытия позиций на разных уровнях TP
  - Применение slippage и fees к каждому частичному выходу
  - Уменьшение `open_notional` и увеличение `balance`
- [x] **Unit test для множества мелких позиций** (2025-01-XX)
  - Добавлен тест `test_fixed_allocation_allows_many_small_positions`
  - Проверяет открытие ≥50 сделок при `percent_per_trade=0.002`, `max_open_positions=100`
- [ ] Более сложные модели комиссий
- [ ] Портфельная оптимизация











