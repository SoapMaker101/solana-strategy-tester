# Руководство по Data Pipeline (Runner-only)

## Оглавление

1. [Glossary](#glossary)
2. [End-to-end Flow](#end-to-end-flow)
3. [Data Model & Keys](#data-model--keys)
4. [PnL & Accounting](#pnl--accounting)
5. [Reset Semantics](#reset-semantics)
6. [Outputs](#outputs)
7. [Audit Gate](#audit-gate)
8. [Stage A/B](#stage-ab)
9. [Debug Cookbook](#debug-cookbook)
10. [Runner-only Принципы](#runner-only-принципы)
11. [Test Requirements](#test-requirements)

---

## Glossary

**Signal** — торговый сигнал из CSV файла. Содержит:
- `signal_id`: уникальный идентификатор
- `contract_address`: адрес токена
- `timestamp`: время сигнала

**Candle** — свеча ценовых данных (OHLC). Загружается через `PriceLoader` для временного окна вокруг сигнала.

**Position** — открытая или закрытая позиция в портфеле. Создается при входе, закрывается при выходе или reset. Имеет:
- `position_id`: UUID (генерируется автоматически)
- `signal_id`: ссылка на исходный сигнал
- `entry_time`, `exit_time`: времена входа/выхода
- `entry_price`, `exit_price`: цены (raw, без slippage)
- `exec_entry_price`, `exec_exit_price`: исполненные цены (с slippage)
- `status`: "open" или "closed"
- `meta`: словарь с дополнительными данными (partial_exits, realized_multiple, и т.д.)

**Event** — каноническое событие портфеля (PortfolioEvent). Всего 4 типа:
- `POSITION_OPENED`: позиция открыта
- `POSITION_PARTIAL_EXIT`: частичный выход (ladder TP)
- `POSITION_CLOSED`: позиция закрыта
- `PORTFOLIO_RESET_TRIGGERED`: сработал portfolio-level reset

**Execution** — запись о фактическом исполнении (fill). Создается для каждого события торговли:
- Entry execution: покупка по `exec_entry_price`
- Partial exit execution: продажа части позиции по `exec_price` на уровне `xn` (только для TP уровней)
- Final exit execution: продажа остатка по `exec_exit_price` (time_stop или полное закрытие на уровнях)

---

## End-to-end Flow

### Схема потока данных

```
┌─────────┐
│ Signals │ (CSV файл с торговыми сигналами)
└────┬────┘
     │
     ▼
┌─────────┐
│ Candles │ (загружаются через PriceLoader для окна вокруг сигнала)
└────┬────┘
     │
     ▼
┌──────────────────┐
│ Runner Decision  │ (RunnerStrategy.on_signal → RunnerLadderEngine.simulate)
│                  │ → возвращает StrategyOutput с realized_multiple, fractions_exited
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│ Portfolio Engine │ (PortfolioEngine.simulate)
│                  │ → создает Position, эмитит Events, создает Executions
└────┬─────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│ Positions / Events / Executions        │
│                                         │
│ - portfolio_positions.csv              │
│ - portfolio_events.csv                 │
│ - portfolio_executions.csv             │
└────┬────────────────────────────────────┘
     │
     ▼
┌─────────┐
│  Audit  │ (InvariantChecker → проверяет P0/P1/P2 инварианты)
└────┬────┘
     │
     ▼ (если P0=0)
┌─────────┐
│ Stage A │ (анализ устойчивости стратегий)
└────┬────┘
     │
     ▼
┌─────────┐
│ Stage B │ (отбор стратегий по критериям)
└─────────┘
```

### Пошаговое описание

1. **Signals → Candles**
   - `SignalLoader` загружает сигналы из CSV
   - Для каждого сигнала `PriceLoader` загружает свечи в окне `[timestamp - before_minutes, timestamp + after_minutes]`

2. **Candles → Runner Decision**
   - `RunnerStrategy.on_signal()` вызывает `RunnerLadderEngine.simulate()`
   - Ladder engine проходит по свечам, отслеживает достижение уровней TP (2x, 5x, 10x)
   - При достижении уровня закрывает долю позиции (`fraction`)
   - Возвращает `RunnerTradeResult` с:
     - `realized_multiple`: суммарный multiple = Σ(fraction_i × xn_i)
     - `fractions_exited`: словарь {xn: fraction}
     - `levels_hit`: словарь {xn: hit_time}

3. **Runner Decision → Portfolio Engine**
   - `PortfolioEngine.simulate()` получает `StrategyOutput` с метаданными Runner
   - Создает `Position` с `position_id` (UUID)
   - Эмитит `POSITION_OPENED` событие
   - При обработке частичных выходов:
     - Эмитит `POSITION_PARTIAL_EXIT` для каждого уровня
     - Создает execution записи в `partial_exits` (fills ledger)
   - При финальном закрытии эмитит `POSITION_CLOSED`

4. **Portfolio Engine → CSV Outputs**
   - `Reporter.save_portfolio_positions_table()` → `portfolio_positions.csv`
   - `Reporter.save_portfolio_events_table()` → `portfolio_events.csv`
   - `Reporter.save_portfolio_executions_table()` → `portfolio_executions.csv`

5. **CSV → Audit**
   - `InvariantChecker` проверяет:
     - P0: базовые инварианты (цены, PnL, время)
     - P1: консистентность positions ↔ events ↔ executions
     - P2: доказательства решений (reset/prune условия)

6. **Audit → Stage A** (если P0=0)
   - `run_stage_a` читает `portfolio_positions.csv`
   - Анализирует устойчивость стратегий по окнам
   - Генерирует `strategy_stability.csv`

7. **Stage A → Stage B** (если P0=0)
   - `run_stage_b` читает `strategy_stability.csv`
   - Применяет критерии отбора (hit_rate_x2, hit_rate_x5, tail_contribution)
   - Генерирует `strategy_selection.csv`

---

## Data Model & Keys

### Таблица сущностей и ключей

| Сущность | Первичный ключ | Внешние ключи | Связи |
|----------|----------------|---------------|-------|
| **Position** | `position_id` (UUID) | `signal_id`, `strategy`, `contract_address` | 1:N с Events, 1:N с Executions |
| **Event** | `event_id` (UUID) | `position_id` (обязательно) | N:1 с Position |
| **Execution** | нет (индекс по `position_id` + `event_time`) | `position_id`, `event_id` (опционально) | N:1 с Position, N:1 с Event |

### Связи между CSV

```
portfolio_positions.csv
├── position_id ──────┐
│                     │
│                     ▼
│            portfolio_events.csv
│                     │
│                     │ position_id
│                     │
│                     ▼
│            portfolio_executions.csv
│                     │
│                     │ position_id
│                     │
└─────────────────────┘
```

**Как связать строки вручную:**

1. Найти позицию в `portfolio_positions.csv` по `position_id`
2. Найти все события в `portfolio_events.csv` где `position_id` совпадает
3. Найти все исполнения в `portfolio_executions.csv` где `position_id` совпадает
4. Связать execution с event по `event_id` (если указан) или по времени (в пределах 1 минуты)

**Пример:**

```python
# Позиция
position_id = "abc123"
signal_id = "sig_001"
strategy = "Runner_v1"

# События для этой позиции
events = events_df[events_df["position_id"] == position_id]
# Должны быть: POSITION_OPENED, возможно несколько POSITION_PARTIAL_EXIT, POSITION_CLOSED

# Исполнения для этой позиции
executions = executions_df[executions_df["position_id"] == position_id]
# Должны быть: entry execution, partial exit executions, final exit execution
```

---

## PnL & Accounting

### Формула PnL в Runner Ladder

**Важно:** В Runner стратегии PnL считается через `realized_multiple`, а НЕ через `exit_price`.

#### Формула realized_multiple

```
realized_multiple = Σ(fraction_i × xn_i)

где:
- fraction_i: доля позиции, закрытая на уровне i
- xn_i: целевой multiple уровня i (например, 2.0, 5.0, 10.0)
```

#### Формула pnl_pct_total

```
pnl_pct_total = (realized_multiple - 1.0) × 100.0
```

#### Формула pnl_sol

```
pnl_sol = size × (realized_multiple - 1.0) - fees_total_sol

где:
- size: размер позиции в SOL (на момент входа)
- fees_total_sol: суммарные комиссии (swap + LP + network)
```

### Почему exit_price не является source of truth

**Проблема:** `exit_price` в Runner стратегии — это цена последнего закрытия (market close при time_stop или остаток позиции). Но позиция может закрываться частично на разных уровнях (2x, 5x, 10x), и `exit_price` не отражает реальную доходность.

**Пример:**

```
Позиция: size = 10 SOL, entry_price = 1.0

Частичные выходы:
- 40% на 2x → exit_price = 2.0, fraction = 0.4
- 40% на 5x → exit_price = 5.0, fraction = 0.4
- 20% на time_stop → exit_price = 3.0, fraction = 0.2

realized_multiple = 0.4 × 2.0 + 0.4 × 5.0 + 0.2 × 3.0 = 0.8 + 2.0 + 0.6 = 3.4x

pnl_pct_total = (3.4 - 1.0) × 100 = 240%

Но exit_price = 3.0 (цена последнего закрытия) → это НЕ отражает реальную доходность!
```

**Source of truth для PnL:**

1. **Fills ledger** (`meta.partial_exits`): список всех частичных выходов с ценами и PnL
2. **realized_multiple**: агрегированный multiple из `fractions_exited`

**Где хранится:**

- `portfolio_positions.csv`: колонки `realized_multiple`, `pnl_pct_total`, `pnl_sol`
- `portfolio_events.csv`: в `meta_json` для `POSITION_PARTIAL_EXIT` есть `pnl_pct_contrib`, `pnl_sol_contrib`
- `portfolio_executions.csv`: каждая строка partial exit имеет `pnl_sol_delta`

### Интерпретация Executions/Events для Ladder

**Правило:** Remainder по time_stop = final_exit в executions, reason=time_stop в events

#### Пример: TP partial + time_stop final

**Сценарий:**
- Позиция: 0.1 SOL, entry_price = 100
- Достигнут уровень 3x (20% закрыто)
- Price откатывается
- time_stop срабатывает (остаток 80% закрыт)

**В portfolio_events.csv:**
1. `POSITION_OPENED` (entry)
2. `POSITION_PARTIAL_EXIT` (reason="ladder_tp", level_xn=3.0, fraction=0.20) - TP partial
3. `POSITION_PARTIAL_EXIT` (reason="time_stop", is_remainder=True) - remainder exit
4. `POSITION_CLOSED` (reason="time_stop")

**В portfolio_executions.csv:**
1. `entry` (qty_delta=+0.1)
2. `partial_exit` (qty_delta=-0.02, reason="ladder_tp", xn=3.0) - TP partial
3. `final_exit` (qty_delta=-0.08, reason="time_stop") - remainder (НЕ дублируется как partial_exit)

**Важно:**
- Remainder exit (`is_remainder=True`) НЕ записывается как `partial_exit` execution
- Remainder exit отражается только в `final_exit` execution
- `event_id` в `final_exit` ссылается на remainder exit event

### Пример расчета PnL

```python
# Из portfolio_positions.csv
position_id = "abc123"
size = 10.0  # SOL
realized_multiple = 3.4
fees_total_sol = 0.05

# Расчет
pnl_pct_total = (3.4 - 1.0) * 100.0 = 240.0  # %
pnl_sol = 10.0 * (3.4 - 1.0) - 0.05 = 23.95  # SOL

# Проверка через partial_exits (из meta или executions)
partial_exits = [
    {"xn": 2.0, "fraction": 0.4, "pnl_sol": 4.0},   # 10 * 0.4 * (2.0 - 1.0) = 4.0
    {"xn": 5.0, "fraction": 0.4, "pnl_sol": 16.0},  # 10 * 0.4 * (5.0 - 1.0) = 16.0
    {"xn": 3.0, "fraction": 0.2, "pnl_sol": 4.0},  # 10 * 0.2 * (3.0 - 1.0) = 4.0
]

total_pnl_sol = 4.0 + 16.0 + 4.0 = 24.0  # Без учета fees
pnl_sol_after_fees = 24.0 - 0.05 = 23.95  # Совпадает!
```

---

## Reset Semantics

### Что такое Reset

**Reset** — это portfolio-level операция, которая закрывает все открытые позиции при достижении пороговых значений equity.

### Типы Reset

1. **Profit Reset** (`profit_reset`)
   - Триггер: `equity_peak_in_cycle >= cycle_start_equity × profit_reset_multiple`
   - Закрывает все позиции market close
   - Обновляет `cycle_start_equity = balance` после reset

2. **Capacity Prune** (`capacity_prune`)
   - Триггер: превышение порогов capacity pressure (blocked_ratio, avg_hold_days)
   - Закрывает подмножество позиций (prune candidates)
   - Может иметь cooldown период

### Цепочка событий при Reset

```
┌─────────────────────────────────────┐
│ PORTFOLIO_RESET_TRIGGERED           │
│ (1 событие)                         │
│ - timestamp: время reset            │
│ - reason: "profit_reset" или        │
│          "capacity_prune"           │
│ - meta.closed_positions_count: N    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ POSITION_CLOSED                      │
│ (N событий, по одному на позицию)   │
│ - position_id: ID закрытой позиции  │
│ - reason: "profit_reset" или        │
│          "capacity_prune"            │
│ - meta.closed_by_reset: true        │
└─────────────────────────────────────┘
```

### Пример Reset Chain

```python
# События в portfolio_events.csv

# 1. Reset triggered
event_id = "evt_reset_001"
event_type = "PORTFOLIO_RESET_TRIGGERED"
timestamp = "2025-01-15T10:00:00"
reason = "profit_reset"
meta_json = {
    "closed_positions_count": 3,
    "cycle_start_equity": 10.0,
    "equity_peak_in_cycle": 20.0,
    "profit_reset_multiple": 2.0
}

# 2. Position 1 closed
event_id = "evt_close_001"
event_type = "POSITION_CLOSED"
position_id = "pos_001"
timestamp = "2025-01-15T10:00:00"
reason = "profit_reset"
meta_json = {
    "closed_by_reset": true,
    "triggered_portfolio_reset": false  # не marker позиция
}

# 3. Position 2 closed (marker)
event_id = "evt_close_002"
event_type = "POSITION_CLOSED"
position_id = "pos_002"
timestamp = "2025-01-15T10:00:00"
reason = "profit_reset"
meta_json = {
    "closed_by_reset": true,
    "triggered_portfolio_reset": true  # marker позиция
}

# 4. Position 3 closed
event_id = "evt_close_003"
event_type = "POSITION_CLOSED"
position_id = "pos_003"
timestamp = "2025-01-15T10:00:00"
reason = "profit_reset"
meta_json = {
    "closed_by_reset": true,
    "triggered_portfolio_reset": false
}
```

### Инварианты Reset

1. **Количество событий:** `PORTFOLIO_RESET_TRIGGERED` = 1, `POSITION_CLOSED` = N (где N = количество закрытых позиций)
2. **Время:** все события имеют одинаковый `timestamp` (или очень близкий)
3. **Причина:** все `POSITION_CLOSED` имеют `reason` = причина reset
4. **Флаги:** все закрытые позиции имеют `meta.closed_by_reset = true`
5. **Marker позиция:** одна позиция имеет `meta.triggered_portfolio_reset = true`

---

## Outputs

### portfolio_positions.csv

**Назначение:** Positions-level таблица (агрегат по позициям). Каждая строка = 1 закрытая позиция.

**Ключевые колонки:**

- `position_id`: UUID позиции (первичный ключ)
- `strategy`: название стратегии
- `signal_id`: ID исходного сигнала
- `entry_time`, `exit_time`: времена входа/выхода
- `size`: размер позиции в SOL
- `pnl_sol`: портфельный PnL в SOL (обязательно!)
- `pnl_pct_total`: PnL в процентах = (realized_multiple - 1.0) × 100
- `realized_multiple`: суммарный multiple из ladder fills
- `exec_entry_price`, `exec_exit_price`: исполненные цены (с slippage)
- `raw_entry_price`, `raw_exit_price`: сырые цены (без slippage)
- `closed_by_reset`: закрыта ли позиция по reset (bool)
- `triggered_portfolio_reset`: триггернула ли portfolio-level reset (bool)
- `max_xn_reached`: максимальный достигнутый XN
- `hit_x2`, `hit_x5`: достигнуты ли уровни 2x и 5x (bool)

**Что проверять глазами:**

- Все позиции имеют `status = "closed"`
- `pnl_sol` не равен 0 для прибыльных позиций
- `realized_multiple >= 1.0` для прибыльных позиций
- `closed_by_reset = true` только для позиций, закрытых по reset
- `max_xn_reached` соответствует `hit_x2` / `hit_x5`

### portfolio_events.csv

**Назначение:** Events-level таблица (канонические события портфеля). Каждая строка = 1 PortfolioEvent.

**Ключевые колонки:**

- `event_id`: UUID события (первичный ключ)
- `timestamp`: время события (ISO)
- `event_type`: тип события (4 типа)
- `position_id`: ссылка на позицию (обязательно)
- `strategy`, `signal_id`, `contract_address`: идентификаторы
- `reason`: каноническая причина (для закрытий/reset)
- `meta_json`: JSON строка с дополнительными данными

**Что проверять глазами:**

- Для каждой позиции есть `POSITION_OPENED`
- Для каждой закрытой позиции есть `POSITION_CLOSED`
- Для Runner позиций с partial exits есть `POSITION_PARTIAL_EXIT` события
- При reset есть `PORTFOLIO_RESET_TRIGGERED` + N `POSITION_CLOSED`
- Все события имеют валидный `position_id`

### portfolio_executions.csv

**Назначение:** Executions-level таблица (фактические исполнения). Каждая строка = 1 fill/partial close.

**Ключевые колонки:**

- `position_id`: ссылка на позицию
- `event_time`: время исполнения
- `event_type`: тип события (POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED)
- `event_id`: ссылка на PortfolioEvent (опционально)
- `raw_price`: сырая цена (без slippage)
- `exec_price`: исполненная цена (с slippage)
- `qty_delta`: изменение количества (положительное для entry, отрицательное для exit)
- `pnl_sol_delta`: изменение PnL для этого события
- `xn`: целевой multiple (для partial exits)
- `fraction`: доля выхода (для partial exits)

**Что проверять глазами:**

- Для каждой позиции есть entry execution
- Для Runner позиций есть partial exit executions (по количеству уровней)
- Для каждой закрытой позиции есть final exit execution
- `exec_price` отличается от `raw_price` (slippage применен)
- `pnl_sol_delta` для partial exits соответствует `xn` и `fraction`

### report_pack.xlsx

**Назначение:** Единый XLSX отчет со всеми ключевыми таблицами (представление, не source of truth).

**Листы:**

- `summary`: сводные метрики
- `positions`: копия `portfolio_positions.csv`
- `portfolio_events`: копия `portfolio_events.csv`
- `stage_a_stability`: результаты Stage A
- `stage_b_selection`: результаты Stage B
- `policy_summary`: статистика по reset/prune

**Важно:** Это представление данных, не source of truth. Для проверки используйте CSV файлы.

---

## Audit Gate

### Что проверяет Audit

**P0 (критичные):**

- Валидность цен (`entry_price > 0`, `exit_price > 0`)
- Формула PnL (`pnl_pct = (exit_price - entry_price) / entry_price` для простых позиций)
- Консистентность reason с PnL (`reason=tp` → `pnl >= 0`, `reason=sl` → `pnl < 0`)
- Порядок времени (`entry_time <= exit_time`)
- Наличие цепочки событий для каждой позиции (`MISSING_EVENTS_CHAIN`)

**P1 (консистентность):**

- Positions ↔ Events: позиция закрыта → есть `POSITION_CLOSED` событие
- Events ↔ Executions: событие торговли → есть execution запись
- Время: execution не может быть раньше события

**P2 (доказательства решений):**

- Profit reset: условие `equity_peak >= cycle_start × multiple` выполнено
- Capacity prune: пороги превышены, действие сработало

### Почему Stage A/B не должны запускаться при P0>0

**Причина:** P0 аномалии указывают на критические ошибки в данных:
- Некорректные цены → неправильный PnL
- Отсутствие событий → невозможно проверить консистентность
- Неправильная формула PnL → метрики Stage A будут неверными

**Проверка перед Stage A/B:**

```python
# В run_stage_a.py и run_stage_b.py
p0_count, _ = audit_run(reports_dir)
if p0_count > 0:
    print("ERROR: Audit P0 anomalies detected. Stage A/B blocked.")
    raise SystemExit(2)
```

---

## Stage A/B

### Stage A: Анализ устойчивости

**Вход:** `portfolio_positions.csv` (positions-level)

**Выход:** `strategy_stability.csv`

**Что делает:**

1. Разбивает позиции на временные окна (rolling windows)
2. Для каждого окна считает метрики:
   - `total_pnl_sol`: суммарный PnL
   - `hit_rate_x2`: доля позиций, достигших 2x
   - `hit_rate_x5`: доля позиций, достигших 5x
   - `tail_contribution`: доля PnL от позиций с `max_xn >= 4.0`
3. Агрегирует метрики по стратегиям:
   - `survival_rate`: доля окон с положительным PnL
   - `worst_window_pnl`: худший PnL по окнам
   - `median_window_pnl`: медианный PnL по окнам

**Требования к входным данным:**

- Только закрытые позиции (`status = "closed"`)
- Обязательна колонка `pnl_sol`
- Обязательны колонки `hit_x2`, `hit_x5` (или вычисляются из `max_xn_reached`)

### Stage B: Отбор стратегий

**Вход:** `strategy_stability.csv` (из Stage A)

**Выход:** `strategy_selection.csv`

**Что делает:**

1. Применяет критерии отбора (Runner Criteria v1):
   - `min_hit_rate_x2`: минимальная доля позиций, достигших 2x
   - `min_hit_rate_x5`: минимальная доля позиций, достигших 5x
   - `max_tail_contribution`: максимальная доля PnL от tail позиций
   - `max_p90_hold_days`: максимальный 90-й перцентиль времени удержания
   - `max_drawdown_pct`: максимальный drawdown
2. Помечает стратегии как `passed = true/false`
3. Записывает причины отклонения в `failed_reasons`

**Требования к входным данным:**

- Обязательны колонки из Stage A: `hit_rate_x2`, `hit_rate_x5`, `tail_contribution`
- Audit P0 = 0 (проверяется перед запуском)

---

## Debug Cookbook

### Если PnL в positions странный

**Симптом:** `pnl_pct_total` или `pnl_sol` выглядят неправильно (слишком большие, отрицательные для прибыльных позиций, и т.д.)

**Шаги диагностики:**

1. **Проверить `realized_multiple`:**
   ```python
   # Должно быть >= 1.0 для прибыльных позиций
   # Формула: realized_multiple = Σ(fraction_i × xn_i)
   ```

2. **Проверить `partial_exits` в meta:**
   ```python
   # Из portfolio_positions.csv или portfolio_events.csv
   # partial_exits должен содержать все частичные выходы
   # Сумма pnl_sol из partial_exits должна совпадать с pnl_sol позиции
   ```

3. **Проверить `fractions_exited`:**
   ```python
   # fractions_exited = {xn: fraction}
   # Сумма fractions должна быть <= 1.0
   # realized_multiple = sum(xn * fraction for xn, fraction in fractions_exited.items())
   ```

4. **Проверить executions:**
   ```python
   # В portfolio_executions.csv найти все executions для position_id
   # Сумма pnl_sol_delta должна совпадать с pnl_sol позиции
   ```

5. **Проверить события:**
   ```python
   # В portfolio_events.csv найти все POSITION_PARTIAL_EXIT для position_id
   # meta_json должен содержать pnl_pct_contrib и pnl_sol_contrib
   ```

### Если audit ругается missing chain

**Симптом:** `MISSING_EVENTS_CHAIN` аномалия для позиции

**Шаги диагностики:**

1. **Проверить наличие `position_id` в positions:**
   ```python
   # В portfolio_positions.csv позиция должна иметь валидный position_id
   ```

2. **Проверить наличие событий:**
   ```python
   # В portfolio_events.csv должны быть события с этим position_id
   # Минимум: POSITION_OPENED и POSITION_CLOSED
   ```

3. **Проверить формат `position_id`:**
   ```python
   # position_id должен быть одинаковым в positions и events
   # Проверить на опечатки, лишние пробелы
   ```

4. **Проверить фильтрацию:**
   ```python
   # Убедиться, что events_df не отфильтрован по strategy
   # Runner-only проект должен видеть все Runner стратегии
   ```

### Если reset chain неполный

**Симптом:** Есть `PORTFOLIO_RESET_TRIGGERED`, но не все позиции имеют `POSITION_CLOSED` с `closed_by_reset = true`

**Шаги диагностики:**

1. **Проверить количество закрытых позиций:**
   ```python
   # meta.closed_positions_count в PORTFOLIO_RESET_TRIGGERED
   # должно совпадать с количеством POSITION_CLOSED с reason = reset_reason
   ```

2. **Проверить время событий:**
   ```python
   # Все события reset должны иметь одинаковый timestamp
   # (или очень близкий, в пределах 1 секунды)
   ```

3. **Проверить флаги:**
   ```python
   # Все закрытые позиции должны иметь closed_by_reset = true
   # Одна позиция должна иметь triggered_portfolio_reset = true
   ```

---

## Runner-only Принципы

### Только 4 типа событий

В Runner-only проекте используются только 4 типа `PortfolioEvent`:

1. **POSITION_OPENED**: позиция открыта
2. **POSITION_PARTIAL_EXIT**: частичный выход (ladder TP)
3. **POSITION_CLOSED**: позиция закрыта
4. **PORTFOLIO_RESET_TRIGGERED**: portfolio-level reset

**Не используются:** старые типы событий (ATTEMPT_REJECTED, EXECUTED_OPEN, и т.д.)

### Reason Taxonomy

Канонические причины закрытия позиций:

- `ladder_tp`: закрытие по ladder take-profit (частичный или полный)
- `stop_loss`: закрытие по stop-loss (не используется в Runner, но может быть в будущем)
- `time_stop`: закрытие по таймауту (time_stop_minutes)
- `capacity_prune`: закрытие по capacity prune
- `profit_reset`: закрытие по profit reset
- `manual_close`: ручное закрытие (для reset операций)

**Где используется:**

- `portfolio_positions.csv`: колонка `reason`
- `portfolio_events.csv`: колонка `reason` для `POSITION_CLOSED` и `PORTFOLIO_RESET_TRIGGERED`
- `portfolio_executions.csv`: колонка `reason` для exit executions

---

## Test Requirements

### Обязательные тесты

#### 1. Events ↔ Executions Linkage

**Название:** `test_events_executions_linkage`

**Логика:**

```python
def test_events_executions_linkage():
    """
    Проверяет, что каждое событие торговли имеет соответствующее execution.
    """
    # Загрузить events и executions
    events_df = load_csv("portfolio_events.csv")
    executions_df = load_csv("portfolio_executions.csv")
    
    # Для каждого POSITION_OPENED / POSITION_PARTIAL_EXIT / POSITION_CLOSED
    trade_events = events_df[events_df["event_type"].isin([
        "POSITION_OPENED", "POSITION_PARTIAL_EXIT", "POSITION_CLOSED"
    ])]
    
    for _, event in trade_events.iterrows():
        position_id = event["position_id"]
        event_time = pd.to_datetime(event["timestamp"])
        
        # Найти execution в пределах 1 минуты
        matching_exec = executions_df[
            (executions_df["position_id"] == position_id) &
            (abs(pd.to_datetime(executions_df["event_time"]) - event_time) < timedelta(minutes=1))
        ]
        
        assert len(matching_exec) > 0, f"No execution found for event {event['event_id']}"
```

#### 2. PnL Source of Truth

**Название:** `test_pnl_source_of_truth`

**Логика:**

```python
def test_pnl_source_of_truth():
    """
    Проверяет, что pnl_sol в positions совпадает с суммой pnl_sol_delta из executions.
    """
    positions_df = load_csv("portfolio_positions.csv")
    executions_df = load_csv("portfolio_executions.csv")
    
    for _, pos in positions_df.iterrows():
        position_id = pos["position_id"]
        
        # Сумма pnl_sol_delta из executions
        exec_pnl = executions_df[
            executions_df["position_id"] == position_id
        ]["pnl_sol_delta"].sum()
        
        # pnl_sol из positions
        pos_pnl = pos["pnl_sol"]
        
        # Должны совпадать (с допуском на округление)
        assert abs(exec_pnl - pos_pnl) < 0.01, \
            f"PnL mismatch for position {position_id}: positions={pos_pnl}, executions={exec_pnl}"
```

#### 3. Reset Chain

**Название:** `test_reset_chain`

**Логика:**

```python
def test_reset_chain():
    """
    Проверяет, что reset chain корректен:
    - 1 PORTFOLIO_RESET_TRIGGERED
    - N POSITION_CLOSED с closed_by_reset = true
    - Все события имеют одинаковый timestamp
    """
    events_df = load_csv("portfolio_events.csv")
    
    reset_events = events_df[
        events_df["event_type"] == "PORTFOLIO_RESET_TRIGGERED"
    ]
    
    for _, reset_event in reset_events.iterrows():
        reset_time = pd.to_datetime(reset_event["timestamp"])
        reset_reason = reset_event["reason"]
        
        # Парсим meta_json
        meta = json.loads(reset_event["meta_json"])
        expected_count = meta.get("closed_positions_count", 0)
        
        # Находим закрытые позиции
        closed_events = events_df[
            (events_df["event_type"] == "POSITION_CLOSED") &
            (events_df["reason"] == reset_reason) &
            (abs(pd.to_datetime(events_df["timestamp"]) - reset_time) < timedelta(seconds=1))
        ]
        
        assert len(closed_events) == expected_count, \
            f"Reset chain incomplete: expected {expected_count}, got {len(closed_events)}"
        
        # Проверяем флаги
        for _, closed_event in closed_events.iterrows():
            closed_meta = json.loads(closed_event["meta_json"])
            assert closed_meta.get("closed_by_reset") == True, \
                f"Position {closed_event['position_id']} missing closed_by_reset flag"
```

### Предложенные тесты

1. **`test_realized_multiple_formula`**: проверяет формулу `realized_multiple = Σ(fraction × xn)`
2. **`test_partial_exits_consistency`**: проверяет, что `partial_exits` в meta совпадает с executions
3. **`test_reset_timestamp_consistency`**: проверяет, что все события reset имеют одинаковый timestamp
4. **`test_position_events_chain`**: проверяет, что для каждой позиции есть OPENED и CLOSED события
5. **`test_execution_prices_with_slippage`**: проверяет, что `exec_price` отличается от `raw_price` (slippage применен)

---

## Заключение

Этот документ описывает полный путь данных в Runner-only проекте:

1. **Signals → Candles → Runner Decision → Portfolio Engine** — симуляция
2. **Positions/Events/Executions → CSV** — экспорт данных
3. **Audit** — проверка инвариантов (P0/P1/P2)
4. **Stage A** — анализ устойчивости
5. **Stage B** — отбор стратегий

**Ключевые принципы:**

- **Source of truth:** `events` + `executions` (fills ledger)
- **Представление:** `positions` table, `report_pack.xlsx`
- **PnL в Runner:** через `realized_multiple`, не через `exit_price`
- **Reset:** цепочка событий `PORTFOLIO_RESET_TRIGGERED` + N `POSITION_CLOSED`
- **Audit gate:** Stage A/B не запускаются при P0>0

**Для нового разработчика:**

1. Начните с понимания потока данных (End-to-end Flow)
2. Изучите связи между CSV (Data Model & Keys)
3. Разберитесь с PnL расчетом (PnL & Accounting)
4. Используйте Debug Cookbook для диагностики проблем
5. Пишите тесты согласно Test Requirements


