# V2 Run Checklist

1. Run backtest:
   ```bash
   python main.py --signals <signals.csv> --strategies-config <strategies.yaml> --backtest-config <backtest.yaml> --reports-dir output/reports
   ```

2. Run audit (must show P0=0):
   ```bash
   python -m backtester.audit.run_audit --reports-dir output/reports
   ```

3. Run Stage A:
   ```bash
   python -m backtester.research.run_stage_a --reports-dir output/reports
   ```

4. Run Stage B:
   ```bash
   python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
   ```

5. Verify outputs:
   - `portfolio_positions.csv` includes `position_id`, `reason`, `pnl_pct_total`, `realized_multiple`
   - `portfolio_events.csv` includes `position_id` and `event_id`
   - `portfolio_executions.csv` includes `position_id`

## Git Push for v2.0 Branch

When working with the `codex/refactor-repository-for-runner-only-v2.0-release` branch locally (as `codex-v2`), push using:

```bash
git push origin HEAD:codex/refactor-repository-for-runner-only-v2.0-release
```

Or set upstream tracking:
```bash
git push -u origin HEAD:codex/refactor-repository-for-runner-only-v2.0-release
```