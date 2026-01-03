# StrategyTrades vs Portfolio Accounting — Feasibility Analysis

## Executive Summary

**Цель:** Разделить стратегию (unit-trades) и портфельный учет (allocation/fees/slippage/capacity/reset) на два независимых слоя.

**Текущее состояние:** Размер позиции (SOL) и влияние на баланс вычисляются на уровне Portfolio, что связывает trade blueprint с портфелем.

**Целевое состояние:** StrategyTrades (unit-trades) генерируются стратегией без учета баланса, Portfolio replay применяет allocation/fees/slippage/capacity/reset.

**Оценка сложности:** Medium (M) для минимально инвазивного подхода), Large (L) для полного рефакторинга.

---

## 1. Current State (AS-IS)

### 1.1 Диаграмма потока данных

```
┌─────────┐
│ Signals │ (CSV)
└────┬────┘
     │
     ▼
┌─────────┐
│ Candles │ (PriceLoader)
└────┬────┘
     │
     ▼
┌──────────────────┐
│ RunnerStrategy   │ → StrategyOutput (с meta: levels_hit, fractions_exited, realized_multiple)
│ .on_signal()     │   НО: нет size в SOL, нет allocation, нет fees/slippage
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│ PortfolioEngine  │ → вычисляет size в SOL (здесь!)
│ .simulate()      │ → применяет allocation_mode (fixed/dynamic)
│                  │ → проверяет capacity (max_exposure, max_open_positions)
│                  │ → применяет fees/slippage через ExecutionModel
│                  │ → создает Position с size в SOL
│                  │ → эмитит Events (POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED)
│                  │ → создает Executions (fills ledger)
└────┬─────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│ CSV Exports                             │
│ - portfolio_positions.csv               │
│ - portfolio_events.csv                  │
│ - portfolio_executions.csv              │
└────┬────────────────────────────────────┘
     │
     ▼
┌─────────┐
│  Audit  │ → проверяет инварианты (P0/P1/P2)
└────┬────┘
     │
     ▼
┌─────────┐
│ Stage A │ → анализ устойчивости
└────┬────┘
     │
     ▼
┌─────────┐
│ Stage B │ → отбор стратегий
└─────────┘
```

### 1.2 Где вычисляется size в SOL

**Место:** `PortfolioEngine._process_position_entry()` (строка ~1650-1700)

**Логика:**

```python
# 1. Вычисление желаемого размера
desired_size = self._position_size(available_balance)
# где _position_size() = base * percent_per_trade
# base = initial_balance_sol (fixed) или current_balance (dynamic)

# 2. Проверка capacity constraints
total_open_notional = sum(p.size for p in state.open_positions)
total_capital = available_balance + total_open_notional  # dynamic mode
max_allowed_notional = (max_exposure * total_capital - total_open_notional) / (1 - max_exposure)

# 3. Ограничение размера
if desired_size > max_allowed_notional:
    blocked_by_capacity = True
    return None  # Сигнал отклонен

# 4. Создание Position с size в SOL
pos = PositionModel(
    size=desired_size,  # ← здесь size в SOL
    ...
)
```

**Проблема:** Size зависит от текущего баланса портфеля, что делает trade blueprint зависимым от портфеля.

### 1.3 Текущие поля в Position.meta

**Что есть:**

- `levels_hit`: `{xn: hit_time_iso}` — когда достигнут каждый уровень
- `fractions_exited`: `{xn: fraction}` — какая доля закрыта на каждом уровне
- `realized_multiple`: суммарный multiple = Σ(fraction × xn)
- `partial_exits`: список словарей с информацией о частичных выходах:
  ```python
  {
      "xn": 2.0,
      "hit_time": "2025-01-15T10:00:00",
      "exit_size": 4.0,  # в SOL
      "exit_price": 2.1,  # exec_price (с slippage)
      "pnl_sol": 4.4,
      "fees_sol": 0.01,
      "network_fee_sol": 0.0005,
      "event_id": "evt_001"
  }
  ```
- `entry_mcap_proxy`: marketcap на момент входа (из StrategyOutput.meta)
- `mcap_usd`, `mcap_usd_at_entry`: для capacity prune

**Чего не хватает:**

- ❌ `partial_exits[].raw_price`: сырая цена (без slippage) для каждого partial exit
- ❌ `partial_exits[].marketcap_proxy`: marketcap на момент каждого partial exit
- ❌ `final_exit.raw_price`: сырая цена финального закрытия (time_stop)
- ❌ `final_exit.marketcap_proxy`: marketcap на момент финального закрытия
- ❌ Явные времена для каждого partial exit (есть `hit_time`, но нет гарантии монотонности)

