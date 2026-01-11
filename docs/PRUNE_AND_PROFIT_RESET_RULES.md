# Полная спецификация механики Capacity Prune и Profit Reset

## TL;DR

**Profit Reset** — механизм закрытия всех открытых позиций при достижении портфелем целевого уровня equity (относительно начала цикла). Используется для фиксации прибыли и перезапуска цикла торговли.

**Capacity Prune** — механизм частичного закрытия "плохих" позиций при превышении лимитов портфеля (capacity pressure). Закрывает только часть позиций, не сбрасывает profit cycle.

**Разница:** Profit reset закрывает ВСЕ позиции и сбрасывает цикл (обновляет `cycle_start_equity`). Capacity prune закрывает ЧАСТЬ позиций и НЕ сбрасывает цикл.

**Scope:** Runner-only, portfolio-level policies.

---

## 1. Термины и определения

### Equity / Balance / Realized PnL

**[FOUND]** `backtester/domain/portfolio_reset.py:111-113`

- **Equity** = `balance + sum(p.size for p in open_positions)` — текущая стоимость портфеля (баланс + открытые позиции)
- **Balance** — доступный баланс в SOL (уже уменьшенный на размер открытых позиций)
- **Realized PnL** — реализованная прибыль/убыток из закрытых позиций

### Cycle: cycle_start_equity, equity_peak_in_cycle, cycle_start_balance

**[FOUND]** `backtester/domain/portfolio.py:216-217` и `backtester/domain/portfolio_reset.py:96-97`

- **cycle_start_equity** (float) — Equity в начале текущего цикла (сбрасывается после reset)
- **equity_peak_in_cycle** (float) — Пик equity в текущем цикле (обновляется при росте equity)
- **cycle_start_balance** (float) — Реализованный баланс (cash) в начале текущего цикла (для realized_balance trigger, сбрасывается после reset)

**[FOUND]** `backtester/domain/portfolio_reset.py:115-119` — метод `update_equity_peak()` обновляет `equity_peak_in_cycle` до текущей equity, если текущая equity больше.

### "Forced close" и "Manual close"

**[FOUND]** `backtester/domain/portfolio.py:344-451` — метод `_forced_close_position()` используется для принудительного закрытия позиций при reset/prune.

- **Forced close** — закрытие позиции по reset/prune (не по стратегии)
- **Manual close** — тип закрытия, используемый в ExecutionModel для forced close (применяет slippage)

### Capacity / Exposure / max_positions / max_exposure

**[FOUND]** `backtester/domain/portfolio.py:98-142` — `PortfolioConfig`:

- **max_open_positions** (int) — максимальное количество открытых позиций
- **max_exposure** (float) — максимальная доля капитала в открытых позициях (0.5 = 50%)
- **capacity_open_ratio_threshold** (float) — порог заполненности (1.0 = 100%)
- **capacity_max_blocked_ratio** (float) — максимальная доля отклоненных сигналов (0.4 = 40%)
- **capacity_max_avg_hold_days** (float) — максимальное среднее время удержания (10.0 дней)

### Reason vs Canonical Reason Family

**[FOUND]** `backtester/domain/portfolio_events.py:40` — Canonical reasons: `ladder_tp`, `stop_loss`, `time_stop`, `capacity_prune`, `profit_reset`, `manual_close`, `no_entry`, `error`

**[INFERRED]** Reset/prune reasons не нормализуются — используются как есть: `"profit_reset"`, `"capacity_prune"`.

---

## 2. Карта кода (Code Map)

| Компонент | Файл | Функция/метод | Роль | Маркер |
|-----------|------|---------------|------|--------|
| Profit Reset — Trigger Condition | `backtester/domain/portfolio.py` | `run()` строки 2241-2243 | Проверка `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple` | FOUND |
| Profit Reset — Execution | `backtester/domain/portfolio.py` | `_apply_reset()` строки 1057-1233 | Вызов `apply_portfolio_reset()` и эмиссия событий | FOUND |
| Profit Reset — Core Logic | `backtester/domain/portfolio_reset.py` | `apply_portfolio_reset()` строки 154-321 | Закрытие позиций, обновление счетчиков, сброс цикла | FOUND |
| Capacity Prune — Trigger Condition | `backtester/domain/portfolio.py` | `_maybe_apply_capacity_prune()` строки 670-730 | Проверка capacity pressure (open_ratio, blocked_ratio, avg_hold_days) | FOUND |
| Capacity Prune — Selection | `backtester/domain/portfolio.py` | `_select_capacity_prune_candidates()` строки 593-668 | Фильтрация кандидатов по hold_days, mcap_usd, current_pnl_pct, protect_min_max_xn | FOUND |
| Capacity Prune — Execution | `backtester/domain/portfolio.py` | `_maybe_apply_capacity_prune()` строки 798-895 | Закрытие выбранных позиций, обновление счетчиков prune (НЕ reset счетчики) | FOUND |
| Forced Close — Unified Method | `backtester/domain/portfolio.py` | `_forced_close_position()` строки 344-451 | Единый метод для принудительного закрытия (reset/prune) | FOUND |
| Reporting — Positions CSV | `backtester/infrastructure/reporter.py` | `save_portfolio_positions_table()` строки 979-1223 | Экспорт positions с полями `closed_by_reset`, `reset_reason`, `triggered_portfolio_reset` | FOUND |
| Reporting — Events CSV | `backtester/infrastructure/reporter.py` | `save_portfolio_events_table()` строки 1225-1316 | Экспорт событий `POSITION_CLOSED` и `PORTFOLIO_RESET_TRIGGERED` | FOUND |
| Reporting — Policy Summary | `backtester/infrastructure/reporter.py` | `save_portfolio_policy_summary()` строки 1610-1703 | Экспорт статистики reset/prune (`portfolio_reset_profit_count`, `portfolio_capacity_prune_count`) | FOUND |
| Audit — Reset Checks | `backtester/audit/invariants.py` | `check_reset_consistency()` строки 120-148 | Проверка наличия `PORTFOLIO_RESET_TRIGGERED` при reset activity | FOUND |

