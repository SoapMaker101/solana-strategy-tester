# Карта тестов проекта — Этап 4

**Дата:** 2025-01-XX  
**Этап:** 4 — Чистка тестов и стабилизация архитектуры

## Классификация тестов

### A) MUST KEEP (НЕ ТРОГАТЬ) 🔒

**Критерий:** Тесты, защищающие архитектурные инварианты (linkage, reset chain, monotonic timestamps, positions-events consistency).

#### `tests/audit/test_invariants.py`
- **Все тесты КЕЕП** ✅
- **Почему:** Проверяет PnL формулы, reason consistency, magic values, time ordering, missing events
- **Ключевые тесты:**
  - `test_pnl_formula_long_basic`
  - `test_tp_reason_requires_non_negative_pnl`
  - `test_sl_reason_requires_negative_pnl`
  - `test_invariant_checker_detects_invalid_entry_price`
  - `test_invariant_checker_detects_time_order_invalid`
  - `test_invariant_checker_detects_missing_events`

#### `tests/audit/test_p1_checks.py`
- **Все тесты КЕЕП** ✅
- **Почему:** Проверяет P1 инварианты positions ↔ events
- **Ключевые тесты:**
  - `test_position_closed_but_no_close_event`
  - `test_close_event_but_position_open`
  - `test_multiple_open_events`
  - `test_unknown_reason_mapping`

#### `tests/audit/test_p1_executions.py`
- **Все тесты КЕЕП** ✅
- **Почему:** Проверяет P1 инварианты events ↔ executions
- **Ключевые тесты:**
  - `test_trade_event_without_execution`
  - `test_execution_without_trade_event`
  - `test_execution_time_before_event`
  - `test_execution_price_out_of_range`

#### `tests/domain/test_position_id_and_event_ledger.py`
- **Большинство тестов КЕЕП** ✅
- **Почему:** Проверяет position_id стабильность, event-ledger корректность, reset chain
- **Ключевые тесты:**
  - `test_position_id_generated_and_stable`
  - `test_reset_emits_full_event_chain`
  - Связанные с linkage событий

---

### B) Replay tests (ОСТАВИТЬ) 🎯

**Критерий:** Тесты, проверяющие PortfolioReplay функциональность (max_hold_minutes, capacity, allocation, reset).

#### `tests/portfolio/test_portfolio_replay.py`
- **Все тесты КЕЕП** ✅
- **Почему:** Основной тестовый набор для PortfolioReplay
- **Ключевые тесты:**
  - `test_replay_two_configs_same_blueprints_different_equity`
  - `test_replay_capacity_blocking_skips_positions`
  - `test_replay_profit_reset_emits_chain`
  - `test_replay_max_hold_closes_positions`

#### `tests/infrastructure/test_reporter_strategy_trades_export.py`
- **КЕЕП** ✅
- **Почему:** Проверяет экспорт strategy_trades.csv (ключевой артефакт этапа 1)

#### `tests/strategy/test_runner_blueprint.py`
- **КЕЕП** ✅
- **Почему:** Проверяет генерацию StrategyTradeBlueprint

#### `tests/application/test_runner_portfolio_config_parsing.py`
- **КЕЕП** ✅
- **Почему:** Проверяет парсинг max_hold_minutes из YAML (этап 2)

---

### C) E2E / Smoke (ОСТАВИТЬ 1–2) 🧪

**Критерий:** Полный прогон пайпа, проверка артефактов (strategy_trades.csv + portfolio csv).

#### `tests/portfolio/test_portfolio_smoke.py`
- **КЕЕП (упростить)** ⚠️
- **Почему:** Базовые smoke тесты для импорта и создания классов
- **Действие:** Оставить только критичные smoke тесты (import, basic instantiation)

#### `tests/portfolio/test_portfolio_single_trade.py`
- **КЕЕП (как упрощенный E2E)** ✅
- **Почему:** Проверяет полный цикл одной сделки с fees/slippage
- **Примечание:** Может служить минимальным E2E тестом