### 1.4 Текущие поля в Events

**Что есть:**

- `POSITION_OPENED`: `meta.size` (в SOL), `meta.exec_entry_price`
- `POSITION_PARTIAL_EXIT`: `meta.xn`, `meta.fraction`, `meta.exit_price` (exec_price), `meta.pnl_sol`, но нет `raw_price` и `marketcap_proxy`
- `POSITION_CLOSED`: `meta.exec_exit_price`, но нет `raw_exit_price` и `marketcap_proxy`

**Чего не хватает:**

- ❌ `raw_price` для каждого partial exit в `POSITION_PARTIAL_EXIT`
- ❌ `marketcap_proxy` для каждого partial exit
- ❌ `raw_exit_price` для `POSITION_CLOSED`
- ❌ `marketcap_proxy` для `POSITION_CLOSED`

### 1.5 Текущие поля в Executions

**Что есть:**

- `raw_price`: сырая цена (НО только для entry, для partial exits вычисляется обратно из exec_price)
- `exec_price`: исполненная цена (с slippage)
- `pnl_sol_delta`: изменение PnL для этого события
- `xn`, `fraction`: для partial exits

**Чего не хватает:**

- ❌ `marketcap_proxy`: marketcap на момент каждого execution
- ❌ Гарантия, что `raw_price` для partial exits корректный (сейчас вычисляется обратно)

---

## 2. Target State (TO-BE)

### 2.1 Новый артефакт: StrategyTradeBlueprint

**Определение:**

```python
@dataclass
class StrategyTradeBlueprint:
    """
    Unit-trade blueprint, генерируемый стратегией без учета портфеля.
    Не содержит size в SOL, fees, slippage - только логику стратегии.
    """
    # Идентификаторы
    signal_id: str
    strategy_id: str  # название стратегии
    contract_address: str
    
    # Entry
    entry_time: datetime
    entry_price_raw: float  # сырая цена (без slippage)
    entry_mcap_proxy: Optional[float] = None  # marketcap на момент входа
    
    # Partial exits (ladder TP)
    partial_exits: List[PartialExitBlueprint] = field(default_factory=list)
    
    # Final exit
    final_exit: Optional[FinalExitBlueprint] = None
    
    # Агрегированные метрики
    realized_multiple: float  # Σ(fraction_i × xn_i)
    max_xn_reached: Optional[float] = None  # максимальный достигнутый XN
    time_stop_minutes_used: Optional[int] = None  # сколько минут использовано до time_stop
    
    # Причина завершения
    reason: str  # "ladder_tp", "time_stop", "no_entry", "error"


@dataclass
class PartialExitBlueprint:
    """Blueprint для частичного выхода."""
    time: datetime  # когда достигнут уровень
    xn: float  # целевой multiple (2.0, 5.0, 10.0)
    fraction: float  # доля позиции (0.4, 0.4, 0.2)
    raw_price: float  # сырая цена (entry_price * xn)
    marketcap_proxy: Optional[float] = None  # marketcap на момент выхода


@dataclass
class FinalExitBlueprint:
    """Blueprint для финального закрытия."""
    time: datetime  # время закрытия
    raw_price: float  # сырая цена (market close)
    reason: str  # "time_stop", "ladder_tp" (все уровни достигнуты)
    marketcap_proxy: Optional[float] = None  # marketcap на момент закрытия
```

**Где генерируется:**

- `RunnerStrategy.on_signal()` → возвращает `StrategyTradeBlueprint` вместо `StrategyOutput`
- Или: `RunnerStrategy.on_signal()` → `StrategyOutput` → конвертер → `StrategyTradeBlueprint`

### 2.2 Как Portfolio превращает blueprint в Position/Events/Executions

**Процесс:**

```
StrategyTradeBlueprint
    ↓
PortfolioReplay.apply_allocation()
    → вычисляет size в SOL (allocation_mode, percent_per_trade, max_exposure)
    → проверяет capacity constraints
    → создает Position с size
    ↓
PortfolioReplay.apply_fees_slippage()
    → применяет slippage к entry_price_raw → exec_entry_price
    → применяет slippage к partial_exits[].raw_price → exec_price
    → применяет slippage к final_exit.raw_price → exec_exit_price
    → вычисляет fees (swap + LP + network)
    ↓
PortfolioReplay.create_executions()
    → создает entry execution (qty_delta = size, exec_price, fees)
    → создает partial exit executions (qty_delta = -exit_size, exec_price, fees, pnl_sol_delta)
    → создает final exit execution (qty_delta = -remaining_size, exec_price, fees, pnl_sol_delta)
    ↓
PortfolioReplay.create_events()
    → эмитит POSITION_OPENED
    → эмитит POSITION_PARTIAL_EXIT для каждого partial exit
    → эмитит POSITION_CLOSED
    ↓
Position / Events / Executions (как сейчас)
```