---

## 3. Profit Reset — Trigger Conditions

### Параметры конфигурации

**[FOUND]** `backtester/domain/portfolio.py:114-175` — `PortfolioConfig`:

- **profit_reset_enabled** (Optional[bool]) — включить/выключить profit reset
- **profit_reset_multiple** (Optional[float]) — множитель для порога (например, 1.3 = 130%, 2.0 = 200%)
  - **ВАЛИДАЦИЯ**: должен быть float > 1.0, иначе reset автоматически disabled
  - Если <= 1.0 или invalid (inf, nan) — reset disabled, warning в лог
- **profit_reset_trigger_basis** (Literal["equity_peak", "realized_balance"]) — основа для триггера reset (по умолчанию "equity_peak")

**[FOUND]** `backtester/domain/portfolio.py:147-175` — методы `resolved_profit_reset_enabled()` и `resolved_profit_reset_multiple()` с fallback на deprecated `runner_reset_enabled`/`runner_reset_multiple`.

### Точное условие срабатывания

**[FOUND]** `backtester/domain/portfolio.py:2405-2417`:

**Режим "equity_peak" (legacy, по умолчанию):**
```python
if self.config.profit_reset_trigger_basis == "equity_peak":
    reset_threshold = state.cycle_start_equity * self.config.resolved_profit_reset_multiple()
    should_trigger = state.equity_peak_in_cycle >= reset_threshold
```

**Формула:** `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`

**Режим "realized_balance" (новый):**
```python
elif self.config.profit_reset_trigger_basis == "realized_balance":
    reset_threshold = state.cycle_start_balance * self.config.resolved_profit_reset_multiple()
    should_trigger = state.balance >= reset_threshold
```

**Формула:** `balance >= cycle_start_balance * profit_reset_multiple`

**Различия:**
- **equity_peak**: проверяется ДО обработки EXIT событий, учитывает floating PnL открытых позиций
- **realized_balance**: проверяется ПОСЛЕ обработки EXIT событий, учитывает только реализованный cash balance (без floating PnL)

**[FOUND]** `backtester/domain/portfolio_reset.py:111-119` — `current_equity()` вычисляет equity как `balance + sum(p.size for p in open_positions)`, `update_equity_peak()` обновляет `equity_peak_in_cycle` если текущая equity больше.

### Когда проверяется

**[FOUND]** `backtester/domain/portfolio.py:2234-2290`:

1. **Обновление equity_peak** — перед обработкой событий на текущем timestamp (строка 2236)
2. **Проверка условия** — ДО обработки EXIT событий (строка 2238), чтобы закрыть позиции reset'ом, а не нормальным EXIT
3. **В event loop** — на каждом timestamp, где есть события

### Edge Cases

**[FOUND]** `backtester/domain/portfolio.py:2169` — `cycle_start_equity` инициализируется как `initial_balance` при старте.

**[INFERRED]** Если `cycle_start_equity == 0.0` и `profit_reset_multiple > 0`, условие `equity_peak_in_cycle >= 0` всегда истинно (но должно быть `> 0` для первого срабатывания).

**[FOUND]** `backtester/domain/portfolio.py:2263-2273` — если `marker_position` не найден, создается временная позиция с `signal_id="__profit_reset_marker__"`.

**[FOUND]** `backtester/domain/portfolio.py:2245-2248` — собираются только реальные открытые позиции (исключается marker по `meta["marker"]`).

### Anti-Spam Guard (v2.2)

**[FOUND]** `backtester/domain/portfolio.py:2467-2469` — anti-spam guard предотвращает повторные reset на одном timestamp:

- Если `last_portfolio_reset_time == current_time` — reset пропускается (уже был reset на этом timestamp)
- Это предотвращает множественные reset при неправильной конфигурации или багах
- **Инвариант**: reset не может срабатывать повторно "сразу же" без изменения цикла/баланса

---

## 4. Profit Reset — Execution Mechanics

### Предусловия

1. `profit_reset_enabled == True`
2. `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`
3. Есть открытые позиции (или marker_position)

### Порядок операций (Order-of-Operations)

**[FOUND]** `backtester/domain/portfolio.py:2281-2288` — вызов `_apply_reset()`:

1. **Сбор позиций для закрытия** (строки 2245-2279):
   - Собираются все открытые позиции (исключая marker)
   - Marker позиция отдельно

