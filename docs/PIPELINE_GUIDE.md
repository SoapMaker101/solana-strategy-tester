# Пайплайн данных Solana Strategy Tester v2.1.9

**Версия фиксации:** 2.1.9 (Frozen Baseline)  
**Дата фиксации:** 2025-01-06  
**Режим:** Runner-only

---

## 1. Общий обзор пайплайна

### High-level схема (текстовая)

```
Signals (CSV)
    ↓
Application Layer (BacktestRunner)
    ↓
Domain Layer (RunnerStrategy → RunnerLadderEngine)
    ↓
StrategyOutput
    ↓
Portfolio Engine (PortfolioEngine)
    ↓
Positions + Events + Executions
    ↓
Audit (InvariantChecker)
    ↓
Stage A (Research) → strategy_stability.csv
    ↓
Stage B (Decision) → strategy_selection.csv
    ↓
Reporting (CSV / XLSX)
```

### Где начинается пайплайн

Пайплайн начинается с:

- **Точка входа:** `main.py`
- **Входные данные:** CSV файл с сигналами (`signals/example_signals.csv`)
- **Команда запуска:** `python main.py --signals ... --strategies-config ... --backtest-config ...`

### Где он заканчивается

Пайплайн заканчивается генерацией артефактов:

- **CSV файлы:** `portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv`
- **Stage A:** `strategy_stability.csv`
- **Stage B:** `strategy_selection.csv`
- **XLSX:** Report pack (best-effort)

---

## 2. Входные данные

### Signals

**Формат:** CSV файл

**Обязательные колонки:**
- `signal_id` — уникальный идентификатор сигнала
- `contract_address` — адрес токена/пула
- `timestamp` — время генерации сигнала

**Опциональные колонки:**
- `source` — источник сигнала
- `narrative` — описание сигнала
- Дополнительные поля в `extra`

**Где валидируются:**
- `backtester/infrastructure/signal_loader.py` — `CsvSignalLoader.load()`

**Пример:**
```csv
signal_id,contract_address,timestamp,source
test1,So11111111111111111111111111111111111111112,2025-01-01T10:00:00,bot
```

### Candles

**Формат:** CSV файл или API (GeckoTerminal)

**Структура:**
- `timestamp` — время закрытия свечи
- `open`, `high`, `low`, `close` — цены OHLC
- `volume` — объем торгов

**Где загружаются:**
- `backtester/infrastructure/price_loader.py` — `CsvPriceLoader` или `GeckoTerminalPriceLoader`

**Временное окно:**
- `before_minutes` — сколько минут до сигнала загружать (по умолчанию: 60)
- `after_minutes` — сколько минут после сигнала загружать (по умолчанию: 360)

**Кеширование:**
- Свечи кешируются в `data/candles/cached/1m/`
- Кеш обновляется только если запрашиваемый диапазон выходит за пределы кеша
- См. `docs/CACHE_UPDATE_BEHAVIOR.md` для деталей

### Configs

**Формат:** YAML файлы

**Типы конфигураций:**

1. **Strategies config** (`config/strategies_example.yaml`):
   - Список стратегий с параметрами
   - Runner-only: все стратегии типа `RUNNER`

2. **Backtest config** (`config/backtest_example.yaml`):
   - Настройки данных (`data.loader`, `data.candles_dir`, `data.before_minutes`, `data.after_minutes`)
   - Настройки портфеля (`portfolio.initial_balance_sol`, `portfolio.allocation_mode`, `portfolio.percent_per_trade`, `portfolio.max_exposure`, `portfolio.max_open_positions`, `portfolio.execution_profile`, `portfolio.fee`)

**Где валидируются:**
- `backtester/application/runner.py` — `BacktestRunner.__init__()`
- `backtester/domain/portfolio.py` — `PortfolioConfig` dataclass

**Парсинг конфигурации:**
- `_parse_bool` — парсит `"true"/"false"`, `1/0`, `True/False` → `bool`
- `_parse_int_optional` — парсит `"4320"`, `0`, `None` → `int` или `None`
- **Критично:** `0 != None` — `max_hold_minutes=0` это валидное значение, не отсутствие

