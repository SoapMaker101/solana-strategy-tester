# Release 2.1.9 — Solana Strategy Tester

**Статус:** ✅ Stable / Frozen  
**Дата фиксации:** 2025-01-06  
**Режим:** Runner-only  
**Тесты:** 306 passed, 0 warnings

---

## 1. Общая информация

**Название проекта:** Solana Strategy Tester  
**Версия:** 2.1.9  
**Дата фиксации:** 2025-01-06  
**Статус:** Stable / Frozen

**Описание:** Runner-only backtesting framework для торговых стратегий на Solana. Система полностью event-driven, использует единый канонический Runner ladder контракт. Версия 2.1.9 — это стабильный baseline с зафиксированными контрактами, полным покрытием тестами и осознанно отложенными техническими проблемами.

---

## 2. Почему версия 2.1.9, а не 2.2

Версия 2.1.9 фиксирует **стабильное рабочее состояние** проекта:

✅ **Тесты зелёные:** 306 passed, 0 warnings  
✅ **Архитектура стабилизирована:** Runner-only режим зафиксирован  
✅ **Контракты защищены:** Guard-тесты добавлены  
✅ **Legacy API сохранён:** Обратная совместимость гарантирована

**Но есть известные технические проблемы**, которые осознанно не исправлялись в этой версии:

- Basedpyright typing warnings
- Технический долг в decision layer (V2-хак)
- Pandas type hints неполные
- Некоторые архитектурные упрощения отложены

Эти проблемы **не блокируют работу системы**, но требуют отдельного цикла разработки. Версия 2.2 будет посвящена cleanup и typing improvements.

**См. также:** `docs/KNOWN_ISSUES_2.1.9.md` для полного списка известных проблем.

---

## 3. Архитектура проекта (AS-IS)

### Слои системы

#### Application Layer
**Файлы:** `backtester/application/runner.py`

**Ответственность:**
- Загрузка сигналов и свечей
- Координация стратегий
- Сбор результатов
- Парсинг конфигурации (`_parse_bool`, `_parse_int_optional`)

**Контракт:** `0 ≠ None` parsing, строгая обработка конфигурации

#### Domain Layer
**Файлы:** `backtester/domain/`

**Ответственность:**
- Модели данных (`StrategyOutput`, `Position`, `PortfolioEvent`)
- Runner стратегии (`RunnerStrategy`, `RunnerLadderEngine`)
- Execution модели (`ExecutionModel`, slippage, fees)
- Portfolio engine (`PortfolioEngine`, `PortfolioReplay`)

**Контракт:**
- `StrategyOutput.canonical_reason` — optional, auto-computed
- Legacy reasons (`tp`/`sl`/`timeout`) → canonical mapping
- `position_id` — UUID, уникальный идентификатор
- `realized_multiple` — из fills ledger, не из `exit_price`

#### Audit Layer
**Файлы:** `backtester/audit/invariants.py`

**Ответственность:**
- Проверка инвариантов (P0/P1/P2)
- Reason consistency checks
- Event chain validation
- Missing events detection

**Контракт:**
- `normalize_reason` — family-based нормализация
- `check_reason_consistency` — epsilon rules для TP/SL
- P0 anomalies блокируют Stage A/B

#### Decision Layer
**Файлы:** `backtester/decision/strategy_selector.py`

**Ответственность:**
- Отбор стратегий по критериям (V1/V2)
- Gate логика для V2 критериев
- Selection table generation

**Контракт:**
- V1 criteria (base) — обязательные
- V2 Runner criteria — опциональные (только если есть колонки)
- `select_strategies` — валидация обязательных колонок

#### Portfolio / Replay Layer
**Файлы:** `backtester/domain/portfolio.py`, `backtester/domain/replay.py`

**Ответственность:**
- Симуляция портфеля
- Создание позиций и событий
- Replay mode (blueprint → position conversion)
- Execution ledger

