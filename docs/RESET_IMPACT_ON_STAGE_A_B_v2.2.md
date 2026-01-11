# Reset Impact on Research & Decision Layers v2.2

**Версия:** 2.2  
**Дата:** 2025-01-XX  
**Статус:** Канонический якорный документ влияния reset/prune на canonical ledger, Audit, Stage A/B

**Цель документа:** Формально и недвусмысленно описать, как Profit Reset и Capacity Prune влияют на canonical ledger, Audit (P0/P1), Stage A (Research) и Stage B (Decision). Документ позволяет понимать, почему стратегия проходит/не проходит Stage B, отделять portfolio policy от strategy quality, и дебажить аномалии без чтения кода.

---

## Содержание

1. [Executive Summary](#1-executive-summary)
2. [Reset как portfolio policy (AS-IS)](#2-reset-как-portfolio-policy-as-is)
3. [Reset → Canonical Ledger → Artifacts](#3-reset--canonical-ledger--artifacts)
4. [Влияние reset на Audit (P0/P1)](#4-влияние-reset-на-audit-p0p1)
5. [Влияние reset на Stage A (Research)](#5-влияние-reset-на-stage-a-research)
6. [Влияние reset на Stage B (Decision)](#6-влияние-reset-на-stage-b-decision)
7. [Edge cases и неочевидные последствия](#7-edge-cases-и-неочевидные-последствия)
8. [Debug Cookbook](#8-debug-cookbook)
9. [Do / Don't для будущих изменений](#9-do--dont-для-будущих-изменений)
10. [Привязка к исходникам](#10-привязка-к-исходникам)

---

## 1. Executive Summary

### Что такое Profit Reset и Capacity Prune

**Profit Reset** — механизм закрытия всех открытых позиций при достижении портфелем целевого уровня equity (относительно начала цикла). Используется для фиксации прибыли и перезапуска цикла торговли. См. `docs/PRUNE_AND_PROFIT_RESET_RULES.md` для детальной спецификации.

**Capacity Prune** — механизм частичного закрытия "плохих" позиций при превышении лимитов портфеля (capacity pressure). Закрывает только часть позиций, не сбрасывает profit cycle. См. `docs/PRUNE_AND_PROFIT_RESET_RULES.md` для детальной спецификации.

### Главная мысль

**Reset меняет распределение PnL и плотность сделок во времени → влияет на окна Stage A → влияет на gate Stage B.**

Reset/prune являются **portfolio-level политиками**, которые:
- Закрывают позиции по внестратегическим причинам (не по TP/SL/timeout)
- Создают временные кластеры закрытий (все позиции закрываются одновременно при reset)
- Меняют распределение hold_minutes (forced close может сократить время удержания)
- Меняют распределение PnL (reset может "зафиксировать" прибыль, prune может "обрезать" убытки)

Stage A/B работают с **executed positions** из `portfolio_positions.csv` и не различают причины закрытия — reset-закрытые позиции обрабатываются так же, как стратегические. Это **ожидаемое поведение** (reset — это часть портфельной политики), но требует осознанной интерпретации метрик.

### Главные риски и искажения

1. **Window clustering** — reset создает временные кластеры закрытий (все позиции закрываются одновременно), которые "склеивают" эффекты в одном временном окне
2. **Empty windows** — reset может создать "пустые окна" после закрытия всех позиций, что снижает `survival_rate` и увеличивает риск low-N проблем
3. **Forced close price** — если свечи отсутствуют, используется `entry_price` как fallback (`get_mark_price_for_position()`), что искажает `pnl_sol` и метрики
4. **Low-N amplification** — multiple reset cascade может создать серию пустых окон, что усиливает low-N проблемы (`windows_total < min_windows`)
5. **Variance distortion** — reset может "зафиксировать" прибыль и снизить `pnl_variance` / `pnl_variance_norm` (или наоборот, если reset происходит на убытках)
6. **Tail masking** — prune может закрыть tail позиции (если не защищены `prune_protect_min_max_xn`) или наоборот, оставить только tail, что искажает `tail_pnl_share` и `hit_rate_x4`

---

## 2. Reset как portfolio policy (AS-IS)

**📌 Важно:** Reset ≠ стратегия, reset ≠ исследовательская логика. Reset — это portfolio-level политика управления рисками.

### Profit Reset

**Триггер:**
- Условие: `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`
- Проверка: в event loop, ДО обработки EXIT событий
- Источник: `backtester/domain/portfolio.py:2241-2243`

**Какие позиции закрываются:**
- **Все открытые позиции** (исключая marker по `meta["marker"]`)
- **Marker позиция** — всегда закрывается (даже если нет реальных позиций)
- Источник: `backtester/domain/portfolio.py:2245-2279`

**Порядок операций:**
1. Сбор всех открытых позиций (исключая marker)
2. Force-close каждой позиции через `_forced_close_position()`:
   - Mark price через `get_mark_price_for_position()` (приоритет: `exit_price` → `meta["raw_exit_price"]` → `entry_price`)
   - Slippage через `execution_model.apply_exit(raw_exit_price, "manual_close")`
   - PnL вычисляется как `(effective_exit_price - exec_entry_price) / exec_entry_price`
   - Fees применяются к возвращаемому нотионалу
   - Meta: `closed_by_reset=True`, `reset_reason="profit_reset"`, `close_reason="profit_reset"`
3. Закрытие marker_position (аналогично, но дополнительно: `triggered_portfolio_reset=True`)
4. Эмиссия POSITION_CLOSED событий (по одной на закрытую позицию, timestamp = reset_time)
5. Эмиссия PORTFOLIO_RESET_TRIGGERED события (timestamp = reset_time, ПОСЛЕ всех POSITION_CLOSED)
6. Обновление счетчиков: `portfolio_reset_profit_count += 1`, `cycle_start_equity = balance`, `equity_peak_in_cycle = cycle_start_equity`
- Источник: `backtester/domain/portfolio_reset.py:154-321`, `backtester/domain/portfolio.py:1057-1233`

**Цена для forced close:**
- Приоритет 1: `pos.exit_price` (если есть)
- Приоритет 2: `pos.meta["raw_exit_price"]` (если есть)
- Fallback: `pos.entry_price` (помечается `meta["reset_exit_price_fallback"]=True`)
- Slippage: `execution_model.apply_exit(raw_exit_price, "manual_close")`
- Источник: `backtester/domain/portfolio_reset.py:122-151`

**PnL и fees:**
- `exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price`
- `exit_pnl_sol = pos.size * exit_pnl_pct`
- `notional_returned = pos.size + exit_pnl_sol`
- `fees_total = notional_returned - notional_after_fees` (swap + LP fees)
- `network_fee_exit` вычитается отдельно из баланса
- Источник: `backtester/domain/portfolio_reset.py:190-237`

**Marker position:**
- Marker позиция создается для гарантии наличия `position_id` для `PORTFOLIO_RESET_TRIGGERED` события
- `signal_id="__profit_reset_marker__"`
- Закрывается всегда (даже если нет реальных позиций)
- Имеет дополнительный флаг `triggered_portfolio_reset=True`
- Источник: `backtester/domain/portfolio.py:2263-2273`, `backtester/domain/portfolio_reset.py:247-296`

### Capacity Prune

**Триггер:**
- Условия (все должны выполняться одновременно):
  - `capacity_reset_enabled == True`
  - `capacity_reset_mode == "prune"`
  - Cooldown не активен
  - `open_ratio >= capacity_open_ratio_threshold` (по умолчанию 1.0)
  - `blocked_ratio >= capacity_max_blocked_ratio` (по умолчанию 0.4)
  - `avg_hold_days >= capacity_max_avg_hold_days` (по умолчанию 10.0)
- Проверка: в event loop, после проверки profit reset (если profit reset не сработал)
- Источник: `backtester/domain/portfolio.py:693-730`

**Какие позиции закрываются:**
- **Часть открытых позиций** (НЕ все) — только кандидаты из `_select_capacity_prune_candidates()`
- Критерии кандидатов:
  - `hold_days >= prune_min_hold_days` (по умолчанию 1.0)
  - `mcap_usd <= prune_max_mcap_usd` (по умолчанию 20000.0, если известен)
  - `current_pnl_pct <= prune_max_current_pnl_pct` (по умолчанию -0.30)
  - Защита tail: позиции с `max_xn >= prune_protect_min_max_xn` (по умолчанию 2.0) исключаются
- Сортировка: по score DESC (более "плохие" первыми)
- Количество: `max(1, int(prune_fraction * len(candidates)))` (по умолчанию 50%)
- Источник: `backtester/domain/portfolio.py:593-668`, `741-772`

**Порядок операций:**
1. Эмиссия PORTFOLIO_RESET_TRIGGERED события (ДО закрытия позиций, `reason="capacity_prune"`)
2. Force-close выбранных позиций через `_forced_close_position()`:
   - Аналогично profit reset (mark price, slippage, PnL, fees)
   - Meta: `closed_by_reset=True`, `reset_reason="capacity_prune"`, `close_reason="capacity_prune"`
   - Дополнительные meta: `capacity_prune=True`, `capacity_prune_trigger_time`, `capacity_prune_current_pnl_pct`, etc.
3. Удаление из `open_positions`
4. Эмиссия POSITION_CLOSED событий (по одной на закрытую позицию)
5. Обновление счетчиков: `portfolio_capacity_prune_count += 1`, **НЕ** обновляются `cycle_start_equity`, `equity_peak_in_cycle`, `portfolio_reset_count`
6. Установка cooldown (если настроен)
- Источник: `backtester/domain/portfolio.py:798-895`

**Цена для forced close:**
- Аналогично profit reset (приоритет: `exit_price` → `meta["raw_exit_price"]` → `entry_price`)
- Источник: `backtester/domain/portfolio.py:344-451`

**PnL и fees:**
- Аналогично profit reset
- Источник: `backtester/domain/portfolio.py:344-451`

**📌 Чётко указать:**
- reset ≠ стратегия
- reset ≠ исследовательская логика
- reset — это portfolio-level политика управления рисками

---

## 3. Reset → Canonical Ledger → Artifacts

**Таблица влияния reset на артефакты:**

| Artifact | Owner | Source of truth | Reset impact | Consumer |
|----------|-------|-----------------|--------------|----------|
| `portfolio_events.csv` | Portfolio | canonical ledger | + `PORTFOLIO_RESET_TRIGGERED` событие, + `POSITION_CLOSED` события с `reason="profit_reset"` / `"capacity_prune"` | Audit (invariants) |
| `portfolio_positions.csv` | Portfolio | positions (source of truth для Stage A) | forced closes (`closed_by_reset=True`, `reset_reason`), мета-поля (`triggered_portfolio_reset`, etc.) | Stage A (window aggregation) |
| `portfolio_executions.csv` | Portfolio | execution-level дебаг | + `final_exit` executions с `reason="profit_reset"` / `"capacity_prune"`, forced close prices | Audit (execution ↔ event consistency) |
| `strategy_stability.csv` | Stage A | derived (из `portfolio_positions.csv`) | window distortion (clustering, empty windows), variance distortion | Stage B (criteria check) |
| `strategy_selection_agg.csv` | Stage B | derived (из `strategy_stability.csv`) | robustness impact (aggregated metrics отражают reset-heavy поведение) | User (primary decision artifact) |

**Отдельно зафиксировать:**

- **Stage A читает только positions:** Stage A использует `portfolio_positions.csv` как единственный источник данных. Stage A НЕ должна читать `portfolio_events.csv` или `portfolio_executions.csv` для вычисления метрик. См. `docs/VARIABLES_REFERENCE.md` раздел 3: "Position-level variables".
- **Stage B читает только Stage A:** Stage B использует `strategy_stability.csv` (и `strategy_stability_agg.csv` если есть) как единственный источник данных. Stage B НЕ должна читать `portfolio_positions.csv` напрямую. См. `docs/VARIABLES_REFERENCE.md` раздел 6: "Stage B (Decision) variables".

**Детали для каждого артефакта:**

### portfolio_positions.csv — source of truth для Stage A

**Что это:** Positions-level агрегат всех executed позиций (закрытых позиций из портфеля).

**Создатель:** `backtester/infrastructure/reporter.py:save_portfolio_positions_table()` (строки 979-1223)

**Потребители:**
- Stage A (`backtester/research/strategy_stability.py`) — основной источник данных
- Audit (`backtester/audit/invariants.py`) — проверка инвариантов
- Reporting (статистика, графики)

**Что reset влияет:**
- **Добавляет строки** с закрытыми позициями (`status="closed"`)
- **Поля reset-закрытых позиций:**
  - `reason = "profit_reset"` или `"capacity_prune"`
  - `closed_by_reset = True`
  - `reset_reason = "profit_reset"` или `"capacity_prune"`
  - `triggered_portfolio_reset = True` (только для marker позиции profit reset)
  - `exit_time = reset_time` (одинаковый для всех позиций при reset)
  - `exit_price = raw_exit_price` (из `get_mark_price_for_position()`)
  - `pnl_sol`, `fees_total_sol` (вычисленные)
  - Meta поля: `capacity_prune=True`, `capacity_prune_trigger_time`, etc. (для prune)
- Источник: `backtester/infrastructure/reporter.py:979-1223`

**Важно:** Stage A читает `portfolio_positions.csv` и **не различает причины закрытия** — reset-закрытые позиции обрабатываются так же, как стратегические. Это ожидаемое поведение (reset — это часть портфельной политики).

### portfolio_events.csv — канонический ledger для audit/инвариантов (детали)

**Что это:** Канонический event ledger всех портфельных событий (POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED, PORTFOLIO_RESET_TRIGGERED).

**Создатель:** `backtester/infrastructure/reporter.py:save_portfolio_events_table()` (строки 1225-1316)

**Потребители:**
- Audit (`backtester/audit/invariants.py`) — проверка инвариантов (P0/P1)
- Debug (поиск причин аномалий)

**Что reset влияет:**
- **Добавляет события POSITION_CLOSED** (по одной на закрытую позицию):
  - `event_type = "position_closed"`
  - `timestamp = reset_time` (одинаковый для всех позиций при reset)
  - `reason = "profit_reset"` или `"capacity_prune"`
  - `position_id` (обязателен)
  - `meta_json` содержит: `closed_by_reset=True`, `reset_reason`, etc.
- **Добавляет событие PORTFOLIO_RESET_TRIGGERED** (1 событие):
  - `event_type = "portfolio_reset_triggered"`
  - `timestamp = reset_time`
  - `reason = "profit_reset"` или `"capacity_prune"`
  - `position_id = marker_position.position_id` (для profit reset) или первая позиция из prune (для capacity prune)
  - `meta_json` содержит: `cycle_start_equity`, `equity_peak_in_cycle`, `closed_positions_count`, etc.
- **Порядок:** POSITION_CLOSED события ДО PORTFOLIO_RESET_TRIGGERED (по timestamp одинаковые, но порядок в списке событий)
- Источник: `backtester/infrastructure/reporter.py:1225-1316`

**Важно:** Audit проверяет инварианты на основе событий (например, `check_reset_consistency()` проверяет наличие `PORTFOLIO_RESET_TRIGGERED` при reset activity). См. раздел "Влияние reset на Audit".

### portfolio_executions.csv — execution-level дебаг (детали)

**Что это:** Execution-level агрегат всех исполнений (entry, partial_exit, final_exit) с ценами, комиссиями, slippage.

**Создатель:** `backtester/infrastructure/reporter.py:save_portfolio_executions_table()` (строки 1324-1608)

**Потребители:**
- Audit (`backtester/audit/invariants.py`) — проверка инвариантов (execution ↔ event consistency)
- Debug (поиск причин аномалий в ценах/комиссиях)

**Что reset влияет:**
- **Добавляет executions типа "final_exit"** (по одной на закрытую позицию):
  - `event_type = "final_exit"`
  - `event_time = reset_time` (одинаковый для всех позиций при reset)
  - `event_id` ссылается на `POSITION_CLOSED.event_id`
  - `reason = "profit_reset"` или `"capacity_prune"`
  - `qty_delta = -remaining_size` (отрицательное)
  - `raw_price`, `exec_price` (из forced close)
  - `fees_sol` (включает network_fee если учитывается)
  - `pnl_sol_delta = pnl_sol` позиции
- Источник: `backtester/infrastructure/reporter.py:1324-1608`

**Важно:** Execution данные позволяют проверить корректность цен и комиссий при reset close (например, сравнить `raw_price` с ожидаемой ценой свечи на момент `exit_time`).

---

## 4. Влияние reset на Audit (P0/P1)

### Какие audit-инварианты особенно чувствительны к reset

**P0 (критические):**
- `POSITION_CLOSED_BUT_NO_CLOSE_EVENT` — позиция закрыта, но нет события `POSITION_CLOSED`
  - **При reset:** Если reset закрывает позицию, но не эмитирует `POSITION_CLOSED` событие
  - **Проверка:** `backtester/audit/invariants.py` — проверка наличия события для каждой закрытой позиции
- `RESET_WITHOUT_EVENTS` — Reset activity без соответствующего события `PORTFOLIO_RESET_TRIGGERED`
  - **При reset:** Если есть позиции с `reset_reason in {"profit_reset", "capacity_prune"}`, но нет события `PORTFOLIO_RESET_TRIGGERED`
  - **Проверка:** `backtester/audit/invariants.py:check_reset_consistency()` (строки 120-148)
- `ENTRY_PRICE_INVALID`, `EXIT_PRICE_INVALID` — невалидные цены
  - **При reset:** Если `exit_price` из `get_mark_price_for_position()` некорректный (например, fallback на `entry_price` при отсутствии свечей)
  - **Проверка:** `backtester/audit/invariants.py` — проверка `entry_price > 0`, `exit_price > 0`
- `TIME_ORDER_INVALID` — `entry_time > exit_time`
  - **При reset:** Не должен возникать (reset использует `current_time` как `exit_time`)

**P1 (важные):**
- `PRUNE_WITHOUT_EVENTS` — Prune activity без соответствующего события
  - **При prune:** Аналогично `RESET_WITHOUT_EVENTS`, но специфично для prune
  - **Проверка:** `backtester/audit/invariants.py:check_reset_consistency()`
- `CLOSE_EVENT_BUT_POSITION_OPEN` — есть событие закрытия, но позиция открыта
  - **При reset:** Если reset эмитирует событие, но не обновляет `status="closed"` в позиции
  - **Проверка:** `backtester/audit/invariants.py` — проверка соответствия событий и статусов позиций

**P2 (информационные):**
- `PROFIT_RESET_TRIGGERED_BUT_CONDITION_FALSE` — Reset сработал, но условие не выполнено
  - **При reset:** Если reset сработал, но `equity_peak_in_cycle < cycle_start_equity * profit_reset_multiple`
  - **Проверка:** `backtester/audit/invariants.py` — проверка условий reset (если реализовано)
- `CAPACITY_ACTION_TRIGGERED_BUT_THRESHOLDS_NOT_MET` — Prune/reset сработал, но пороги не превышены
  - **При prune:** Если prune сработал, но не все условия выполнены (например, `open_ratio < 1.0`)
  - **Проверка:** `backtester/audit/invariants.py` — проверка условий prune (если реализовано)

### Мини playbook: "если audit ругнулся на reset — что смотреть первым"

**Шаг 1:** Проверить `audit_anomalies.csv`:
```python
import pandas as pd
anomalies_df = pd.read_csv("output/reports/audit_anomalies.csv")
reset_anomalies = anomalies_df[anomalies_df["code"].isin(["RESET_WITHOUT_EVENTS", "PRUNE_WITHOUT_EVENTS", "POSITION_CLOSED_BUT_NO_CLOSE_EVENT"])]
print(reset_anomalies[["code", "position_id", "event_id", "severity"]])
```

**Шаг 2:** Проверить `portfolio_events.csv` для позиций с reset:
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
reset_positions = positions_df[positions_df["closed_by_reset"] == True]
reset_position_ids = reset_positions["position_id"].tolist()

events_df = pd.read_csv("output/reports/portfolio_events.csv")
reset_events = events_df[
    (events_df["position_id"].isin(reset_position_ids)) | 
    (events_df["event_type"] == "portfolio_reset_triggered")
]
print(reset_events[["timestamp", "event_type", "position_id", "reason"]].sort_values("timestamp"))
```

**Шаг 3:** Проверить порядок событий:
- Должны быть `POSITION_CLOSED` события ДО `PORTFOLIO_RESET_TRIGGERED`
- Все `POSITION_CLOSED` должны иметь `reason in {"profit_reset", "capacity_prune"}`
- `PORTFOLIO_RESET_TRIGGERED` должен иметь соответствующий `reason`

**Шаг 4:** Проверить execution consistency (если есть `POSITION_CLOSED_BUT_NO_CLOSE_EVENT`):
```python
executions_df = pd.read_csv("output/reports/portfolio_executions.csv")
reset_executions = executions_df[
    (executions_df["event_id"].isin(reset_events["event_id"])) &
    (executions_df["reason"].isin(["profit_reset", "capacity_prune"]))
]
print(reset_executions[["event_time", "event_type", "reason", "raw_price", "exec_price"]].sort_values("event_time"))
```

**Шаг 5:** Проверить exit_price fallback (если есть `EXIT_PRICE_INVALID`):
```python
reset_positions_with_fallback = reset_positions[
    reset_positions["meta_json"].str.contains("reset_exit_price_fallback", na=False)
]
if len(reset_positions_with_fallback) > 0:
    print(f"Found {len(reset_positions_with_fallback)} positions with exit_price fallback")
    print(reset_positions_with_fallback[["position_id", "entry_price", "exit_price", "pnl_sol"]])
```

---

## 5. Влияние reset на Stage A (Research)

### A) Windowing bias

**Проблема:** Reset создает временные кластеры закрытий (все позиции закрываются одновременно при profit reset, часть позиций — при capacity prune), которые "склеивают" эффекты в одном временном окне.

**Как это работает:**
- Stage A разбивает сделки на равные по времени окна (time-based split)
- Источник: `backtester/research/window_aggregator.py:split_into_equal_windows()` (строки 248-303)
- Если reset срабатывает в середине периода, все закрытые позиции попадают в одно окно
- Это создает "пик" PnL в одном окне и потенциально "пустые окна" после reset

**Пример:**
- Период: 100 дней, `split_count = 5` → 5 окон по 20 дней
- Reset на 40-й день → все закрытые позиции попадают во второе окно (дни 21-40)
- Окна 3-5 могут быть "пустыми" (если новых позиций не открывалось)

**Как это отражается на метриках:**
- **survival_rate:** Может снизиться, если reset создает "пустые окна" (пустые окна имеют `total_pnl_sol = 0.0`, считаются невыжившими)
- **worst_window_pnl:** Может быть искажен, если reset закрывает позиции на убытках (или наоборот, если reset фиксирует прибыль)
- **median_window_pnl:** Может быть искажен, если reset создает "пик" PnL в одном окне
- **pnl_variance / pnl_variance_norm:** Может снизиться, если reset "склеивает" PnL в одно окно (или наоборот, если reset создает большой разброс между окнами)
- Источник: `backtester/research/strategy_stability.py:calculate_stability_metrics()` (строки 93-171)

**Важно:** Это **не баг**, а следствие portfolio-level политики. Stage A должен обрабатывать reset-закрытые позиции как обычные закрытия.

### B) Что Stage A НЕ имеет права делать

**Принцип (из `docs/ARCH_REBOOT_RUNNER_ONLY.md`):** Stage A = observation. Stage A наблюдает за executed positions, но НЕ интерпретирует reset reasons. Reset — это portfolio policy, не strategy quality.

**Stage A MUST NOT:**
- ❌ Фильтровать позиции по `closed_by_reset` (см. `docs/VARIABLES_REFERENCE.md` раздел 5: "Что Stage A НЕ имеет права делать")
- ❌ Корректировать метрики на основе `reset_reason`
- ❌ Пересчитывать `pnl_sol` из `exec_entry_price` / `exec_exit_price` (Stage A использует `pnl_sol` из `portfolio_positions.csv` как source of truth)
- ❌ "Лечить" данные (Stage A только читает и агрегирует)

**Почему (из `docs/VARIABLES_REFERENCE.md`):**
- Stage A должна быть честной observation
- Фильтрация/корректировка скрывает реальное поведение стратегии
- Reset — это portfolio policy, не strategy quality

**Какие поля Stage A читает, но не интерпретирует (из `docs/VARIABLES_REFERENCE.md`):**
- `closed_by_reset` — читается для observability, но не влияет на метрики
- `reset_reason` — читается для observability, но не влияет на метрики
- `triggered_portfolio_reset` — читается для observability, но не влияет на метрики

**Какие поля/колонки Stage A обязана использовать (из `docs/VARIABLES_REFERENCE.md`):**
- `entry_time`, `exit_time` — для windowing
- `pnl_sol` — для метрик (обязательно, source of truth)
- `exec_entry_price`, `exec_exit_price` — для валидации (если необходимо)
- `status = "closed"` — все позиции должны быть закрыты
- Источник: `backtester/research/window_aggregator.py:validate_trades_table()` (строки 27-79)

**Какие поля/колонки Stage A должна игнорировать:**
- `closed_by_reset`, `reset_reason` — Stage A не должна фильтровать или корректировать метрики на основе этих полей
- `triggered_portfolio_reset` — маркер для marker позиции, не должен влиять на метрики
- `capacity_prune=True`, `capacity_prune_trigger_time`, etc. — детали prune, не должны влиять на метрики

**Важно:** Stage A работает с **executed positions** и не должна делать предположения о причинах закрытия. Reset-закрытые позиции обрабатываются так же, как стратегические.

### C) Рекомендованные sanity-checks для Stage A при reset-heavy данных

**Топ-метрики/срезы:**

1. **Доля сделок, закрытых reset:**
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
reset_count = len(positions_df[positions_df["closed_by_reset"] == True])
total_count = len(positions_df)
reset_share = reset_count / total_count if total_count > 0 else 0.0
print(f"Reset-closed positions share: {reset_share:.2%}")
```

2. **Распределение hold_minutes:**
```python
positions_df["hold_minutes"] = (pd.to_datetime(positions_df["exit_time"]) - pd.to_datetime(positions_df["entry_time"])).dt.total_seconds() / 60
reset_hold = positions_df[positions_df["closed_by_reset"] == True]["hold_minutes"]
normal_hold = positions_df[positions_df["closed_by_reset"] == False]["hold_minutes"]
print(f"Reset hold_minutes: median={reset_hold.median():.1f}, mean={reset_hold.mean():.1f}")
print(f"Normal hold_minutes: median={normal_hold.median():.1f}, mean={normal_hold.mean():.1f}")
```

3. **Доля forced close:**
```python
forced_close_count = len(positions_df[positions_df["closed_by_reset"] == True])
forced_close_share = forced_close_count / total_count if total_count > 0 else 0.0
print(f"Forced close share: {forced_close_share:.2%}")
```

4. **Распределение PnL для reset vs normal:**
```python
reset_pnl = positions_df[positions_df["closed_by_reset"] == True]["pnl_sol"]
normal_pnl = positions_df[positions_df["closed_by_reset"] == False]["pnl_sol"]
print(f"Reset PnL: median={reset_pnl.median():.3f}, mean={reset_pnl.mean():.3f}")
print(f"Normal PnL: median={normal_pnl.median():.3f}, mean={normal_pnl.mean():.3f}")
```

**"Красные флаги":**

1. **Внезапная смена распределения PnL из-за fallback exit price:**
   - Если много позиций с `meta["reset_exit_price_fallback"]=True`, `exit_price = entry_price` → `pnl_sol = 0.0`
   - Проверка: `positions_df[positions_df["meta_json"].str.contains("reset_exit_price_fallback", na=False)]["pnl_sol"].describe()`

2. **Кластеры закрытий во времени:**
   - Если все reset-закрытые позиции имеют одинаковый `exit_time`, они попадают в одно окно
   - Проверка: группировка по `exit_time` для reset-закрытых позиций

3. **Пустые окна после reset:**
   - Если reset закрывает все позиции, следующие окна могут быть пустыми
   - Проверка: `stage_a_summary.csv` → окна с `trades_count = 0` после reset-окон

---

## 6. Влияние reset на Stage B (Decision)

### Как reset влияет на gate критерии

**min_windows:**
- **Влияние:** Косвенное — reset может создать "пустые окна", что снижает `windows_total` для некоторых `split_count`
- **Если `windows_total < min_windows`:** Стратегия не проходит (hard-gate)
- **Интерпретация:** Reset-heavy данные могут привести к недостаточному количеству окон, но это следствие portfolio policy, а не стратегии

**survival_rate:**
- **Влияние:** Reset может создать "пустые окна" (пустые окна имеют `total_pnl_sol = 0.0`, считаются невыжившими) → снижает `survival_rate`
- **Если `survival_rate < min_survival_rate`:** Стратегия не проходит
- **Интерпретация:** Низкий `survival_rate` из-за reset-heavy поведения не должен "наказывать" стратегию, но критерии это делают косвенно
- **Решение:** Использовать aggregated selection (`strategy_selection_agg.csv`) для робастности к разбиению на окна

**worst_window_pnl:**
- **Влияние:** Reset может создать "пик" убытков в одном окне (если reset закрывает позиции на убытках) → снижает `worst_window_pnl`
- **Если `worst_window_pnl < min_worst_window_pnl`:** Стратегия не проходит
- **Интерпретация:** Reset-heavy данные могут привести к низкому `worst_window_pnl`, но это следствие portfolio policy

**variance (legacy vs normalized):**
- **Влияние:** Reset может "склеивать" PnL в одно окно → снижает `pnl_variance` (или наоборот, если reset создает большой разброс)
- **Если `pnl_variance > max_pnl_variance` (legacy) или `pnl_variance_norm > max_pnl_variance` (normalized):** Стратегия не проходит
- **Интерпретация:** Нормализованная метрика (`pnl_variance_norm`) предпочтительна, так как не зависит от абсолютных значений PnL
- **Resolution order:** Stage B использует `pnl_variance_norm` если она присутствует, иначе fallback на `pnl_variance`
- Источник: `backtester/decision/strategy_selector.py:check_strategy_criteria()` (строки 436-439)

**Важно:** Stage B не должен "наказывать" стратегию за portfolio policy, но критерии это делают косвенно (например, низкий `survival_rate` из-за reset-heavy поведения). Это **ожидаемое поведение** (reset — это часть портфельной политики), но требует осознанной интерпретации метрик.

### Как правильно интерпретировать strategy_selection_agg.csv при наличии reset-heavy поведения

**robust_pass_rate:**
- Средний `passed` по всем `split_count`
- **При reset-heavy данных:** Может быть низким, если reset создает "пустые окна" для некоторых `split_count`
- **Интерпретация:** Низкий `robust_pass_rate` указывает на нестабильность метрик по разбиениям, но не обязательно на плохую стратегию

**passed_any:**
- Прошла ли стратегия хотя бы при одном `split_count`
- **При reset-heavy данных:** Может быть `False`, если reset влияет на все разбиения
- **Интерпретация:** `passed_any = False` — стратегия не проходит ни при одном разбиении

**passed_all:**
- Прошла ли стратегия при всех `split_count`
- **При reset-heavy данных:** Может быть `False`, если reset влияет на некоторые разбиения
- **Интерпретация:** `passed_all = False` — стратегия нестабильна по разбиениям

**worst_case_window_pnl:**
- Минимальный `worst_window_pnl` по всем `split_count`
- **При reset-heavy данных:** Может быть низким, если reset создает "пик" убытков
- **Интерпретация:** Низкий `worst_case_window_pnl` указывает на худший случай по разбиениям

**max_pnl_variance / max_pnl_variance_norm:**
- Максимальный `pnl_variance` / `pnl_variance_norm` по всем `split_count`
- **При reset-heavy данных:** Может быть высоким, если reset создает большой разброс между окнами
- **Интерпретация:** Высокая variance указывает на нестабильность метрик

**Рекомендация:** Использовать aggregated selection (`strategy_selection_agg.csv`) для принятия решений, так как он обеспечивает робастность к разбиению на окна и reset-heavy поведению.

---

## 7. Edge cases и неочевидные последствия

### Edge Case 1: Profit reset срабатывает на хвостовой сделке (tail) → может "улучшить" PnL и маскировать дисперсию

**Сценарий:**
- Стратегия имеет несколько tail позиций (большой PnL)
- Profit reset срабатывает, когда equity достигает threshold
- Все позиции закрываются одновременно, включая tail позиции
- Это создает "пик" PnL в одном окне

**Последствия:**
- **Stage A:** `worst_window_pnl` может быть улучшен (если reset фиксирует прибыль), `pnl_variance` может снизиться (если reset "склеивает" PnL в одно окно)
- **Stage B:** Стратегия может пройти критерии, даже если она нестабильна (reset маскирует дисперсию)
- **Интерпретация:** Reset-heavy данные могут "маскировать" проблемы стратегии, зафиксировав прибыль на пике

**Как проверить:**
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
reset_positions = positions_df[positions_df["closed_by_reset"] == True]
reset_pnl = reset_positions["pnl_sol"].sum()
total_pnl = positions_df["pnl_sol"].sum()
reset_share = reset_pnl / total_pnl if abs(total_pnl) > 1e-6 else 0.0
print(f"Reset PnL share: {reset_share:.2%}")
# Если reset_share > 50%, reset может маскировать дисперсию
```

### Edge Case 2: Capacity prune закрывает позиции "хуже/лучше" → меняется tail_pnl_share/non_tail_pnl_share

**Сценарий:**
- Prune выбирает кандидатов по score (более "плохие" первыми)
- Prune защищает tail позиции (`max_xn >= prune_protect_min_max_xn`)
- Prune закрывает часть позиций, оставляя остальные

**Последствия:**
- **Если prune закрывает non-tail позиции:** `tail_pnl_share` увеличивается (больше доля tail в оставшихся позициях)
- **Если prune закрывает tail позиции (не защищены):** `tail_pnl_share` уменьшается
- **Stage A:** Runner метрики (`tail_pnl_share`, `non_tail_pnl_share`) меняются в зависимости от того, какие позиции закрыл prune
- **Stage B:** Критерии V2 (`tail_pnl_share >= 0.30`) могут быть нарушены, если prune закрывает tail позиции

**Как проверить:**
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
pruned_positions = positions_df[positions_df["reset_reason"] == "capacity_prune"]
pruned_tail_count = len(pruned_positions[pruned_positions["max_xn_reached"] >= 4.0])
pruned_non_tail_count = len(pruned_positions[pruned_positions["max_xn_reached"] < 4.0])
print(f"Pruned tail positions: {pruned_tail_count}, non-tail: {pruned_non_tail_count}")
# Если pruned_tail_count > 0, prune закрыл tail позиции
```

### Edge Case 3: Reset close price fallback (если свечи отсутствуют) → искажение PnL

**Сценарий:**
- Reset срабатывает, но свечи для контракта отсутствуют (или не загружены)
- `get_mark_price_for_position()` использует fallback: `pos.entry_price`
- `exit_price = entry_price` → `pnl_sol = 0.0` (независимо от реального PnL)

**Последствия:**
- **Stage A:** `pnl_sol = 0.0` для reset-закрытых позиций → искажает метрики (survival_rate, worst_window_pnl, pnl_variance)
- **Stage B:** Стратегия может пройти критерии из-за "нулевого" PnL (независимо от реального PnL)
- **Интерпретация:** Fallback exit price — это технический артефакт, который может исказить метрики

**Как проверить:**
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
import json
positions_df["meta"] = positions_df["meta_json"].apply(lambda x: json.loads(x) if pd.notna(x) else {})
reset_with_fallback = positions_df[
    (positions_df["closed_by_reset"] == True) &
    (positions_df["meta"].apply(lambda m: m.get("reset_exit_price_fallback", False)))
]
if len(reset_with_fallback) > 0:
    print(f"Found {len(reset_with_fallback)} reset positions with exit_price fallback")
    print(reset_with_fallback[["position_id", "entry_price", "exit_price", "pnl_sol"]])
```

### Edge Case 4: Много reset подряд → деградация low-N/empty windows

**Сценарий:**
- Профит-цикл короткий → reset срабатывает часто
- Между reset'ами мало сделок → окна становятся пустыми
- `windows_total` остается постоянным, но `windows_positive` падает → `survival_rate` снижается

**Последствия:**
- Low-N проблемы: `windows_total < min_windows` (критерий Stage B)
- `survival_rate` падает из-за пустых окон (пустые окна имеют `total_pnl_sol = 0.0`, считаются невыжившими)
- `worst_window_pnl` может быть искажен (пустые окна имеют `total_pnl_sol = 0.0`, не учитываются в worst case)

**Как проверить:**
```python
# Проверить частоту reset'ов
policy_summary_df = pd.read_csv("output/reports/portfolio_policy_summary.csv")
reset_frequency = policy_summary_df["portfolio_reset_profit_count"] / (total_period_days / 30)  # resets per month
# Если reset_frequency > 0.1, reset может создавать пустые окна
```

### Edge Case 5: Reset в начале периода → пустые окна в начале

**Сценарий:**
- Reset срабатывает в начале периода (например, на 10-й день из 100)
- После reset открывается мало новых позиций
- Первые окна остаются пустыми (или почти пустыми)

**Последствия:**
- Первые окна имеют `total_pnl_sol = 0.0` → считаются невыжившими
- `survival_rate` снижается (например, если `split_count=5`, а первые 2 окна пустые → `survival_rate = 3/5 = 0.6`)
- `median_window_pnl` может быть искажен (медиана вычисляется с учетом пустых окон)

**Как проверить:**
```python
# Проверить пустые окна
summary_df = pd.read_csv("output/reports/stage_a_summary.csv")
empty_windows = summary_df[summary_df["trades_count"] == 0]
first_empty = empty_windows[empty_windows["window_index"] <= 2]  # Первые 2 окна
if len(first_empty) > 0:
    print(f"Found {len(first_empty)} empty windows in the beginning")
```

### Edge Case 6: Prune без reset → незаметное ухудшение survival_rate

**Сценарий:**
- Capacity prune закрывает "плохие" позиции (убыточные)
- Profit reset НЕ срабатывает (equity не достигла threshold)
- Pruned позиции имеют отрицательный `pnl_sol`
- Окна, где произошел prune, получают отрицательный PnL → могут стать невыжившими

**Последствия:**
- `survival_rate` снижается (окна с pruned позициями имеют `total_pnl_sol < 0`, считаются невыжившими)
- `worst_window_pnl` ухудшается (prune добавляет убытки в окна)
- Изменения незаметны в `portfolio_policy_summary.csv` (только `portfolio_capacity_prune_count`)

**Как проверить:**
```python
# Проверить prune влияние на окна
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
pruned_positions = positions_df[positions_df["reset_reason"] == "capacity_prune"]
pruned_pnl = pruned_positions["pnl_sol"].sum()
# Если pruned_pnl сильно отрицательный, prune может влиять на survival_rate
```

---

## 8. Debug Cookbook

### Рецепт 1: Стратегия стала rejected после включения prune — как проверить почему

**Шаг 1:** Проверить `strategy_selection.csv` для rejected стратегии:
```python
selection_df = pd.read_csv("output/reports/strategy_selection.csv")
rejected = selection_df[selection_df["passed"] == False]
print(rejected[["strategy", "split_count", "passed", "failed_reasons"]])
```

**Шаг 2:** Проверить `strategy_stability.csv` для rejected стратегии:
```python
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
rejected_strategy = rejected["strategy"].iloc[0]  # Пример
strategy_stability = stability_df[stability_df["strategy"] == rejected_strategy]
print(strategy_stability[["strategy", "split_count", "survival_rate", "worst_window_pnl", "pnl_variance"]])
```

**Шаг 3:** Проверить `portfolio_positions.csv` для prune activity:
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
strategy_positions = positions_df[positions_df["strategy"] == rejected_strategy]
pruned_count = len(strategy_positions[strategy_positions["reset_reason"] == "capacity_prune"])
total_count = len(strategy_positions)
pruned_share = pruned_count / total_count if total_count > 0 else 0.0
print(f"Pruned positions share: {pruned_share:.2%}")
```

**Шаг 4:** Проверить `portfolio_policy_summary.csv` для prune statistics:
```python
policy_summary_df = pd.read_csv("output/reports/portfolio_policy_summary.csv")
strategy_policy = policy_summary_df[policy_summary_df["strategy"] == rejected_strategy]
print(strategy_policy[["portfolio_capacity_prune_count", "avg_pruned_positions_per_event", "pruned_positions_share_of_all_closed"]])
```

**Шаг 5:** Проверить window breakdown в `stage_a_summary.csv`:
```python
summary_df = pd.read_csv("output/reports/stage_a_summary.csv")
strategy_summary = summary_df[summary_df["strategy"] == rejected_strategy]
print(strategy_summary[["split_count", "window_index", "trades_count", "total_pnl_sol"]].sort_values(["split_count", "window_index"]))
# Ищем окна с trades_count = 0 или низким total_pnl_sol
```

### Рецепт 2: Stage A survival_rate упал после reset — где смотреть

**Шаг 1:** Проверить `strategy_stability.csv` для стратегии:
```python
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
strategy_stability = stability_df[stability_df["strategy"] == "Strategy_Name"]
print(strategy_stability[["split_count", "survival_rate", "windows_positive", "windows_total", "trades_total"]])
```

**Шаг 2:** Проверить `stage_a_summary.csv` для window breakdown:
```python
summary_df = pd.read_csv("output/reports/stage_a_summary.csv")
strategy_summary = summary_df[summary_df["strategy"] == "Strategy_Name"]
print(strategy_summary[["split_count", "window_index", "window_start", "window_end", "trades_count", "total_pnl_sol"]].sort_values(["split_count", "window_index"]))
# Ищем окна с trades_count = 0 (пустые окна) или total_pnl_sol <= 0 (невыжившие окна)
```

**Шаг 3:** Проверить `portfolio_positions.csv` для reset activity:
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
strategy_positions = positions_df[positions_df["strategy"] == "Strategy_Name"]
reset_positions = strategy_positions[strategy_positions["closed_by_reset"] == True]
print(f"Reset positions: {len(reset_positions)} / {len(strategy_positions)}")
# Проверяем распределение exit_time для reset-закрытых позиций
reset_positions["exit_time"] = pd.to_datetime(reset_positions["exit_time"])
reset_time_groups = reset_positions.groupby(reset_positions["exit_time"].dt.date).size()
print(reset_time_groups)
# Если есть кластеры закрытий, они попадают в одно окно
```

**Шаг 4:** Проверить `portfolio_events.csv` для reset событий:
```python
events_df = pd.read_csv("output/reports/portfolio_events.csv")
strategy_events = events_df[events_df["strategy"] == "Strategy_Name"]
reset_events = strategy_events[strategy_events["event_type"] == "portfolio_reset_triggered"]
print(reset_events[["timestamp", "reason", "meta_json"]])
# Проверяем количество и время reset'ов
```

### Рецепт 3: Audit P0 на reset close price — какие поля сравнить

**Шаг 1:** Проверить `audit_anomalies.csv`:
```python
anomalies_df = pd.read_csv("output/reports/audit_anomalies.csv")
price_anomalies = anomalies_df[anomalies_df["code"] == "EXIT_PRICE_INVALID"]
print(price_anomalies[["position_id", "entry_price", "exit_price", "details_json"]])
```

**Шаг 2:** Проверить `portfolio_positions.csv` для позиций с аномалиями:
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
anomaly_positions = positions_df[positions_df["position_id"].isin(price_anomalies["position_id"])]
print(anomaly_positions[["position_id", "entry_price", "exit_price", "pnl_sol", "closed_by_reset", "reset_reason"]])
```

**Шаг 3:** Проверить `portfolio_executions.csv` для execution данных:
```python
executions_df = pd.read_csv("output/reports/portfolio_executions.csv")
anomaly_executions = executions_df[executions_df["position_id"].isin(price_anomalies["position_id"])]
print(anomaly_executions[["position_id", "event_time", "event_type", "raw_price", "exec_price", "reason"]])
```

**Шаг 4:** Проверить fallback exit price:
```python
import json
anomaly_positions["meta"] = anomaly_positions["meta_json"].apply(lambda x: json.loads(x) if pd.notna(x) else {})
fallback_positions = anomaly_positions[
    anomaly_positions["meta"].apply(lambda m: m.get("reset_exit_price_fallback", False))
]
if len(fallback_positions) > 0:
    print(f"Found {len(fallback_positions)} positions with exit_price fallback")
    print(fallback_positions[["position_id", "entry_price", "exit_price", "pnl_sol"]])
    # Если exit_price == entry_price и pnl_sol == 0.0, это fallback
```

### Рецепт 4: Стратегия rejected по variance после reset — как проверить

**Шаг 1:** Проверить `strategy_selection.csv`:
```python
selection_df = pd.read_csv("output/reports/strategy_selection.csv")
rejected = selection_df[selection_df["passed"] == False]
variance_failures = rejected[rejected["failed_reasons"].str.contains("pnl_variance", na=False)]
print(variance_failures[["strategy", "split_count", "failed_reasons"]])
```

**Шаг 2:** Проверить `strategy_stability.csv` для variance:
```python
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
strategy_stability = stability_df[stability_df["strategy"] == rejected_strategy]
print(strategy_stability[["split_count", "pnl_variance", "pnl_variance_norm"]])
```

**Шаг 3:** Проверить window breakdown для variance:
```python
summary_df = pd.read_csv("output/reports/stage_a_summary.csv")
strategy_summary = summary_df[summary_df["strategy"] == rejected_strategy]
window_pnls = strategy_summary.groupby("split_count")["total_pnl_sol"].apply(list)
for split_count, pnls in window_pnls.items():
    variance = statistics.variance(pnls) if len(pnls) > 1 else 0.0
    print(f"split_count={split_count}: variance={variance:.6f}, pnls={pnls}")
```

**Шаг 4:** Проверить reset activity для variance влияния:
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
strategy_positions = positions_df[positions_df["strategy"] == rejected_strategy]
reset_positions = strategy_positions[strategy_positions["closed_by_reset"] == True]
reset_pnl = reset_positions["pnl_sol"].sum()
total_pnl = strategy_positions["pnl_sol"].sum()
reset_share = reset_pnl / total_pnl if abs(total_pnl) > 1e-6 else 0.0
print(f"Reset PnL share: {reset_share:.2%}")
# Если reset_share > 50%, reset может влиять на variance
```

### Рецепт 5: Много reset подряд — как проверить деградацию windows

**Шаг 1:** Проверить `portfolio_policy_summary.csv`:
```python
policy_summary_df = pd.read_csv("output/reports/portfolio_policy_summary.csv")
print(policy_summary_df[["strategy", "portfolio_reset_profit_count", "portfolio_capacity_prune_count"]])
```

**Шаг 2:** Проверить `portfolio_events.csv` для reset событий:
```python
events_df = pd.read_csv("output/reports/portfolio_events.csv")
reset_events = events_df[events_df["event_type"] == "portfolio_reset_triggered"]
reset_events["timestamp"] = pd.to_datetime(reset_events["timestamp"])
reset_events = reset_events.sort_values("timestamp")
print(reset_events[["timestamp", "strategy", "reason"]])
# Проверяем частоту reset'ов
```

**Шаг 3:** Проверить `stage_a_summary.csv` для empty windows:
```python
summary_df = pd.read_csv("output/reports/stage_a_summary.csv")
empty_windows = summary_df[summary_df["trades_count"] == 0]
print(f"Empty windows: {len(empty_windows)} / {len(summary_df)}")
print(empty_windows[["strategy", "split_count", "window_index", "window_start", "window_end"]])
```

**Шаг 4:** Проверить `strategy_stability.csv` для windows_total:
```python
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
low_windows = stability_df[stability_df["windows_total"] < 3]
print(low_windows[["strategy", "split_count", "windows_total", "trades_total"]])
# Если windows_total < 3, стратегия может не пройти критерий min_windows
```

### Рецепт 6: Prune закрыл tail позиции — как проверить влияние на метрики

**Шаг 1:** Проверить `portfolio_positions.csv` для pruned tail positions:
```python
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
pruned_positions = positions_df[positions_df["reset_reason"] == "capacity_prune"]
pruned_tail = pruned_positions[pruned_positions["max_xn_reached"] >= 4.0]
print(f"Pruned tail positions: {len(pruned_tail)} / {len(pruned_positions)}")
print(pruned_tail[["position_id", "max_xn_reached", "pnl_sol"]])
```

**Шаг 2:** Проверить `strategy_stability.csv` для tail_pnl_share:
```python
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
strategy_stability = stability_df[stability_df["strategy"] == "Strategy_Name"]
print(strategy_stability[["strategy", "split_count", "tail_pnl_share", "non_tail_pnl_share", "hit_rate_x4"]])
```

**Шаг 3:** Проверить `portfolio_policy_summary.csv` для prune statistics:
```python
policy_summary_df = pd.read_csv("output/reports/portfolio_policy_summary.csv")
strategy_policy = policy_summary_df[policy_summary_df["strategy"] == "Strategy_Name"]
print(strategy_policy[["portfolio_capacity_prune_count", "avg_pruned_positions_per_event", "pruned_positions_share_of_all_closed"]])
```

**Шаг 4:** Проверить Stage B критерии для tail_pnl_share:
```python
selection_df = pd.read_csv("output/reports/strategy_selection.csv")
strategy_selection = selection_df[selection_df["strategy"] == "Strategy_Name"]
tail_failures = strategy_selection[strategy_selection["failed_reasons"].str.contains("tail_pnl_share", na=False)]
print(tail_failures[["strategy", "split_count", "failed_reasons"]])
# Если есть failures по tail_pnl_share, prune мог закрыть tail позиции
```

---

## 9. Do / Don't для будущих изменений

### Что можно менять без разрушения research/decision

**Можно:**
- Изменять параметры reset/prune (thresholds, cooldowns, selection criteria) — это не влияет на контракты артефактов
- Добавлять новые meta поля в позиции/события — Stage A/B не используют их напрямую
- Изменять логику выбора кандидатов для prune — это не влияет на контракты, если не меняются поля в CSV
- Добавлять новые типы reset (например, risk-based reset) — если они используют те же поля и события

**Ограничения:**
- Поля в `portfolio_positions.csv` не должны удаляться или менять тип без миграции
- Порядок событий (`POSITION_CLOSED` → `PORTFOLIO_RESET_TRIGGERED`) не должен меняться
- Поля `closed_by_reset`, `reset_reason`, `reason` должны оставаться совместимыми

### Что нельзя (ломает контракты, baseline)

**Нельзя:**
- Менять структуру событий (`PortfolioEvent` fields) без миграции — это ломает audit контракты
- Удалять обязательные поля из `portfolio_positions.csv` (`entry_time`, `exit_time`, `pnl_sol`, `status`) — это ломает Stage A
- Менять порядок эмиссии событий (например, `PORTFOLIO_RESET_TRIGGERED` ДО `POSITION_CLOSED`) — это ломает audit инварианты
- Менять значения `reason` для reset (`"profit_reset"`, `"capacity_prune"`) — это ломает фильтрацию и анализ
- Удалять marker position для profit reset — это ломает `PORTFOLIO_RESET_TRIGGERED` событие

**Критические контракты:**
- `portfolio_positions.csv` — source of truth для Stage A, обязательные поля не должны меняться
- `portfolio_events.csv` — канонический ledger для audit, структура событий не должна меняться
- Порядок событий (`POSITION_CLOSED` → `PORTFOLIO_RESET_TRIGGERED`) — инвариант для audit
- Поля `closed_by_reset`, `reset_reason`, `triggered_portfolio_reset` — используются для фильтрации и анализа

### Какие изменения требуют новых тестов и почему

**Требуют новых тестов:**
1. **Изменения логики reset/prune:**
   - Новая логика выбора кандидатов для prune → нужны тесты для корректности выбора
   - Новые условия trigger для reset → нужны тесты для корректности trigger
   - Новая логика forced close → нужны тесты для корректности PnL и fees

2. **Изменения полей в CSV:**
   - Новые поля в `portfolio_positions.csv` → нужны тесты для Stage A (валидация, использование)
   - Новые поля в `portfolio_events.csv` → нужны тесты для audit (инварианты, consistency)
   - Изменения типов полей → нужны тесты для обратной совместимости

3. **Изменения порядка событий:**
   - Новый порядок эмиссии событий → нужны тесты для audit (инварианты порядка)
   - Новые типы событий → нужны тесты для корректности эмиссии

4. **Изменения метрик Stage A:**
   - Новые метрики → нужны тесты для корректности вычисления
   - Изменения формул метрик → нужны тесты для корректности результатов

**Почему это важно:**
- Reset/prune влияют на все слои (Audit, Stage A, Stage B), поэтому изменения должны быть покрыты тестами
- Контракты артефактов должны оставаться стабильными для обратной совместимости
- Инварианты audit должны проверяться для новых логик

---

## 10. Привязка к исходникам

### Reset/Prune логика

| Компонент | Файл | Функция/метод | Описание |
|-----------|------|---------------|----------|
| Profit Reset — Trigger | `backtester/domain/portfolio.py` | `run()` строки 2241-2243 | Проверка `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple` |
| Profit Reset — Execution | `backtester/domain/portfolio.py` | `_apply_reset()` строки 1057-1233 | Вызов `apply_portfolio_reset()` и эмиссия событий |
| Profit Reset — Core Logic | `backtester/domain/portfolio_reset.py` | `apply_portfolio_reset()` строки 154-321 | Закрытие позиций, обновление счетчиков, сброс цикла |
| Capacity Prune — Trigger | `backtester/domain/portfolio.py` | `_maybe_apply_capacity_prune()` строки 670-730 | Проверка capacity pressure |
| Capacity Prune — Selection | `backtester/domain/portfolio.py` | `_select_capacity_prune_candidates()` строки 593-668 | Фильтрация кандидатов |
| Capacity Prune — Execution | `backtester/domain/portfolio.py` | `_maybe_apply_capacity_prune()` строки 798-895 | Закрытие выбранных позиций |
| Forced Close — Unified | `backtester/domain/portfolio.py` | `_forced_close_position()` строки 344-451 | Единый метод для принудительного закрытия |
| Exit Price Logic | `backtester/domain/portfolio_reset.py` | `get_mark_price_for_position()` строки 122-151 | Получение mark price для forced close |

### Reporting (CSV артефакты)

| Артефакт | Файл | Функция/метод | Описание |
|----------|------|---------------|----------|
| portfolio_positions.csv | `backtester/infrastructure/reporter.py` | `save_portfolio_positions_table()` строки 979-1223 | Экспорт positions с полями reset |
| portfolio_events.csv | `backtester/infrastructure/reporter.py` | `save_portfolio_events_table()` строки 1225-1316 | Экспорт событий `POSITION_CLOSED` и `PORTFOLIO_RESET_TRIGGERED` |
| portfolio_executions.csv | `backtester/infrastructure/reporter.py` | `save_portfolio_executions_table()` строки 1324-1608 | Экспорт executions для forced close |
| portfolio_policy_summary.csv | `backtester/infrastructure/reporter.py` | `save_portfolio_policy_summary()` строки 1610-1703 | Экспорт статистики reset/prune |

### Audit

| Компонент | Файл | Функция/метод | Описание |
|-----------|------|---------------|----------|
| Reset Consistency Check | `backtester/audit/invariants.py` | `check_reset_consistency()` строки 120-148 | Проверка наличия `PORTFOLIO_RESET_TRIGGERED` при reset activity |
| Anomaly Types | `backtester/audit/invariants.py` | `AnomalyType` (enum) | Типы аномалий: `RESET_WITHOUT_EVENTS`, `PRUNE_WITHOUT_EVENTS`, etc. |

### Stage A (Research)

| Компонент | Файл | Функция/метод | Описание |
|-----------|------|---------------|----------|
| Window Aggregation | `backtester/research/window_aggregator.py` | `split_into_equal_windows()` строки 248-303 | Разбиение сделок на равные окна |
| Window Metrics | `backtester/research/window_aggregator.py` | `calculate_window_metrics()` строки 122-246 | Метрики одного окна |
| Stability Metrics | `backtester/research/strategy_stability.py` | `calculate_stability_metrics()` строки 93-171 | Метрики устойчивости (survival_rate, pnl_variance, etc.) |
| Runner Metrics | `backtester/research/strategy_stability.py` | `calculate_runner_metrics()` строки 172-271 | Runner метрики (hit_rate_x4, tail_pnl_share, etc.) |

### Stage B (Decision)

| Компонент | Файл | Функция/метод | Описание |
|-----------|------|---------------|----------|
| Strategy Selector | `backtester/decision/strategy_selector.py` | `check_strategy_criteria()` строки 27-250 | Проверка критериев для одной стратегии |
| Variance Resolution | `backtester/decision/strategy_selector.py` | `check_strategy_criteria()` строки 436-439 | Resolution order: `pnl_variance_norm` → `pnl_variance` |
| Selection Aggregator | `backtester/decision/selection_aggregator.py` | `aggregate_selection()` строки 102-230 | Aggregation across split_count |

---

## Связанные документы

**Обязательные источники (используются как терминологические и архитектурные якоря):**
- `docs/VARIABLES_REFERENCE.md` — **канонический справочник всех переменных и метрик** (терминология должна соответствовать)
- `docs/ARCH_REBOOT_RUNNER_ONLY.md` — **архитектурная рамка** (portfolio-first, reset = policy, Stage A = observation, Stage B = decision)

**Базовые документы:**
- `docs/PRUNE_AND_PROFIT_RESET_RULES.md` — детальная спецификация механизмов reset/prune
- `docs/STAGE_A_B_PRINCIPLES_v2.2.md` — контракты Stage A/B и aggregated outputs
- `docs/PIPELINE_GUIDE.md` — общий пайплайн и source of truth
- `docs/CANONICAL_LEDGER_CONTRACT.md` — структура событий и инварианты
- `docs/TEST_GREEN_BASELINE_2025-01-06.md` — baseline и контракты, которые нельзя ломать

**Дополнительные:**
- `docs/V1.6_IMPLEMENTATION_SUMMARY.md` — исторический контекст capacity reset
- `docs/TECHNICAL_ANALYSIS.md` — guard-контракты и tech debt

---

*Документ создан: 2025-01-XX*  
*Версия спецификации: 1.0*
