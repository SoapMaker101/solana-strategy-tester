# Документ-Якорь: Починка тестов (этап)

**Дата старта документа:** 06.01.2025  
**Проект:** Проект тестинга стратегий (Runner-only)  
**Цель документа:** зафиксировать текущее состояние "этапа починки тестов", контракты и план фикса так, чтобы в любом новом чате/итерации можно было быстро восстановить контекст, понять "что сломано / почему / что делаем дальше", и отслеживать прогресс по группам тестов.

---

## 1. TL;DR (1 экран)

**Что работает:**
- Profit reset / event ledger по reset — зелёный
- Debug по reset — удалён (или готов к удалению)

**Текущее состояние тестов:**
- **27 failed, 260 passed** (`python -m pytest tests/ -q`)

**Главная причина (гипотеза):**
- "Контракты разъехались": reason normalization (каноника vs алиасы), runner strategy API (blueprint метод), reporter schema (canonical columns), config parsing (bool/int + replay mode), decision layer (criteria frozen vs колонки/типы)

**План фикса:**
- Последовательный фикс по порядку: application config parsing → reporter exports → runner blueprint API → runner_strategy expectations → audit invariants → decision layer

---

## 2. Контекст этапа

### Что было сделано до этого этапа
- Profit reset / event ledger по reset реализован и работает
- Debug по reset удалён (или готов к удалению)
- Базовая инфраструктура Runner-only v2.0.1 работает

### Definition of Done (что считается "готово" на этом этапе)
- Все тесты зелёные: `python -m pytest tests/ -q` → 0 failed
- Контракты синхронизированы между кодом и тестами
- Все CSV схемы соответствуют `docs/REPORTING_SCHEMA.md`
- Reason normalization работает консистентно во всех слоях
- Config parsing корректно обрабатывает `use_replay_mode` и `max_hold_minutes`

### Scope-out (что НЕ является целью этапа)
- Добавление новых фич
- Рефакторинг архитектуры
- Изменение бизнес-логики
- Оптимизация производительности

---

## 3. Baseline: как зафиксировать ошибки

### Шаг 0: baseline (обязательные команды)

```bash
# Создать папку для артефактов (если нет)
mkdir -p artifacts/test_failures/2025-01-06

# Запустить упавшие группы тестов и сохранить вывод
python -m pytest tests/application/test_runner_portfolio_config_parsing.py -q > artifacts/test_failures/2025-01-06/test_runner_portfolio_config_parsing.log 2>&1
python -m pytest tests/audit/test_invariants.py -q > artifacts/test_failures/2025-01-06/test_invariants.log 2>&1
python -m pytest tests/decision -q > artifacts/test_failures/2025-01-06/test_decision.log 2>&1
python -m pytest tests/domain/test_runner_strategy.py -q > artifacts/test_failures/2025-01-06/test_runner_strategy.log 2>&1
python -m pytest tests/infrastructure/test_reporter_exports_events_csv.py -q > artifacts/test_failures/2025-01-06/test_reporter_exports_events_csv.log 2>&1
python -m pytest tests/infrastructure/test_reporter_strategy_trades_export.py -q > artifacts/test_failures/2025-01-06/test_reporter_strategy_trades_export.log 2>&1
python -m pytest tests/strategy/test_runner_blueprint.py -q > artifacts/test_failures/2025-01-06/test_runner_blueprint.log 2>&1
python -m pytest tests/test_metrics_v1.py::test_is_runner_strategy -q > artifacts/test_failures/2025-01-06/test_metrics_v1_is_runner_strategy.log 2>&1

# Полный прогон для общего статуса
python -m pytest tests/ -q > artifacts/test_failures/2025-01-06/full_run.log 2>&1
```

### Правила фиксации логов
- Сохранять stdout целиком в `artifacts/test_failures/<date>/...`
- Именование файлов: `test_<module_name>.log` или `test_<module_name>_<test_name>.log`
- После каждого фикса — перезапускать тесты и обновлять логи
- Приносить в новый чат: traceback + head CSV (если есть) + 3 snippets кода

