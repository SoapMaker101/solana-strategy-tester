# Release Notes

## v2.1.9 (Runner-only) — Stable Baseline / Frozen

**Статус:** ✅ Stable / Frozen  
**Дата:** 2025-01-06  
**Тесты:** 306 passed, 0 warnings

### Что это за версия

Версия 2.1.9 — это **стабильный baseline** с зафиксированными контрактами, полным покрытием тестами и осознанно отложенными техническими проблемами.

### Основные характеристики

- ✅ **306 passed, 0 warnings** — все тесты зелёные
- ✅ **Guard-тесты** — защита критичных контрактов
- ✅ **Legacy compatibility** — обратная совместимость сохранена
- ✅ **Warnings as errors** — строгий контроль качества
- ✅ **Resource leaks fixed** — все файловые дескрипторы закрываются

### Что исправлено с v2.0.1

- Исправлены утечки файловых дескрипторов в XLSX тестах
- Добавлены guard-тесты для защиты контрактов
- Зафиксированы все контракты в документации
- Настроен `pytest.ini` для warnings as errors

### Известные проблемы

См. `docs/KNOWN_ISSUES_2.1.9.md` для полного списка известных проблем, которые осознанно отложены для версии 2.2+.

### Документация

- `docs/RELEASE_2.1.9.md` — полное описание релиза
- `docs/TEST_GREEN_BASELINE_2025-01-06.md` — контракты и guard-тесты
- `docs/KNOWN_ISSUES_2.1.9.md` — известные проблемы

### Рекомендуемый Tag

`v2.1.9`

---

## v2.0.1 (Runner-only) — Full Refactor + Audit Contract

### What's Changed
- **Full refactor**: Cleaned up all legacy event types, unified to canonical 4-event contract
- **Event contract**: Only `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- **Reset semantics**: Reset emits full chain: `PORTFOLIO_RESET_TRIGGERED` + N `POSITION_CLOSED` events
- **Runner ladder**: `exit_price` = market close (first candle >= exit_time), PnL from fills ledger (`realized_multiple`)
- **Audit layer**: Enhanced invariant checks, safe column access, strict P0/P1 classification
- **Reporter exports**: Fixed column order, removed duplicates, unified CSV format
- **Source of truth**: PnL always from fills ledger + `realized_multiple`, never from `exit_price`

### Fixed Issues
- Fixed `Position` dataclass TypeError (field order)
- Removed duplicate `position_id` in CSV exports
- Fixed column ordering in all CSV exports
- Safe column access in audit (no crashes on missing columns)
- Removed all legacy event factory methods

### Breaking Changes
- All legacy PortfolioEventType values removed
- Event factory methods cleaned up (only canonical ones remain)
- CSV column order standardized

### How to Run (v2.0.1)
1. `python main.py --config config/backtest_A.yaml`
2. `python -m backtester.audit.run_audit --reports-dir output/reports`
3. `python -m backtester.research.run_stage_a --reports-dir output/reports`
4. `python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv`

### Recommended Tag
`v2.0.1`

---

## v2.2 — Stability & Typing Hardening

**Статус:** ✅ Stable  
**Дата:** 2025-01-XX  
**Тесты:** Все зелёные, 0 basedpyright проблем

### Key Points
- No behavior changes
- No test changes
- Runner-only pipeline preserved
- basedpyright reduced to zero noise
- Explicit guards instead of pandas truthiness
- Optional datetime normalization (NaT → None)

This release is a stability anchor before further evolution.

### What Changed
- Explicit pandas checks (`is None`, `.empty`, `.any()`) instead of implicit truthiness
- Normalization of Optional types (NaT → None at boundaries)
- Localized type ignores for known stub limitations (dataclass kwargs, pandas overloads)
- Runtime guards for type narrowing (Series/DataFrame checks before method calls)

### What Did NOT Change
- Strategy logic
- Portfolio logic
- Stage A / Stage B behavior
- Test suite
- Event contracts
- Data contracts

### Documentation
- `docs/V2.2_IMPLEMENTATION_STATUS.md` — детали изменений
- `docs/TYPING_POLICY.md` — политика типизации
- `docs/KNOWN_LIMITATIONS.md` — известные ограничения

---

## v2.0.0 (Runner-only)

### Highlights
- Runner-only pipeline with canonical event ledger.
- Audit v2 (P0/P1 anomaly model) with `audit_trade` introspection.
- Portfolio outputs include `position_id` and canonical reasons everywhere.

### Breaking changes
- RR/RRD strategies and legacy selection paths removed.
- PortfolioEvent types restricted to:
  `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`.
- Runner ladder PnL derived from fills ledger (`realized_multiple`), not exit_price.
- Stage A/B are blocked if audit P0 > 0.
