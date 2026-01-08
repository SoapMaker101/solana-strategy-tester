# ARCH_FREEZE_RUNNER_v2.2

**Status:** FROZEN  
**Scope:** Runner-only  
**Date:** 2025-01-XX  
**Baseline tag:** v2.2.0-runner-final-exit

## Кратко

Этот документ фиксирует каноническую архитектурную модель Runner v2.2 после внедрения **Variant C** (remainder semantics).

**Что зафиксировано:**
- Семантика закрытия позиций (partial exits, remainder, final exit)
- Связь между Events, Executions и Positions
- Инварианты fees accounting
- Правила определения `reason` и `time_stop_triggered`

**Почему этот freeze:**
- До v2.2 существовала архитектурная неоднозначность в обработке remainder (остаток позиции при time_stop)
- Variant C устраняет двусмысленность: remainder не является отдельным `POSITION_PARTIAL_EXIT`, а отражается только через `POSITION_CLOSED`
- Это обеспечивает однозначную интерпретацию Runner economics для downstream аналитики

---

## 1. Контекст и проблема (WHY THIS FREEZE EXISTS)

До v2.2 существовала архитектурная неоднозначность в обработке remainder (остаток позиции, закрываемый по time_stop после частичных TP exits).

### Классы ошибок, которые порождала неоднозначность:

1. **Двусмысленность финального reason:**
   - Remainder создавался как `POSITION_PARTIAL_EXIT` с `reason="time_stop"`, но затем также создавался `POSITION_CLOSED`
   - Невозможно было однозначно определить, что является "финальным" событием закрытия

2. **Remainder как partial_exit:**
   - Remainder попадал в `portfolio_events.csv` как `POSITION_PARTIAL_EXIT` с `is_remainder=True`
   - Это создавало путаницу: remainder по смыслу — финальный close, а не partial exit

3. **Потенциальный двойной учёт:**
   - Один и тот же remainder мог отражаться и как `POSITION_PARTIAL_EXIT`, и как `POSITION_CLOSED` на одном timestamp
   - Риск двойного учёта в downstream аналитике

4. **Невозможность однозначного анализа Runner economics:**
   - Неясно, где искать "последний выход" для расчёта финального PnL
   - Неясно, как интерпретировать `reason` в контексте partial + remainder

5. **Нарушение контракта Events ↔ Executions:**
   - Remainder как `POSITION_PARTIAL_EXIT` создавал неоднозначность в связке с `final_exit` execution
   - `event_id` в `final_exit` не мог однозначно ссылаться на финальное событие закрытия

**Variant C (v2.2) устраняет эти проблемы:**
- Remainder не создаёт отдельный `POSITION_PARTIAL_EXIT` event
- Финальный остаток отражается только через `POSITION_CLOSED` (reason="time_stop")
- Однозначная связь: `final_exit.event_id` → `POSITION_CLOSED.event_id`

---

## 2. Каноническая модель Runner (TO-BE)

### 2.1 High-level схема (текстом)

```
Signal
  ↓
Strategy (Runner)
  ↓
  RunnerLadderEngine.simulate()
  ↓
  RunnerTradeResult
    - levels_hit: Dict[float, datetime]
    - fractions_exited: Dict[float, float]
    - realized_multiple: float
    - reason: "ladder_tp" | "time_stop" | "stop_loss" | "no_entry"
    - time_stop_triggered: bool
  ↓
StrategyOutput
  - meta["ladder_reason"]: канонический reason
  - meta["time_stop_triggered"]: bool
  - meta["levels_hit"]: Dict
  - meta["fractions_exited"]: Dict
  ↓
PortfolioEngine.simulate()
  ↓
  _process_runner_partial_exits()
    - Создаёт POSITION_PARTIAL_EXIT для каждого TP уровня
    - Сохраняет remainder данные в pos.meta["remainder_exit_data"]
    - НЕ создаёт POSITION_PARTIAL_EXIT для remainder
  ↓
  _process_position_exit()
    - Создаёт POSITION_CLOSED (reason из time_stop_triggered или ladder_reason)
    - Использует remainder_exit_data для правильных цен/PnL
    - Сохраняет close_event_id в pos.meta
  ↓
PortfolioResult
  - positions: List[Position]
  - events: List[PortfolioEvent]
  ↓
Reporter
  - save_portfolio_events_table() → portfolio_events.csv
  - save_portfolio_executions_table() → portfolio_executions.csv
  - save_portfolio_positions_table() → portfolio_positions.csv
```