---

## 4. Карта упавших тестов

| Test group / file | Симптом (что падает по смыслу) | Вероятная причина (контракт/схема/тип) | Где чинить (примерные модули/файлы) | Статус | Что проверить после фикса |
|-------------------|--------------------------------|------------------------------------------|--------------------------------------|--------|---------------------------|
| `tests/application/test_runner_portfolio_config_parsing.py` | Парсинг `use_replay_mode` и `max_hold_minutes` из YAML не работает корректно | Config parsing: bool/int типы, Optional handling | `backtester/application/runner.py` → `_build_portfolio_config()` | TODO | `python -m pytest tests/application/test_runner_portfolio_config_parsing.py -q` |
| `tests/audit/test_invariants.py` | Reason normalization не работает или не применяется | Reason normalization: CANONICAL_REASONS vs REASON_ALIASES, `normalize_reason()` | `backtester/audit/invariants.py` → `normalize_reason()`, проверки инвариантов | TODO | `python -m pytest tests/audit/test_invariants.py -q` |
| `tests/decision/*` | Decision layer ожидает frozen критерии, но получает изменяемые или неправильные типы | Decision layer: критерии frozen, типы bool (python bool, не numpy bool), колонки стабильны | `backtester/decision/selection_rules.py`, `backtester/decision/strategy_selector.py` | TODO | `python -m pytest tests/decision -q` |
| `tests/domain/test_runner_strategy.py` | RunnerStrategy API не соответствует ожиданиям тестов | RunnerStrategy API: методы, blueprint контракт | `backtester/domain/runner_strategy.py` | TODO | `python -m pytest tests/domain/test_runner_strategy.py -q` |
| `tests/infrastructure/test_reporter_exports_events_csv.py` | CSV схема `portfolio_events.csv` не соответствует контракту | Reporting schema: колонки, порядок, типы данных | `backtester/infrastructure/reporter.py` → `save_portfolio_events_table()` | TODO | `python -m pytest tests/infrastructure/test_reporter_exports_events_csv.py -q` |
| `tests/infrastructure/test_reporter_strategy_trades_export.py` | CSV схема `strategy_trades.csv` не соответствует контракту (особенно `final_exit_json`) | Reporting schema: `final_exit_json` пустая строка при None, колонки | `backtester/infrastructure/reporter.py` → `save_strategy_trades()`, `backtester/domain/strategy_trade_blueprint.py` → `to_row()` | TODO | `python -m pytest tests/infrastructure/test_reporter_strategy_trades_export.py -q` |
| `tests/strategy/test_runner_blueprint.py` | `on_signal_blueprint()` не возвращает корректный blueprint или структура неверна | RunnerStrategy blueprint API: метод `on_signal_blueprint()`, структура `StrategyTradeBlueprint` | `backtester/domain/runner_strategy.py` → `on_signal_blueprint()` | TODO | `python -m pytest tests/strategy/test_runner_blueprint.py -q` |
| `tests/test_metrics_v1.py::test_is_runner_strategy` | Функция `is_runner_strategy()` не работает корректно | Runner strategy detection: логика определения Runner стратегий | `backtester/research/strategy_stability.py` → `is_runner_strategy()` | TODO | `python -m pytest tests/test_metrics_v1.py::test_is_runner_strategy -q` |

**Примечание:** Если точный файл в коде неизвестен — помечено как "TBD (найти в repo)". Нужно подтвердить в коде перед фиксом.

---

## 5. Контракты, которые должны совпасть (Source of Truth)

### 5.1 Reason Normalization

**Канонические значения (CANONICAL_REASONS):**
- Определены в `backtester/audit/invariants.py`:
  - `"ladder_tp"`, `"stop_loss"`, `"time_stop"`, `"capacity_prune"`, `"profit_reset"`, `"manual_close"`, `"no_entry"`, `"error"`, `"max_hold_minutes"`

