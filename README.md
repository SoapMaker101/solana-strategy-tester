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

## Outputs (Runner-only v2.2)

All research outputs live in `output/reports/`:

- `portfolio_positions.csv` (positions-level source of truth)
- `portfolio_events.csv` (canonical event ledger)
- `portfolio_executions.csv` (execution ledger)
- `strategy_stability.csv` (Stage A)
- `strategy_selection.csv` (Stage B)
- `portfolio_summary.csv` / `strategy_summary.csv`

## Documentation

📚 **Full documentation index:** [`docs/README.md`](docs/README.md)

Documentation is organized into:
- **Architecture** — System design, contracts, event chain
- **Pipeline** — Backtest → Audit → Stage A → Stage B flow
- **Policies** — Reset/prune rules, configuration reference
- **Usage** — User guides, configuration examples, troubleshooting
- **Testing** — Test baselines, guards, test maps
- **Releases** — Changelog, release notes, version history
- **Analysis** ⚠️ — Internal investigation documents (development use only)

Quick links:
- [`docs/pipeline/PIPELINE_GUIDE.md`](docs/pipeline/PIPELINE_GUIDE.md) — Complete pipeline guide
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) — System architecture
- [`docs/releases/RELEASE_2.1.9.md`](docs/releases/RELEASE_2.1.9.md) — v2.1.9 release (frozen baseline)