2. **Вызов apply_portfolio_reset()** (строка 1092 в `_apply_reset()`):

   **[FOUND]** `backtester/domain/portfolio_reset.py:154-321` — `apply_portfolio_reset()`:
   
   - **Force-close позиций из positions_to_force_close** (строки 188-237):
     - Для каждой позиции: получение mark price через `get_mark_price_for_position()`
     - Применение slippage через `execution_model.apply_exit(raw_exit_price, "manual_close")`
     - Вычисление PnL: `exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price`
     - Применение fees: `notional_returned = pos.size + exit_pnl_sol`, `fees_total = notional_returned - notional_after_fees`
     - Обновление позиции: `pos.exit_time = reset_time`, `pos.exit_price = raw_exit_price`, `pos.status = "closed"`
     - Meta поля: `closed_by_reset=True`, `reset_reason="profit_reset"`, `close_reason="profit_reset"`, `pnl_sol`, `fees_total_sol`
     - Возврат капитала: `state.balance += notional_after_fees`, `state.balance -= network_fee_exit`
   
   - **Закрытие marker_position** (строки 247-296):
     - Аналогично force-close, но дополнительно: `triggered_portfolio_reset=True`
   
   - **Обновление счетчиков reset** (строки 305-312):
     - `state.portfolio_reset_count += 1`
     - `state.portfolio_reset_profit_count += 1`
     - `state.last_portfolio_reset_time = reset_time`
     - `state.cycle_start_equity = state.balance` (НОВЫЙ цикл)
     - `state.equity_peak_in_cycle = state.cycle_start_equity` (СБРОС пика)

3. **Эмиссия событий** (строки 1096-1224 в `_apply_reset()`):

   **[FOUND]** `backtester/domain/portfolio.py:1141-1173` — POSITION_CLOSED events (ПЕРВЫМИ):
   
   - Для каждой закрытой позиции создается `PortfolioEvent.create_position_closed()`
   - `timestamp = reset_time` (строго reset_time, без +epsilon)
   - `reason = "profit_reset"` (строго "profit_reset", не нормализуется)
   - `position_id` обязателен
   - Meta: `closed_by_reset=True`, `reset_reason="profit_reset"`
   
   **[FOUND]** `backtester/domain/portfolio.py:1205-1224` — PORTFOLIO_RESET_TRIGGERED event (ПОСЛЕ всех POSITION_CLOSED):
   
   - Создается `PortfolioEvent.create_portfolio_reset_triggered()`
   - `timestamp = reset_time`
   - `reason = "profit_reset"`
   - `position_id = marker_position.position_id`
   - Meta: `cycle_start_equity`, `equity_peak_in_cycle`, `current_balance`, `reset_time`

### Какие позиции закрываются

**[FOUND]** `backtester/domain/portfolio.py:2245-2279`:

- **Все открытые позиции** (исключая marker по `meta["marker"]`)
- **Marker позиция** — всегда закрывается (даже если нет реальных позиций, строка 1135)

### Флаги и Meta поля

**[FOUND]** `backtester/domain/portfolio_reset.py:226-232` — для позиций из positions_to_force_close:
- `closed_by_reset = True`
- `reset_reason = "profit_reset"`
- `close_reason = "profit_reset"`
- `pnl_sol` (вычисленный)
- `fees_total_sol` (вычисленный)
- `network_fee_sol` (обновляется)

**[FOUND]** `backtester/domain/portfolio_reset.py:283-290` — для marker_position дополнительно:
- `triggered_portfolio_reset = True`

### Exit Price и Timestamp

**[FOUND]** `backtester/domain/portfolio_reset.py:122-151` — `get_mark_price_for_position()`:
1. Приоритет 1: `pos.exit_price` (если есть)
2. Приоритет 2: `pos.meta["raw_exit_price"]` (если есть)
3. Fallback: `pos.entry_price` (помечается `meta["reset_exit_price_fallback"]=True`)

**[FOUND]** `backtester/domain/portfolio_reset.py:190-193` — применение slippage:
- `effective_exit_price = execution_model.apply_exit(raw_exit_price, "manual_close")`

**[FOUND]** `backtester/domain/portfolio.py:2284` — `reset_time = current_time` (timestamp события, на котором сработал reset)

### Обновление Cycle/Peak

**[FOUND]** `backtester/domain/portfolio_reset.py:311-312`:
- `state.cycle_start_equity = state.balance` (НОВЫЙ цикл начинается с текущего баланса)
- `state.equity_peak_in_cycle = state.cycle_start_equity` (пик сбрасывается на начало цикла)

### Постусловия

1. Все открытые позиции закрыты (`open_positions` не содержит позиций, кроме marker)
2. Marker позиция закрыта (`status="closed"`, `triggered_portfolio_reset=True`)
3. `cycle_start_equity` обновлен на текущий баланс
4. `equity_peak_in_cycle` сброшен на `cycle_start_equity`
5. `portfolio_reset_profit_count` увеличен на 1
6. Все закрытые позиции имеют `POSITION_CLOSED` событие с `reason="profit_reset"`
7. Есть `PORTFOLIO_RESET_TRIGGERED` событие с `reason="profit_reset"`

---

## 5. Profit Reset — Ledger & Reporting Contract

### portfolio_events.csv

**[FOUND]** `backtester/infrastructure/reporter.py:1225-1316` — `save_portfolio_events_table()`:

**Обязательные события:**

1. **POSITION_CLOSED** (N событий, по одной на закрытую позицию):
   - `event_type = "position_closed"`
   - `timestamp = reset_time` (ISO)
   - `reason = "profit_reset"`
   - `position_id` (обязателен, UUID)
   - `signal_id`, `contract_address`, `strategy`
   - `meta_json` содержит: `entry_time`, `exit_time`, `fees_total_sol`, `closed_by_reset=True`, `reset_reason="profit_reset"`