**Алиасы для legacy (REASON_ALIASES):**
- Определены в `backtester/audit/invariants.py`:
  - `"tp"` → `"ladder_tp"`
  - `"sl"` → `"stop_loss"`
  - `"timeout"` → `"time_stop"`

**Где должна происходить нормализация:**
- Функция `normalize_reason()` в `backtester/audit/invariants.py` (строка 1838)
- Применяется в audit invariants проверках
- **TBD:** Нужно проверить, применяется ли нормализация в других местах (domain, reporter exports)

**Референс:**
- `backtester/audit/invariants.py` → `CANONICAL_REASONS`, `REASON_ALIASES`, `normalize_reason()`

### 5.2 RunnerStrategy API

**Обязательные методы:**
- `on_signal(data: StrategyInput) -> StrategyOutput` (базовый метод из `Strategy` ABC)
- `on_signal_blueprint(data: StrategyInput) -> StrategyTradeBlueprint` (новый метод для blueprint)

**Blueprint контракт (что возвращает `on_signal_blueprint()`):**
- Возвращает `StrategyTradeBlueprint` объект
- Структура определена в `backtester/domain/strategy_trade_blueprint.py`
- Обязательные поля: `signal_id`, `strategy_id`, `contract_address`, `entry_time`, `entry_price_raw`, `partial_exits`, `final_exit`, `realized_multiple`, `max_xn_reached`, `reason`

**Референс:**
- `backtester/domain/runner_strategy.py` → `RunnerStrategy` класс
- `backtester/domain/strategy_trade_blueprint.py` → `StrategyTradeBlueprint` dataclass
- `tests/strategy/test_runner_blueprint.py` → тесты blueprint API

### 5.3 Reporting Schema

**Source of Truth:**
- `docs/REPORTING_SCHEMA.md` — каноническая схема всех CSV файлов

**portfolio_events.csv:**
- Колонки (порядок): `timestamp`, `event_type`, `strategy`, `signal_id`, `contract_address`, `position_id`, `event_id`, `reason`, `meta_json`
- `reason` — каноническая таксономия (из CANONICAL_REASONS)
- `meta_json` — JSON строка с execution данными

**strategy_trades.csv:**
- Колонки (порядок): `signal_id`, `strategy_id`, `contract_address`, `entry_time`, `entry_price_raw`, `entry_mcap_proxy`, `partial_exits_json`, `final_exit_json`, `realized_multiple`, `max_xn_reached`, `reason`
- **Критическое правило:** `final_exit_json` пустая строка (`""`) когда `final_exit=None` (НЕ `"null"`, НЕ `"{}"`, НЕ `null`)
- `partial_exits_json` — всегда валидный JSON (пустой массив `[]` если нет partial exits)

**portfolio_positions.csv:**
- Схема определена в `docs/REPORTING_SCHEMA.md` (строки 61-93)
- Колонки включают: `position_id`, `strategy`, `signal_id`, `contract_address`, `entry_time`, `exit_time`, `status`, `size`, `pnl_sol`, `pnl_pct_total`, `reason`, и т.д.

**Референс:**
- `docs/REPORTING_SCHEMA.md` — полная схема
- `backtester/infrastructure/reporter.py` → методы экспорта
- `backtester/domain/strategy_trade_blueprint.py` → `to_row()` метод

### 5.4 Config Parsing

**Поддерживаемые поля:**
- `use_replay_mode`: bool (дефолт: `False`)
- `max_hold_minutes`: Optional[int] (дефолт: `None`)

**Типы на выходе:**
- `use_replay_mode` → `bool` (python bool, не строка)
- `max_hold_minutes` → `Optional[int]` (int или None, не строка)

**Replay fields:**
- Должны парситься из `global_config["portfolio"]` секции
- YAML парсер может вернуть строки — нужна нормализация типов

**Референс:**
- `backtester/application/runner.py` → `_build_portfolio_config()` метод
- `tests/application/test_runner_portfolio_config_parsing.py` → тесты парсинга

