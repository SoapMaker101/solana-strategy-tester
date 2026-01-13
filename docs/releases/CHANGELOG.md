# Changelog

## v2.2.1 (Runner-only) — Profit Reset Multiple Parsing + Anti-Spam Guard + Reset Ledger Fixes

**Дата:** 2025-01-XX  
**Статус:** ✅ Development

### Fixed
- **Profit reset multiple validation**: Добавлена жёсткая валидация `profit_reset_multiple`:
  - Должен быть `float > 1.0`, иначе reset автоматически disabled
  - Если `<= 1.0` или invalid (inf, nan) — reset disabled, warning в лог
  - Исправлен парсинг из YAML (гарантированно float)
- **Anti-spam guard**: Добавлен защитный механизм против множественных reset на одном timestamp:
  - Reset не может сработать повторно если `last_portfolio_reset_time == current_time`
  - Предотвращает reset spam при неправильной конфигурации или багах
- **Reset ledger improvements**:
  - Уникальный `reset_id` (UUID) генерируется для каждого reset события
  - Уникальный `position_id` для каждого marker позиции (создается заново для каждого reset)
  - `reset_id` добавляется в `meta` marker позиций и reset событий
  - `closed_positions_count` корректно считает только force-closed позиции (без marker)

### Tests
- Создан `tests/portfolio/test_profit_reset_sanity_and_ledger.py` с 6 тестами:
  - `test_profit_reset_multiple_float_parsed_correctly_no_spam` — проверка что reset не спамит при правильном multiple
  - `test_profit_reset_multiple_le_1_disables_reset` — проверка что multiple <= 1.0 отключает reset
  - `test_profit_reset_emits_reset_id_and_unique_marker_position_id` — проверка уникальности reset_id и marker position_id
  - `test_profit_reset_guard_prevents_multiple_resets_same_timestamp` — проверка anti-spam guard
  - `test_profit_reset_multiple_float_type` — проверка типизации profit_reset_multiple
  - `test_profit_reset_config_c_scenario_no_spam` — имитация сценария конфига C (убыточный результат не триггерит reset)

### Documentation
- Обновлен `docs/policies/PRUNE_AND_PROFIT_RESET_RULES.md`:
  - Добавлено описание валидации `profit_reset_multiple` (float > 1.0)
  - Добавлено описание anti-spam guard как инварианта

---

## v2.2.0 (Runner-only) — Profit Reset Realized Balance + Hybrid Sizing

**Дата:** 2025-01-XX  
**Статус:** ✅ Development

### Added
- **Profit reset trigger basis**: Новый параметр `profit_reset_trigger_basis` с двумя режимами:
  - `"equity_peak"` (legacy, default) — проверка по equity peak (включая floating PnL)
  - `"realized_balance"` (новый) — проверка по реализованному cash balance (без floating PnL)
- **Hybrid allocation mode**: Новый режим `"fixed_then_dynamic_after_profit_reset"`:
  - До первого profit reset: размер считается от `initial_balance_sol` (как `"fixed"`)
  - После первого profit reset: размер считается от текущего баланса (как `"dynamic"`)
- **Reset ledger improvements**:
  - Уникальный `reset_id` (UUID) для каждого reset события
  - Уникальный `position_id` для каждого marker позиции
  - Корректный `closed_positions_count` (только force-closed позиции, без marker)
- **Cycle start balance tracking**: Добавлено поле `cycle_start_balance` для отслеживания реализованного баланса в начале цикла

### Fixed
- Marker позиции теперь создаются заново для каждого reset (уникальный `position_id`)
- `closed_positions_count` в `PORTFOLIO_RESET_TRIGGERED` теперь корректно считает только force-closed позиции
- `reset_id` добавляется в `meta` marker позиций для трассируемости

### Documentation
- Обновлен `docs/PRUNE_AND_PROFIT_RESET_RULES.md` с описанием новых режимов trigger и allocation
- Добавлены примеры использования `profit_reset_trigger_basis` и `fixed_then_dynamic_after_profit_reset`

### Tests
- Создан `tests/domain/test_profit_reset_realized_balance_and_sizing.py` с 6 тестами:
  - `test_realized_balance_not_triggered_by_floating` — проверка что floating PnL не триггерит reset
  - `test_realized_balance_triggered_after_normal_exit` — проверка что reset срабатывает после exit
  - `test_allocation_mode_fixed_preserves_size_after_reset` — проверка что fixed mode сохраняет размер
  - `test_allocation_mode_hybrid_increases_size_after_reset` — проверка что hybrid mode увеличивает размер
  - `test_reset_ledger_unique` — проверка уникальности reset_id и marker position_id
  - `test_marker_no_executions` — проверка что marker не создает лишних executions