2. **PORTFOLIO_RESET_TRIGGERED** (1 событие):
   - `event_type = "portfolio_reset_triggered"`
   - `timestamp = reset_time` (ISO)
   - `reason = "profit_reset"`
   - `position_id = marker_position.position_id`
   - `meta_json` содержит: `reset_time`, `cycle_start_equity`, `equity_peak_in_cycle`, `current_balance`, `closed_positions_count`

**Порядок:** POSITION_CLOSED события ДО PORTFOLIO_RESET_TRIGGERED (по timestamp одинаковые, но порядок в списке событий).

### portfolio_positions.csv

**[FOUND]** `backtester/infrastructure/reporter.py:979-1223` — `save_portfolio_positions_table()`:

**Обязательные поля для закрытых позиций:**

- `status = "closed"`
- `exit_time` (ISO, не пустое)
- `reason = "profit_reset"` (или из `meta["close_reason"]`)
- `closed_by_reset = True`
- `reset_reason = "profit_reset"`
- `triggered_portfolio_reset = True` (только для marker позиции)
- `pnl_sol` (вычисленный)
- `fees_total_sol` (вычисленный)
- `exec_exit_price`, `raw_exit_price`

### portfolio_executions.csv

**[FOUND]** `backtester/infrastructure/reporter.py:1324-1608` — `save_portfolio_executions_table()`:

**Для каждой закрытой позиции должно быть execution типа "final_exit":**

- `event_type = "final_exit"`
- `event_time = reset_time` (ISO)
- `event_id` ссылается на `POSITION_CLOSED.event_id`
- `reason = "profit_reset"`
- `qty_delta = -remaining_size` (отрицательное)
- `raw_price`, `exec_price`
- `fees_sol` (включает network_fee если учитывается)
- `pnl_sol_delta = pnl_sol` позиции

---

## 6. Capacity Prune — Trigger Conditions

### Параметры конфигурации

**[FOUND]** `backtester/domain/portfolio.py:130-141` — `PortfolioConfig`:

- **capacity_reset_enabled** (bool, default=True) — включить/выключить capacity reset/prune
- **capacity_reset_mode** (Literal["close_all", "prune"], default="close_all") — режим: "prune" для частичного закрытия
- **capacity_open_ratio_threshold** (float, default=1.0) — порог заполненности (1.0 = 100%)
- **capacity_max_blocked_ratio** (float, default=0.4) — максимальная доля отклоненных сигналов (0.4 = 40%)
- **capacity_max_avg_hold_days** (float, default=10.0) — максимальное среднее время удержания (10.0 дней)
- **prune_cooldown_signals** (int, default=0) — cooldown по количеству сигналов (0 = отключен)
- **prune_cooldown_days** (Optional[float], default=None) — cooldown по времени в днях (None = отключен)
- **prune_min_candidates** (int, default=3) — минимальное количество кандидатов для выполнения prune

### Точные условия срабатывания

**[FOUND]** `backtester/domain/portfolio.py:693-730` — `_maybe_apply_capacity_prune()`:

1. **capacity_reset_enabled == True** (строка 693)
2. **capacity_reset_mode == "prune"** (строка 696)
3. **Cooldown не активен** (строки 700-708):
   - Если `prune_cooldown_signals > 0`, проверка `signal_index >= capacity_prune_cooldown_until_signal_index`
   - Если `prune_cooldown_days is not None`, проверка `current_time >= capacity_prune_cooldown_until_time`
4. **open_ratio >= capacity_open_ratio_threshold** (строки 715-717):
   - `open_ratio = len(open_positions) / max_open_positions`
   - `open_ratio >= 1.0` (по умолчанию)
5. **blocked_ratio >= capacity_max_blocked_ratio** (строки 719-725):
   - `blocked_ratio = blocked_by_capacity_in_window / signals_in_window`
   - `blocked_ratio >= 0.4` (по умолчанию)
6. **avg_hold_days >= capacity_max_avg_hold_days** (строки 727-730):
   - `avg_hold_days >= 10.0` (по умолчанию)

Все условия должны выполняться одновременно (AND).

### Когда проверяется

**[FOUND]** `backtester/domain/portfolio.py:2403-2426` — в event loop после проверки profit reset (если profit reset не сработал):

```python
# Проверка capacity reset/prune (только если profit reset не сработал)
if not profit_reset_triggered_before_exit:
    if self.config.capacity_reset_mode == "prune":
        prune_applied = self._maybe_apply_capacity_prune(...)
```

### Edge Cases

**[FOUND]** `backtester/domain/portfolio.py:735-739` — если кандидатов меньше `prune_min_candidates`, prune НЕ выполняется (возврат False).

**[FOUND]** `backtester/domain/portfolio.py:775-776` — если после фильтрации кандидатов `positions_to_prune` пуст, возврат False.

---

## 7. Capacity Prune — Selection Mechanics

### Алгоритм выбора кандидатов

**[FOUND]** `backtester/domain/portfolio.py:593-668` — `_select_capacity_prune_candidates()`:

**Фильтрация (все условия должны выполняться):**

1. **hold_days >= prune_min_hold_days** (строки 619-623):
   - `hold_days = (current_time - pos.entry_time).total_seconds() / (24 * 3600)`
   - По умолчанию `prune_min_hold_days = 1.0` день