**Где принимается решение:**
- `RunnerLadderEngine`: определяет, какие уровни достигнуты, когда сработал time_stop
- `PortfolioEngine._process_runner_partial_exits`: принимает решение о создании partial exits и remainder
- `PortfolioEngine._process_position_exit`: принимает решение о reason для `POSITION_CLOSED`

**Где происходит учёт:**
- `PortfolioEngine`: накапливает fees, PnL, обновляет баланс
- `Position.meta`: хранит `partial_exits`, `remainder_exit_data`, `fees_total_sol`, `pnl_sol`

**Где только отражение:**
- `Reporter`: экспортирует данные в CSV, не изменяет экономику
- `portfolio_executions.csv`: распределение `fees_total_sol` по execution-строкам для проверки

### 2.2 Семантика закрытия позиции (КЛЮЧЕВО)

#### RUNNER EXIT SEMANTICS (v2.2)

**Обязательные правила (как контракт):**

##### Partial Exits (TP уровни):

- **Создаются только для ladder TP уровней:**
  - При достижении уровня из `take_profit_levels` (например, 3x, 7x, 15x)
  - Только если `allow_partial_fills=True` и `exit_on_first_tp=False`
  
- **Event:**
  - `event_type = POSITION_PARTIAL_EXIT`
  - `reason = "ladder_tp"`
  - `meta` содержит: `level_xn`, `fraction`, `pnl_sol_contrib`, `fees_sol`, `network_fee_sol`
  
- **Execution:**
  - `event_type = "partial_exit"`
  - `reason = "ladder_tp"`
  - `qty_delta = -exit_size` (отрицательное)
  - `xn = level_xn` (например, 3.0)
  - `fraction = exit_size / original_size`

- **Хранение:**
  - Сохраняется в `pos.meta["partial_exits"]` как dict с ключами: `exit_size`, `exit_price`, `pnl_sol`, `fees_sol`, `network_fee_sol`, `xn`, `hit_time`
  - `is_remainder = False` (явно или отсутствует)

##### Remainder (остаток по time_stop):

- **НЕ является отдельным partial_exit event:**
  - ❌ НЕ создаётся `POSITION_PARTIAL_EXIT` для remainder
  - ❌ НЕ попадает в `portfolio_events.csv` как отдельное событие
  
- **Хранение:**
  - Данные сохраняются в `pos.meta["remainder_exit_data"]`:
    - `raw_price`: цена до slippage
    - `exec_price`: цена после slippage
    - `pnl_sol`: PnL для остатка
    - `pnl_pct`: PnL в процентах
    - `fees_sol`: swap + LP fees
    - `network_fee_sol`: network fee
    - `exit_size`: размер остатка
  - Также сохраняется в `pos.meta["partial_exits"]` с `is_remainder=True` (для внутреннего учёта)
  
- **Использование:**
  - Данные из `remainder_exit_data` используются в `_process_position_exit` для создания `POSITION_CLOSED` с правильными ценами и PnL

##### Final Exit:

- **Всегда один на позицию:**
  - Создаётся в `_process_position_exit` когда `pos.size <= 1e-9` и `pos.status == "closed"`
  
- **Event:**
  - `event_type = POSITION_CLOSED`
  - `reason` определяется по правилам:
    - Если `time_stop_triggered == True` → `reason = "time_stop"`
    - Иначе если позиция закрыта полностью на уровнях → `reason = "ladder_tp"`
    - Иначе используется `pos.meta["close_reason"]` или `pos.meta["ladder_reason"]`
  - `meta` содержит: `entry_time`, `exit_time`, `fees_total_sol`, `runner_ladder=True`
  - `event_id` сохраняется в `pos.meta["close_event_id"]` для связи с execution
  
