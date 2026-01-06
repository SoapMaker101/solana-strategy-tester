# Changelog

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
