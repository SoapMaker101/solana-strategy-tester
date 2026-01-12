# Канонический справочник переменных и метрик v2.2

**Версия:** 2.2  
**Дата:** 2025-01-XX  
**Статус:** Канонический справочник всех переменных и метрик проекта

---

## Содержание

1. [Общие принципы](#1-общие-принципы)
2. [Execution-level variables](#2-execution-level-variables)
3. [Position-level variables](#3-position-level-variables)
4. [Portfolio-level variables](#4-portfolio-level-variables)
5. [Stage A (Research) variables](#5-stage-a-research-variables)
6. [Stage B (Decision) variables](#6-stage-b-decision-variables)
7. [Reset-related variables](#7-reset-related-variables)
8. [Типовые ошибки и анти-паттерны](#8-типовые-ошибки-и-анти-паттерны)
9. [Привязка к исходникам](#9-привязка-к-исходникам)

---

## 1. Общие принципы

### Уровни данных

Система работает с данными на разных уровнях агрегации:

**Execution-level:**
- Данные отдельных исполнений (entry, partial_exit, final_exit)
- Источник: `portfolio_executions.csv` / `PortfolioEvent.meta`
- Уровень детализации: одно исполнение = одна строка

**Position-level:**
- Данные исполненных позиций (positions-level агрегат)
- Источник: `portfolio_positions.csv`
- Уровень детализации: одна позиция = одна строка (агрегат по всем executions позиции)

**Portfolio-level:**
- Данные портфеля в целом (runtime / summary)
- Источник: `PortfolioStats`, `portfolio_summary.csv`, `portfolio_policy_summary.csv`
- Уровень детализации: один портфель = одна строка / объект

**Research-level (Stage A):**
- Метрики устойчивости стратегий (window-based агрегат)
- Источник: `strategy_stability.csv`, `stage_a_summary.csv`
- Уровень детализации: одна стратегия × один split_count = одна строка (или агрегировано)

**Decision-level (Stage B):**
- Результаты отбора стратегий (decision artifact)
- Источник: `strategy_selection.csv`, `strategy_selection_agg.csv`
- Уровень детализации: одна стратегия × один split_count = одна строка (или агрегировано)

### Source of Truth vs Derived

**Source of Truth (никогда не пересчитывается):**
- `portfolio_positions.csv` — source of truth для Stage A
- `portfolio_events.csv` — канонический ledger для audit
- `portfolio_executions.csv` — execution-level дебаг
- `PortfolioStats` (runtime) — source of truth для portfolio-level метрик

**Derived (вычисляется из source of truth):**
- `strategy_stability.csv` — вычисляется из `portfolio_positions.csv`
- `strategy_selection.csv` — вычисляется из `strategy_stability.csv`
- `portfolio_summary.csv` — агрегируется из `portfolio_positions.csv`

### Запрет на переопределение значений между уровнями

**Правило:** Значения на одном уровне не должны переопределяться на другом уровне.

**Примеры:**
- ❌ Stage A не должна пересчитывать `pnl_sol` из `exec_entry_price` / `exec_exit_price`
- ❌ Stage B не должна пересчитывать `survival_rate` из `portfolio_positions.csv`
- ✅ Stage A использует `pnl_sol` из `portfolio_positions.csv` как есть
- ✅ Stage B использует `survival_rate` из `strategy_stability.csv` как есть

**Исключения:**
- Нормализация (например, `pnl_variance_norm` = `pnl_variance / initial_balance_sol²`) — допустима, если явно обозначена как derived
- Агрегация (например, `strategy_stability_agg.csv` из `strategy_stability.csv`) — допустима, если явно обозначена как aggregated

---

## 2. Execution-level variables

**Источник:** `portfolio_executions.csv` / `PortfolioEvent.meta`  
**Создатель:** `backtester/infrastructure/reporter.py:save_portfolio_executions_table()` (строки 1324-1608)  
**Потребители:** Audit (consistency checks), Debug (price/slippage analysis)

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `position_id` | Execution | str (UUID) | - | Идентификатор позиции | `Position.position_id` | Audit, Debug |
| `signal_id` | Execution | str | - | Идентификатор сигнала | `Position.signal_id` | Debug |
| `strategy` | Execution | str | - | Название стратегии | `PortfolioResult` key | Debug |
| `event_time` | Execution | datetime (ISO) | UTC | Время события исполнения | `Position.entry_time` / `Position.exit_time` / partial exit `hit_time` | Audit (ordering) |
| `event_type` | Execution | str | - | Тип исполнения: `"entry"` / `"partial_exit"` / `"final_exit"` | `PortfolioEvent.event_type` | Audit (bijection) |
| `event_id` | Execution | str (UUID) | - | Ссылка на `PortfolioEvent.event_id` | `PortfolioEvent.event_id` | Audit (events ↔ executions) |
| `qty_delta` | Execution | float | SOL | Изменение размера позиции (для entry положительное, для exit отрицательное) | `Position.size` / `partial_exit.exit_size` / `remainder_exit_data.exit_size` | Debug |
| `raw_price` | Execution | float | USD (или нативная цена токена) | Цена до slippage | `Position.meta["raw_entry_price"]` / `Position.meta["raw_exit_price"]` / `partial_exit.raw_price` | Debug (slippage analysis) |
| `exec_price` | Execution | float | USD (или нативная цена токена) | Цена после slippage | `Position.meta["exec_entry_price"]` / `Position.meta["exec_exit_price"]` / `partial_exit.exec_price` | Debug (execution analysis) |
| `fees_sol` | Execution | float | SOL | Комиссии для этого execution (включая network_fee если учитывается в `fees_total_sol` позиции) | Распределение `Position.meta["fees_total_sol"]` по executions | Audit (sum == position.fees_total_sol) |
| `pnl_sol_delta` | Execution | float | SOL | Изменение PnL для этого execution (для entry = 0.0, для exit = `pnl_sol` позиции) | `Position.meta["pnl_sol"]` (для final_exit), `partial_exit.pnl_sol` (для partial_exit) | Debug |
| `reason` | Execution | str | - | Каноническая причина (для exit executions) | `Position.meta["close_reason"]` / `reset_reason` / `"ladder_tp"` (для partial_exit) | Debug |
| `xn` | Execution | float | - | Target multiple (для ladder partial_exit, иначе None) | `partial_exit.xn` | Debug |
| `fraction` | Execution | float | - | Доля выхода (для ladder partial_exit, иначе None) | `partial_exit.exit_size / original_size` | Debug |

**Важно:**
- `fees_sol` в executions распределяется так, чтобы `sum(executions.fees_sol) == position.fees_total_sol`
- Для позиций с partial_exits: `fees_entry = max(0, fees_total - exit_fee_sum)`, остальное в exit executions
- Для обычных позиций: `fees_entry = 0.0`, все fees в `final_exit`
- `execution_type` не является отдельным полем в CSV — он определяется по `event_type` (entry / partial_exit / final_exit)

**Source:** `backtester/infrastructure/reporter.py:save_portfolio_executions_table()` (строки 1324-1608)

---

## 3. Position-level variables

**Источник:** `portfolio_positions.csv`  
**Создатель:** `backtester/infrastructure/reporter.py:save_portfolio_positions_table()` (строки 979-1223)  
**Потребители:** Stage A (основной источник), Audit (инварианты), Reporting (статистика)

### Идентификаторы и базовые поля

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `position_id` | Position | str (UUID) | - | Уникальный идентификатор позиции | `Position.position_id` (генерируется автоматически) | Stage A, Audit, Debug |
| `strategy` | Position | str | - | Название стратегии | `PortfolioResult` key | Stage A (группировка) |
| `signal_id` | Position | str | - | Идентификатор сигнала | `Position.signal_id` | Stage A, Debug |
| `contract_address` | Position | str | - | Адрес контракта токена | `Position.contract_address` | Stage A, Debug |

### Время и статус

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `entry_time` | Position | datetime (ISO) | UTC | Время входа в позицию | `Position.entry_time` | Stage A (windowing), Audit (ordering) |
| `exit_time` | Position | datetime (ISO) | UTC | Время выхода из позиции | `Position.exit_time` | Stage A (windowing), Audit (ordering) |
| `status` | Position | str | - | Статус позиции: `"open"` / `"closed"` | `Position.status` | Stage A (только `"closed"`), Audit |
| `hold_minutes` | Position | int | minutes | Длительность удержания позиции в минутах | `(exit_time - entry_time).total_seconds() / 60` | Stage A (p90_hold_days) |

### Размер и PnL

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `size` | Position | float | SOL | Размер позиции в SOL (номинал) | `Position.meta["original_size"]` (если есть) / `Position.size` | Stage A (не используется напрямую) |
| `pnl_sol` | Position | float | SOL | **Портфельный PnL в SOL (обязательно для Stage A)** | `Position.meta["pnl_sol"]` (source of truth) | Stage A (основная метрика), Audit |
| `pnl_pct_total` | Position | float | percent | PnL в процентах (от realized_multiple) | `(realized_multiple - 1.0) * 100.0` | Debug (legacy compatibility) |
| `realized_multiple` | Position | float | - | Суммарный multiple из ladder fills | `Position.meta["realized_multiple"]` / `Σ(fraction * xn)` | Stage A (не используется), Debug |

### Цены

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `exec_entry_price` | Position | float | USD (или нативная цена) | Исполненная цена входа (с slippage) | `Position.meta["exec_entry_price"]` / `Position.entry_price` | Stage A (валидация), Debug |
| `exec_exit_price` | Position | float | USD (или нативная цена) | Исполненная цена выхода (с slippage) | `Position.meta["exec_exit_price"]` / `Position.exit_price` | Stage A (валидация), Debug |
| `raw_entry_price` | Position | float | USD (или нативная цена) | Сырая цена входа (без slippage, для диагностики) | `Position.meta["raw_entry_price"]` / `Position.entry_price` | Debug (slippage analysis) |
| `raw_exit_price` | Position | float | USD (или нативная цена) | Сырая цена выхода (без slippage, для диагностики) | `Position.meta["raw_exit_price"]` / `Position.exit_price` | Debug (slippage analysis) |

**Важно:** Stage A использует `pnl_sol` (source of truth), а не пересчитывает из `exec_entry_price` / `exec_exit_price`. `exec_entry_price` / `exec_exit_price` используются только для валидации.

### Комиссии

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `fees_total_sol` | Position | float | SOL | Суммарные комиссии позиции (swap + LP + network_fee, если учитывается) | `Position.meta["fees_total_sol"]` (source of truth) | Reporting (strategy_summary), Audit (sum == executions.fees_sol) |

**Важно:** `fees_total_sol` берется ТОЛЬКО из `Position.meta["fees_total_sol"]`. Никаких пересчётов через executions или helper методы. См. `docs/CANONICAL_LEDGER_CONTRACT.md`.

### Причины закрытия

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `reason` | Position | str | - | Каноническая причина закрытия | `Position.meta["close_reason"]` / `reset_reason` | Stage A (читает, но не интерпретирует), Audit (consistency) |

**Важно:** Stage A читает `reason`, но не должна фильтровать или корректировать метрики на основе причины закрытия. Reset-закрытые позиции обрабатываются так же, как стратегические.

### Reset-related поля

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `closed_by_reset` | Position | bool | - | Закрыта ли позиция по reset/prune | `Position.meta["closed_by_reset"]` | Stage A (читает, но не интерпретирует), Debug |
| `reset_reason` | Position | str | - | Причина reset: `"profit_reset"` / `"capacity_prune"` / `"none"` | `Position.meta["reset_reason"]` | Stage A (читает, но не интерпретирует), Audit (consistency) |
| `triggered_portfolio_reset` | Position | bool | - | Триггернула ли portfolio-level reset (только для marker позиции profit reset) | `Position.meta["triggered_portfolio_reset"]` | Debug (marker identification) |

**Важно:** Stage A НЕ должна фильтровать или корректировать метрики на основе `closed_by_reset` / `reset_reason`. Эти поля существуют для observability, но не должны влиять на вычисление метрик.

### Runner ladder метрики

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `max_xn_reached` | Position | float | - | Максимальный XN достигнутый (из levels_hit или fallback на цены) | `Position.meta["max_xn"]` / `Position.meta["max_xn_reached"]` / вычисление из цен | Stage A (hit_rate_x2/x5/x4, tail_pnl_share) |
| `hit_x2` | Position | bool | - | Достигнут ли XN >= 2.0 | `max_xn_reached >= 2.0` | Stage A (hit_rate_x2) |
| `hit_x5` | Position | bool | - | Достигнут ли XN >= 5.0 | `max_xn_reached >= 5.0` | Stage A (hit_rate_x5) |
| `realized_total_pnl_sol` | Position | float | SOL | Суммарный realized PnL из partial_exits | `Σ(partial_exit.pnl_sol)` / fallback на `pnl_sol` | Stage A (tail_pnl_share, non_tail_pnl_share) |
| `realized_tail_pnl_sol` | Position | float | SOL | Суммарный realized PnL от tail сделок (max_xn >= 4.0) | `Σ(partial_exit.pnl_sol where xn >= 4.0)` / fallback | Stage A (tail_pnl_share) |

### Что агрегируется

**Агрегируются из executions:**
- `pnl_sol` — агрегируется из всех executions позиции (на самом деле вычисляется один раз в PortfolioEngine, но концептуально агрегат)
- `fees_total_sol` — сумма всех `fees_sol` по executions позиции (инвариант: `sum(executions.fees_sol) == position.fees_total_sol`)
- `realized_multiple` — агрегируется из partial_exits: `Σ(fraction * xn)`

**Никогда не пересчитываются:**
- `entry_time`, `exit_time` — устанавливаются один раз при открытии/закрытии
- `exec_entry_price`, `exec_exit_price` — устанавливаются один раз при открытии/закрытии
- `pnl_sol` — вычисляется один раз при закрытии, не пересчитывается
- `fees_total_sol` — устанавливается один раз при закрытии, не пересчитывается

**Source:** `backtester/infrastructure/reporter.py:save_portfolio_positions_table()` (строки 979-1223)

---

## 4. Portfolio-level variables

**Источник:** `PortfolioStats` (runtime), `portfolio_summary.csv`, `portfolio_policy_summary.csv`  
**Создатель:** `PortfolioEngine` (runtime), `backtester/infrastructure/reporter.py` (CSV)  
**Потребители:** Stage A (initial_balance_sol для нормализации), Reporting, Debug

### Баланс и equity

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `initial_balance_sol` | Portfolio | float | SOL | Начальный баланс портфеля | `PortfolioConfig.initial_balance_sol` | Stage A (normalization), Reporting |
| `initial_balance_sol_used` | Portfolio | float | SOL | Начальный баланс, используемый для нормализации (если присутствует в CSV) | Из portfolio config (same as `initial_balance_sol`) | Stage A (pnl_variance_norm) |
| `final_balance_sol` | Portfolio | float | SOL | Финальный баланс портфеля | `PortfolioStats.final_balance_sol` | Reporting, Debug |
| `total_return_pct` | Portfolio | float | percent | Общая доходность портфеля: `(final_balance - initial_balance) / initial_balance * 100` | `PortfolioStats.total_return_pct` | Reporting |

### Cycle и equity tracking

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `cycle_start_equity` | Portfolio | float | SOL | Equity в начале текущего цикла (сбрасывается после profit reset) | `PortfolioStats.cycle_start_equity` | Reset logic (trigger condition) |
| `equity_peak_in_cycle` | Portfolio | float | SOL | Пик equity в текущем цикле (обновляется при росте equity, сбрасывается после profit reset) | `PortfolioStats.equity_peak_in_cycle` | Reset logic (trigger condition) |

**Когда equity "сбрасывается":**
- **Profit reset:** `cycle_start_equity = balance` (новый цикл), `equity_peak_in_cycle = cycle_start_equity` (сброс пика)
- **Capacity prune:** НЕ сбрасывает `cycle_start_equity` и `equity_peak_in_cycle` (цикл продолжается)

**Когда equity "продолжается":**
- **Capacity prune:** Equity не сбрасывается, цикл продолжается
- **Обычные закрытия:** Equity не сбрасывается, цикл продолжается

**Как reset влияет на baseline для Stage A:**
- Stage A использует `initial_balance_sol` для нормализации `pnl_variance_norm`
- `initial_balance_sol` не меняется после reset (это начальный баланс портфеля, не цикловой)
- Profit reset меняет `cycle_start_equity`, но это не влияет на Stage A normalization (Stage A использует `initial_balance_sol`, а не `cycle_start_equity`)

### Drawdown

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `max_drawdown_pct` | Portfolio | float | percent | Максимальная просадка портфеля (отрицательное значение, например -0.60 = -60%) | `PortfolioStats.max_drawdown_pct` | Stage A (Runner метрика), Stage B (V2 критерий) |

### Reset/prune статистика

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `portfolio_reset_profit_count` | Portfolio | int | - | Количество срабатываний profit reset | `PortfolioStats.portfolio_reset_profit_count` | Reporting (portfolio_policy_summary.csv) |
| `portfolio_reset_capacity_count` | Portfolio | int | - | Количество срабатываний capacity reset (close-all) | `PortfolioStats.portfolio_reset_capacity_count` | Reporting |
| `portfolio_capacity_prune_count` | Portfolio | int | - | Количество срабатываний capacity prune | `PortfolioStats.portfolio_capacity_prune_count` | Reporting (portfolio_policy_summary.csv) |
| `avg_pruned_positions_per_event` | Portfolio | float | - | Среднее количество закрытых позиций за prune событие | Агрегация из `capacity_prune_events` | Reporting (portfolio_policy_summary.csv) |
| `median_pruned_hold_days` | Portfolio | float | days | Медианное время удержания закрытых позиций при prune | Агрегация из `capacity_prune_events` | Reporting |
| `median_pruned_current_pnl_pct` | Portfolio | float | percent | Медианный current_pnl_pct закрытых позиций при prune | Агрегация из `capacity_prune_events` | Reporting |
| `pruned_positions_share_of_all_closed` | Portfolio | float | - | Доля prune позиций от всех закрытых (0.0 - 1.0) | `count(pruned) / count(closed)` | Reporting |

**Source:** `backtester/domain/portfolio.py:PortfolioStats` (строки 178-225), `backtester/infrastructure/reporter.py:save_portfolio_policy_summary()` (строки 1610-1703)

---

## 5. Stage A (Research) variables

**Источник:** `strategy_stability.csv`, `stage_a_summary.csv`  
**Создатель:** `backtester/research/strategy_stability.py:generate_stability_table_from_portfolio_trades()`  
**Потребители:** Stage B (основной источник), Reporting, Debug

### Window-based метрики

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `split_count` | Stage A | int | - | Количество окон для разбиения периода (например, 2, 3, 4, 5) | Параметр `--splits` или `DEFAULT_SPLITS = [2, 3, 4, 5]` | Stage B (группировка для aggregation) |
| `windows_total` | Stage A | int | - | Общее количество окон (равно `split_count`, включает пустые окна) | `len(all_windows)` | Stage B (критерий `min_windows`) |
| `windows_positive` | Stage A | int | - | Количество окон с положительным PnL (`total_pnl_sol > 0`) | `sum(1 for pnl in window_pnls if pnl > 0)` | Stage A (survival_rate) |
| `survival_rate` | Stage A | float | - | Доля выживших окон: `windows_positive / windows_total` | `windows_positive / windows_total` | Stage B (критерий `min_survival_rate`) |
| `worst_window_pnl` | Stage A | float | SOL | Наихудший PnL окна: `min(window_pnls)` | `min(all_window_pnls)` | Stage B (критерий `min_worst_window_pnl`) |
| `median_window_pnl` | Stage A | float | SOL | Медианный PnL окна: `median(window_pnls)` | `statistics.median(all_window_pnls)` | Stage B (критерий `min_median_window_pnl`) |
| `best_window_pnl` | Stage A | float | SOL | Наилучший PnL окна: `max(window_pnls)` | `max(all_window_pnls)` | Debug |
| `pnl_variance` | Stage A | float | SOL² | Дисперсия PnL по окнам (legacy, не нормализовано) | `statistics.variance(all_window_pnls)` | Stage B (fallback если нет `pnl_variance_norm`) |
| `pnl_variance_norm` | Stage A | float | - | Нормализованная дисперсия PnL: `variance(window_pnl_sol / initial_balance_sol)` | `statistics.variance([pnl / initial_balance_sol for pnl in all_window_pnls])` | Stage B (предпочтительная метрика) |
| `trades_total` | Stage A | int | - | Общее количество исполненных сделок стратегии | `len(positions_df[positions_df["strategy"] == strategy_name])` | Stage A (low-N detection) |

**Важно:**
- `pnl_variance_norm` — предпочтительная метрика для Stage B (безразмерная, корректное сравнение стратегий с разными начальными балансами)
- `pnl_variance` (legacy) — остается для обратной совместимости и диагностики
- Stage B использует `pnl_variance_norm` если она присутствует, иначе fallback на `pnl_variance`

### Runner метрики (опциональные)

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `hit_rate_x2` | Stage A | float | - | Доля сделок, достигших x2: `count(max_xn >= 2.0) / total` | `calculate_runner_metrics()` из `portfolio_positions.csv` | Stage B (V1 критерий, если задан) |
| `hit_rate_x5` | Stage A | float | - | Доля сделок, достигших x5: `count(max_xn >= 5.0) / total` | `calculate_runner_metrics()` | Stage B (V1 критерий, если задан) |
| `hit_rate_x4` | Stage A | float | - | Доля сделок, достигших x4 (tail threshold): `count(max_xn >= 4.0) / total` | `calculate_runner_metrics()` | Stage B (V2 критерий) |
| `p90_hold_days` | Stage A | float | days | 90-й перцентиль времени удержания (конвертируется из `hold_minutes`) | `percentile(hold_minutes / (24 * 60), 90)` | Stage B (V1 критерий, если задан) |
| `tail_pnl_share` | Stage A | float | - | Доля realized PnL от tail сделок (max_xn >= 4.0): `realized_tail_pnl_sol / realized_total_pnl_sol` | `calculate_runner_metrics()` из `portfolio_positions.csv` | Stage B (V2 критерий) |
| `non_tail_pnl_share` | Stage A | float | - | Доля realized PnL от non-tail сделок (может быть отрицательной): `(realized_total - realized_tail) / realized_total` | `calculate_runner_metrics()` | Stage B (V2 критерий) |
| `tail_contribution` | Stage A | float | - | Legacy: доля PnL от сделок с max_xn >= 5.0 (используется `pnl_sol`, не `realized_pnl_sol`) | `calculate_runner_metrics()` | Debug (legacy compatibility) |
| `max_drawdown_pct` | Stage A | float | percent | Максимальная просадка портфеля (из `portfolio_summary.csv`) | `portfolio_summary.csv` | Stage B (V2 критерий, если задан) |

**Source:** `backtester/research/strategy_stability.py:calculate_stability_metrics()` (строки 93-171), `calculate_runner_metrics()` (строки 172-400)

### Что Stage A НЕ имеет права делать

**Запрещено:**
- ❌ Фильтровать позиции по `closed_by_reset` / `reset_reason`
- ❌ Корректировать метрики на основе причины закрытия
- ❌ Пересчитывать `pnl_sol` из `exec_entry_price` / `exec_exit_price`
- ❌ Использовать execution-level CSV (должен использоваться только positions-level)
- ❌ Изменять данные (Stage A только читает и агрегирует)

**Какие поля Stage A читает, но не интерпретирует:**
- `closed_by_reset` — читается для observability, но не влияет на метрики
- `reset_reason` — читается для observability, но не влияет на метрики
- `triggered_portfolio_reset` — читается для observability, но не влияет на метрики

**Важно:** Stage A работает с **executed positions** и не должна делать предположения о причинах закрытия. Reset-закрытые позиции обрабатываются так же, как стратегические. См. `docs/RESET_IMPACT_ON_STAGE_A_B_v2.2.md`.

---

## 6. Stage B (Decision) variables

**Источник:** `strategy_selection.csv`, `strategy_selection_agg.csv`  
**Создатель:** `backtester/decision/strategy_selector.py:select_strategies()`, `backtester/decision/selection_aggregator.py:aggregate_selection()`  
**Потребители:** Пользователь (primary decision artifact), Reporting

### Per-split selection (strategy_selection.csv)

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `strategy` | Stage B | str | - | Название стратегии | Из `strategy_stability.csv` | Grouping |
| `split_count` | Stage B | int | - | Количество окон (для grouping) | Из `strategy_stability.csv` | Aggregation |
| `passed` | Stage B | bool | - | **Decision-critical:** Прошла ли стратегия все критерии для данного `split_count` | `check_strategy_criteria()` | User (decision), Aggregation |
| `failed_reasons` | Stage B | List[str] | - | Список причин отклонения (если `passed=False`), разделитель `"; "` | `check_strategy_criteria()` | Debug (explainability) |
| `selection_status` | Stage B | str (optional) | - | Статус отбора: `"passed"` / `"rejected"` / `"insufficient_data"` (если присутствует) | В будущем (low-N evolution) | Aggregation (insufficient_data_rate, rejected_rate) |

**Все метрики из `strategy_stability.csv` копируются как есть** (survival_rate, worst_window_pnl, median_window_pnl, pnl_variance, pnl_variance_norm, etc.)

### Aggregated selection (strategy_selection_agg.csv) — primary decision artifact

| Variable | Level | Type | Units | Description | Source | Consumers |
|----------|-------|------|-------|-------------|--------|-----------|
| `strategy` | Stage B | str | - | Название стратегии | Из `strategy_selection.csv` | User (decision) |
| `splits_total` | Stage B | int | - | Количество значений `split_count`, по которым агрегирована стратегия | `len(group_df)` | Debug |
| `robust_pass_rate` | Stage B | float | - | **Decision-critical:** Средний `passed` по всем `split_count` (доля разбиений, где стратегия прошла) | `mean(passed_series)` | User (decision robustness) |
| `passed_any` | Stage B | bool | - | **Decision-critical:** Прошла ли стратегия хотя бы при одном `split_count` | `any(passed_series)` | User (decision) |
| `passed_all` | Stage B | bool | - | Прошла ли стратегия при всех `split_count` | `all(passed_series)` | Debug (stability) |
| `worst_case_window_pnl` | Stage B | float | SOL | Минимальный `worst_window_pnl` по всем `split_count` | `min(worst_window_pnl)` | User (worst case) |
| `median_survival_rate` | Stage B | float | - | Медианный `survival_rate` по всем `split_count` | `median(survival_rate)` | User (robustness) |
| `median_median_window_pnl` | Stage B | float | SOL | Медиана медианных PnL окон по всем `split_count` | `median(median_window_pnl)` | User (robustness) |
| `max_pnl_variance` | Stage B | float | SOL² | Максимальный `pnl_variance` по всем `split_count` | `max(pnl_variance)` | User (worst case) |
| `max_pnl_variance_norm` | Stage B | float | - | Максимальный `pnl_variance_norm` по всем `split_count` (если присутствует) | `max(pnl_variance_norm)` | User (worst case, preferred) |
| `insufficient_data_rate` | Stage B | float | - | Доля разбиений со статусом `insufficient_data` (если `selection_status` присутствует) | `mean(selection_status == "insufficient_data")` | Debug (low-N detection) |
| `rejected_rate` | Stage B | float | - | Доля разбиений со статусом `rejected` (если `selection_status` присутствует) | `mean(selection_status == "rejected")` | Debug (rejection analysis) |

**Дополнительные метрики из `strategy_stability.csv`** копируются (медиана если варьируется, значение если постоянно)

### Decision-critical vs Diagnostic

**Decision-critical (используются для принятия решений):**
- `passed` (per-split) / `robust_pass_rate`, `passed_any`, `passed_all` (aggregated)
- `worst_case_window_pnl`, `median_survival_rate`, `median_median_window_pnl`, `max_pnl_variance` / `max_pnl_variance_norm` (aggregated)

**Purely diagnostic (только для объяснения/отладки):**
- `failed_reasons` — объясняет, почему стратегия не прошла
- `split_count` (per-split) / `splits_total` (aggregated) — для понимания чувствительности
- `insufficient_data_rate`, `rejected_rate` — для понимания low-N проблем

**Важно:** Decision about a strategy SHOULD be made using aggregated selection (`strategy_selection_agg.csv`). Per-split selection exists for diagnostics and sensitivity analysis. См. `docs/STAGE_A_B_PRINCIPLES_v2.2.md`.

**Source:** `backtester/decision/strategy_selector.py:check_strategy_criteria()` (строки 27-250), `backtester/decision/selection_aggregator.py:aggregate_selection()` (строки 102-230)

---

## 7. Reset-related variables

**Сводная таблица reset-related переменных через все уровни**

| Variable | Level | Set by | Meaning | Used by | Notes |
|----------|-------|--------|---------|---------|-------|
| `reset_reason` | Position | `apply_portfolio_reset()`, `_maybe_apply_capacity_prune()` | Причина reset: `"profit_reset"` / `"capacity_prune"` / `"none"` | Stage A (читает, но не интерпретирует), Audit (consistency), Debug | Не нормализуется, используется как есть |
| `closed_by_reset` | Position | `apply_portfolio_reset()`, `_forced_close_position()` | Закрыта ли позиция по reset/prune | Stage A (читает, но не интерпретирует), Audit (consistency), Debug | Boolean флаг |
| `triggered_portfolio_reset` | Position | `apply_portfolio_reset()` (только для marker) | Триггернула ли portfolio-level reset (только для marker позиции profit reset) | Debug (marker identification) | Только для marker позиции |
| `reset_exit_price_fallback` | Position | `get_mark_price_for_position()` | Fallback exit price использован (если свечи отсутствуют, используется `entry_price`) | Debug (price validation) | Помечается в `Position.meta` |
| `cycle_start_equity` | Portfolio | `apply_portfolio_reset()` (profit reset only) | Equity в начале текущего цикла (сбрасывается после profit reset) | Reset logic (trigger condition) | Только profit reset сбрасывает |
| `equity_peak_in_cycle` | Portfolio | `update_equity_peak()`, `apply_portfolio_reset()` (profit reset only) | Пик equity в текущем цикле (сбрасывается после profit reset) | Reset logic (trigger condition) | Только profit reset сбрасывает |
| `portfolio_reset_profit_count` | Portfolio | `apply_portfolio_reset()` (profit reset only) | Количество срабатываний profit reset | Reporting (portfolio_policy_summary.csv) | Только profit reset увеличивает |
| `portfolio_capacity_prune_count` | Portfolio | `_maybe_apply_capacity_prune()` (prune only) | Количество срабатываний capacity prune | Reporting (portfolio_policy_summary.csv) | Только prune увеличивает, НЕ увеличивает `portfolio_reset_count` |
| `capacity_prune_trigger_time` | Position | `_maybe_apply_capacity_prune()` | Время срабатывания prune (ISO) | Debug (prune analysis) | Сохраняется в `Position.meta` |
| `capacity_prune_current_pnl_pct` | Position | `_maybe_apply_capacity_prune()` | current_pnl_pct позиции до закрытия | Debug (prune analysis) | Сохраняется в `Position.meta` |
| `capacity_prune_score` | Position | `_maybe_apply_capacity_prune()` | Score позиции для выбора кандидатов | Debug (prune analysis) | Сохраняется в `Position.meta` |

**Важно:**
- Profit reset сбрасывает `cycle_start_equity` и `equity_peak_in_cycle`
- Capacity prune НЕ сбрасывает `cycle_start_equity` и `equity_peak_in_cycle` (цикл продолжается)
- Stage A читает reset-related поля, но не должна интерпретировать их (reset — это portfolio policy, а Stage A — observation)

**Source:** `docs/PRUNE_AND_PROFIT_RESET_RULES.md`, `backtester/domain/portfolio_reset.py`, `backtester/domain/portfolio.py`

---

## 8. Типовые ошибки и анти-паттерны

### Ошибка 1: Путать pnl_sol и pnl_pct

**Проблема:**
- `pnl_sol` (SOL) — портфельный PnL в SOL (source of truth для Stage A)
- `pnl_pct_total` (percent) — PnL в процентах (от realized_multiple, legacy compatibility)

**Неправильно:**
- Использовать `pnl_pct_total` в Stage A вместо `pnl_sol`
- Пересчитывать `pnl_sol` из `pnl_pct_total * size`

**Правильно:**
- Stage A использует `pnl_sol` из `portfolio_positions.csv` как есть
- `pnl_pct_total` используется только для legacy compatibility

**Source:** `backtester/research/window_aggregator.py:calculate_window_metrics()` (строки 122-246) использует `pnl_sol` для portfolio trades

### Ошибка 2: Использовать execution price в Stage A

**Проблема:**
- Execution prices (`exec_entry_price`, `exec_exit_price`) — для диагностики slippage
- Stage A использует `pnl_sol` (source of truth), а не пересчитывает из execution prices

**Неправильно:**
- Пересчитывать `pnl_sol = (exec_exit_price - exec_entry_price) / exec_entry_price * size` в Stage A
- Использовать `exec_entry_price` / `exec_exit_price` для вычисления метрик

**Правильно:**
- Stage A использует `pnl_sol` из `portfolio_positions.csv` как есть
- `exec_entry_price` / `exec_exit_price` используются только для валидации (если необходимо)

**Source:** `backtester/research/window_aggregator.py:validate_trades_table()` (строки 27-79) валидирует наличие `pnl_sol`, но не требует `exec_entry_price` / `exec_exit_price`

### Ошибка 3: Нормализовать variance повторно

**Проблема:**
- `pnl_variance_norm` уже нормализована в Stage A
- Stage B не должна нормализовать `pnl_variance` повторно

**Неправильно:**
- Нормализовать `pnl_variance` в Stage B: `pnl_variance_norm = pnl_variance / initial_balance_sol²`
- Использовать `pnl_variance` если `pnl_variance_norm` присутствует

**Правильно:**
- Stage B использует `pnl_variance_norm` если она присутствует в `strategy_stability.csv`
- Если `pnl_variance_norm` отсутствует, Stage B использует fallback на `pnl_variance` (legacy)

**Source:** `backtester/decision/strategy_selector.py:check_strategy_criteria()` (строки 436-439) — resolution order: `pnl_variance_norm` → `pnl_variance`

### Ошибка 4: Считать equity из positions напрямую

**Проблема:**
- Equity — это portfolio-level метрика (`balance + sum(open_positions.size)`)
- Equity нельзя считать из `portfolio_positions.csv` напрямую (нужно знать баланс и открытые позиции)

**Неправильно:**
- Считать equity как `sum(pnl_sol)` из `portfolio_positions.csv`
- Использовать `final_balance_sol - initial_balance_sol` как equity

**Правильно:**
- Equity считается в runtime: `balance + sum(p.size for p in open_positions)`
- Stage A использует `initial_balance_sol` из config для нормализации, а не equity

**Source:** `backtester/domain/portfolio_reset.py:current_equity()` (строки 111-113)

### Ошибка 5: Фильтровать позиции по reset_reason в Stage A

**Проблема:**
- Reset-закрытые позиции — это часть portfolio policy
- Stage A должна обрабатывать все executed positions одинаково

**Неправильно:**
- Фильтровать `positions_df[positions_df["closed_by_reset"] == False]` в Stage A
- Корректировать метрики на основе `reset_reason`

**Правильно:**
- Stage A читает все позиции из `portfolio_positions.csv` (status="closed")
- Stage A не фильтрует по `closed_by_reset` / `reset_reason`
- Reset-закрытые позиции обрабатываются так же, как стратегические

**Source:** `backtester/research/window_aggregator.py:validate_trades_table()` (строки 27-79) — валидирует только `status="closed"`, не фильтрует по reset

---

## 9. Привязка к исходникам

### Reporter (CSV артефакты)

| Артефакт | Функция/метод | Описание |
|----------|---------------|----------|
| `portfolio_positions.csv` | `backtester/infrastructure/reporter.py:save_portfolio_positions_table()` (строки 979-1223) | Positions-level агрегат, source of truth для Stage A |
| `portfolio_events.csv` | `backtester/infrastructure/reporter.py:save_portfolio_events_table()` (строки 1225-1316) | Канонический event ledger, source of truth для audit |
| `portfolio_executions.csv` | `backtester/infrastructure/reporter.py:save_portfolio_executions_table()` (строки 1324-1608) | Execution-level дебаг, источник цен и комиссий |
| `portfolio_policy_summary.csv` | `backtester/infrastructure/reporter.py:save_portfolio_policy_summary()` (строки 1610-1703) | Статистика reset/prune |

### Stage A (Research)

| Метрика | Функция/метод | Описание |
|---------|---------------|----------|
| Window metrics | `backtester/research/window_aggregator.py:calculate_window_metrics()` (строки 122-246) | Метрики одного окна (total_pnl_sol, trades_count) |
| Stability metrics | `backtester/research/strategy_stability.py:calculate_stability_metrics()` (строки 93-171) | Метрики устойчивости (survival_rate, pnl_variance, worst_window_pnl, etc.) |
| Runner metrics | `backtester/research/strategy_stability.py:calculate_runner_metrics()` (строки 172-400) | Runner метрики (hit_rate_x2/x5/x4, tail_pnl_share, etc.) |

### Stage B (Decision)

| Метрика | Функция/метод | Описание |
|---------|---------------|----------|
| Selection criteria | `backtester/decision/strategy_selector.py:check_strategy_criteria()` (строки 27-250) | Проверка критериев для одной стратегии (passed, failed_reasons) |
| Variance resolution | `backtester/decision/strategy_selector.py:check_strategy_criteria()` (строки 436-439) | Resolution order: `pnl_variance_norm` → `pnl_variance` |
| Aggregation | `backtester/decision/selection_aggregator.py:aggregate_selection()` (строки 102-230) | Aggregation across split_count (robust_pass_rate, passed_any/all, etc.) |

### Portfolio (Runtime)

| Переменная | Класс/файл | Описание |
|------------|------------|----------|
| `initial_balance_sol` | `backtester/domain/portfolio.py:PortfolioConfig` (строка 102) | Начальный баланс портфеля |
| `cycle_start_equity` | `backtester/domain/portfolio.py:PortfolioStats` (строка 214) | Equity в начале цикла |
| `equity_peak_in_cycle` | `backtester/domain/portfolio.py:PortfolioStats` (строка 215) | Пик equity в цикле |
| `portfolio_reset_profit_count` | `backtester/domain/portfolio.py:PortfolioStats` (строка 192) | Счетчик profit reset |
| `portfolio_capacity_prune_count` | `backtester/domain/portfolio.py:PortfolioStats` (строка 218) | Счетчик capacity prune |

---

## Связанные документы

- `docs/CANONICAL_LEDGER_CONTRACT.md` — структура событий и инварианты
- `docs/STAGE_A_B_PRINCIPLES_v2.2.md` — контракты Stage A/B и метрики
- `docs/PRUNE_AND_PROFIT_RESET_RULES.md` — reset-related переменные и поля
- `docs/PIPELINE_GUIDE.md` — общий пайплайн и source of truth
- `docs/RESET_IMPACT_ON_STAGE_A_B_v2.2.md` — влияние reset на Stage A/B

---

*Документ создан: 2025-01-XX*  
*Версия справочника: 1.0*
