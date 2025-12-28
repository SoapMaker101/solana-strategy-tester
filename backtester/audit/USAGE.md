# Audit Module — Руководство по использованию

> **Полное руководство по запуску и разбору результатов аудита прогонов**

---

## A. Что такое audit/ и что он проверяет

Модуль `audit/` выполняет системную проверку корректности прогона бэктеста на трёх уровнях:

- **P0 (критичные)**: Базовые инварианты — формулы PnL, валидность цен, консистентность причин закрытия, порядок времени
- **P1 (data integrity)**: Cross-check между `positions ↔ events ↔ executions` — полнота цепочек событий, соответствие исполнений
- **P2 (decision proofs)**: Доказательства решений — проверка условий срабатывания reset/prune/close-all по фактическим метрикам

**Результат аудита:**
- `audit_anomalies.csv` — список всех найденных отклонений
- `audit_summary.md` — человеческий отчёт с группировками
- `audit_metrics.csv` — агрегированные метрики по severity/типам/стратегиям

**Цель:** Находить поломки в механиках расчёта PnL, цепочке событий, исполнениях, reset/prune до того, как они попадут в production.

---

## B. Предварительные условия

### 1. Активированная виртуальная среда

```powershell
# Активируй venv
.\.venv\Scripts\activate

# Должно быть видно:
(.venv) PS C:\Прочее\Крипта\Тестер соланы>
```

### 2. Наличие входных файлов

В `run_dir` должны существовать стандартные файлы прогона:

- `portfolio_positions.csv` (обязательно)
- `portfolio_events.csv` (желательно, для P1/P2 проверок)
- `portfolio_executions.csv` (опционально, для P1 проверок executions)

**Проверка:**
```powershell
# Проверь наличие файлов
ls runs/v1.10/exp_A/portfolio_*.csv
```

### 3. PowerShell: правильный перенос строк

⚠️ **Важно:** В PowerShell используй **backtick `` ` ``** для переноса строк, **НЕ** `\`

**❌ Неправильно:**
```powershell
python -m backtester.cli.audit_run \
  --run-dir runs/v1.10/exp_A
```

**✅ Правильно:**
```powershell
python -m backtester.cli.audit_run `
  --run-dir runs/v1.10/exp_A
```

Или в одну строку:
```powershell
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A
```

---

## C. Быстрый старт (1 команда)

```powershell
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A
```

**После выполнения:**
- Создаётся папка `runs/v1.10/exp_A/audit/`
- В ней появляются файлы: `audit_anomalies.csv`, `audit_summary.md`, `audit_metrics.csv`

**Выходной код:**
- `0` — нет аномалий
- `1` — найдены аномалии

---

## D. Где смотреть результаты

### Файлы в `run_dir/audit/`:

#### 1. `audit_anomalies.csv` — главный файл

**Колонки:**
- `severity` — P0/P1/P2
- `code` — код аномалии (например, `pnl_cap_or_magic`)
- `position_id` — ID позиции (если применимо)
- `event_id` — ID события (если применимо)
- `strategy` — название стратегии
- `entry_time`, `exit_time` — времена
- `entry_price`, `exit_price` — цены
- `pnl_pct` — PnL в процентах
- `reason` — причина закрытия
- `details_json` — JSON с деталями

**Как использовать:**
- Открой в Excel/LibreOffice
- Отфильтруй по `severity = P0`
- Отсортируй по `pnl_pct` (по убыванию абсолютного значения)

#### 2. `audit_summary.md` — отчёт для человека

**Содержит:**
- Сводку по количеству позиций/событий/исполнений
- Группировку аномалий по severity (P0/P1/P2)
- Топ-20 аномалий по кодам
- Топ-10 стратегий по количеству аномалий

**Как использовать:**
- Открой в любом Markdown-редакторе
- Сначала смотри раздел "Anomalies by Severity"
- Затем "Top Anomalies (by Severity)"

#### 3. `audit_metrics.csv` — агрегированные метрики

