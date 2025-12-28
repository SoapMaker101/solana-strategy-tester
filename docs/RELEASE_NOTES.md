# Release Notes — v2.0 (Runner-only)

## Highlights
- Runner-only pipeline with canonical event ledger.
- Audit v2 (P0/P1 anomaly model) with `audit_trade` introspection.
- Portfolio outputs include `position_id` and canonical reasons everywhere.

## Breaking changes
- RR/RRD strategies and legacy selection paths removed.
- PortfolioEvent types restricted to:
  `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`.
- Runner ladder PnL derived from fills ledger (`realized_multiple`), not exit_price.
- Stage A/B are blocked if audit P0 > 0.

## How to run
1. `python main.py` (backtest + reports)
2. `python -m backtester.audit.run_audit --reports-dir output/reports`
3. `python -m backtester.research.run_stage_a --reports-dir output/reports`
4. `python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv`

## Recommended tag
`v2.0.0`