---

## 3. Execution pipeline

### on_signal

**Где:** `backtester/domain/runner_strategy.py` — `RunnerStrategy.on_signal()`

**Входы:**
- `StrategyInput` (сигнал + свечи + глобальные параметры)

**Процесс:**
1. Отбираются свечи, начиная с момента сигнала
2. Вызывается `RunnerLadderEngine.simulate()`
3. Формируется `StrategyOutput` с результатами

**Выходы:**
- `StrategyOutput` с:
  - `entry_time`, `entry_price` — вход
  - `exit_time`, `exit_price` — выход
  - `realized_multiple` — множитель из fills ledger
  - `canonical_reason` — каноническая причина выхода
  - `meta` — дополнительные данные (levels_hit, fractions_exited, etc.)

### RunnerLadderEngine

**Где:** `backtester/domain/runner_ladder.py` — `RunnerLadderEngine.simulate()`

**Процесс:**
1. Получает уровни TP из конфига (`take_profit_levels`)
2. Проверяет каждый уровень на достижение
3. Частично закрывает позицию на каждом достигнутом уровне
4. Вычисляет `realized_multiple` как сумму `xn * fraction` для всех уровней
5. Определяет финальный выход (все уровни достигнуты или timeout)

**Выходы:**
- `RunnerTradeResult` с:
  - `levels_hit` — когда был достигнут каждый уровень
  - `fractions_exited` — какая доля закрыта на каждом уровне
  - `realized_multiple` — реализованный множитель

### Partial exits

**Где:** `backtester/domain/runner_ladder.py`

**Процесс:**
- Для каждого уровня TP (например, 2x, 5x, 10x):
  - Проверяется, достигнута ли цена уровня
  - Если да — закрывается доля позиции (`fraction`)
  - Событие `POSITION_PARTIAL_EXIT` эмитится Portfolio Engine

**Данные:**
- `PartialExitBlueprint` с `fraction` и `level` (xn)
- Хранится в `StrategyOutput.meta["partial_exits"]`

### Final exit

**Где:** `backtester/domain/runner_ladder.py`

**Процессы:**
1. **Все уровни достигнуты:** `reason="all_levels_hit"` → `canonical_reason="ladder_tp"`
2. **Timeout:** `reason="time_stop"` → `canonical_reason="time_stop"`
3. **Нет данных:** `reason="no_data"` → `canonical_reason="no_entry"`

**Данные:**
- `FinalExitBlueprint` с `exit_time`, `exit_price`, `reason`
- Хранится в `StrategyOutput.meta["final_exit"]`

### Slippage

**Где:** `backtester/domain/execution_model.py` — `ExecutionModel.apply_entry()`, `ExecutionModel.apply_exit()`

**Процесс:**
1. Reason нормализуется в exit type через `_normalize_reason_to_exit_type()`
2. Применяется slippage multiplier из execution profile
3. Для входа: `effective_price = price * (1 + slippage)`
4. Для выхода: `effective_price = price * (1 - slippage)`

**Execution profiles:**
- `realistic` — реалистичные multipliers (exit_tp: 0.7, exit_sl: 1.2, exit_timeout: 0.3)
- `stress` — стрессовые multipliers
- `custom` — пользовательские настройки

### Fees

**Где:** `backtester/domain/execution_model.py` — `ExecutionModel.apply_fees()`, `ExecutionModel.network_fee()`

**Типы комиссий:**
- **Swap fee:** процентная комиссия за swap (по умолчанию: 0.3%)
- **LP fee:** процентная комиссия за LP (по умолчанию: 0.1%)
- **Network fee:** фиксированная комиссия сети в SOL (по умолчанию: 0.0005 SOL)

**Применение:**
- Swap + LP fees вычитаются из нотионала
- Network fee вычитается отдельно из баланса портфеля

---

## 4. Portfolio / Replay

### Position lifecycle

**Где:** `backtester/domain/portfolio.py` — `PortfolioEngine.simulate()`

**Жизненный цикл позиции:**

