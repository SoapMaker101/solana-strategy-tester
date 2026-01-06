# Test Green Baseline — 2025-01-06

**Статус:** ✅ STABLE  
**Режим:** Runner-only v1.10  
**Дата фиксации:** 2025-01-06

## 🚫 СТРОГИЕ ЗАПРЕТЫ

**Cursor НЕ ИМЕЕТ ПРАВА:**
- Менять ожидания тестов, если баг в коде → тесты = контракт
- Удалять или ужесточать legacy-поведение (`tp`/`sl`/`timeout`, отсутствие `canonical_reason`)
- Менять публичные сигнатуры (`StrategyOutput(...)`, `select_strategies(...)`, `apply_exit(...)`)
- Добавлять эвристики вида `if hasattr(...)`, "угадывание" версии критериев
- Чистить код "для красоты", если это меняет семантику или типы

## 1️⃣ Baseline

```bash
python -m pytest tests/ -q
```

**Result:** 287 passed, 0 warnings  
**Date:** 2025-01-06  
**Mode:** Runner-only

---

## 2️⃣ DO NOT REGRESS

### Application config parsing

- **`_parse_bool`** — парсит `"true"/"false"`, `1/0`, `True/False` → `bool`
- **`_parse_int_optional`** — парсит `"4320"`, `0`, `None` → `int` или `None`
- **Критично:** `0 != None` — `max_hold_minutes=0` это валидное значение, не отсутствие

### Audit invariants

- **`normalize_reason`** — family-based нормализация:
  - `tp_5x` → `tp`
  - `sl` → `sl` (остается как есть)
  - `stop_loss` → `sl` (канон → legacy)
  - `ladder_tp` → `tp` (канон → legacy)
- **`check_reason_consistency`** — epsilon rules:
  - `tp` / `ladder_tp` → `pnl_pct >= -epsilon`
  - `sl` / `stop_loss` → `pnl_pct < -epsilon`

### StrategyOutput

- **`canonical_reason: Optional`** — автоматически вычисляется в `__post_init__`
- **Маппинг legacy → canonical:**
  - `"tp"` → `"ladder_tp"`
  - `"sl"` → `"stop_loss"`
  - `"timeout"` → `"time_stop"`
- **Приоритет:** `meta["ladder_reason"]` > `reason` маппинг

### ExecutionModel

- **`_normalize_reason_to_exit_type`** — нормализует reason в exit type:
  - TP family (`tp`, `tp_*`, `ladder_tp`) → `"exit_tp"`
  - SL family (`sl`, `stop_loss`) → `"exit_sl"`
  - Timeout family (`timeout`, `time_stop`, `max_hold_minutes`) → `"exit_timeout"`
  - Manual/forced (`manual_close`, `profit_reset`, `capacity_prune`) → `"exit_manual"`
- **`network_fee()`** — возвращает `float` (0.0 если `None`)

### Decision

- **V1 criteria (base)** — обязательные:
  - `survival_rate`, `pnl_variance`, `worst_window_pnl`, `median_window_pnl`, `windows_total`
- **V2 Runner criteria** — опциональные (только если есть колонки):
  - `hit_rate_x4` >= 0.10
  - `tail_pnl_share` >= 0.30
  - `non_tail_pnl_share` >= -0.20
- **V2 gate:** проверка наличия колонок перед применением

### Reporter / Replay

- **Market close price** — используется `candles[-1].close`, не синтетический
- **Partial exits** — `PartialExitBlueprint` с `fraction` и `level`
- **Realized multiple** — `Σ(fraction * level)` для ladder, `exit_price / entry_price` для timeout

### Warnings

- **Pandas boolean reindex fix** — маски выровнены по индексу `positions_df`
- **XNAnalyzer local suppression** — только в тесте `test_no_candles_after_signal_returns_none`
- **pytest.ini:** `filterwarnings = error` — warnings as errors (кроме локально подавленных)

---

## 3️⃣ Source of Truth

| Layer | File | Contract | Guarded by tests |
|-------|------|----------|------------------|
| Application | `runner.py` | `0 ≠ None` parsing | `test_runner_portfolio_config_parsing` |
| Audit | `invariants.py` | reason family logic | `test_invariants` |
| Domain | `models.py` | legacy StrategyOutput | `test_runner_strategy`, `test_strategy_output_contract` |
| Execution | `execution_model.py` | exit reason mapping | `portfolio` tests |
| Decision | `strategy_selector.py` | V1/V2 logic | `decision` tests |

---

## 4️⃣ Allowed Changes Policy

### ✅ Можно менять без обновления тестов

- Комментарии и документация
- Внутренние переменные (не меняющие поведение)
- Форматирование кода (без изменения логики)
- Добавление guard-тестов

### ⚠️ Требует RFC / migration / doc update

- Изменение публичных сигнатур (`StrategyOutput`, `select_strategies`, `apply_exit`)
- Изменение legacy поведения (`tp`/`sl`/`timeout` маппинг)
- Изменение критериев отбора (V1/V2 логика)
- Изменение нормализации reason
- Изменение контрактов execution profiles

---

## 5️⃣ TECH_DEBT

### V2-хак в `select_strategies`

**Текущая реализация:**
```python
if runner_criteria is None:
    required_v2_cols = {"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}
    has_v2_cols = required_v2_cols.issubset(set(stability_df.columns))
    if has_v2_cols and (criteria.min_hit_rate_x2 is None and criteria.min_hit_rate_x5 is None):
        runner_criteria = criteria
        criteria = DEFAULT_CRITERIA_V1
```

**Статус:** ✅ Допустим ТОЛЬКО как временная совместимость  
**Проблема:** Неявная логика определения V2 критериев  
**Будущий рефактор (ПОСЛЕ freeze):**
```python
select_strategies(
    stability_df,
    base_criteria: SelectionCriteria,
    runner_criteria: Optional[RunnerCriteria]
)
```

**⚠️ НЕ УЛУЧШАТЬ сейчас** — помечено как TECH_DEBT для будущего рефактора.

---

## 6️⃣ Guard Tests

Guard-тесты защищают от регрессий критичные контракты:

### StrategyOutput Contract
**Файл:** `tests/domain/test_strategy_output_contract.py`
- Legacy reasons → canonical mapping
- `meta["ladder_reason"]` priority
- `canonical_reason` optional and auto-computed

### Config Parsing Contract
**Файл:** `tests/application/test_portfolio_config_guards.py`
- `0 ≠ None` parsing (`_parse_int_optional`)
- String bool parsing (`_parse_bool`)
- Missing keys handling

### Decision V2 Gate Contract
**Файл:** `tests/decision/test_stage_b_v2_gate_contract.py`
- V2 applies only when V2 columns present
- V2 rejects `tail_pnl_share < 0.30`
- V2 checks `hit_rate_x4 >= 0.10` and `non_tail_pnl_share >= -0.20`

---

## 7️⃣ Freeze Status

**После выполнения этого ТЗ:**
- ✅ Проект официально выходит из режима "вечных фиксов"
- ✅ Можно безопасно freeze + tag
- ✅ Можно безопасно развивать Stage B evolution
- ✅ Можно безопасно добавлять replay analytics
- ✅ Можно безопасно делать архитектурную чистку

**Критерий приёмки:**
- Документ создан ✅
- Guard-тесты добавлены ✅
- `python -m pytest tests/ -q` → 287 passed, 0 warnings ✅
- НИ ОДИН существующий тест не переписан "под код" ✅