---

## v2.1.9 (Runner-only) — Stable Baseline / Frozen

**Дата:** 2025-01-06  
**Статус:** ✅ Stable / Frozen  
**Тесты:** 306 passed, 0 warnings

### Changes
- **Stable baseline:** Зафиксированы все контракты, добавлены guard-тесты
- **Warnings as errors:** Настроен `pytest.ini` для строгого контроля качества
- **Resource leaks fixed:** Исправлены утечки файловых дескрипторов в XLSX тестах
- **Documentation:** Полная документация релиза, известных проблем, контрактов

### Fixed
- Исправлены утечки файловых дескрипторов в `tests/infrastructure/test_xlsx_writer.py`
- Исправлены утечки файловых дескрипторов в `tests/infrastructure/test_report_pack_xlsx.py`
- Все `pd.ExcelFile` теперь используют контекст-менеджер `with`
- Все `load_workbook` обернуты в `try/finally` с `wb.close()`

### Documentation
- Создан `docs/RELEASE_2.1.9.md` — полное описание релиза
- Создан `docs/KNOWN_ISSUES_2.1.9.md` — известные проблемы (отложены для 2.2+)
- Обновлен `README.md` — упоминание версии 2.1.9
- Обновлен `docs/RELEASE_NOTES.md` — добавлена информация о версии 2.1.9
- Обновлен `backtester/infrastructure/reporting/report_pack.py` — версия в метаданных

### Known Issues (Deferred to 2.2+)
- Basedpyright typing warnings (см. `docs/KNOWN_ISSUES_2.1.9.md`)
- V2-хак в `select_strategies` (см. `docs/KNOWN_ISSUES_2.1.9.md`)
- Pandas type hints неполные (см. `docs/KNOWN_ISSUES_2.1.9.md`)

**См. также:** `docs/RELEASE_2.1.9.md` для полного описания релиза.

---

## v2.0.1 (Runner-only) — Full Refactor + Audit Contract

### Changes
- **Full refactor**: Removed all legacy event types, unified event contract to 4 canonical types
- **Event contract**: Only `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- **Reset semantics**: Reset emits `PORTFOLIO_RESET_TRIGGERED` (1 event) + N `POSITION_CLOSED` events (per closed position)
- **Runner ladder**: `exit_price` is market close (first candle with timestamp >= exit_time), PnL calculated from fills ledger
- **Audit layer**: Enhanced invariant checks, safe column access, strict reason consistency
- **Reporter exports**: Fixed column order in CSV exports, removed duplicates, unified format
- **Position dataclass**: Fixed field order to comply with dataclass rules
- **Documentation**: Updated to reflect v2.0.1 contract and pipeline

### Fixed
- Fixed TypeError in `Position` dataclass (non-default argument order)
- Removed duplicate `position_id` in `portfolio_positions.csv` export
- Fixed column order in all CSV exports to match v2.0.1 spec
- Removed all legacy event factory methods (create_executed_close, create_closed_by_*, etc.)
- Safe column access in audit invariants (no crashes on missing columns)

### Removed
- All legacy PortfolioEventType values (ATTEMPT_*, EXECUTED_CLOSE, CLOSED_BY_*, etc.)
- Legacy event factory methods from PortfolioEvent
- References to RR/RRD strategies in report generation

## v2.0.0 (Runner-only)

### Breaking changes
- Removed all RR/RRD strategies and legacy pipeline branches.
- Canonical PortfolioEvent types are now:
  `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`.
- PnL for Runner ladder is derived from fills ledger (`realized_multiple`), not exit_price.
- Stage A/B now require audit P0=0 before execution.

### Removed modules/configs
- `backtester/domain/rr_strategy.py`
- `backtester/domain/rrd_strategy.py`
- `backtester/domain/rr_utils.py`
- `config/strategies_rr_rrd_grid.yaml`

### Runner-only updates
- `position_id` is mandatory and exported in all reports.
- Reset chain emits `PORTFOLIO_RESET_TRIGGERED` + N `POSITION_CLOSED`.
- Audit v2 commands: `run_audit` and `audit_trade`.