#### `tests/test_imports_smoke.py`
- **КЕЕП** ✅
- **Почему:** Проверяет, что все модули импортируются без ошибок

---

### D) Implementation-detail tests (КАНДИДАТ НА УДАЛЕНИЕ) 🗑️

**Критерий:** Проверяют внутренние поля, старые meta флаги, дублируют логику других тестов, тесты для удаленного legacy пути.

#### `tests/portfolio/test_portfolio_runner_partial_exits.py`
- **УДАЛИТЬ** ❌
- **Почему:** 
  - Тесты используют старый путь через `PortfolioEngine.simulate()` с `StrategyOutput`
  - Проверяют `time_stop` логику (строка 9: "Time_stop закрывает остаток корректно")
  - Дублируют функциональность `test_portfolio_replay.py` (partial exits уже проверяются там)
- **Действие:** Удалить файл полностью

#### `tests/portfolio/test_profit_reset_backward_compatibility.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Тестирует backward compatibility для deprecated `runner_reset_*` полей
  - Это implementation detail конфига, не архитектурный инвариант
  - Если нужна обратная совместимость, она должна проверяться интеграционными тестами
- **Действие:** Удалить файл полностью

#### `tests/portfolio/test_debug_portfolio_reset_marker.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Диагностический/отладочный тест (с `print` в коде)
  - Не защищает инвариант, а помогает отладке
- **Действие:** Удалить файл полностью

#### `tests/portfolio/test_portfolio_limits.py`
- **УПРОСТИТЬ** ⚠️
- **Почему:**
  - Проверяет `max_open_positions` и `max_exposure`
  - Это portfolio-level конфигурация, но тесты могут быть упрощены
  - Некоторые проверки дублируют `test_portfolio_replay.py` (capacity blocking)
- **Действие:** Оставить 1–2 ключевых теста, удалить избыточные

#### `tests/portfolio/test_portfolio_dynamic_allocation.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Тестирует allocation_mode="dynamic" через старый путь `PortfolioEngine`
  - Логика allocation уже проверяется в `test_portfolio_replay.py`
  - Implementation detail конфига
- **Действие:** Удалить файл полностью (или оставить 1 простой тест, если нет покрытия в replay)

#### `tests/portfolio/test_portfolio_capacity_reset.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Использует старый путь через `PortfolioEngine.simulate()` с `StrategyOutput`
  - Capacity reset должен тестироваться через `PortfolioReplay` (если поддерживается)
  - Reset chain корректность проверяется в audit invariants
- **Действие:** Удалить файл полностью (или переписать на PortfolioReplay если capacity reset критичен)

#### `tests/portfolio/test_portfolio_runner_reset_portfolio_level.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Использует старый путь через `PortfolioEngine.simulate()` с `StrategyOutput`
  - Profit reset уже тестируется в `test_replay_profit_reset_emits_chain`
  - Reset chain корректность проверяется в audit invariants
- **Действие:** Удалить файл полностью

#### `tests/portfolio/test_portfolio_fees_turn_profit_to_loss.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Проверяет специфический edge case (fees > profit)
  - Это уже покрывается `test_portfolio_single_trade.py` и audit invariants
  - Implementation detail расчета fees
- **Действие:** Удалить файл полностью

#### `tests/portfolio/test_execution_profiles.py`
- **УПРОСТИТЬ** ⚠️
- **Почему:**
  - Тесты для execution profiles (slippage по reason)
  - Содержит тест `test_legacy_config_compatibility` (строка 305)
  - Проверяет детали реализации, не архитектурные инварианты
- **Действие:** Оставить 1–2 базовых теста, удалить legacy compatibility тест

#### `tests/domain/test_runner_ladder.py`
- **КЕЕП** ✅
- **Почему:** Unit тесты для RunnerLadderEngine (доменная логика стратегии)
- **Примечание:** Может содержать устаревшие ссылки на `time_stop`, но сам тест нужен