2. **mcap_usd <= prune_max_mcap_usd** (строки 625-639):
   - Источники mcap: `pos.meta["mcap_usd"]`, `pos.meta["mcap_usd_at_entry"]`, `pos.meta["entry_mcap_proxy"]`
   - По умолчанию `prune_max_mcap_usd = 20000.0` USD
   - Если mcap неизвестно (None) — фильтр НЕ применяется (v1.9: robust к None)

3. **current_pnl_pct <= prune_max_current_pnl_pct** (строки 641-645):
   - Вычисляется через `_compute_current_pnl_pct()` (mark-to-market)
   - По умолчанию `prune_max_current_pnl_pct = -0.30` (-30%)
   - Только убыточные позиции (или небольшая прибыль)

4. **protect_min_max_xn** (строки 647-663):
   - Если `prune_protect_min_max_xn is not None` (по умолчанию 2.0), позиции с `max_xn >= 2.0` защищены от prune
   - Источники max_xn: `pos.meta["max_xn"]`, `pos.meta["max_xn_reached"]`, `levels_hit` (Runner)

### Сортировка и выбор

**[FOUND]** `backtester/domain/portfolio.py:741-765` — вычисление score:

- **Score формула** (строки 757-760):
  - `score = (-current_pnl_pct) * 100 + hold_days * 1.0`
  - Если mcap известен: `score += (prune_max_mcap_usd - mcap_usd) / prune_max_mcap_usd`
- **Сортировка:** по score DESC (более "плохие" первыми, строка 765)

**[FOUND]** `backtester/domain/portfolio.py:767-772` — выбор количества:

- `prune_count = max(1, int(prune_fraction * len(candidates)))`
- `prune_fraction` по умолчанию 0.5 (50%)
- Берется top-K кандидатов: `positions_to_prune = candidate_scores[:prune_count]`

### Сколько закрываем

**[FOUND]** `backtester/domain/portfolio.py:767-769`:
- Минимум 1 позиция (даже если `prune_fraction * len(candidates) < 1`)
- Максимум `len(candidates)` (не больше кандидатов)

### Исключения

**[FOUND]** `backtester/domain/portfolio.py:647-663` — защита tail позиций:
- Позиции с `max_xn >= prune_protect_min_max_xn` (по умолчанию 2.0) исключаются из кандидатов

**[FOUND]** `backtester/domain/portfolio.py:616-617` — только открытые позиции:
- `pos.status == "open"` и `pos.entry_time is not None`

### Fallback

**[FOUND]** `backtester/domain/portfolio.py:735-739` — если кандидатов меньше `prune_min_candidates`, prune НЕ выполняется.

---

## 8. Capacity Prune — Execution Mechanics

### Порядок операций

**[FOUND]** `backtester/domain/portfolio.py:798-895` — `_maybe_apply_capacity_prune()`:

1. **Эмиссия PORTFOLIO_RESET_TRIGGERED события** (строки 778-797):
   - Создается ДО закрытия позиций
   - `reason = "capacity_prune"`
   - `position_id = marker_position.position_id` (первая позиция из positions_to_prune)
   - Meta: `open_ratio`, `blocked_window`, `signals_in_window`, `avg_hold_days`, `closed_positions_count`

2. **Закрытие выбранных позиций** (строки 799-851):
   - Для каждой позиции вызывается `_forced_close_position()`:
     - `reset_reason = "capacity_prune"`
     - `additional_meta`: `capacity_prune=True`, `capacity_prune_trigger_time`, `capacity_prune_current_pnl_pct`, `capacity_prune_mcap_usd`, `capacity_prune_hold_days`, `capacity_prune_score`
   - Возврат капитала: `state.balance += notional_after_fees`, `state.balance -= network_fee_exit`

3. **Удаление из open_positions** (строки 853-857):
   - `state.open_positions = [p for p in open_positions if p.signal_id not in pruned_signal_ids]`

4. **Обновление счетчиков prune** (строки 859-861):
   - `state.portfolio_capacity_prune_count += 1`
   - `state.last_capacity_prune_time = current_time`
   - **ВАЖНО:** НЕ обновляются `portfolio_reset_count`, `cycle_start_equity`, `equity_peak_in_cycle`

5. **Установка cooldown** (строки 863-869):
   - Если `prune_cooldown_signals > 0`: `capacity_prune_cooldown_until_signal_index = signal_index + prune_cooldown_signals`
   - Если `prune_cooldown_days is not None`: `capacity_prune_cooldown_until_time = current_time + timedelta(days=prune_cooldown_days)`

6. **Сохранение статистики** (строки 871-887):
   - Добавление в `state.capacity_prune_events` (список событий для observability)

### Reason и Canonical Reason

**[FOUND]** `backtester/domain/portfolio.py:831` — `reset_reason = "capacity_prune"`

**[FOUND]** `backtester/domain/portfolio.py:787` — событие `PORTFOLIO_RESET_TRIGGERED` с `reason="capacity_prune"`

### Meta Flags

**[FOUND]** `backtester/domain/portfolio.py:832-839` — для каждой закрытой позиции:
- `capacity_prune = True`
- `capacity_prune_trigger_time = current_time.isoformat()`
- `capacity_prune_current_pnl_pct` (current_pnl_pct до закрытия)
- `capacity_prune_mcap_usd`
- `capacity_prune_hold_days`
- `capacity_prune_score`