### 5.5 Decision Layer (Stage B)

**Критерии заморожены (frozen):**
- Определены в `backtester/decision/selection_rules.py`
- `DEFAULT_RUNNER_CRITERIA_V3` — canonical критерии (строка 158)
- Критерии должны быть immutable (frozen dataclass или константа)

**Типы булев:**
- Python `bool` (не numpy `bool_`, не `int`)
- Ожидается в тестах: `assert selection_df["passed"].dtype == bool`

**Колонки в входных CSV:**
- `strategy_stability.csv` — стабильные колонки (определены в `docs/REPORTING_SCHEMA.md` или тестах)
- Runner-специфичные колонки: `hit_rate_x2`, `hit_rate_x5`, `p90_hold_days`, `tail_contribution`

**Референс:**
- `backtester/decision/selection_rules.py` → критерии
- `backtester/decision/strategy_selector.py` → логика отбора
- `tests/decision/*` → тесты decision layer

---

## 6. Порядок фикса (дешёвый → дорогой)

### 6.1 Application Config Parsing

**Цель:** Тесты `tests/application/test_runner_portfolio_config_parsing.py` должны стать зелёными.

**Готовые критерии приемки:**
- `use_replay_mode` корректно парсится из YAML (bool, не строка)
- `max_hold_minutes` корректно парсится из YAML (int или None, не строка)
- Дефолты работают (False, None)
- Обратная совместимость (старые конфиги без replay полей работают)

**Файлы (вероятно затронем):**
- `backtester/application/runner.py` → `_build_portfolio_config()`

**Smoke-test:**
```bash
python -m pytest tests/application/test_runner_portfolio_config_parsing.py -q
```

---

### 6.2 Reporter Exports (Schema)

**Цель:** Тесты `tests/infrastructure/test_reporter_exports_events_csv.py` и `tests/infrastructure/test_reporter_strategy_trades_export.py` должны стать зелёными.

**Готовые критерии приемки:**
- `portfolio_events.csv` содержит все колонки в правильном порядке (см. `docs/REPORTING_SCHEMA.md`)
- `strategy_trades.csv` содержит все колонки в правильном порядке
- `final_exit_json` пустая строка (`""`) когда `final_exit=None` (не `"null"`, не `"{}"`)
- `meta_json` в `portfolio_events.csv` валидный JSON
- `partial_exits_json` в `strategy_trades.csv` валидный JSON (пустой массив `[]` если нет partial exits)

**Файлы (вероятно затронем):**
- `backtester/infrastructure/reporter.py` → `save_portfolio_events_table()`, `save_strategy_trades()`
- `backtester/domain/strategy_trade_blueprint.py` → `to_row()` метод

**Smoke-test:**
```bash
python -m pytest tests/infrastructure/test_reporter_exports_events_csv.py -q
python -m pytest tests/infrastructure/test_reporter_strategy_trades_export.py -q
```

---

### 6.3 Runner Blueprint API + Metrics V1 is_runner_strategy

**Цель:** Тесты `tests/strategy/test_runner_blueprint.py` и `tests/test_metrics_v1.py::test_is_runner_strategy` должны стать зелёными.

**Готовые критерии приемки:**
- `RunnerStrategy.on_signal_blueprint()` возвращает `StrategyTradeBlueprint`
- Структура blueprint соответствует контракту (см. раздел 5.2)
- `is_runner_strategy()` корректно определяет Runner стратегии (по префиксу "Runner", "RR", "RRD" и т.д.)

**Файлы (вероятно затронем):**
- `backtester/domain/runner_strategy.py` → `on_signal_blueprint()` метод
- `backtester/research/strategy_stability.py` → `is_runner_strategy()` функция

**Smoke-test:**
```bash
python -m pytest tests/strategy/test_runner_blueprint.py -q
python -m pytest tests/test_metrics_v1.py::test_is_runner_strategy -q
```