#### `tests/domain/test_runner_strategy.py`
- **КЕЕП** ✅
- **Почему:** Unit тесты для RunnerStrategy
- **Примечание:** Проверяет стратегическую логику, не portfolio

#### `tests/domain/test_portfolio_event_partial_exit.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Тест `test_partial_exit_with_custom_reason` (строка 63) проверяет `reason="time_stop"` — deprecated
  - Это implementation detail фабричного метода, не инвариант
- **Действие:** Удалить файл или оставить только базовый тест создания события

#### `tests/domain/test_portfolio_reset_reason_mapping.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Проверяет маппинг reset reasons (implementation detail)
  - Если маппинг критичен, он должен проверяться через audit invariants
- **Действие:** Удалить файл полностью

#### `tests/domain/test_reset_reason_fix.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Специфичный тест для фикса бага (fix-specific test)
  - Не защищает архитектурный инвариант
- **Действие:** Удалить файл полностью

#### `tests/domain/test_portfolio_event_contract.py`
- **УДАЛИТЬ** ❌
- **Почему:**
  - Просто проверяет конструктор dataclass PortfolioEvent
  - Не защищает архитектурный инвариант
  - Проверка структуры dataclass не требует отдельного теста
- **Действие:** Удалить файл полностью

#### `tests/infrastructure/test_reporter_output_dir_stage_2_5.py`
- **УДАЛИТЬ ИЛИ ПЕРЕИМЕНОВАТЬ** ⚠️
- **Почему:**
  - Тест для этапа 2.5 (legacy vs replay сравнение)
  - Legacy удален, но тест может быть полезен для проверки output dir
  - Переименовать в более общий тест или удалить
- **Действие:** Упростить и переименовать в `test_reporter_output_dir.py`

#### `tests/application/test_runner_empty_candles.py`
- **КЕЕП** ✅
- **Почему:** Проверяет обработку edge case (пустые свечи)

---

## Файлы вне категорий (research/decision/reports)

### Research тесты (`tests/research/`)
- **НЕ ТРОГАТЬ** (не в scope этапа 4)
- Это тесты для анализа данных и research пайплайна

### Decision тесты (`tests/decision/`)
- **НЕ ТРОГАТЬ** (не в scope этапа 4)
- Тесты для стратегического селектора и фильтров

### Reports тесты (`tests/reports/`)
- **НЕ ТРОГАТЬ** (не в scope этапа 4)
- Тесты для генерации отчетов и метрик

---

## Сводная таблица действий

| Файл | Действие | Причина |
|------|----------|---------|
| `tests/portfolio/test_portfolio_runner_partial_exits.py` | ❌ УДАЛИТЬ | Legacy путь, time_stop, дублирует replay |
| `tests/portfolio/test_profit_reset_backward_compatibility.py` | ❌ УДАЛИТЬ | Implementation detail, deprecated поля |
| `tests/portfolio/test_debug_portfolio_reset_marker.py` | ❌ УДАЛИТЬ | Отладочный тест с print |
| `tests/portfolio/test_portfolio_dynamic_allocation.py` | ❌ УДАЛИТЬ | Legacy путь, дублирует replay |
| `tests/portfolio/test_portfolio_fees_turn_profit_to_loss.py` | ❌ УДАЛИТЬ | Edge case, уже покрыт другими тестами |
| `tests/domain/test_portfolio_event_partial_exit.py` | ❌ УДАЛИТЬ | time_stop reason, implementation detail |
| `tests/domain/test_portfolio_reset_reason_mapping.py` | ❌ УДАЛИТЬ | Implementation detail маппинга |
| `tests/domain/test_reset_reason_fix.py` | ❌ УДАЛИТЬ | Fix-specific тест |
| `tests/portfolio/test_portfolio_limits.py` | ⚠️ УПРОСТИТЬ | Оставить 1–2 ключевых теста |
| `tests/portfolio/test_portfolio_capacity_reset.py` | ❌ УДАЛИТЬ | Legacy путь, reset уже в replay/audit |
| `tests/portfolio/test_portfolio_runner_reset_portfolio_level.py` | ❌ УДАЛИТЬ | Legacy путь, дублирует replay |
| `tests/portfolio/test_execution_profiles.py` | ⚠️ УПРОСТИТЬ | Удалить legacy compatibility тест |
| `tests/infrastructure/test_reporter_output_dir_stage_2_5.py` | ⚠️ ПЕРЕИМЕНОВАТЬ | Упростить и убрать "stage_2_5" |
| `tests/domain/test_portfolio_event_contract.py` | ❌ УДАЛИТЬ | Просто проверка конструктора dataclass |
| `tests/portfolio/test_portfolio_smoke.py` | ⚠️ УПРОСТИТЬ | Оставить только критичные smoke |