**Содержит:**
- `total_positions`, `positions_closed`, `events_total`, `executions_total`
- `anomalies_total`, `anomaly_rate_pct`
- `anomalies_p0`, `anomalies_p1`, `anomalies_p2`
- `anomalies_by_code_*` — метрики по кодам
- `anomalies_by_strategy_*` — метрики по стратегиям

**Как использовать:**
- Открой в Excel/LibreOffice
- Сравни метрики между прогонами (до/после исправлений)

---

## E. Приоритет разбора (как мыслить)

### Правило приоритизации:

1. **Сначала P0** — ломает логику / доказательства
2. **Потом P1** — data integrity, события↔исполнения
3. **Потом P2** — proof'ы reset/prune и глубокая аналитика

### Чек-лист по severity:

#### P0 (критичные — исправлять в первую очередь):

- `reset_without_events` — Reset без соответствующих событий
- `pnl_cap_or_magic` — Магическое значение PnL (например, 920%)
- `tp_reason_but_negative_pnl` — reason=tp, но pnl < 0
- `sl_reason_but_positive_pnl` — reason=sl, но pnl > 0
- `time_order_invalid` — entry_time > exit_time
- `entry_price_invalid` / `exit_price_invalid` — невалидные цены
- `missing_required_fields` — отсутствуют обязательные поля

#### P1 (data integrity — исправлять после P0):

- `execution_without_trade_event` — Execution без соответствующего события
- `trade_event_without_execution` — Событие торговли без execution
- `position_closed_but_no_close_event` — Позиция закрыта, но нет события закрытия
- `close_event_but_position_open` — Есть событие закрытия, но позиция открыта
- `execution_price_out_of_range` — Цена execution вне разумных пределов
- `execution_time_before_event` — Execution раньше события
- `multiple_open_events` / `multiple_close_events` — Несколько событий открытия/закрытия
- `unknown_reason_mapping` — Неизвестный маппинг reason ↔ event_type

#### P2 (decision proofs — для глубокой аналитики):

- `profit_reset_triggered_but_condition_false` — Reset сработал, но условие не выполнено
- `capacity_action_triggered_but_thresholds_not_met` — Prune/reset сработал, но пороги не превышены
- `close_all_without_policy_event` — Close-all без policy event
- `close_all_did_not_close_all_positions` — Close-all не закрыл все позиции

---

## F. Пошаговый workflow (главное)

### Шаг 1 — Запусти аудит

```powershell
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A
```

**Ожидаемый вывод:**
```
[audit] Starting audit for: runs/v1.10/exp_A
[audit] Loaded 150 positions
[audit] Loaded 300 events
[audit] Loaded 200 executions
[audit] Running invariant checks...
[audit] Found 25 anomalies
[audit] Generating report in: runs/v1.10/exp_A/audit
[audit] Saved 25 anomalies to runs/v1.10/exp_A/audit/audit_anomalies.csv
[audit] Saved summary to runs/v1.10/exp_A/audit/audit_summary.md
[audit] Saved metrics to runs/v1.10/exp_A/audit/audit_metrics.csv
[audit] Audit complete. Found 25 anomalies.
```

### Шаг 2 — Открой anomalies и отфильтруй P0

**В Excel/LibreOffice:**
1. Открой `runs/v1.10/exp_A/audit/audit_anomalies.csv`
2. Примени фильтр: `severity = P0`
3. Отсортируй по `pnl_pct` (по убыванию абсолютного значения) или по `code`

**В PowerShell (если нужно быстро посмотреть):**
```powershell
# Показать только P0 аномалии
Import-Csv runs/v1.10/exp_A/audit/audit_anomalies.csv | Where-Object { $_.severity -eq "P0" } | Format-Table position_id, code, pnl_pct, reason
```

### Шаг 3 — Выбери 3–10 самых плохих кейсов

**Критерии выбора:**
- Экстремальный `pnl_pct` (например, 920% или -90%)
- `reset_without_events` — reset без событий
- Расхождение `reason`/знак `pnl` (tp при отрицательном PnL)
- Позиции без событий/исполнений (`missing_events_chain`)
- Невалидные цены (`entry_price_invalid`, `exit_price_invalid`)