---

### 6.4 Runner Strategy Expectations

**Цель:** Тесты `tests/domain/test_runner_strategy.py` должны стать зелёными.

**Готовые критерии приемки:**
- RunnerStrategy API соответствует ожиданиям тестов
- Методы работают корректно
- Контракты соблюдены

**Файлы (вероятно затронем):**
- `backtester/domain/runner_strategy.py` → `RunnerStrategy` класс
- **TBD:** Нужно посмотреть, что именно ожидают тесты

**Smoke-test:**
```bash
python -m pytest tests/domain/test_runner_strategy.py -q
```

---

### 6.5 Audit Invariants Normalize Reason

**Цель:** Тесты `tests/audit/test_invariants.py` должны стать зелёными.

**Готовые критерии приемки:**
- `normalize_reason()` работает корректно (применяет алиасы)
- Reason normalization применяется во всех нужных местах
- Инварианты проверяют нормализованные причины

**Файлы (вероятно затронем):**
- `backtester/audit/invariants.py` → `normalize_reason()`, проверки инвариантов
- **TBD:** Нужно проверить, применяется ли нормализация в domain/reporter слоях

**Smoke-test:**
```bash
python -m pytest tests/audit/test_invariants.py -q
```

---

### 6.6 Decision Layer

**Цель:** Тесты `tests/decision/*` должны стать зелёными.

**Готовые критерии приемки:**
- Критерии frozen (неизменяемые)
- Типы bool — python bool (не numpy bool)
- Колонки в входных CSV стабильны
- Логика отбора работает корректно

**Файлы (вероятно затронем):**
- `backtester/decision/selection_rules.py` → критерии
- `backtester/decision/strategy_selector.py` → логика отбора
- **TBD:** Нужно посмотреть, что именно падает в тестах

**Smoke-test:**
```bash
python -m pytest tests/decision -q
```

---

## 7. Требования к тестам (как мы работаем с тестами)

### Что мы считаем "контрактом"
- Тесты фиксируют контракт между кодом и ожиданиями
- Контракты описаны в документации (`docs/REPORTING_SCHEMA.md`, `docs/CANONICAL_LEDGER_CONTRACT.md`, и т.д.)
- Тесты проверяют соответствие кода контрактам

### Когда мы меняем код, а когда меняем тесты
- **Меняем код**, если тест проверяет правильный контракт, но код не соответствует контракту
- **Меняем тесты**, если тест проверяет неправильный/устаревший контракт (но только после обсуждения и обновления документации)
- **НЕ ослабляем тесты** без объяснения (например, убирать проверки или менять ожидаемые значения)

### Запрет на "ослабление" тестов
- Нельзя просто убрать проверку, чтобы тест прошёл
- Нельзя изменить ожидаемое значение без обновления контракта
- Если тест слишком строгий — нужно обновить контракт в документации, затем обновить тест

### Обязательная проверка полного прогона
- После каждой крупной правки запускать: `python -m pytest tests/ -q`
- Отслеживать общее количество failed/passed тестов
- Не допускать регрессий (новые падения после фикса)

---

## 8. Логи и артефакты

### Где хранить логи падений
- `artifacts/test_failures/<date>/` — папка для логов конкретной даты
- Именование: `test_<module_name>.log` или `test_<module_name>_<test_name>.log`
- Сохранять stdout целиком (включая traceback)

### Какие CSV/артефакты прикладывать к отчёту
- Head CSV файлов (первые 5-10 строк) для проверки схемы
- Traceback из логов падений
- 3 snippets кода (до/после фикса, или проблемный участок)

### Что приносить в новый чат (минимальный набор)
1. **Traceback** из лога падения (полный, не обрезанный)
2. **Head CSV** (если проблема в схеме экспорта) — первые 5-10 строк
3. **3 snippets кода:**
   - Проблемный участок кода (где падает)
   - Контракт/схема (из документации или кода)
   - Ожидаемое поведение (из теста)

---