**Source of truth:**

- **StrategyTradeBlueprint**: source of truth для логики стратегии (когда, на каком уровне, какая доля)
- **Position.meta.partial_exits**: source of truth для портфельного PnL (pnl_sol_delta, fees)
- **Events**: source of truth для канонических событий портфеля
- **Executions**: source of truth для fills ledger

**Формулы:**

```python
# Entry execution
exec_entry_price = entry_price_raw * (1 + slippage_entry)
qty_delta = size  # в SOL
fees_entry = network_fee + (size * swap_fee_pct) + (size * lp_fee_pct)

# Partial exit execution
exec_price = partial_exit.raw_price * (1 - slippage_exit)
exit_size = size * partial_exit.fraction
qty_delta = -exit_size
pnl_sol_delta = exit_size * ((exec_price - exec_entry_price) / exec_entry_price)
fees_exit = network_fee + (notional_returned * swap_fee_pct) + (notional_returned * lp_fee_pct)

# Final exit execution
exec_exit_price = final_exit.raw_price * (1 - slippage_exit)
remaining_size = size - sum(partial_exits[].exit_size)
qty_delta = -remaining_size
pnl_sol_delta = remaining_size * ((exec_exit_price - exec_entry_price) / exec_entry_price)
fees_exit = network_fee + (notional_returned * swap_fee_pct) + (notional_returned * lp_fee_pct)

# Итоговый pnl_sol
total_pnl_sol = sum(executions[].pnl_sol_delta) - sum(executions[].fees_sol)
```

---

## 3. Options (миграционные стратегии)

### Option A: Minimal Invasive

**Суть:** Добавить недостающие поля в текущие `meta`/`events`/`executions`, НЕ вводя отдельный артефакт `StrategyTradeBlueprint`.

**Изменения:**

1. **В `RunnerStrategy.on_signal()`:**
   - Вычислять `marketcap_proxy` для каждого partial exit
   - Сохранять `raw_price` для каждого partial exit (сейчас вычисляется обратно)
   - Сохранять `raw_exit_price` для final exit

2. **В `PortfolioEngine._process_runner_partial_exits()`:**
   - Сохранять `raw_price` в `partial_exits[]` (сейчас только `exit_price` = exec_price)
   - Сохранять `marketcap_proxy` в `partial_exits[]`

3. **В `PortfolioEvent.create_position_partial_exit()`:**
   - Добавить `raw_price` и `marketcap_proxy` в `meta`

4. **В `PortfolioEvent.create_position_closed()`:**
   - Добавить `raw_exit_price` и `marketcap_proxy` в `meta`

5. **В `Reporter.save_portfolio_executions_table()`:**
   - Сохранять `marketcap_proxy` для каждого execution

**Плюсы:**

- ✅ Минимальные изменения в коде
- ✅ Обратная совместимость (старые поля остаются)
- ✅ Низкий риск для audit/stage A/B (не меняется структура данных)
- ✅ Можно внедрить постепенно (feature flag не обязателен)

**Минусы:**

- ❌ Не решает основную проблему: size в SOL все еще вычисляется в Portfolio
- ❌ Strategy все еще зависит от Portfolio (нужно знать, когда применять fees/slippage)
- ❌ Нет четкого разделения между strategy logic и portfolio accounting

**Риски:**

- 🟡 **Audit:** Низкий риск (добавляются только новые поля)
- 🟡 **Stage A/B:** Низкий риск (используют существующие поля)
- 🟡 **Reporting:** Низкий риск (можно добавить новые колонки опционально)

**Оценка сложности:** Small (S) — 2-3 дня

**Затронутые модули:**

- `backtester/domain/runner_strategy.py` — вычисление marketcap_proxy для partial exits
- `backtester/domain/portfolio.py` — сохранение raw_price и marketcap_proxy
- `backtester/domain/portfolio_events.py` — добавление полей в meta
- `backtester/infrastructure/reporter.py` — экспорт новых полей в CSV

### Option B: Full Refactor

**Суть:** Внедрить `StrategyTradeBlueprint` как отдельный слой и сделать `PortfolioReplay`.

**Изменения:**

