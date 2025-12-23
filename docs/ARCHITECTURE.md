# Архитектура проекта Solana Strategy Tester

> **Версия:** 2025-12-XX  
> **⚠️ ВАЖНО:** С декабря 2025 проект работает только с **RUNNER** стратегиями. RR/RRD признаны неэффективными и исключены из пайплайна. Они остаются только как legacy-код для обратной совместимости.

---

## 🏗️ Обзор архитектуры

Проект следует принципам **Clean Architecture** с четким разделением на слои:

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                          │
│  BacktestRunner: orchestrates signals → strategies → portfolio│
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                      Domain Layer                             │
│  Business logic: Strategies, Portfolio, Position, Models     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  Infrastructure Layer                        │
│  I/O: SignalLoader, PriceLoader, Reporter                   │
└─────────────────────────────────────────────────────────────┘
```

**Принципы:**
- **Dependency Inversion**: Domain не зависит от Infrastructure
- **Single Responsibility**: Каждый класс отвечает за одну задачу
- **Open/Closed**: Легко добавлять новые стратегии без изменения существующего кода
- **Separation of Concerns**: Бизнес-логика изолирована от I/O

---

## 📦 Слои архитектуры

### 1. Domain Layer (`backtester/domain/`)

**Назначение:** Бизнес-логика, не зависящая от внешних зависимостей.

#### 1.1 Модели данных (`models.py`)

**Signal** — входной сигнал для торговли:
```python
@dataclass
class Signal:
    id: str
    contract_address: str
    timestamp: datetime  # UTC
    source: str          # e.g. "madapes"
    narrative: str       # e.g. "memecoin"
    extra: Dict[str, Any] = field(default_factory=dict)
```

**Candle** — OHLCV свеча:
```python
@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
```

**StrategyInput** — входные данные для стратегии:
```python
@dataclass
class StrategyInput:
    signal: Signal
    candles: List[Candle]
    global_params: Dict[str, Any]
```

**StrategyOutput** — результат выполнения стратегии:
```python
@dataclass
class StrategyOutput:
    entry_time: Optional[datetime]
    entry_price: Optional[float]
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    pnl: float
    reason: Literal["tp", "sl", "timeout", "no_entry", "error"]
    meta: Dict[str, Any] = field(default_factory=dict)
```

#### 1.2 Стратегии

**Strategy Base** (`strategy_base.py`):
```python
class Strategy(ABC):
    def __init__(self, config: StrategyConfig):
        self.config = config
    
    @abstractmethod
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        ...
```

**Runner Strategy** (`runner_strategy.py`):
- Адаптер между `RunnerLadderEngine` и интерфейсом `Strategy`
- Конвертирует `List[Candle]` → `pd.DataFrame` для ladder engine
- Конвертирует `RunnerTradeResult` → `StrategyOutput`

**Runner Ladder Engine** (`runner_ladder.py`):
- Независимая core-логика симуляции Runner Ladder
- Не зависит от PortfolioEngine
- Работает только с ценами и временем
- Метод `simulate()` возвращает `RunnerTradeResult` с:
  - `levels_hit`: Dict[str, datetime] — когда достигнуты уровни (2.0, 5.0, 10.0)
  - `fractions_exited`: Dict[str, float] — какая доля закрыта на каждом уровне
  - `realized_multiple`: float — средневзвешенный XN

**Runner Config** (`runner_config.py`):
```python
@dataclass
class RunnerTakeProfitLevel:
    xn: float      # e.g. 2.0, 5.0, 10.0
    fraction: float # e.g. 0.4, 0.4, 0.2

@dataclass
class RunnerConfig(StrategyConfig):
    take_profit_levels: List[RunnerTakeProfitLevel]
    time_stop_minutes: Optional[int]
    use_high_for_targets: bool
    exit_on_first_tp: bool
    allow_partial_fills: bool