**Пример выбора:**
```
position_id: pos_9081, code: pnl_cap_or_magic, pnl_pct: 9.2 (920%)
position_id: pos_1234, code: reset_without_events, reason: profit
position_id: pos_5678, code: tp_reason_but_negative_pnl, pnl_pct: -0.15
```

### Шаг 4 — Запусти детальный разбор одной позиции

```powershell
python -m backtester.cli.audit_trade `
  --run-dir runs/v1.10/exp_A `
  --position-id pos_9081
```

**Или по signal_id:**
```powershell
python -m backtester.cli.audit_trade `
  --run-dir runs/v1.10/exp_A `
  --signal-id sig_123 `
  --strategy Runner_Baseline `
  --contract-address 0xABC...
```

**Что должно вывести:**
- Основные поля позиции (entry/exit, prices, pnl)
- Список событий по позиции
- Список исполнений по позиции
- Отмеченные нарушения (если есть)

**Сохранение в файл:**
```powershell
python -m backtester.cli.audit_trade `
  --run-dir runs/v1.10/exp_A `
  --position-id pos_9081 `
  --output runs/v1.10/exp_A/audit/replay_pos_9081.json
```

### Шаг 5 — Найди корневую причину

**Куда смотреть в коде в зависимости от типа аномалии:**

#### Если `reset_without_events`:
- **Файл:** `backtester/domain/portfolio_reset.py`
- **Места:** Функции `trigger_profit_reset()`, `trigger_capacity_reset()`
- **Что проверить:** Эмиссия событий `PROFIT_RESET_TRIGGERED`, `CAPACITY_RESET_TRIGGERED`

#### Если `pnl_cap_or_magic`:
- **Файл:** `backtester/domain/portfolio.py`, `backtester/domain/execution_model.py`
- **Места:** Расчёт PnL, нормализация цен, decimals
- **Что проверить:** Формула `pnl_pct = (exit_price - entry_price) / entry_price`, масштабирование цен, decimals токенов

#### Если `execution_without_trade_event`:
- **Файл:** `backtester/infrastructure/reporter.py` (метод `save_portfolio_executions_table`)
- **Места:** Маппинг `event_id ↔ execution`, источники ID
- **Что проверить:** Эмиссия trade events на open/close, связка execution с событиями

#### Если `tp_reason_but_negative_pnl`:
- **Файл:** `backtester/domain/runner_strategy.py`, `backtester/domain/portfolio.py`
- **Места:** Логика определения `reason`, расчёт PnL
- **Что проверить:** Условие срабатывания TP, формула PnL, slippage

#### Если `position_closed_but_no_close_event`:
- **Файл:** `backtester/domain/portfolio.py` (метод `simulate()`)
- **Места:** Эмиссия событий закрытия позиций
- **Что проверить:** События `EXECUTED_CLOSE`, `CLOSED_BY_*` для всех закрытых позиций

### Шаг 6 — Исправь и прогони тесты audit

```powershell
# Запусти тесты audit
python -m pytest tests/audit -q

# Если есть ошибки — исправь и повтори
```

**Ожидаемый вывод:**
```
tests/audit/test_invariants.py .......... [100%]
tests/audit/test_p1_checks.py .......... [100%]
tests/audit/test_p1_executions.py .......... [100%]

========= 30 passed in 2.34s =========
```

### Шаг 7 — Перезапусти audit_run и сравни метрики

```powershell
# Перезапусти аудит
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A
```

**Сравни метрики:**

**До исправления:**
```
anomalies_total: 25
anomalies_p0: 8
anomalies_p1: 15
anomalies_p2: 2
```

**После исправления:**
```
anomalies_total: 12
anomalies_p0: 0  ← должно быть 0!
anomalies_p1: 10
anomalies_p2: 2
```

**Ожидаем:**
- Количество P0 падает к 0
- P1 уменьшается после починки событий/исполнений
- P2 может остаться (если proof'ы не реализованы полностью)

### Шаг 8 — Зафиксируй результат (что изменилось)

**Шаблон секции "До/После":**

```markdown
## Исправления в прогоне runs/v1.10/exp_A