1. **Новый модуль `backtester/domain/strategy_trade_blueprint.py`:**
   - Классы `StrategyTradeBlueprint`, `PartialExitBlueprint`, `FinalExitBlueprint`

2. **Изменение `RunnerStrategy.on_signal()`:**
   - Возвращает `StrategyTradeBlueprint` вместо `StrategyOutput`
   - Или: конвертер `StrategyOutput` → `StrategyTradeBlueprint`

3. **Новый модуль `backtester/domain/portfolio_replay.py`:**
   - Класс `PortfolioReplay` с методами:
     - `apply_allocation(blueprint, state) -> Position`
     - `apply_fees_slippage(blueprint, position) -> Position`
     - `create_executions(blueprint, position) -> List[Execution]`
     - `create_events(blueprint, position, executions) -> List[PortfolioEvent]`

4. **Изменение `PortfolioEngine.simulate()`:**
   - Принимает `List[StrategyTradeBlueprint]` вместо `List[Dict[str, Any]]`
   - Использует `PortfolioReplay` для преобразования blueprints в positions/events/executions

5. **Изменение `BacktestRunner.run()`:**
   - Собирает `List[StrategyTradeBlueprint]` вместо `List[Dict[str, Any]]`
   - Передает blueprints в `PortfolioEngine.simulate()`

**Плюсы:**

- ✅ Четкое разделение ответственности: strategy logic vs portfolio accounting
- ✅ Strategy не зависит от Portfolio (можно тестировать отдельно)
- ✅ Можно генерировать blueprints один раз и применять разные portfolio configs
- ✅ Легче добавлять новые стратегии (не нужно знать про portfolio)

**Минусы:**

- ❌ Большие изменения в коде (много файлов)
- ❌ Риск сломать существующие тесты
- ❌ Нужна миграция существующих данных (если есть)
- ❌ Дольше внедрять (нужен feature flag)

**Риски:**

- 🔴 **Audit:** Средний риск (может измениться структура данных, нужны тесты)
- 🔴 **Stage A/B:** Средний риск (зависит от того, как изменится `portfolio_positions.csv`)
- 🟡 **Reporting:** Низкий риск (можно сохранить совместимость формата CSV)

**Оценка сложности:** Large (L) — 2-3 недели

**Затронутые модули:**

- `backtester/domain/strategy_trade_blueprint.py` — новый модуль
- `backtester/domain/portfolio_replay.py` — новый модуль
- `backtester/domain/runner_strategy.py` — изменение возвращаемого типа
- `backtester/domain/portfolio.py` — рефакторинг `simulate()` и `_process_position_entry()`
- `backtester/application/runner.py` — изменение `run()` и `run_portfolio()`
- `backtester/infrastructure/reporter.py` — возможно, изменения в экспорте
- Все тесты, которые используют `StrategyOutput` или `PortfolioEngine`

---

## 4. Time Triggers / time_stop_minutes

### 4.1 Текущее состояние

**Где задается:** `RunnerConfig.time_stop_minutes` (на уровне стратегии)

**Как используется:** `RunnerLadderEngine` проверяет `time_stop_time = entry_time + time_stop_minutes` и закрывает остаток позиции при достижении.

**Проблема:** Нет портфельного ограничения на время удержания (может быть полезно для capacity management).

### 4.2 Предложение: Двухуровневое ограничение

**Идея:** Сохранить `time_stop_minutes` как часть стратегии, но добавить `portfolio.max_hold_minutes` как верхнее ограничение.

**Реализация:**

```python
# В RunnerLadderEngine.simulate()
strategy_time_stop = config.time_stop_minutes
portfolio_time_stop = portfolio_config.max_hold_minutes if portfolio_config.max_hold_minutes else None

effective_time_stop = min(
    strategy_time_stop,
    portfolio_time_stop
) if portfolio_time_stop else strategy_time_stop

time_stop_time = entry_time + timedelta(minutes=effective_time_stop)
```

**Плюсы:**

- ✅ Гибкость: стратегия может иметь свой time_stop, но портфель может ограничить
- ✅ Обратная совместимость: если `max_hold_minutes` не задан, используется стратегия
- ✅ Полезно для capacity management (закрывать старые позиции)

**Минусы:**

- ❌ Может изменить поведение стратегии (если portfolio ограничивает сильнее)
- ❌ Нужно документировать, какой time_stop использован (strategy или portfolio)

### 4.3 Альтернатива: Полное удаление time_stop из стратегии

**Идея:** Убрать `time_stop_minutes` из `RunnerConfig`, оставить только на уровне портфеля.