**Контракт:**
- Канонические события: `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- Market close price — `candles[-1].close`
- Partial exits — `PartialExitBlueprint` с `fraction` и `level`

#### Reporting Layer
**Файлы:** `backtester/infrastructure/reporter.py`, `backtester/infrastructure/xlsx_writer.py`

**Ответственность:**
- Экспорт CSV (positions, events, executions)
- Экспорт XLSX (report pack)
- Column ordering, empty string handling

**Контракт:**
- `portfolio_events.csv` — фиксированный порядок колонок
- `final_exit_json` — `""` вместо `NaN`
- `quoting=csv.QUOTE_ALL` для CSV

### Source of Truth

| Layer | File | Contract | Guarded by tests |
|-------|------|----------|------------------|
| Application | `runner.py` | `0 ≠ None` parsing | `test_runner_portfolio_config_parsing` |
| Audit | `invariants.py` | reason family logic | `test_invariants` |
| Domain | `models.py` | legacy StrategyOutput | `test_runner_strategy`, `test_strategy_output_contract` |
| Execution | `execution_model.py` | exit reason mapping | `portfolio` tests |
| Decision | `strategy_selector.py` | V1/V2 logic | `decision` tests |

---

## 4. Полный pipeline данных

### End-to-end Flow

```
┌─────────┐
│ Signals │ (CSV файл с торговыми сигналами)
│         │ - signal_id, contract_address, timestamp
└────┬────┘
     │
     ▼
┌─────────┐
│ Candles │ (загружаются через PriceLoader)
│         │ - OHLC данные для окна вокруг сигнала
└────┬────┘
     │
     ▼
┌──────────────────┐
│ Runner Strategy  │ (RunnerStrategy.on_signal)
│                  │ → RunnerLadderEngine.simulate
│                  │ → StrategyOutput с:
│                  │   - realized_multiple
│                  │   - fractions_exited
│                  │   - canonical_reason
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│ Portfolio Engine │ (PortfolioEngine.simulate)
│                  │ → создает Position (position_id)
│                  │ → эмитит PortfolioEvent (canonical)
│                  │ → создает Execution (fills ledger)
└────┬─────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│ Positions / Events / Executions        │
│                                         │
│ - portfolio_positions.csv              │
│   (position_id, entry/exit, pnl_sol)   │
│                                         │
│ - portfolio_events.csv                  │
│   (canonical event ledger)             │
│                                         │
│ - portfolio_executions.csv             │
│   (fills ledger, realized_multiple)    │
└────┬────────────────────────────────────┘
     │
     ▼
┌─────────┐
│  Audit  │ (InvariantChecker)
│         │ → проверяет P0/P1/P2 инварианты
│         │ → reason consistency
│         │ → event chain validation
└────┬────┘
     │
     ▼ (если P0=0)
┌─────────┐
│ Stage A │ (research/run_stage_a.py)
│         │ → window aggregator
│         │ → strategy stability metrics
│         │ → strategy_stability.csv
└────┬────┘
     │
     ▼
┌─────────┐
│ Stage B │ (decision/run_stage_b.py)
│         │ → strategy selection
│         │ → V1/V2 criteria
│         │ → strategy_selection.csv
└─────────┘
```

### Входные данные

**Signals (CSV):**
- `signal_id`: уникальный идентификатор
- `contract_address`: адрес токена
- `timestamp`: время сигнала

**Candles (PriceLoader):**
- OHLC данные для временного окна
- Загружаются динамически через API или из CSV

### Промежуточные данные

**StrategyOutput:**
- `entry_time`, `entry_price`: вход
- `exit_time`, `exit_price`: выход
- `realized_multiple`: множитель из fills ledger
- `canonical_reason`: каноническая причина выхода
- `meta`: дополнительные данные (levels_hit, fractions_exited, etc.)

**Position:**
- `position_id`: UUID, уникальный идентификатор
- `signal_id`: ссылка на исходный сигнал
- `status`: "open" или "closed"
- `pnl_sol`: PnL в SOL (из fills ledger)

**PortfolioEvent:**
- Канонические типы: `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- `position_id`: ссылка на позицию
- `event_id`: уникальный идентификатор события

### Выходные данные (Source of Truth)

**portfolio_positions.csv:**
- Позиции с `position_id`, entry/exit, pnl_sol
- Source of truth для positions-level данных

**portfolio_events.csv:**
- Канонический event ledger
- Фиксированный порядок колонок: `["timestamp", "event_type", "strategy", "signal_id", "contract_address", "position_id", "event_id", "reason", "meta_json"]`