1. **Создание:** `Position` создается при обработке `StrategyOutput`
   - `position_id` — UUID, генерируется автоматически
   - `status="open"`
   - `entry_time`, `entry_price` из `StrategyOutput`

2. **Partial exits:** Частичные закрытия через `POSITION_PARTIAL_EXIT` события
   - Размер позиции уменьшается на `fraction`
   - `realized_multiple` обновляется

3. **Final exit:** Полное закрытие через `POSITION_CLOSED` событие
   - `status="closed"`
   - `exit_time`, `exit_price` из `StrategyOutput`
   - `pnl_sol` вычисляется из fills ledger

### Events

**Где:** `backtester/domain/portfolio_events.py`

**Типы событий:**
- `POSITION_OPENED` — открытие позиции
- `POSITION_PARTIAL_EXIT` — частичное закрытие позиции
- `POSITION_CLOSED` — полное закрытие позиции
- `PORTFOLIO_RESET_TRIGGERED` — срабатывание portfolio-level reset

**Структура события:**
- `event_id` — UUID, генерируется автоматически
- `timestamp` — время события
- `event_type` — тип события
- `position_id` — ссылка на позицию
- `reason` — каноническая причина
- `meta` — execution данные (raw_price, exec_price, execution_type, etc.)

**Порядок событий:**
- Для каждого `position_id`: `POSITION_OPENED` → `POSITION_PARTIAL_EXIT*` → `POSITION_CLOSED`
- `PORTFOLIO_RESET_TRIGGERED` эмитится после закрытий всех позиций при reset

**Где смотреть подтверждение partial/final (Variant C):**
- **portfolio_events.csv:**
  - TP partial exits: `POSITION_PARTIAL_EXIT` с `reason="ladder_tp"`
  - Final close (remainder): `POSITION_CLOSED` с `reason="time_stop"` (НЕ отдельный `POSITION_PARTIAL_EXIT` для remainder)
  - Final close (полное закрытие на уровнях): `POSITION_CLOSED` с `reason="ladder_tp"`
- **portfolio_executions.csv:**
  - TP partial exits: `event_type="partial_exit"`, `reason="ladder_tp"`
  - Final exit (remainder): `event_type="final_exit"`, `reason="time_stop"`, `event_id` ссылается на `POSITION_CLOSED.event_id`
  - Final exit (полное закрытие на уровнях): `event_type="final_exit"`, `reason="ladder_tp"`
- **Важно:** Остаток закрыт по time_stop → проверяйте `executions.final_exit` + `events.position_closed` (reason="time_stop")

### Capacity rules

**Где:** `backtester/domain/portfolio.py` — `PortfolioEngine._check_capacity()`

**Правила:**
- `max_open_positions` — максимальное количество открытых позиций
- `max_exposure` — максимальная экспозиция (доля баланса в открытых позициях)
- `allocation_mode` — режим аллокации (`dynamic` или `fixed`)

**При превышении:**
- Новые сигналы отклоняются
- При `capacity_prune` — закрываются худшие позиции

### Profit reset

**Где:** `backtester/domain/portfolio_reset.py`

**Условия:**
- `profit_reset_threshold_pct` — порог прибыли для reset (по умолчанию: 50%)
- Когда equity превышает `cycle_start_equity * (1 + threshold)`, срабатывает reset

**Процесс:**
1. Все открытые позиции закрываются с `reason="profit_reset"`
2. Эмитится `PORTFOLIO_RESET_TRIGGERED` событие
3. `cycle_start_equity` обновляется

### Replay determinism

**Где:** `backtester/domain/portfolio_replay.py` — `PortfolioReplay`

**Процесс:**
1. `StrategyTradeBlueprint` конвертируется в `Position`
2. События генерируются в детерминированном порядке
3. Market close price используется `candles[-1].close`

**Гарантии:**
- Детерминированный порядок событий
- Детерминированные цены (market close)
- Детерминированные `position_id` и `event_id` (UUID, но детерминированные при одинаковых входных данных)

---

## 5. Audit pipeline

### Когда запускается

**Где:** `backtester/audit/run_audit.py` — `audit_run()`

