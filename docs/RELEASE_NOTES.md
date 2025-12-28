# Release Notes

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