---

## Метрики

- **Всего тестовых файлов:** ~66
- **К удалению:** ~12 файлов
- **К упрощению/переименованию:** ~3 файла
- **К сохранению без изменений:** ~50 файлов

---

## Примечания

1. **Legacy путь:** Все тесты, использующие `PortfolioEngine.simulate()` со старым API (`StrategyOutput`), должны быть удалены или переписаны на `PortfolioReplay` через blueprints.

2. **time_stop:** Тесты, проверяющие `time_stop` в стратегии, должны быть удалены (это теперь только `max_hold_minutes` на уровне портфеля).

3. **Implementation details:** Тесты, проверяющие внутренние поля (`meta`, `reason` mapping), должны быть удалены, если они не защищают архитектурный инвариант.

4. **Дублирование:** Если функциональность уже проверяется в `test_portfolio_replay.py` или audit invariants, тест можно удалить.

---

## Краткое резюме

### Файлы к удалению (12):
1. `tests/portfolio/test_portfolio_runner_partial_exits.py` — legacy путь, time_stop
2. `tests/portfolio/test_profit_reset_backward_compatibility.py` — deprecated поля
3. `tests/portfolio/test_debug_portfolio_reset_marker.py` — отладочный тест
4. `tests/portfolio/test_portfolio_dynamic_allocation.py` — legacy путь
5. `tests/portfolio/test_portfolio_fees_turn_profit_to_loss.py` — edge case
6. `tests/portfolio/test_portfolio_capacity_reset.py` — legacy путь
7. `tests/portfolio/test_portfolio_runner_reset_portfolio_level.py` — legacy путь
8. `tests/domain/test_portfolio_event_partial_exit.py` — time_stop reason
9. `tests/domain/test_portfolio_reset_reason_mapping.py` — implementation detail
10. `tests/domain/test_reset_reason_fix.py` — fix-specific тест
11. `tests/domain/test_portfolio_event_contract.py` — конструктор dataclass
12. *(возможно другие после детального просмотра)*

### Файлы к упрощению (3):
1. `tests/portfolio/test_portfolio_limits.py` — оставить 1–2 ключевых теста
2. `tests/portfolio/test_execution_profiles.py` — удалить legacy compatibility тест
3. `tests/infrastructure/test_reporter_output_dir_stage_2_5.py` — переименовать и упростить

### Критичные файлы КЕЕП:
- **Audit invariants:** `test_invariants.py`, `test_p1_checks.py`, `test_p1_executions.py`
- **Replay tests:** `test_portfolio_replay.py`
- **Blueprint tests:** `test_runner_blueprint.py`, `test_reporter_strategy_trades_export.py`
- **Domain logic:** `test_runner_ladder.py`, `test_runner_strategy.py`
- **E2E/Smoke:** `test_portfolio_single_trade.py`, `test_portfolio_smoke.py` (упрощенный), `test_imports_smoke.py`