**Триггеры:**
- После основного бэктеста (перед Stage A/B)
- Перед Stage A (блокирует если P0 > 0)
- Перед Stage B (блокирует если P0 > 0)

**Команда:**
```bash
python -m backtester.audit.run_audit --reports-dir output/reports
```

### P0 / P1

**Классификация аномалий:**

- **P0 (критические):**
  - `PNL_CAP_OR_MAGIC` — магическое значение PnL
  - `TP_REASON_BUT_NEGATIVE_PNL` — reason=tp, но pnl < 0
  - `SL_REASON_BUT_POSITIVE_PNL` — reason=sl, но pnl > 0
  - `ENTRY_PRICE_INVALID` — entry_price <= 0 или NaN
  - `EXIT_PRICE_INVALID` — exit_price <= 0 или NaN
  - `TIME_ORDER_INVALID` — entry_time > exit_time
  - `MISSING_EVENTS_CHAIN` — нет цепочки событий для позиции

- **P1 (важные):**
  - `POSITION_CLOSED_BUT_NO_CLOSE_EVENT` — позиция закрыта, но нет события закрытия
  - `CLOSE_EVENT_BUT_POSITION_OPEN` — есть событие закрытия, но позиция открыта
  - `TRADE_EVENT_WITHOUT_EXECUTION` — событие торговли без execution

- **P2 (информационные):**
  - `PROFIT_RESET_TRIGGERED_BUT_CONDITION_FALSE` — reset сработал, но условие не выполнено
  - `CAPACITY_THRESHOLDS_MET_BUT_NO_ACTION` — пороги превышены, но действие не сработало

### Invariants

**Где:** `backtester/audit/invariants.py` — `InvariantChecker`

**Проверяемые инварианты:**

1. **PnL consistency:**
   - TP reason → pnl >= -epsilon
   - SL reason → pnl < -epsilon

2. **Price validity:**
   - entry_price > 0 и не NaN
   - exit_price > 0 и не NaN (если позиция закрыта)

3. **Time ordering:**
   - entry_time <= exit_time (если позиция закрыта)

4. **Event chain:**
   - Для каждого position_id: OPENED → PARTIAL_EXIT* → CLOSED
   - Порядок событий монотонный по timestamp

5. **Execution consistency:**
   - Каждое trade-related событие имеет execution в meta
   - Execution данные согласованы с событием

### Reason families

**Где:** `backtester/audit/invariants.py` — `normalize_reason()`

**Reason families:**
- TP family: `tp`, `tp_*`, `ladder_tp` → нормализуется в `tp`
- SL family: `sl`, `stop_loss` → нормализуется в `sl`
- Timeout family: `timeout`, `time_stop`, `max_hold_minutes` → нормализуется в `timeout`

**Использование:**
- Для проверки consistency (TP → pnl >= 0, SL → pnl < 0)
- Для группировки причин выхода в статистике

### Что блокирует Stage A/B

**Блокировка при P0 > 0:**
- Stage A отказывается запускаться
- Stage B отказывается запускаться
- Exit code 2 возвращается

**Логика:**
- `backtester/research/run_stage_a.py` — проверка перед запуском
- `backtester/decision/run_stage_b.py` — проверка перед запуском

---

## 6. Stage A (Research)

### Что считает

**Где:** `backtester/research/strategy_stability.py` — `generate_stability_table_from_portfolio_trades()`

**Метрики:**

1. **Survival rate:** доля окон, показывающих прибыльность (0.0 - 1.0)
2. **Worst window PnL:** худший PnL среди всех окон
3. **Median window PnL:** медианный PnL окон
4. **PnL variance:** дисперсия PnL окон
5. **Windows total:** общее количество окон

**Для Runner стратегий дополнительно:**
- `hit_rate_x2` — доля сделок, достигших уровня >=2x
- `hit_rate_x5` — доля сделок, достигших уровня >=5x
- `hit_rate_x4` — доля сделок, достигших уровня >=4x (V2)
- `p90_hold_days` — 90-й перцентиль времени удержания позиции в днях
- `tail_contribution` / `tail_pnl_share` — доля PnL от сделок с `realized_multiple >= 5x`
- `non_tail_pnl_share` — доля PnL от сделок с `realized_multiple < 5x` (V2)