- **Execution:**
  - `event_type = "final_exit"`
  - `reason` из `POSITION_CLOSED.reason` (или `pos.meta["close_reason"]`)
  - `qty_delta = -remaining_size` (отрицательное)
  - `event_id` ссылается на `POSITION_CLOSED.event_id` (через `pos.meta["close_event_id"]`)
  - `fees_sol`:
    - Если есть `remainder_exit_data` → `fees_sol = remainder.fees_sol + remainder.network_fee_sol`
    - Если remainder нет (позиция закрыта полностью на уровнях) → `fees_sol = 0.0` (все fees уже учтены в partial_exits)
    - Для обычной позиции (без partial_exits) → `fees_sol = fees_total_sol`

##### time_stop_triggered:

- **Определение:**
  - `True` только если финальный exit произошёл по time_stop
  - То есть: если позиция закрылась полностью на уровнях → `time_stop_triggered = False`
  - Если позиция дожила до таймстопа и остаток закрыт по таймстопу → `time_stop_triggered = True`
  
- **Хранение:**
  - В `RunnerTradeResult.time_stop_triggered`
  - В `StrategyOutput.meta["time_stop_triggered"]`
  - В `Position.meta["time_stop_triggered"]`
  
- **Использование:**
  - Определяет `reason` для `POSITION_CLOSED`: если `time_stop_triggered == True` → `reason = "time_stop"`

---

## 3. Events / Executions / Positions — роли и запреты

### 3.1 portfolio_events.csv

**Роль:**
- События состояния портфеля (когда что произошло)
- Источник `reason` (каноническая причина закрытия)
- `event_id` — первичный идентификатор факта события

**Структура для Runner:**
- `POSITION_OPENED`: открытие позиции (1 на позицию)
- `POSITION_PARTIAL_EXIT`: частичные выходы по TP уровням (0 или более на позицию, только для TP)
- `POSITION_CLOSED`: финальное закрытие позиции (1 на позицию)

**Запреты:**
- ❌ Remainder НЕ создаётся как `POSITION_PARTIAL_EXIT`
- ❌ Несколько `POSITION_CLOSED` на одну позицию
- ❌ `POSITION_PARTIAL_EXIT` с `is_remainder=True` в events (это внутренний флаг в meta, не event)

**Порядок событий:**
- Для каждого `position_id`: `POSITION_OPENED` → `POSITION_PARTIAL_EXIT*` → `POSITION_CLOSED`
- Timestamps монотонны

### 3.2 portfolio_executions.csv

**Роль:**
- Отражение исполнений (цены, комиссии, slippage)
- Распределение `fees_total_sol` по execution-строкам для проверки
- Связь с events через `event_id`

**Структура для Runner:**
- `entry`: вход в позицию (1 на позицию)
  - `fees_sol`: network_fee при входе (для Runner с partial_exits) или 0 (для обычных позиций)
- `partial_exit`: частичные выходы по TP уровням (0 или более на позицию)
  - `reason = "ladder_tp"`
  - `fees_sol = fees_sol + network_fee_sol` из partial_exit
- `final_exit`: финальный выход (1 на позицию)
  - `reason`: из `POSITION_CLOSED.reason` (или `pos.meta["close_reason"]`)
  - `event_id`: ссылается на `POSITION_CLOSED.event_id` (через `pos.meta["close_event_id"]`)
  - `fees_sol`: из `remainder_exit_data` (если есть) или 0 (если позиция закрыта полностью на уровнях)

**Жёсткий инвариант:**
- ✅ `Σ executions.fees_sol == positions.fees_total_sol` (eps 1e-9)
- Проверяется в `Reporter.save_portfolio_executions_table()` через `logging.debug` (без warnings/raise)

**Запреты:**
- ❌ Remainder НЕ записывается как `partial_exit` execution
- ❌ `final_exit` не может ссылаться на несуществующий event_id

