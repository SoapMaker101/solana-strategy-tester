# Changelog

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