### До исправления:
- `anomalies_total`: 25
- `anomalies_p0`: 8
- `anomalies_p1`: 15
- `anomalies_p2`: 2

### После исправления:
- `anomalies_total`: 12
- `anomalies_p0`: 0 ✅
- `anomalies_p1`: 10
- `anomalies_p2`: 2

### Какие anomaly_type уменьшились:
- `pnl_cap_or_magic`: 5 → 0 (исправлена нормализация decimals)
- `reset_without_events`: 3 → 0 (добавлена эмиссия событий)
- `tp_reason_but_negative_pnl`: 2 → 0 (исправлена логика TP)

### Какие позиции были исправлены:
- `pos_9081` — исправлена нормализация decimals
- `pos_1234` — добавлено событие reset
- `pos_5678` — исправлена логика TP
```

---

## G. Пример сценария: разбор PNL_CAP_OR_MAGIC

### Шаг 1: Фильтрация в anomalies

**В Excel/LibreOffice:**
1. Открой `runs/v1.10/exp_A/audit/audit_anomalies.csv`
2. Фильтр: `severity = P0` AND `code = pnl_cap_or_magic`
3. Сортировка: `pnl_pct` по убыванию

**Нашли:**
```
position_id: pos_9081
pnl_pct: 9.2 (920%)
entry_price: 0.00000123
exit_price: 0.000114
```

### Шаг 2: Детальный разбор

```powershell
python -m backtester.cli.audit_trade `
  --run-dir runs/v1.10/exp_A `
  --position-id pos_9081 `
  --output runs/v1.10/exp_A/audit/replay_pos_9081.json
```

**В выводе увидели:**
```json
{
  "entry_price": 0.00000123,
  "exit_price": 0.000114,
  "executions": [
    {
      "event_type": "entry",
      "exec_price": 0.00000123,
      "raw_price": 0.00000123
    },
    {
      "event_type": "final_exit",
      "exec_price": 0.000114,
      "raw_price": 114000  ← другая шкала!
    }
  ]
}
```

**Проблема:** `raw_price` для exit = 114000, но `exec_price` = 0.000114 — разные шкалы (decimals mismatch).

### Шаг 3: Поиск корневой причины

**Файл:** `backtester/domain/execution_model.py` или `backtester/infrastructure/reporter.py`

**Проблема:** При сохранении `portfolio_executions.csv` используется `raw_exit_price` из одной шкалы, а `exec_exit_price` — из другой.

**Исправление:**
- Нормализация decimals в месте формирования `execution.price` или `position.exit_price`
- Проверка единообразия шкал цен (всегда в одной единице измерения)

### Шаг 4: Проверка

```powershell
# Запусти тесты
python -m pytest tests/audit -q

# Перезапусти аудит
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A

# Проверь метрики
Import-Csv runs/v1.10/exp_A/audit/audit_metrics.csv | Where-Object { $_.metric -like "*pnl_cap*" }
```

**Результат:**
- `anomalies_by_code_pnl_cap_or_magic`: 5 → 0 ✅
- `anomalies_p0`: 8 → 3 ✅

---

## H. Типовые ошибки запуска

### Ошибка 1: IndentationError в report.py

**Симптом:**
```
IndentationError: unexpected indent
  File "backtester/audit/report.py", line 99
    "pnl_pct", "reason", "anomaly_type", "details_json",
    ^
```

**Причина:** Смешанные табы и пробелы, неправильные отступы.

**Решение:**
1. Открой `backtester/audit/report.py`
2. Проверь отступы на строках 96-100 (должны быть пробелы, не табы)
3. Исправь отступы (обычно 4 пробела на уровень)

**Проверка:**
```powershell
python -m pytest tests/audit -q
```