**Плюсы:**

- ✅ Единое место управления (portfolio config)
- ✅ Проще логика (нет двух источников truth)

**Минусы:**

- ❌ Меняет контракт стратегии (breaking change)
- ❌ Менее гибко (нельзя иметь разные time_stop для разных стратегий)

**Рекомендация:** Использовать двухуровневое ограничение (предложение 4.2).

---

## 5. Tests Impact

### 5.1 Тесты, которые можно удалить/перенести

**Удалить (если Option B):**

- Тесты, которые проверяют вычисление `size` в SOL на уровне стратегии (таких нет, size всегда в Portfolio)
- Тесты, которые проверяют применение fees/slippage в стратегии (это должно быть в PortfolioReplay)

**Перенести в strategy-layer (если Option B):**

- `test_runner_ladder_levels_hit()` → тест `StrategyTradeBlueprint.partial_exits`
- `test_runner_ladder_fractions_exited()` → тест `StrategyTradeBlueprint.partial_exits`
- `test_runner_ladder_realized_multiple()` → тест `StrategyTradeBlueprint.realized_multiple`

### 5.2 Тесты, которые обязательно сохранить

**Критичные тесты (не трогать):**

1. **`test_events_executions_linkage()`** — проверяет, что каждое событие имеет execution
2. **`test_pnl_source_of_truth()`** — проверяет, что `pnl_sol` в positions = сумма `pnl_sol_delta` из executions
3. **`test_reset_chain()`** — проверяет цепочку событий при reset
4. **`test_positions_events_consistency()`** — проверяет, что позиция закрыта → есть событие закрытия

**Где находятся:**

- `tests/audit/test_invariants.py` (если есть)
- `tests/portfolio/test_portfolio_*.py`

### 5.3 Новые тесты для StrategyTradeBlueprint

**Если Option B:**

```python
def test_strategy_trade_blueprint_partial_exits_timestamps_monotonic():
    """
    Проверяет, что timestamps partial exits монотонно возрастают.
    """
    blueprint = StrategyTradeBlueprint(
        signal_id="sig_001",
        strategy_id="Runner_v1",
        contract_address="0x123",
        entry_time=datetime(2025, 1, 15, 10, 0, 0),
        entry_price_raw=1.0,
        partial_exits=[
            PartialExitBlueprint(
                time=datetime(2025, 1, 15, 10, 30, 0),
                xn=2.0,
                fraction=0.4,
                raw_price=2.0,
            ),
            PartialExitBlueprint(
                time=datetime(2025, 1, 15, 11, 0, 0),
                xn=5.0,
                fraction=0.4,
                raw_price=5.0,
            ),
        ],
        realized_multiple=3.0,
    )
    
    timestamps = [exit.time for exit in blueprint.partial_exits]
    assert timestamps == sorted(timestamps), "Partial exit timestamps must be monotonic"


def test_strategy_trade_blueprint_realized_multiple_formula():
    """
    Проверяет формулу realized_multiple = Σ(fraction × xn).
    """
    blueprint = StrategyTradeBlueprint(
        signal_id="sig_001",
        strategy_id="Runner_v1",
        contract_address="0x123",
        entry_time=datetime(2025, 1, 15, 10, 0, 0),
        entry_price_raw=1.0,
        partial_exits=[
            PartialExitBlueprint(xn=2.0, fraction=0.4, ...),
            PartialExitBlueprint(xn=5.0, fraction=0.4, ...),
            PartialExitBlueprint(xn=10.0, fraction=0.2, ...),
        ],
        realized_multiple=4.0,  # 0.4*2 + 0.4*5 + 0.2*10 = 0.8 + 2.0 + 2.0 = 4.8
    )
    
    expected = sum(exit.fraction * exit.xn for exit in blueprint.partial_exits)
    assert abs(blueprint.realized_multiple - expected) < 1e-6, \
        f"realized_multiple mismatch: expected {expected}, got {blueprint.realized_multiple}"


def test_strategy_trade_blueprint_marketcap_proxy_consistency():
    """
    Проверяет, что marketcap_proxy вычисляется консистентно на entry и exit.
    """
    blueprint = StrategyTradeBlueprint(
        signal_id="sig_001",
        strategy_id="Runner_v1",
        contract_address="0x123",
        entry_time=datetime(2025, 1, 15, 10, 0, 0),
        entry_price_raw=1.0,
        entry_mcap_proxy=10000.0,
        partial_exits=[
            PartialExitBlueprint(
                time=datetime(2025, 1, 15, 10, 30, 0),
                xn=2.0,
                fraction=0.4,
                raw_price=2.0,
                marketcap_proxy=20000.0,  # должно быть entry_mcap * (raw_price / entry_price)
            ),
        ],
    )
    
    # Проверяем, что marketcap_proxy для partial exit = entry_mcap * (raw_price / entry_price)
    for exit in blueprint.partial_exits:
        expected_mcap = blueprint.entry_mcap_proxy * (exit.raw_price / blueprint.entry_price_raw)
        assert abs(exit.marketcap_proxy - expected_mcap) < 1e-6, \
            f"marketcap_proxy mismatch for exit at {exit.time}"
```