**[FOUND]** `backtester/domain/portfolio.py:401-404` — через `_forced_close_position()` также устанавливаются:
- `closed_by_reset = True`
- `reset_reason = "capacity_prune"`
- `close_reason = "capacity_prune"`

### Exit Price и Timestamp

**[FOUND]** `backtester/domain/portfolio.py:344-451` — `_forced_close_position()` использует тот же механизм, что и profit reset:
- Mark price через `get_mark_price_for_position()`
- Slippage через `execution_model.apply_exit(raw_exit_price, "manual_close")`
- `exit_time = current_time`

### Постусловия

1. Часть открытых позиций закрыта (но НЕ все)
2. `portfolio_capacity_prune_count` увеличен на 1
3. `last_capacity_prune_time` обновлен
4. Cooldown установлен (если настроен)
5. **НЕ обновлены:** `cycle_start_equity`, `equity_peak_in_cycle`, `portfolio_reset_count`
6. Все закрытые позиции имеют `POSITION_CLOSED` событие с `reason="capacity_prune"`
7. Есть `PORTFOLIO_RESET_TRIGGERED` событие с `reason="capacity_prune"`

---

## 9. Capacity Prune — Ledger & Reporting Contract

### portfolio_events.csv

**[FOUND]** `backtester/infrastructure/reporter.py:1225-1316`:

**Обязательные события:**

1. **POSITION_CLOSED** (N событий, по одной на закрытую позицию):
   - `event_type = "position_closed"`
   - `timestamp = prune_time` (ISO)
   - `reason = "capacity_prune"`
   - `position_id` (обязателен)
   - `meta_json` содержит: `capacity_prune=True`, `capacity_prune_trigger_time`, `capacity_prune_current_pnl_pct`, etc.

2. **PORTFOLIO_RESET_TRIGGERED** (1 событие):
   - `event_type = "portfolio_reset_triggered"`
   - `timestamp = prune_time` (ISO)
   - `reason = "capacity_prune"`
   - `position_id = marker_position.position_id`
   - `meta_json` содержит: `open_ratio`, `blocked_window`, `signals_in_window`, `avg_hold_days`, `closed_positions_count`

### portfolio_positions.csv

**[FOUND]** `backtester/infrastructure/reporter.py:979-1223`:

**Обязательные поля для закрытых позиций:**

- `status = "closed"`
- `exit_time` (ISO)
- `reason = "capacity_prune"`
- `closed_by_reset = True`
- `reset_reason = "capacity_prune"`
- `triggered_portfolio_reset = False` (prune НЕ триггерит portfolio reset)
- Meta поля: `capacity_prune=True`, `capacity_prune_trigger_time`, `capacity_prune_current_pnl_pct`, etc.

### portfolio_policy_summary.csv

**[FOUND]** `backtester/infrastructure/reporter.py:1610-1703` — `save_portfolio_policy_summary()`:

**Обязательные поля:**

- `portfolio_capacity_prune_count` (int) — количество срабатываний prune
- `avg_pruned_positions_per_event` (float) — среднее количество закрытых позиций за событие
- `median_pruned_hold_days` (float) — медианное время удержания закрытых позиций
- `median_pruned_current_pnl_pct` (float) — медианный current_pnl_pct закрытых позиций
- `pruned_positions_share_of_all_closed` (float) — доля prune позиций от всех закрытых

---

## 10. Audit Invariants & Failure Modes

### Проверки в invariants.py

**[FOUND]** `backtester/audit/invariants.py:120-148` — `check_reset_consistency()`:

**Проверка:** Если есть позиции с `reset_reason in {"profit_reset", "capacity_prune"}`, должно быть событие `PORTFOLIO_RESET_TRIGGERED` с соответствующим reason.

**[FOUND]** `backtester/audit/invariants.py:47-48` — `AnomalyType`:

- `RESET_WITHOUT_EVENTS` — Reset без соответствующих событий
- `PRUNE_WITHOUT_EVENTS` — Prune без событий

**[FOUND]** `backtester/audit/invariants.py:90-96` — P2 checks:

- `PROFIT_RESET_TRIGGERED_BUT_CONDITION_FALSE` — Reset сработал, но условие не выполнено
- `PROFIT_RESET_CONDITION_TRUE_BUT_NO_RESET` — Условие выполнено, но reset не сработал
- `CAPACITY_ACTION_TRIGGERED_BUT_THRESHOLDS_NOT_MET` — Prune/reset сработал, но пороги не превышены
- `CAPACITY_THRESHOLDS_MET_BUT_NO_ACTION` — Пороги превышены, но действие не сработало
- `CLOSE_ALL_WITHOUT_POLICY_EVENT` — Close-all без policy event
- `CLOSE_ALL_DID_NOT_CLOSE_ALL_POSITIONS` — Close-all не закрыл все позиции

### Failure Modes

**[INFERRED]** На основе кода и тестов:

1. **Reset закрывает позицию, но event отсутствует:**
   - P1 аномалия: `POSITION_CLOSED_BUT_NO_CLOSE_EVENT`
   - Источник: ошибка в `_apply_reset()` или `_maybe_apply_capacity_prune()`

2. **Reset event без закрытых позиций:**
   - P1 аномалия: `RESET_WITHOUT_EVENTS`
   - Источник: ошибка в порядке эмиссии событий