```

**LEGACY: RR/RRD** (`rr_strategy.py`, `rrd_strategy.py`):
- Помечены как deprecated
- Исключены из research pipeline
- Остаются только для обратной совместимости

#### 1.3 Портфельный слой

**Portfolio Engine** (`portfolio.py`):
- Реалистичная симуляция торговли с учетом:
  - Комиссий (`FeeModel`)
  - Проскальзывания (`ExecutionProfileConfig`)
  - Ограничений портфеля (max positions, position sizing)
- Обрабатывает частичные выходы Runner стратегий
- Реализует portfolio-level reset (закрытие всех позиций при достижении equity threshold)

**Position** (`position.py`):
- Модель позиции с поддержкой частичных выходов
- `meta: Dict[str, Any]` — метаданные (levels_hit, fractions_exited, realized_multiple)

**Portfolio Reset** (`portfolio_reset.py`):
- Логика portfolio-level reset
- Проверка порогов equity
- Закрытие всех позиций через ExecutionModel

**Trade Features** (`trade_features.py`):
- Market cap proxy
- Volume/volatility windows
- Дополнительные фичи для анализа сделок

#### 1.4 Execution Model (`execution_model.py`)

**ExecutionProfileConfig**:
- Моделирование исполнения ордеров
- Проскальзывание (slippage)
- Различные профили исполнения (conservative, aggressive, etc.)

---

### 2. Application Layer (`backtester/application/`)

**BacktestRunner** (`runner.py`):
- Оркестратор всего процесса бэктестинга
- Координирует работу всех компонентов:
  1. Загружает сигналы через `SignalLoader`
  2. Для каждого сигнала:
     - Загружает свечи через `PriceLoader`
     - Создает `StrategyInput`
     - Запускает все стратегии: `strategy.on_signal(input)`
     - Собирает результаты
  3. Запускает портфельную симуляцию: `PortfolioEngine.simulate()`
  4. Сохраняет результаты через `Reporter`

**Особенности:**
- Поддержка параллельной обработки сигналов (`parallel=True`)
- Потокобезопасная статистика обработки
- Дедупликация предупреждений через `WarnDedup`

---

### 3. Infrastructure Layer (`backtester/infrastructure/`)

**SignalLoader** (`signal_loader.py`):
- Интерфейс: `load_signals() -> List[Signal]`
- Реализация: `CsvSignalLoader` — загрузка из CSV

**PriceLoader** (`price_loader.py`):
- Интерфейс: `load_candles(contract, start, end) -> List[Candle]`
- Реализации:
  - `CsvPriceLoader` — загрузка из локальных CSV
  - `GeckoTerminalPriceLoader` — загрузка через GeckoTerminal API

**Reporter** (`reporter.py`):
- Сохранение результатов бэктеста:
  - `portfolio_positions.csv` — positions-level data (source of truth)
  - `strategy_summary.csv` — portfolio-derived summary
  - `portfolio_summary.csv` — aggregated portfolio stats
  - `portfolio_executions.csv` — executions-level data (для дебага)
  - Equity curves, charts, JSON stats

**Ключевые методы:**
- `save_portfolio_positions_table()` — сохраняет `portfolio_positions.csv` с `max_xn_reached`, `hit_x2`, `hit_x5`
- `save_strategy_summary()` — генерирует portfolio-derived summary
- `compute_max_xn_reached()` — вычисляет `max_xn_reached` из `levels_hit` (приоритет) или цен

---

### 4. Research Layer (`backtester/research/`)

**Stage A** (`run_stage_a.py`):
- Window-based stability analysis
- Читает `portfolio_positions.csv` из `--reports-dir`
- Вычисляет Runner метрики через `calculate_runner_metrics()`
- Сохраняет `strategy_stability.csv` с метриками:
  - `hit_rate_x2`, `hit_rate_x5`
  - `p90_hold_days`
  - `tail_contribution`
  - `max_drawdown_pct`

**Strategy Stability** (`strategy_stability.py`):
- `calculate_runner_metrics()` — вычисляет Runner-специфичные метрики
- Использует `max_xn_reached` из `portfolio_positions.csv`
- Вычисляет `tail_contribution` как долю PnL от сделок с `max_xn_reached >= 5.0`

**Window Aggregator** (`window_aggregator.py`):
- Логика агрегации по временным окнам
- Группировка позиций по стратегиям и окнам

**XN Analysis** (`xn_analysis/`):
- Теоретический анализ потенциала роста сигналов
- Генерирует `xn_per_signal.csv` и `xn_summary.csv`

---

### 5. Decision Layer (`backtester/decision/`)

**Stage B** (`run_stage_b.py`):
- Strategy selection by criteria
- Читает `strategy_stability.csv`
- Применяет критерии отбора через `StrategySelector`
- Сохраняет `strategy_selection.csv` с флагом `passed`

**Strategy Selector** (`strategy_selector.py`):
- Автоматически определяет тип стратегии (Runner vs RR/RRD)
- Применяет соответствующие критерии

**Selection Rules** (`selection_rules.py`):
- `DEFAULT_RUNNER_CRITERIA`:
  - `min_hit_rate_x2: 0.30`
  - `min_hit_rate_x5: 0.10`
  - `min_tail_contribution: 0.3`
  - `max_drawdown_pct: -0.5`

---

## 🔄 Поток данных

### Backtest Flow

```
1. main.py
   ↓