**portfolio_executions.csv:**
- Fills ledger
- `realized_multiple` для каждой позиции

**strategy_stability.csv (Stage A):**
- Метрики устойчивости стратегий
- Window-based агрегация

**strategy_selection.csv (Stage B):**
- Результаты отбора стратегий
- `passed` статус, `failed_reasons`

### Канонические данные

**Канонический reason:**
- `ladder_tp`, `stop_loss`, `time_stop`, `capacity_prune`, `profit_reset`, `manual_close`, `no_entry`, `error`, `max_hold_minutes`

**Legacy reasons (автоматически маппятся):**
- `tp` → `ladder_tp`
- `sl` → `stop_loss`
- `timeout` → `time_stop`

**PnL calculation:**
- Всегда из fills ledger (`realized_multiple`)
- Никогда из `exit_price` напрямую

---

## 5. Контракты, которые запрещено ломать

### StrategyOutput

**Файл:** `backtester/domain/models.py`

**Контракт:**
- `canonical_reason: Optional[Literal[...]]` — optional, auto-computed в `__post_init__`
- `reason: str` — legacy reason (может быть `"tp"`, `"sl"`, `"timeout"`)
- `meta["ladder_reason"]` имеет приоритет над `reason` маппингом
- Legacy → canonical mapping: `"tp"` → `"ladder_tp"`, `"sl"` → `"stop_loss"`, `"timeout"` → `"time_stop"`

**Guard tests:** `tests/domain/test_strategy_output_contract.py`

### position_id

**Контракт:**
- UUID (uuid4 hex), генерируется автоматически
- Уникальный идентификатор позиции
- Используется для связи `Position` ↔ `PortfolioEvent`

### PortfolioEvent