3. **Условие reset выполнено, но reset не сработал:**
   - P2 аномалия: `PROFIT_RESET_CONDITION_TRUE_BUT_NO_RESET`
   - Источник: ошибка в проверке условия или timing

4. **Prune закрыл позицию, но цикл сброшен:**
   - P1 аномалия: нарушение инварианта (prune НЕ должен сбрасывать цикл)
   - Источник: ошибка в `_maybe_apply_capacity_prune()` (не должна вызывать `apply_portfolio_reset()` для profit reset)

---

## 11. Test Contract

### Найденные тесты

**[FOUND]** `tests/portfolio/test_portfolio_replay.py:248` — `test_replay_profit_reset_emits_chain`:

**Что гарантирует:**
- Есть `PORTFOLIO_RESET_TRIGGERED` event
- Все позиции закрыты с `reason="profit_reset"`
- Правильный порядок событий (POSITION_CLOSED → PORTFOLIO_RESET_TRIGGERED)

**Команда запуска:**
```bash
pytest tests/portfolio/test_portfolio_replay.py::test_replay_profit_reset_emits_chain -v
```

**[TBD]** Тесты для capacity prune не найдены через grep (возможно, в других файлах или через integration tests).

**Где искали:**
- `tests/portfolio/` — найден только profit reset тест
- `tests/infrastructure/test_reporter_policy_summary.py` — возможно, есть тесты для policy summary

### Missing Tests (Future Work)

**[INFERRED]** На основе анализа кода, рекомендуемые тесты:

1. **Capacity Prune — Trigger Conditions:**
   - Тест: prune срабатывает при выполнении всех условий
   - Тест: prune НЕ срабатывает при cooldown
   - Тест: prune НЕ срабатывает при недостаточном количестве кандидатов

2. **Capacity Prune — Selection:**
   - Тест: правильная фильтрация кандидатов (hold_days, mcap_usd, current_pnl_pct)
   - Тест: защита tail позиций (prune_protect_min_max_xn)
   - Тест: правильная сортировка по score

3. **Capacity Prune — Execution:**
   - Тест: правильный порядок событий (POSITION_CLOSED → PORTFOLIO_RESET_TRIGGERED)
   - Тест: цикл НЕ сброшен после prune

4. **Profit Reset — Edge Cases:**
   - Тест: reset при пустом портфеле (только marker)
   - Тест: reset при cycle_start_equity=0

---

## 12. История изменений (Git)

### Релевантные коммиты

**[FOUND]** Через `git log -S "profit_reset"` и `git log -S "capacity_prune"`:

| Дата | Commit Hash | Subject | Что изменилось | Почему важно | Риск регресса |
|------|-------------|---------|----------------|--------------|---------------|
| - | fa4cc30 | Enhance PortfolioEngine to ensure creation of POSITION_CLOSED events for all closed positions | Гарантия создания POSITION_CLOSED для всех закрытых позиций | Критично для audit контракта | P1: пропущенные события |
| - | 4e720a7 | Refactor profit reset logic in PortfolioEngine to improve state management and event handling | Рефактор profit reset логики | Улучшение состояния и событий | P1: неправильный порядок событий |
| - | 3b663c1 | Remove debug logging related to profit resets in PortfolioEngine and PortfolioReplay | Удаление debug логирования | Очистка кода | Низкий |
| - | 058457b | Improve snapshot handling in PortfolioEngine during profit resets | Улучшение snapshot handling | Критично для правильного состояния | P1: неправильное состояние после reset |
| - | 0d82d60 | Enhance profit reset handling in PortfolioEngine and PortfolioReplay | Улучшение обработки profit reset | Общие улучшения | Средний |
| - | 2b9324b | Refactor debug handling in PortfolioEngine and PortfolioReplay for reset events | Рефактор debug handling | Очистка кода | Низкий |
| - | fe9f7a3 | Refactor PortfolioEngine and PortfolioReplay for enhanced profit reset handling and event emission | Рефактор для улучшенной обработки и эмиссии событий | Критично для событий | P1: пропущенные события |
| - | ee08a55 | Enhance PortfolioEngine with profit reset handling and mathematical PnL calculations | Улучшение profit reset и PnL расчетов | Критично для корректности PnL | P1: неправильный PnL |

**[TBD]** Полные даты коммитов не получены (git log не вернул даты в формате --date=short). Рекомендуется выполнить `git log --format="%H|%ad|%s" --date=short` для получения полной информации.

**Где искали:**
- `git log -S "profit_reset" --oneline --date=short --all`
- `git log -S "capacity_prune" --oneline --date=short --all`
- `git log --oneline --date=short --all -- backtester/domain/portfolio.py`

---

## 13. Appendix: Examples

### Example A: Profit Reset срабатывает и закрывает позиции

**[INFERRED/EXAMPLE]** На основе `tests/portfolio/test_portfolio_replay.py:248` и `runs/C/reports/portfolio_positions.csv`:

**Сценарий:**
- Начальный баланс: 10.0 SOL
- `profit_reset_multiple = 1.3` (threshold = 13.0 SOL)
- Equity достигла 13.5 SOL → reset сработал
- Закрыто 3 позиции