## 9. Итоговый статус (ручное заполнение)

**Дата последнего обновления:** 06.01.2025  
**Кто делал:** TBD

### Что стало зелёным
- TBD (заполнять после каждого фикса)

### Что осталось
- TBD (заполнять после каждого фикса)

### Следующий шаг
- TBD (заполнять после каждого фикса)

---

## 10. Список файлов-контрактов проекта

Документы в `docs/`, которые нужно держать в синхроне с тестами:

1. **`docs/REPORTING_SCHEMA.md`** — схемы CSV файлов (portfolio_events.csv, strategy_trades.csv, portfolio_positions.csv, portfolio_executions.csv)
2. **`docs/CANONICAL_LEDGER_CONTRACT.md`** — контракт канонического ledger (StrategyTradeBlueprint, Position, PortfolioEvent, PortfolioExecution)
3. **`docs/DATA_PIPELINE_RUNNER_ONLY.md`** — общее описание pipeline и потоков данных
4. **`docs/ARCHITECTURE.md`** — архитектура домена и event chain
5. **`docs/TESTING_GUARDS.md`** — правила тестирования и контракты

**Правило:** При изменении контракта в коде — обновить соответствующий документ в `docs/`, затем обновить тесты.

---

## 11. Риски (где обычно ломается совместимость)

1. **Reason normalization:**
   - Алиасы (tp/sl/timeout) не применяются во всех слоях
   - Legacy значения попадают в CSV без нормализации
   - Разные слои используют разные нормализации

2. **Schema (enum strings):**
   - Изменение значений enum (например, `"position_opened"` vs `"POSITION_OPENED"`)
   - Порядок колонок в CSV не соответствует схеме
   - Новые колонки добавлены, но схема не обновлена

3. **JSON пустые значения:**
   - `final_exit_json` не пустая строка для None (вместо `""` возвращается `"null"` или `"{}"`)
   - `meta_json` не валидный JSON
   - Пустые массивы не сериализуются как `[]`

4. **Timezone:**
   - Timestamp в разных форматах (ISO8601 vs другие)
   - Timezone не UTC (timezone-aware vs naive datetime)
   - Парсинг timestamp из CSV не учитывает timezone

5. **Типы данных:**
   - Bool как строка (`"true"`/`"false"`) вместо python bool
   - Int как строка (`"4320"`) вместо python int
   - Numpy bool вместо python bool (в decision layer)

6. **Config parsing:**
   - YAML парсер возвращает строки вместо bool/int
   - Optional поля не обрабатываются корректно (None vs отсутствие поля)
   - Дефолты не применяются

---

## Источник данных

Документ построен на основе состояния репозитория на момент 06.01.2025 и фактов:

- Profit reset / event ledger по reset — зелёный
- Debug по reset — удалён (или готов к удалению)
- `python -m pytest tests/ -q` → **27 failed, 260 passed**
- Упавшие группы тестов идентифицированы из структуры проекта и документации
- Контракты извлечены из кода: `backtester/audit/invariants.py`, `backtester/domain/strategy_trade_blueprint.py`, `docs/REPORTING_SCHEMA.md`, и т.д.

**ВАЖНО:** Документ НЕ содержит выдуманных подробностей. Если где-то нужна проверка в коде — помечено как "TBD (найти в repo)" или "TBD: нужно подтвердить в файле X".

Важно: маленькая ремарка по V2 “хаку”

То, что Cursor добавил “если criteria выглядит как RunnerCriteriaV2 → использовать как runner_criteria и подставить DEFAULT_CRITERIA_V1” — ок для тестов, но это место риска.

После общего прогона предлагаю (уже после зелени) сделать микро-рефактор:

select_strategies(stability_df, base_criteria: SelectionCriteria, runner_criteria: Optional[RunnerCriteria])

а в CLI/пайплайне явно передавать, чтобы не было магии с hasattr.

Но это после того, как всё зелёное.

Жду вывод pytest tests/ -q.