### 3.3 portfolio_positions.csv

**Роль:**
- Single source of truth по:
  - `pnl_sol`: итоговый PnL позиции
  - `fees_total_sol`: итоговые комиссии
  - `status`: статус позиции (open/closed)
  - `realized_multiple`: реализованный множитель
  - `pnl_pct_total`: PnL в процентах

**Источник данных:**
- `fees_total_sol`: из `pos.meta["fees_total_sol"]` (накоплено в PortfolioEngine)
- `pnl_sol`: из `pos.meta["pnl_sol"]` (пересчитано из всех partial_exits)
- `realized_multiple`: из `pos.meta["realized_multiple"]` (сумма xn * fraction)

**Правило:**
- Derived данные (например, `fees_total_sol` из executions) допустимы для проверки, но не являются источником расчёта
- `portfolio_positions.csv` — это агрегат, а не пересчёт из executions

**Запреты:**
- ❌ Не должно быть дублей по `(strategy, signal_id, contract_address)`
- ❌ Не должно быть нескольких строк для одной позиции из-за partial exits

---

## 4. Финальные инварианты (MUST HOLD)

Это контракт v2.2. Все эти инварианты должны выполняться для корректной работы системы.

### Инварианты событий:

✅ **У позиции ровно один финальный exit:**
- Всегда создаётся ровно один `POSITION_CLOSED` event для закрытой позиции
- Всегда создаётся ровно один `final_exit` execution для закрытой позиции

✅ **reason отражает финальный способ закрытия:**
- `POSITION_CLOSED.reason` определяется из `time_stop_triggered` или `ladder_reason`
- `final_exit.reason` совпадает с `POSITION_CLOSED.reason` (или берётся из `pos.meta["close_reason"]`)

✅ **time_stop_triggered ⇔ final reason = time_stop:**
- Если `time_stop_triggered == True` → `POSITION_CLOSED.reason == "time_stop"`
- Если `POSITION_CLOSED.reason == "time_stop"` → `time_stop_triggered == True`

✅ **partial_exit не может быть финалом:**
- `POSITION_PARTIAL_EXIT` создаётся только для TP уровней (reason="ladder_tp")
- Remainder НЕ создаётся как `POSITION_PARTIAL_EXIT`

### Инварианты fees:

✅ **fees сходятся между positions и executions:**
- `Σ executions.fees_sol == positions.fees_total_sol` (eps 1e-9)
- Проверяется в `Reporter.save_portfolio_executions_table()`

✅ **executions не могут менять экономику позиции:**
- `Reporter` не мутирует `pos.meta["fees_total_sol"]`
- Executions — это отражение, а не источник расчёта

### Инварианты связей:

✅ **final_exit.event_id ссылается на POSITION_CLOSED:**
- `final_exit.event_id` всегда равен `POSITION_CLOSED.event_id` (если доступно)
- Связь через `pos.meta["close_event_id"]`

✅ **Порядок событий монотонен:**
- Для каждого `position_id`: `POSITION_OPENED` → `POSITION_PARTIAL_EXIT*` → `POSITION_CLOSED`
- Timestamps не убывают

### Инварианты данных:

✅ **remainder_exit_data существует только если был remainder:**
- Если `pos.meta["remainder_exit_data"]` существует → был remainder по time_stop
- Если remainder не было → `remainder_exit_data` отсутствует

✅ **partial_exits содержит remainder только для внутреннего учёта:**
- Remainder сохраняется в `pos.meta["partial_exits"]` с `is_remainder=True` для учёта fees/PnL
- Но НЕ создаётся отдельный `POSITION_PARTIAL_EXIT` event для него

---

## 5. Backward Compatibility

### Legacy-поля, сохранённые для BC:

- **StrategyOutput.reason:**
  - `"tp"` (legacy) → `meta["ladder_reason"] = "ladder_tp"` (canonical)
  - `"timeout"` (legacy) → `meta["ladder_reason"] = "time_stop"` (canonical)
  - `meta["ladder_reason"]` всегда содержит каноническое значение