**portfolio_events.csv:**
```csv
timestamp,event_type,strategy,signal_id,contract_address,position_id,reason,meta_json
2025-07-14T20:43:00+00:00,position_closed,Runner_Tail_3_7_15_20d,sig_1,TOKEN_A,uuid1,profit_reset,{"closed_by_reset":true,"reset_reason":"profit_reset"}
2025-07-14T20:43:00+00:00,position_closed,Runner_Tail_3_7_15_20d,sig_2,TOKEN_B,uuid2,profit_reset,{"closed_by_reset":true,"reset_reason":"profit_reset"}
2025-07-14T20:43:00+00:00,position_closed,Runner_Tail_3_7_15_20d,sig_3,TOKEN_C,uuid3,profit_reset,{"closed_by_reset":true,"reset_reason":"profit_reset"}
2025-07-14T20:43:00+00:00,portfolio_reset_triggered,Runner_Tail_3_7_15_20d,__profit_reset_marker__,__profit_reset_marker__,uuid_marker,profit_reset,{"closed_positions_count":3,"cycle_start_equity":13.5,"equity_peak_in_cycle":13.5}
```

**portfolio_positions.csv (выдержка):**
```csv
position_id,signal_id,status,exit_time,reason,closed_by_reset,reset_reason,triggered_portfolio_reset
uuid1,sig_1,closed,2025-07-14T20:43:00+00:00,profit_reset,True,profit_reset,False
uuid2,sig_2,closed,2025-07-14T20:43:00+00:00,profit_reset,True,profit_reset,False
uuid3,sig_3,closed,2025-07-14T20:43:00+00:00,profit_reset,True,profit_reset,False
uuid_marker,__profit_reset_marker__,closed,2025-07-14T20:43:00+00:00,profit_reset,True,profit_reset,True
```

### Example B: Capacity Prune закрывает N позиций

**[INFERRED/EXAMPLE]** На основе кода `_maybe_apply_capacity_prune()`:

**Сценарий:**
- `max_open_positions = 10`, открыто 10 позиций
- `open_ratio = 1.0 >= 1.0` ✅
- `blocked_ratio = 0.5 >= 0.4` ✅
- `avg_hold_days = 12.0 >= 10.0` ✅
- Найдено 6 кандидатов, `prune_fraction = 0.5` → закрыто 3 позиции

**portfolio_events.csv:**
```csv
timestamp,event_type,strategy,signal_id,contract_address,position_id,reason,meta_json
2025-07-15T10:00:00+00:00,position_closed,Runner_Tail_3_7_15_20d,sig_4,TOKEN_D,uuid4,capacity_prune,{"capacity_prune":true,"capacity_prune_trigger_time":"2025-07-15T10:00:00+00:00","capacity_prune_current_pnl_pct":-0.35}
2025-07-15T10:00:00+00:00,position_closed,Runner_Tail_3_7_15_20d,sig_5,TOKEN_E,uuid5,capacity_prune,{"capacity_prune":true,"capacity_prune_trigger_time":"2025-07-15T10:00:00+00:00","capacity_prune_current_pnl_pct":-0.40}
2025-07-15T10:00:00+00:00,position_closed,Runner_Tail_3_7_15_20d,sig_6,TOKEN_F,uuid6,capacity_prune,{"capacity_prune":true,"capacity_prune_trigger_time":"2025-07-15T10:00:00+00:00","capacity_prune_current_pnl_pct":-0.42}
2025-07-15T10:00:00+00:00,portfolio_reset_triggered,Runner_Tail_3_7_15_20d,sig_4,TOKEN_D,uuid4,capacity_prune,{"closed_positions_count":3,"open_ratio":1.0,"blocked_window":5,"signals_in_window":10}
```

**portfolio_positions.csv (выдержка):**
```csv
position_id,signal_id,status,exit_time,reason,closed_by_reset,reset_reason,triggered_portfolio_reset
uuid4,sig_4,closed,2025-07-15T10:00:00+00:00,capacity_prune,True,capacity_prune,False
uuid5,sig_5,closed,2025-07-15T10:00:00+00:00,capacity_prune,True,capacity_prune,False
uuid6,sig_6,closed,2025-07-15T10:00:00+00:00,capacity_prune,True,capacity_prune,False
```

**portfolio_policy_summary.csv:**
```csv
strategy,portfolio_reset_profit_count,portfolio_reset_capacity_count,portfolio_capacity_prune_count,avg_pruned_positions_per_event
Runner_Tail_3_7_15_20d,0,0,1,3.0
```

---

## 14. Заключение

Документ описывает текущую реализацию механизмов Profit Reset и Capacity Prune в проекте Solana Strategy Tester (Runner-only).

**Ключевые инварианты:**

1. **Profit Reset:** Закрывает ВСЕ позиции, сбрасывает цикл (`cycle_start_equity`, `equity_peak_in_cycle`), увеличивает `portfolio_reset_profit_count`
2. **Capacity Prune:** Закрывает ЧАСТЬ позиций, НЕ сбрасывает цикл, увеличивает только `portfolio_capacity_prune_count`
3. **События:** Порядок всегда POSITION_CLOSED (N событий) → PORTFOLIO_RESET_TRIGGERED (1 событие)
4. **Meta поля:** `closed_by_reset=True`, `reset_reason`, `close_reason` обязательны для всех закрытых позиций

**Источник истины:** Код в `backtester/domain/portfolio.py`, `backtester/domain/portfolio_reset.py`, `backtester/infrastructure/reporter.py`.

---

*Документ создан: 2025-01-XX*  
*Версия спецификации: 1.0*