**Если Option A:**

- Тесты для новых полей (`raw_price`, `marketcap_proxy`) в `partial_exits` и `final_exit`
- Тесты для экспорта новых полей в CSV

---

## 6. Rollout Plan

### 6.1 Option A: Minimal Invasive (рекомендуется)

**Шаг 1: Добавить вычисление marketcap_proxy для partial exits**

- Файл: `backtester/domain/runner_strategy.py`
- Изменение: В `_ladder_result_to_strategy_output()` вычислять `marketcap_proxy` для каждого уровня
- Тесты: `test_runner_strategy_partial_exits_marketcap_proxy()`
- Коммит: `feat: add marketcap_proxy to partial exits in runner strategy`

**Шаг 2: Сохранить raw_price в partial_exits**

- Файл: `backtester/domain/portfolio.py`
- Изменение: В `_process_runner_partial_exits()` сохранять `raw_price = entry_price * xn`
- Тесты: `test_portfolio_partial_exits_raw_price()`
- Коммит: `feat: store raw_price in partial_exits meta`

**Шаг 3: Добавить raw_price и marketcap_proxy в Events**

- Файл: `backtester/domain/portfolio_events.py`
- Изменение: В `create_position_partial_exit()` и `create_position_closed()` добавить поля в `meta`
- Тесты: `test_portfolio_events_raw_price_fields()`
- Коммит: `feat: add raw_price and marketcap_proxy to portfolio events`

**Шаг 4: Экспорт новых полей в CSV**

- Файл: `backtester/infrastructure/reporter.py`
- Изменение: В `save_portfolio_executions_table()` добавить колонки `raw_price` и `marketcap_proxy`
- Тесты: `test_reporter_executions_raw_price_export()`
- Коммит: `feat: export raw_price and marketcap_proxy in executions CSV`

**Шаг 5: Обновить документацию**

- Файл: `docs/DATA_PIPELINE_RUNNER_ONLY.md`
- Изменение: Добавить описание новых полей
- Коммит: `docs: update pipeline guide with raw_price and marketcap_proxy fields`

**Feature flag:** Не требуется (обратная совместимость сохранена)

**Сравнение результатов:** Можно сравнить старые и новые CSV на одинаковых входных данных (новые поля просто добавятся, старые останутся).

### 6.2 Option B: Full Refactor

**Шаг 1: Создать StrategyTradeBlueprint (без использования)**

- Файл: `backtester/domain/strategy_trade_blueprint.py` (новый)
- Изменение: Определить классы `StrategyTradeBlueprint`, `PartialExitBlueprint`, `FinalExitBlueprint`
- Тесты: `test_strategy_trade_blueprint_*.py` (новые)
- Коммит: `feat: add StrategyTradeBlueprint data model`

**Шаг 2: Изменить RunnerStrategy для генерации blueprints (feature flag)**

- Файл: `backtester/domain/runner_strategy.py`
- Изменение: Добавить метод `on_signal_blueprint()` который возвращает `StrategyTradeBlueprint`
- Feature flag: `generate_strategy_trades=true` в config
- Тесты: `test_runner_strategy_blueprint_generation()`
- Коммит: `feat: add blueprint generation in RunnerStrategy (feature flag)`

**Шаг 3: Создать PortfolioReplay (без использования)**

- Файл: `backtester/domain/portfolio_replay.py` (новый)
- Изменение: Реализовать класс `PortfolioReplay` с методами `apply_allocation()`, `apply_fees_slippage()`, `create_executions()`, `create_events()`
- Тесты: `test_portfolio_replay_*.py` (новые)
- Коммит: `feat: add PortfolioReplay for blueprint to position conversion`

**Шаг 4: Интегрировать PortfolioReplay в PortfolioEngine (feature flag)**

- Файл: `backtester/domain/portfolio.py`
- Изменение: Добавить метод `simulate_from_blueprints()` который использует `PortfolioReplay`
- Feature flag: `use_portfolio_replay=true` в config
- Тесты: `test_portfolio_engine_blueprint_mode()`
- Коммит: `feat: integrate PortfolioReplay into PortfolioEngine (feature flag)`