- **Position.meta:**
  - `close_reason`: может содержать legacy значения ("tp", "timeout")
  - `ladder_reason`: каноническое значение ("ladder_tp", "time_stop")
  - Оба поля могут существовать одновременно

### Legacy-нейминг, допускаемый:

- `reason = "tp"` в старых тестах → маппится в `"ladder_tp"` для canonical
- `reason = "timeout"` в старых тестах → маппится в `"time_stop"` для canonical

### Что НЕ гарантируется для старых прогонов:

- Старые прогоны (до v2.2) могут содержать remainder как `POSITION_PARTIAL_EXIT` с `is_remainder=True`
- Для старых прогонов может не быть `remainder_exit_data` в meta
- Для старых прогонов `final_exit.event_id` может не ссылаться на `POSITION_CLOSED.event_id`

**Рекомендация:** Для анализа старых прогонов используйте `is_remainder=True` в `partial_exits` как индикатор remainder.

---

## 6. Что намеренно НЕ входит в freeze

Этот freeze документ фиксирует только архитектурную модель Runner v2.2. Следующие аспекты намеренно НЕ входят в freeze:

### Stage A/B логика:
- Критерии отбора стратегий
- Метрики устойчивости
- Логика принятия решений

### Стратегия отбора:
- Параметры Runner (take_profit_levels, time_stop_minutes, etc.)
- Оптимизация параметров
- Backtesting конфигурации

### Оптимизация performance:
- Алгоритмы расчёта
- Кэширование
- Параллелизация

### Новые метрики:
- Дополнительные поля в CSV
- Новые агрегации
- Расширенная аналитика

### Execution profiles:
- Реалистичные/stress/custom multipliers
- Slippage модели
- Fee модели (кроме структуры fees_total_sol)

**Важно:** Изменения в этих областях не должны нарушать инварианты, зафиксированные в этом freeze.

---

## 7. Как использовать этот документ (HOW TO USE THIS FREEZE)

### Как проверять регрессии:

1. **Проверка инвариантов:**
   - После любых изменений в PortfolioEngine или Reporter запустить тесты:
     - `tests/portfolio/test_fees_total_is_sum_of_executions.py`
     - `tests/infrastructure/test_reporter_dual_tables.py`
     - `tests/integration/test_runner_ladder_partial_exits.py`
   - Проверить, что `Σ executions.fees_sol == positions.fees_total_sol`

2. **Проверка семантики событий:**
   - Для сценария "TP partial + time_stop remainder":
     - В `portfolio_events.csv`: есть `POSITION_PARTIAL_EXIT` только для TP, есть `POSITION_CLOSED` (reason="time_stop")
     - В `portfolio_executions.csv`: есть `partial_exit` для TP, есть `final_exit` (reason="time_stop")
     - Нет `POSITION_PARTIAL_EXIT` с `is_remainder=True` в events

3. **Проверка связей:**
   - `final_exit.event_id` должен ссылаться на `POSITION_CLOSED.event_id`
   - Порядок событий должен быть монотонным

### Когда обязательно обновлять:

- **При изменении семантики закрытия позиций:**
  - Если меняется логика создания `POSITION_CLOSED` или `POSITION_PARTIAL_EXIT`
  - Если меняется определение `time_stop_triggered` или `ladder_reason`
  - Если меняется структура `remainder_exit_data`

- **При изменении инвариантов:**
  - Если меняется правило расчёта `fees_total_sol`
  - Если меняется связь между events и executions
  - Если меняется структура `portfolio_positions.csv`

- **При добавлении новых полей:**
  - Если добавляются новые обязательные поля в meta
  - Если меняется формат CSV (колонки)

### Когда запрещено менять без нового freeze:

- **Запрещено менять без нового freeze:**
  - Семантику `POSITION_CLOSED` и `POSITION_PARTIAL_EXIT`
  - Правила определения `reason` и `time_stop_triggered`
  - Инвариант `Σ executions.fees_sol == positions.fees_total_sol`
  - Структуру `remainder_exit_data`
  - Связь `final_exit.event_id` → `POSITION_CLOSED.event_id`

