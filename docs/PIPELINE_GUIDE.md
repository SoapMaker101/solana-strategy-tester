# Pipeline Guide — Runner-only v2.0

## Where configs live

- `config/backtest_example.yaml` — global backtest + portfolio configuration
- `config/runner_baseline.yaml` — Runner ladder strategy definitions
- `config/strategies_example.yaml` — minimal example list

## Runner ladder config fields

```yaml
take_profit_levels:
  - { xn: 2.0, fraction: 0.4 }
  - { xn: 5.0, fraction: 0.4 }
  - { xn: 10.0, fraction: 0.2 }
time_stop_minutes: 20160
use_high_for_targets: true
exit_on_first_tp: false
allow_partial_fills: true
```

Semantics:
- targets are triggered by candle **high** when `use_high_for_targets=true`
- each target emits `POSITION_PARTIAL_EXIT`
- `realized_multiple = Σ fraction_i * xn_i`
- PnL derives from `realized_multiple`, not `exit_price`

## Reset policies

Portfolio resets are Runner-only:

- **profit_reset**: triggered when `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`
- **capacity_prune**: triggered by capacity pressure and closes a subset of positions

Both emit:
- `PORTFOLIO_RESET_TRIGGERED`
- `POSITION_CLOSED` for each forced close

## Pipeline sequence

1. `python main.py` (backtest + reports)
2. `python -m backtester.audit.run_audit` (must be P0=0)
3. `python -m backtester.research.run_stage_a`
4. `python -m backtester.decision.run_stage_b`
