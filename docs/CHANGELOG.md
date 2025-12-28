# Changelog

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
