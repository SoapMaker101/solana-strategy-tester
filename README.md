# Solana Strategy Tester — Runner-only v2.1.9

Runner-only backtesting framework for Solana signals. The system is now fully
event-driven and uses a single, canonical Runner ladder contract.

**Version 2.2** (CURRENT STABLE) — Stability anchor with typing hardening, zero basedpyright noise, and preserved behavior.

**Previous baseline:** Version 2.1.9 (FROZEN BASELINE) — see `docs/releases/RELEASE_2.1.9.md` for complete release documentation.

### Current Stable Version

The current stable baseline is **v2.2 (Runner-only)**.

This version focuses on:
- pipeline correctness
- explicit data contracts
- static typing hygiene
- full test coverage

Recommended starting point for new work.

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

- `docs/releases/RELEASE_2.1.9.md` — Complete release documentation
- `docs/architecture/ARCHITECTURE.md` — Domain contracts and event chain
- `docs/usage/PIPELINE_GUIDE.md` — Configs and Runner ladder fields
- `docs/releases/RELEASE_NOTES.md` — Release notes and breaking changes
- `docs/releases/KNOWN_ISSUES_2.1.9.md` — Known issues (deferred to 2.2+)

## Documentation Structure

Documentation is organized into the following categories:

- **`docs/architecture/`** — Architecture documentation, domain contracts, and event chain specifications
- **`docs/usage/`** — User guides, configuration examples, and how-to documentation
- **`docs/releases/`** — Release notes, changelog, implementation status, and known issues
- **`docs/testing/`** — Testing guides, test maps, and testing-related documentation
- **`docs/analysis/`** — Internal analysis reports, completion reports, and technical deep-dives