### Что НЕ решает

Stage A не принимает решений:

- Не отбирает стратегии (это делает Stage B)
- Не изменяет execution (decision не влияет на execution)
- Не проверяет инварианты (это делает Audit)

### Какие CSV формирует

**Выходные файлы:**

1. **`strategy_stability.csv`:**
   - Колонки: `strategy`, `split_count`, `survival_rate`, `worst_window_pnl`, `median_window_pnl`, `pnl_variance`, `windows_total`
   - Для Runner: дополнительные колонки с метриками

2. **`stage_a_summary.csv`:**
   - Детальная таблица со всеми окнами
   - Колонки: `strategy`, `split_count`, `window_index`, `window_start`, `window_end`, `trades_count`, `winrate`, `total_pnl`, `median_pnl`, etc.

**Где создаются:**
- `backtester/research/run_stage_a.py` — CLI entry point
- `backtester/research/window_aggregator.py` — агрегация по окнам

---

## 7. Stage B (Decision)

### Criteria V1

**Где:** `backtester/decision/selection_rules.py` — `DEFAULT_CRITERIA_V1`

**Обязательные критерии:**
- `survival_rate >= 0.60` (60% окон должны быть прибыльными)
- `pnl_variance <= 0.15` (дисперсия не должна быть слишком высокой)
- `worst_window_pnl >= -0.25` (даже худший период не должен принести >25% потерь)
- `median_window_pnl >= 0.00` (медианный результат должен быть неотрицательным)
- `windows_total >= 3` (минимум 3 окна для статистической значимости)

**Применение:**
- Все стратегии проверяются по V1 критериям
- Если хотя бы один критерий не выполнен — стратегия отклоняется

### Runner Criteria V2

**Где:** `backtester/decision/selection_rules.py` — `DEFAULT_RUNNER_CRITERIA_V2`

**Опциональные критерии (только если есть колонки):**
- `hit_rate_x4 >= 0.10` (10% сделок должны достичь x4)
- `tail_pnl_share >= 0.30` (30% PnL от tail сделок)
- `non_tail_pnl_share >= -0.20` (non-tail сделки не должны приносить >20% потерь)

**Применение:**
- Проверяется наличие колонок `hit_rate_x4`, `tail_pnl_share`, `non_tail_pnl_share`
- Если колонки есть — применяются V2 критерии
- Если колонок нет — применяются только V1 критерии

### Gate-логика

**Где:** `backtester/decision/strategy_selector.py` — `check_strategy_criteria()`

**Процесс:**

1. Проверяются обязательные V1 критерии
2. Если `runner_criteria` задан:
   - Проверяется наличие V2 колонок
   - Если есть — применяются V2 критерии
   - Если нет — применяются V1 Runner критерии (если есть колонки)

**Gate проверка:**
- `required_v2_cols = {"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}`
- `has_v2_cols = required_v2_cols.issubset(set(stability_df.columns))`
- Если `has_v2_cols` и нет V1 колонок — применяются V2 критерии

### Почему есть V2-hack

**Где:** `backtester/decision/strategy_selector.py` — `select_strategies()`

**V2-hack:**
```python
if runner_criteria is None:
    required_v2_cols = {"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}
    has_v2_cols = required_v2_cols.issubset(set(stability_df.columns))
    if has_v2_cols and (criteria.min_hit_rate_x2 is None and criteria.min_hit_rate_x5 is None):
        runner_criteria = criteria
        criteria = DEFAULT_CRITERIA_V1
```

**Причина:**
- Неявная логика определения V2 критериев через проверку колонок
- Эвристика вместо явного указания версии
- Обеспечивает обратную совместимость

**Статус:**
- Помечено как TECH_DEBT в `docs/TEST_GREEN_BASELINE_2025-01-06.md`
- Планируется рефакторинг в версии 2.2

### Где это задокументировано как TECH_DEBT