**Контракт:**
- Канонические типы: `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- `position_id` — обязательное поле
- `event_id` — уникальный идентификатор события

### ExecutionModel

**Файл:** `backtester/domain/execution_model.py`

**Контракт:**
- `_normalize_reason_to_exit_type` — нормализует reason в exit type для slippage
- `network_fee()` — возвращает `float` (0.0 если `None`)
- Exit types: `exit_tp`, `exit_sl`, `exit_timeout`, `exit_manual`

### Stage B criteria

**Файл:** `backtester/decision/strategy_selector.py`

**Контракт:**
- V1 criteria (base) — обязательные: `survival_rate`, `pnl_variance`, `worst_window_pnl`, `median_window_pnl`, `windows_total`
- V2 Runner criteria — опциональные (только если есть колонки): `hit_rate_x4 >= 0.10`, `tail_pnl_share >= 0.30`, `non_tail_pnl_share >= -0.20`
- V2 gate: проверка наличия колонок перед применением
- `select_strategies` — валидация обязательных колонок, `ValueError` если отсутствуют

**Guard tests:** `tests/decision/test_stage_b_v2_gate_contract.py`

### Config parsing

**Файл:** `backtester/application/runner.py`

**Контракт:**
- `_parse_bool` — парсит `"true"/"false"`, `1/0`, `True/False` → `bool`
- `_parse_int_optional` — парсит `"4320"`, `0`, `None` → `int` или `None`
- **Критично:** `0 != None` — `max_hold_minutes=0` это валидное значение, не отсутствие

**Guard tests:** `tests/application/test_portfolio_config_guards.py`

**См. также:** `docs/TEST_GREEN_BASELINE_2025-01-06.md` для полного списка контрактов.

---

## 6. Что гарантирует версия 2.1.9

### Deterministic replay

✅ **Replay mode:** `use_replay_mode=True` в конфигурации  
✅ **Blueprint → Position conversion:** `PortfolioReplay` корректно конвертирует `StrategyTradeBlueprint` в `Position`  
✅ **Event ordering:** События генерируются в правильном порядке  
✅ **Market close price:** Используется `candles[-1].close`, не синтетический

### Audit consistency

✅ **P0/P1/P2 classification:** Строгая классификация аномалий  
✅ **Reason consistency:** `check_reason_consistency` проверяет TP/SL правила  
✅ **Event chain validation:** Проверка целостности цепочки событий  
✅ **Missing events detection:** Обнаружение отсутствующих событий

### Legacy compatibility

✅ **Legacy reasons:** `tp`/`sl`/`timeout` автоматически маппятся в canonical  
✅ **StrategyOutput:** `canonical_reason` optional, auto-computed  
✅ **Backward compatibility:** Старые тесты работают без изменений

### Runner-only логика

✅ **Runner ladder:** Единый контракт для всех Runner стратегий  
✅ **Realized multiple:** Всегда из fills ledger  
✅ **Partial exits:** Корректная обработка ladder TP

### Warnings as errors

✅ **pytest.ini:** `filterwarnings = error`  
✅ **Resource leaks:** Все файловые дескрипторы закрываются  
✅ **0 warnings:** Все тесты проходят без warnings

---

## 7. Что НЕ гарантируется

### Строгая типизация

❌ **Basedpyright warnings:** Есть typing warnings, которые не блокируют работу  
❌ **Pandas types:** Неполные type hints для pandas операций  
❌ **Dynamic types:** Некоторые места используют `Any` или `Dict[str, Any]`

**Планируемый fix:** Версия 2.2 (typing cleanup)

### Чистота pandas-типов

❌ **Nullable types:** Некоторые колонки могут иметь `object` dtype вместо строгих типов  
❌ **Type inference:** Pandas автоматически выводит типы, что может приводить к неожиданным результатам

**Планируемый fix:** Версия 2.2 (pandas type hints)

### Отсутствие технического долга

❌ **V2-хак в `select_strategies`:** Неявная логика определения V2 критериев  
❌ **Эвристики:** Некоторые места используют `hasattr` для определения версий  
❌ **Архитектурные упрощения:** Некоторые слои можно упростить

**Планируемый fix:** Версия 2.2 (refactoring)

**См. также:** `docs/KNOWN_ISSUES_2.1.9.md` для полного списка известных проблем.

---

## 8. Правила работы с этой версией

### ✅ Можно делать

- **Документация:** Добавлять, обновлять, улучшать документацию
- **Аналитика:** Добавлять новые метрики, исследования
- **Исследования:** Экспериментировать с новыми стратегиями
- **Guard-тесты:** Добавлять новые guard-тесты для защиты контрактов
- **Bug fixes:** Исправлять критические баги (с обновлением тестов)

### ❌ Нельзя делать

- **Менять логику без bump версии:** Любые изменения логики требуют новой версии
- **Ломать контракты:** `StrategyOutput`, `position_id`, `PortfolioEvent` — неприкосновенны
- **Удалять legacy API:** `tp`/`sl`/`timeout` должны продолжать работать
- **Менять тесты "под код":** Тесты = контракт, код должен соответствовать тестам
- **Добавлять глобальные suppressions:** Warnings должны исправляться, а не подавляться

### 🔄 Процесс изменений

1. **Bug fix:** Исправить код → обновить тесты → проверить guard-тесты
2. **Feature:** Создать новую ветку → реализовать → добавить тесты → обновить документацию
3. **Breaking change:** Обсудить → создать migration guide → bump версии → обновить все документы

---

## 9. Следующие шаги

После фиксации версии 2.1.9 можно безопасно:

1. **Git tag:** `git tag v2.1.9`
2. **Changelog:** Обновить `CHANGELOG.md` с описанием изменений
3. **Release checklist:** Подготовить checklist для релиза

### Планируемые версии

- **2.2.0:** Typing cleanup, basedpyright fixes, pandas type hints
- **2.3.0:** Analytics improvements, новые метрики
- **3.0.0:** Архитектурные изменения (если потребуются)

---

## 10. Ссылки

- **Baseline document:** `docs/TEST_GREEN_BASELINE_2025-01-06.md`
- **Known issues:** `docs/KNOWN_ISSUES_2.1.9.md`
- **Architecture:** `docs/ARCHITECTURE.md`
- **Pipeline guide:** `docs/DATA_PIPELINE_RUNNER_ONLY.md`
- **Canonical ledger:** `docs/CANONICAL_LEDGER_CONTRACT.md`

---

**Версия 2.1.9 — это правильная и очень взрослая точка фиксации.**

