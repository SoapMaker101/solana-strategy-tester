# Solana Strategy Tester — Runner-only v2.0.1

Runner-only backtesting framework for Solana signals. The system is fully
event-driven and uses a single, canonical Runner ladder contract with blueprint-based portfolio simulation.

**Version 2.0.1** includes unified architecture: signals → blueprints → PortfolioReplay → portfolio reports.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # or .\\.venv\\Scripts\\activate on Windows
pip install -r requirements.txt
```

Run a backtest:

```bash
python main.py --signals signals/example_signals.csv --strategies-config config/runner_baseline.yaml --backtest-config config/backtest_example.yaml --reports-dir output/reports
```

## Pipeline architecture

The pipeline follows a clear separation of concerns:

1. **Signals** → Strategy generates **blueprints** (`strategy_trades.csv`)
   - Strategy intent only (ladder levels, partial exits)
   - No portfolio logic (no position sizing, fees, time limits)
   
2. **Blueprints** → **PortfolioReplay** simulates portfolio execution
   - Applies portfolio rules (position sizing, capacity, resets)
   - Handles time-based closes via `max_hold_minutes` (portfolio-level)
   - Generates portfolio reports (positions, events, executions)

3. **Portfolio Reports** → Analysis pipeline (audit, Stage A, Stage B)

Full pipeline:

```bash
python main.py --signals signals/example_signals.csv --strategies-config config/runner_baseline.yaml --backtest-config config/backtest_example.yaml --reports-dir output/reports
python -m backtester.audit.run_audit --reports-dir output/reports
python -m backtester.research.run_stage_a --reports-dir output/reports
python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
```

Stage A/B refuse to run when the audit reports any P0 anomalies.

## Outputs

All reports live in `output/reports/`:

**Strategy artifacts:**
- `strategy_trades.csv` — trade blueprints (strategy intent without portfolio)

**Portfolio reports:**
- `portfolio_positions.csv` — positions-level source of truth
- `portfolio_events.csv` — canonical event ledger
- `portfolio_executions.csv` — execution ledger
- `portfolio_stats.json` — portfolio summary statistics

**Analysis outputs:**
- `strategy_stability.csv` (Stage A)
- `strategy_selection.csv` (Stage B)

See:

- `docs/ARCHITECTURE.md` — domain contracts and event chain
- `docs/PIPELINE_GUIDE.md` — configuration and Runner ladder fields
- `docs/RELEASE_NOTES.md` — v2.0 notes and breaking changes

## Verify

### Run tests

```bash
pytest -q
```

### Run backtest

```bash
python main.py --signals "C:\Прочее\Крипта\Тестер соланы\signals\example_signals.csv" --backtest-config "C:\Прочее\Крипта\Тестер соланы\config\backtest_example.yaml" --reports-dir "C:\Прочее\Крипта\Тестер соланы\output\reports"
```

### Expected artifacts

After a successful backtest run, the following files should be created in the `--reports-dir`:

**Strategy artifacts:**
- `strategy_trades.csv` — trade blueprints (strategy intent)

**Portfolio reports:**
- `portfolio_positions.csv` — positions-level source of truth
- `portfolio_events.csv` — canonical event ledger
- `portfolio_executions.csv` — execution ledger
- `portfolio_stats.json` — portfolio summary statistics (one per strategy: `{strategy_name}_portfolio_stats.json`)
- `portfolio_policy_summary.csv` — aggregated portfolio policy statistics
- `{strategy_name}_equity_curve.csv` — equity curve over time (one per strategy)