- **Если нужно изменить зафиксированное поведение:**
  1. Создать новый freeze документ (например, `ARCH_FREEZE_RUNNER_v2.3.md`)
  2. Описать изменения и причины
  3. Обновить baseline tag
  4. Получить согласование перед внедрением

---

## 8. Примеры использования

### Пример 1: TP partial + time_stop remainder

**Сценарий:**
- Позиция: 0.1 SOL, entry_price = 100
- Достигнут уровень 3x (20% закрыто)
- Price откатывается
- time_stop срабатывает (остаток 80% закрыт)

**В portfolio_events.csv:**
1. `POSITION_OPENED` (entry)
2. `POSITION_PARTIAL_EXIT` (reason="ladder_tp", level_xn=3.0, fraction=0.20) - TP partial
3. `POSITION_CLOSED` (reason="time_stop") - финальное закрытие остатка

**В portfolio_executions.csv:**
1. `entry` (qty_delta=+0.1, fees_sol=network_fee_entry)
2. `partial_exit` (qty_delta=-0.02, reason="ladder_tp", xn=3.0, fees_sol=fees_partial)
3. `final_exit` (qty_delta=-0.08, reason="time_stop", event_id=POSITION_CLOSED.event_id, fees_sol=fees_remainder)

**В portfolio_positions.csv:**
- `fees_total_sol = network_fee_entry + fees_partial + fees_remainder`
- `pnl_sol = pnl_partial + pnl_remainder`
- `realized_multiple = 0.2 * 3.0 + 0.8 * (exit_price / entry_price)`

### Пример 2: Полное закрытие на уровнях

**Сценарий:**
- Позиция: 0.1 SOL, entry_price = 100
- Достигнуты уровни 3x (20%), 7x (30%), 15x (50%)
- Позиция закрыта полностью на уровнях

**В portfolio_events.csv:**
1. `POSITION_OPENED` (entry)
2. `POSITION_PARTIAL_EXIT` (reason="ladder_tp", level_xn=3.0, fraction=0.20)
3. `POSITION_PARTIAL_EXIT` (reason="ladder_tp", level_xn=7.0, fraction=0.30)
4. `POSITION_PARTIAL_EXIT` (reason="ladder_tp", level_xn=15.0, fraction=0.50)
5. `POSITION_CLOSED` (reason="ladder_tp") - финальное закрытие

**В portfolio_executions.csv:**
1. `entry` (qty_delta=+0.1, fees_sol=network_fee_entry)
2. `partial_exit` (qty_delta=-0.02, reason="ladder_tp", xn=3.0, fees_sol=fees_partial_1)
3. `partial_exit` (qty_delta=-0.03, reason="ladder_tp", xn=7.0, fees_sol=fees_partial_2)
4. `partial_exit` (qty_delta=-0.05, reason="ladder_tp", xn=15.0, fees_sol=fees_partial_3)
5. `final_exit` (qty_delta=0.0, reason="ladder_tp", event_id=POSITION_CLOSED.event_id, fees_sol=0.0)

**В portfolio_positions.csv:**
- `fees_total_sol = network_fee_entry + fees_partial_1 + fees_partial_2 + fees_partial_3`
- `pnl_sol = pnl_partial_1 + pnl_partial_2 + pnl_partial_3`
- `realized_multiple = 0.2 * 3.0 + 0.3 * 7.0 + 0.5 * 15.0`

---

## 9. Контакты и обновления

**Этот документ зафиксирован для Runner v2.2.**

**Для изменений:**
- Создать новый freeze документ с обновлённой версией
- Описать причины изменений
- Получить согласование перед внедрением

**Вопросы:**
- Если обнаружено несоответствие между кодом и этим документом → создать issue
- Если нужны изменения в зафиксированном поведении → создать proposal для нового freeze

---

**END OF FREEZE DOCUMENT**