### Ошибка 2: PowerShell ругается на --run-dir

**Симптом:**
```
python: error: unrecognized arguments: --run-dir
```

**Причина:** Перенос строки через `\` (не работает в PowerShell).

**Решение:**
- Используй backtick `` ` `` для переноса:
```powershell
python -m backtester.cli.audit_run `
  --run-dir runs/v1.10/exp_A
```

- Или в одну строку:
```powershell
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A
```

### Ошибка 3: audit/ не создаётся

**Симптом:**
```
[audit] Starting audit for: runs/v1.10/exp_A
[audit] WARNING: No positions found. Cannot run audit.
```

**Причина:** Неправильный путь или отсутствие входных файлов.

**Решение:**
1. Проверь путь:
```powershell
ls runs/v1.10/exp_A/portfolio_positions.csv
```

2. Проверь наличие файлов:
```powershell
ls runs/v1.10/exp_A/portfolio_*.csv
```

3. Проверь права на запись:
```powershell
# Попробуй создать файл вручную
New-Item -Path "runs/v1.10/exp_A/audit/test.txt" -ItemType File
```

### Ошибка 4: ModuleNotFoundError: No module named 'backtester'

**Симптом:**
```
ModuleNotFoundError: No module named 'backtester'
```

**Причина:** Не активирована виртуальная среда или неправильная рабочая директория.

**Решение:**
1. Активируй venv:
```powershell
.\.venv\Scripts\activate
```

2. Проверь рабочую директорию (должна быть корень проекта):
```powershell
pwd
# Должно быть: C:\Прочее\Крипта\Тестер соланы
```

3. Установи зависимости (если нужно):
```powershell
pip install -r requirements.txt
```

### Ошибка 5: FileNotFoundError при загрузке свечей в audit_trade

**Симптом:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'data/candles/...'
```

**Причина:** Не указан `--candles-dir` или неправильный путь.

**Решение:**
```powershell
python -m backtester.cli.audit_trade `
  --run-dir runs/v1.10/exp_A `
  --position-id pos_9081 `
  --candles-dir data/candles
```

---

## I. Дополнительные команды

### Фильтрация по severity в CLI (если реализовано)

```powershell
# Только P0 (если флаг добавлен)
python -m backtester.cli.audit_run `
  --run-dir runs/v1.10/exp_A `
  --severity-threshold P0
```

### Ограничение количества позиций (для быстрых прогонов)

```powershell
# Первые 10 позиций (если флаг добавлен)
python -m backtester.cli.audit_run `
  --run-dir runs/v1.10/exp_A `
  --positions-limit 10
```

### Фильтрация по стратегии

```powershell
# Только Runner стратегии (если флаг добавлен)
python -m backtester.cli.audit_run `
  --run-dir runs/v1.10/exp_A `
  --strategy-filter Runner_*
```

---

## J. Итерационный цикл "пофиксил → перезапустил → сравнил"

### Быстрый скрипт для сравнения метрик:

```powershell
# Сохрани метрики "до"
Copy-Item runs/v1.10/exp_A/audit/audit_metrics.csv runs/v1.10/exp_A/audit/audit_metrics_before.csv

# Исправь код

# Перезапусти аудит
python -m backtester.cli.audit_run --run-dir runs/v1.10/exp_A

# Сохрани метрики "после"
Copy-Item runs/v1.10/exp_A/audit/audit_metrics.csv runs/v1.10/exp_A/audit/audit_metrics_after.csv

# Сравни
Compare-Object `
  (Import-Csv runs/v1.10/exp_A/audit/audit_metrics_before.csv) `
  (Import-Csv runs/v1.10/exp_A/audit/audit_metrics_after.csv) `
  -Property metric, value
```

---

## K. Полезные ссылки

- **Основной README:** `backtester/audit/README.md`
- **Код модуля:** `backtester/audit/`
- **Тесты:** `tests/audit/`
- **Документация по инвариантам:** `backtester/audit/invariants.py` (docstrings)

---

**Последнее обновление:** 2025-12-28