**Шаг 5: Изменить BacktestRunner для поддержки blueprints (feature flag)**

- Файл: `backtester/application/runner.py`
- Изменение: Добавить метод `run_blueprints()` который собирает `List[StrategyTradeBlueprint]`
- Feature flag: `use_blueprints=true` в config
- Тесты: `test_backtest_runner_blueprint_mode()`
- Коммит: `feat: add blueprint mode to BacktestRunner (feature flag)`

**Шаг 6: Сравнение результатов старого и нового пайплайна**

- Скрипт: `scripts/compare_old_vs_new_pipeline.py` (новый)
- Логика: Запустить оба пайплайна на одинаковых входных данных, сравнить `portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv`
- Коммит: `feat: add comparison script for old vs new pipeline`

**Шаг 7: Включить новый пайплайн по умолчанию (после проверки)**

- Файлы: `backtester/application/runner.py`, `backtester/domain/portfolio.py`
- Изменение: Установить `use_blueprints=True` по умолчанию
- Тесты: Запустить все существующие тесты
- Коммит: `feat: enable blueprint mode by default`

**Шаг 8: Удалить старый код (после стабилизации)**

- Файлы: Все затронутые модули
- Изменение: Удалить старую логику, оставить только blueprint mode
- Тесты: Обновить тесты для использования blueprints
- Коммит: `refactor: remove legacy portfolio simulation code`

**Feature flag:** `use_blueprints=true/false` в config

**Сравнение результатов:** Скрипт `compare_old_vs_new_pipeline.py` сравнивает CSV файлы построчно.

---

## 7. Рекомендации

### 7.1 Выбор опции

**Рекомендация: Option A (Minimal Invasive)**

**Причины:**

1. ✅ Низкий риск для существующей функциональности
2. ✅ Быстрое внедрение (2-3 дня)
3. ✅ Обратная совместимость
4. ✅ Решает проблему недостающих полей (raw_price, marketcap_proxy)

**Когда выбрать Option B:**

- Если планируется поддержка множественных portfolio configs для одних и тех же blueprints
- Если нужна полная независимость стратегии от портфеля
- Если есть время на полный рефакторинг (2-3 недели)

### 7.2 Time Stop

**Рекомендация:** Двухуровневое ограничение (strategy + portfolio)

**Причины:**

- ✅ Гибкость (стратегия может иметь свой time_stop, но портфель может ограничить)
- ✅ Обратная совместимость
- ✅ Полезно для capacity management

### 7.3 Приоритеты

1. **Высокий:** Добавить `raw_price` и `marketcap_proxy` в partial exits (Option A, шаги 1-3)
2. **Средний:** Двухуровневое ограничение time_stop
3. **Низкий:** Полный рефакторинг (Option B) — только если есть бизнес-требование

---

## 8. TODO Checklist

### Option A: Minimal Invasive

- [ ] **Шаг 1:** Добавить вычисление `marketcap_proxy` для partial exits в `RunnerStrategy`
  - [ ] Изменить `_ladder_result_to_strategy_output()`
  - [ ] Добавить тест `test_runner_strategy_partial_exits_marketcap_proxy()`
  - [ ] Коммит: `feat: add marketcap_proxy to partial exits in runner strategy`

- [ ] **Шаг 2:** Сохранить `raw_price` в `partial_exits` meta
  - [ ] Изменить `_process_runner_partial_exits()` в `portfolio.py`
  - [ ] Добавить тест `test_portfolio_partial_exits_raw_price()`
  - [ ] Коммит: `feat: store raw_price in partial_exits meta`

- [ ] **Шаг 3:** Добавить `raw_price` и `marketcap_proxy` в Events
  - [ ] Изменить `create_position_partial_exit()` в `portfolio_events.py`
  - [ ] Изменить `create_position_closed()` в `portfolio_events.py`
  - [ ] Добавить тест `test_portfolio_events_raw_price_fields()`
  - [ ] Коммит: `feat: add raw_price and marketcap_proxy to portfolio events`

- [ ] **Шаг 4:** Экспорт новых полей в CSV
  - [ ] Изменить `save_portfolio_executions_table()` в `reporter.py`
  - [ ] Добавить колонки `raw_price` и `marketcap_proxy`
  - [ ] Добавить тест `test_reporter_executions_raw_price_export()`
  - [ ] Коммит: `feat: export raw_price and marketcap_proxy in executions CSV`