2. BacktestRunner.__init__()
   - SignalLoader, PriceLoader, Strategies, Reporter
   ↓
3. BacktestRunner.run()
   - Загружает сигналы
   - Для каждого сигнала:
     - Загружает свечи
     - Запускает стратегии → StrategyOutput[]
   ↓
4. BacktestRunner.run_portfolio()
   - PortfolioEngine.simulate()
   - Обрабатывает StrategyOutput[] → Positions
   - Применяет portfolio-level reset
   ↓
5. Reporter.save_*()
   - portfolio_positions.csv (source of truth)
   - strategy_summary.csv
   - portfolio_summary.csv
```

### Research Pipeline Flow

```
1. main.py → portfolio_positions.csv
   ↓
2. Stage A (run_stage_a.py)
   - Читает portfolio_positions.csv
   - Вычисляет Runner метрики
   - Сохраняет strategy_stability.csv
   ↓
3. Stage B (run_stage_b.py)
   - Читает strategy_stability.csv
   - Применяет критерии отбора
   - Сохраняет strategy_selection.csv
```

---

## 📊 Ключевые контракты

### portfolio_positions.csv (Source of Truth)

**Обязательные колонки:**
- `strategy`, `signal_id`, `contract_address`
- `pnl_sol`, `fees_total_sol`, `hold_minutes`
- `max_xn_reached` — максимальный XN (приоритет: `levels_hit` → raw prices → exec prices)
- `hit_x2`, `hit_x5` — boolean flags
- `closed_by_reset`, `triggered_portfolio_reset`, `reset_reason`

**Расчет `max_xn_reached`:**
1. **Приоритет 1:** `levels_hit` из `Position.meta` (Runner truth)
   - Парсит ключи как float, берет максимум
2. **Приоритет 2:** `raw_exit_price / raw_entry_price` (если доступны)
3. **Приоритет 3:** `exec_exit_price / exec_entry_price` (fallback)

### strategy_summary.csv (Portfolio-Derived)

**Все метрики вычисляются из `portfolio_positions.csv`:**
- `total_trades` — количество позиций
- `strategy_total_pnl_sol` — суммарный PnL
- `best_trade_pnl_sol`, `worst_trade_pnl_sol`
- `winning_trades`, `losing_trades`, `winrate`
- `p50_hold_minutes`, `avg_hold_minutes`
- `closed_by_reset_count`, `triggered_portfolio_reset_count`, `profit_reset_closed_count`

---

## 🎯 Инварианты архитектуры

1. **Runner-only Pipeline:**
   - Stage A/B работают только с Runner стратегиями
   - RR/RRD исключены из research pipeline
   - Все примеры используют только `type: RUNNER`

2. **Единый источник правды:**
   - `portfolio_positions.csv` — единственный источник для Stage A/B
   - Все метрики в `strategy_summary.csv` вычисляются из `portfolio_positions.csv`

3. **Unified Reports Directory:**
   - Все research артефакты сохраняются в `output/reports/`
   - Запрещено сохранять в run-specific dirs

4. **Dependency Direction:**
   - Domain не зависит от Infrastructure
   - Application зависит от Domain и Infrastructure
   - Infrastructure реализует интерфейсы из Domain

---

## 🔧 Расширяемость

### Добавление новой стратегии

1. Создать класс, наследующий `Strategy`
2. Реализовать `on_signal()` → `StrategyOutput`
3. Добавить конфигурацию в `strategy_base.py` (если нужна)
4. Зарегистрировать в `main.py` (если нужна специальная обработка)

### Добавление нового источника данных

1. Реализовать интерфейс `SignalLoader` или `PriceLoader`
2. Использовать в `BacktestRunner`

### Добавление новых метрик

1. Добавить вычисление в `strategy_stability.py`
2. Обновить `strategy_stability.csv` схему
3. Обновить критерии в `selection_rules.py` (если нужно)

---

## 📚 См. также

- [`docs/RESEARCH_PIPELINE.md`](./RESEARCH_PIPELINE.md) — Research pipeline детали
- [`docs/PORTFOLIO_LAYER.md`](./PORTFOLIO_LAYER.md) — Portfolio layer детали
- [`docs/RUNNER_COMPLETE_GUIDE.md`](./RUNNER_COMPLETE_GUIDE.md) — Runner strategy guide
- [`docs/TECHNICAL_REPORT.md`](./TECHNICAL_REPORT.md) — Technical audit

