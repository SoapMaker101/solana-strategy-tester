# Solana Strategy Tester — Runner-only v2.1.9

Runner-only backtesting framework for Solana signals. The system is now fully
event-driven and uses a single, canonical Runner ladder contract.

**Version 2.1.9** (FROZEN BASELINE) — Stable release with fixed contracts, full test coverage, and documented known issues.

**See:** `docs/RELEASE_2.1.9.md` for complete release documentation.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # or .\\.venv\\Scripts\\activate on Windows
pip install -r requirements.txt
```

Run a backtest:

```bash
python main.py \
  --signals signals/example_signals.csv \
  --strategies-config config/runner_baseline.yaml \
  --backtest-config config/backtest_example.yaml \
  --reports-dir output/reports
```

## Runner-only pipeline

Pipeline order:

1. **Backtest** → `main.py`
2. **Audit** → `python -m backtester.audit.run_audit`
3. **Stage A** → `python -m backtester.research.run_stage_a`
4. **Stage B** → `python -m backtester.decision.run_stage_b`

Example:

```bash
python -m backtester.audit.run_audit --reports-dir output/reports
python -m backtester.research.run_stage_a --reports-dir output/reports
python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
```

Stage A/B refuse to run when the audit reports any P0 anomalies.

## Outputs (Runner-only v2.1.9)

All research outputs live in `output/reports/`:

- `portfolio_positions.csv` (positions-level source of truth)
- `portfolio_events.csv` (canonical event ledger)
- `portfolio_executions.csv` (execution ledger)
- `strategy_stability.csv` (Stage A)
- `strategy_selection.csv` (Stage B)
- `portfolio_summary.csv` / `strategy_summary.csv`

See:

- `docs/RELEASE_2.1.9.md` — Complete release documentation
- `docs/ARCHITECTURE.md` — Domain contracts and event chain
- `docs/PIPELINE_GUIDE.md` — Configs and Runner ladder fields
- `docs/RELEASE_NOTES.md` — Release notes and breaking changes
- `docs/KNOWN_ISSUES_2.1.9.md` — Known issues (deferred to 2.2+)