**Документы:**
- `docs/TEST_GREEN_BASELINE_2025-01-06.md` — секция "TECH_DEBT"
- `docs/KNOWN_ISSUES_2.1.9.md` — Issue #2: V2-хак в select_strategies

---

## 8. Reporting

### CSV

**Где:** `backtester/infrastructure/reporter.py` — `Reporter.save_csv_report()`

**Файлы:**
- `portfolio_positions.csv` — positions-level source of truth
- `portfolio_events.csv` — канонический event ledger
- `portfolio_executions.csv` — execution ledger

**Контракты:**
- `portfolio_events.csv` — фиксированный порядок колонок: `["timestamp", "event_type", "strategy", "signal_id", "contract_address", "position_id", "event_id", "reason", "meta_json"]`
- `final_exit_json` — `""` вместо `NaN`
- `quoting=csv.QUOTE_ALL` для CSV

### XLSX

**Где:** `backtester/infrastructure/xlsx_writer.py` — `save_xlsx()`

**Файлы:**
- Report pack XLSX (best-effort)

**Особенности:**
- Best-effort экспорт (не является каноникой)
- Может содержать агрегации и вычисления
- Может иметь форматирование и дополнительные колонки
- Используется для удобства просмотра, но не для программной обработки

### Best-effort

**Почему XLSX не канон:**
- Может содержать округления и форматирование
- Может иметь дополнительные вычисления
- Не гарантирует детерминированность
- CSV файлы являются source of truth

### Почему XLSX не канон

**Причины:**
1. Форматирование может изменять значения (округления)
2. Дополнительные вычисления могут отличаться от исходных
3. Не гарантируется детерминированность при повторной генерации
4. CSV файлы содержат исходные данные без изменений

---

## 9. Артефакты пайплайна

| Файл | Кто создает | Кто потребляет | Can be missing / Cannot |
|------|-------------|----------------|------------------------|
| `portfolio_positions.csv` | `PortfolioEngine` | Audit, Stage A, Reporting | Cannot |
| `portfolio_events.csv` | `PortfolioEngine` | Audit, Reporting | Cannot |
| `portfolio_executions.csv` | `PortfolioEngine` | Audit, Reporting | Cannot |
| `strategy_stability.csv` | Stage A (`run_stage_a.py`) | Stage B | Cannot (для Stage B) |
| `strategy_selection.csv` | Stage B (`run_stage_b.py`) | Пользователь | Can |
| `audit_anomalies.csv` | Audit (`run_audit.py`) | Пользователь | Can |
| `portfolio_summary.csv` | `Reporter` | Пользователь | Can |
| `strategy_summary.csv` | `Reporter` | Пользователь | Can |

**Важно о strategy_summary:**
- `portfolio-derived strategy_summary` считает `fees_total_sol` только из `positions-level` (сумма `fees_total_sol` по всем позициям стратегии)
- Никаких пересчётов через executions или helper методы
- `executions.fees_sol` — это распределение `fees_total_sol` по execution-строкам для проверки и дебага, и сумма должна сходиться
| XLSX report pack | `Reporter` | Пользователь | Can |

### Особые требования

**Чётко отмечены точки, где пайплайн намеренно "не умный":**

1. **Best-effort XLSX:**
   - XLSX файлы не являются каноникой
   - Могут содержать округления и форматирование
   - Используются только для просмотра

2. **Optional runner metrics:**
   - V2 критерии применяются только если есть колонки
   - Если колонок нет — применяются только V1 критерии

3. **Legacy compatibility:**
   - Legacy reasons автоматически маппятся в canonical
   - `canonical_reason` optional, auto-computed

4. **Cache update:**
   - Кеш обновляется полностью, а не инкрементально
   - См. `docs/CACHE_UPDATE_BEHAVIOR.md`

---

## Ссылки

- `docs/ARCHITECTURE.md` — архитектура проекта
- `docs/RELEASE_2.1.9.md` — полное описание релиза
- `docs/CANONICAL_LEDGER_CONTRACT.md` — спецификация канонического ledger
- `docs/CACHE_UPDATE_BEHAVIOR.md` — поведение обновления кеша