- [ ] **Шаг 5:** Обновить документацию
  - [ ] Обновить `docs/DATA_PIPELINE_RUNNER_ONLY.md`
  - [ ] Добавить описание новых полей
  - [ ] Коммит: `docs: update pipeline guide with raw_price and marketcap_proxy fields`

### Option B: Full Refactor (если выбран)

- [ ] **Шаг 1:** Создать `StrategyTradeBlueprint` data model
  - [ ] Создать `backtester/domain/strategy_trade_blueprint.py`
  - [ ] Определить классы `StrategyTradeBlueprint`, `PartialExitBlueprint`, `FinalExitBlueprint`
  - [ ] Добавить тесты `test_strategy_trade_blueprint_*.py`
  - [ ] Коммит: `feat: add StrategyTradeBlueprint data model`

- [ ] **Шаг 2:** Изменить `RunnerStrategy` для генерации blueprints
  - [ ] Добавить метод `on_signal_blueprint()` в `RunnerStrategy`
  - [ ] Добавить feature flag `generate_strategy_trades`
  - [ ] Добавить тест `test_runner_strategy_blueprint_generation()`
  - [ ] Коммит: `feat: add blueprint generation in RunnerStrategy (feature flag)`

- [ ] **Шаг 3:** Создать `PortfolioReplay`
  - [ ] Создать `backtester/domain/portfolio_replay.py`
  - [ ] Реализовать методы `apply_allocation()`, `apply_fees_slippage()`, `create_executions()`, `create_events()`
  - [ ] Добавить тесты `test_portfolio_replay_*.py`
  - [ ] Коммит: `feat: add PortfolioReplay for blueprint to position conversion`

- [ ] **Шаг 4:** Интегрировать `PortfolioReplay` в `PortfolioEngine`
  - [ ] Добавить метод `simulate_from_blueprints()` в `PortfolioEngine`
  - [ ] Добавить feature flag `use_portfolio_replay`
  - [ ] Добавить тест `test_portfolio_engine_blueprint_mode()`
  - [ ] Коммит: `feat: integrate PortfolioReplay into PortfolioEngine (feature flag)`

- [ ] **Шаг 5:** Изменить `BacktestRunner` для поддержки blueprints
  - [ ] Добавить метод `run_blueprints()` в `BacktestRunner`
  - [ ] Добавить feature flag `use_blueprints`
  - [ ] Добавить тест `test_backtest_runner_blueprint_mode()`
  - [ ] Коммит: `feat: add blueprint mode to BacktestRunner (feature flag)`

- [ ] **Шаг 6:** Создать скрипт сравнения результатов
  - [ ] Создать `scripts/compare_old_vs_new_pipeline.py`
  - [ ] Реализовать сравнение CSV файлов
  - [ ] Коммит: `feat: add comparison script for old vs new pipeline`

- [ ] **Шаг 7:** Включить новый пайплайн по умолчанию
  - [ ] Установить `use_blueprints=True` по умолчанию
  - [ ] Запустить все тесты
  - [ ] Коммит: `feat: enable blueprint mode by default`

- [ ] **Шаг 8:** Удалить старый код
  - [ ] Удалить старую логику из `PortfolioEngine`
  - [ ] Обновить тесты
  - [ ] Коммит: `refactor: remove legacy portfolio simulation code`

### Time Stop (опционально)

- [ ] Добавить `max_hold_minutes` в `PortfolioConfig`
- [ ] Изменить `RunnerLadderEngine.simulate()` для использования `min(strategy_time_stop, portfolio_time_stop)`
- [ ] Добавить тест `test_runner_ladder_effective_time_stop()`
- [ ] Коммит: `feat: add portfolio-level max_hold_minutes constraint`

---

## 9. Заключение

**Рекомендуемый подход:** Option A (Minimal Invasive) с добавлением недостающих полей (`raw_price`, `marketcap_proxy`) в существующие структуры данных.

**Обоснование:**

1. Решает проблему недостающих полей без больших изменений
2. Низкий риск для существующей функциональности
3. Быстрое внедрение (2-3 дня)
4. Обратная совместимость сохранена

**Option B (Full Refactor)** следует рассматривать только если есть бизнес-требование для полной независимости стратегии от портфеля или поддержки множественных portfolio configs для одних и тех же blueprints.

**Следующие шаги:**

1. Обсудить с командой выбор опции (A или B)
2. Если выбран Option A — начать с шага 1 (добавление marketcap_proxy)
3. Если выбран Option B — начать с шага 1 (создание StrategyTradeBlueprint)

