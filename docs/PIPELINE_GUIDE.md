# Pipeline Guide — Runner-only v2.0

## Pipeline flow

```
Signals → Strategy Blueprints (strategy_trades.csv) → PortfolioReplay → Portfolio Reports
```

1. **Strategy** processes signals and generates **blueprints** (strategy intent)
   - Ladder levels, partial exits, final exits (if all levels hit)
   - No portfolio logic (no sizing, fees, time limits)

2. **PortfolioReplay** simulates portfolio execution from blueprints
   - Applies position sizing, capacity rules, profit/capacity resets
   - Handles time-based closes via `max_hold_minutes` (portfolio-level)
   - Generates positions, events, executions

## Configuration files

- `config/backtest_example.yaml` — global backtest + portfolio configuration
- `config/runner_baseline.yaml` — Runner ladder strategy definitions
- `config/strategies_example.yaml` — minimal example list

## Runner ladder strategy config

```yaml
take_profit_levels:
  - { xn: 2.0, fraction: 0.4 }
  - { xn: 5.0, fraction: 0.4 }
  - { xn: 10.0, fraction: 0.2 }
use_high_for_targets: true
exit_on_first_tp: false
allow_partial_fills: true
```

**Note:** `time_stop_minutes` removed from strategy. Time-based closing is handled at portfolio level via `max_hold_minutes` in portfolio config.

Semantics:
- Targets are triggered by candle **high** when `use_high_for_targets=true`
- Each target emits `POSITION_PARTIAL_EXIT` in blueprint
- `realized_multiple = Σ fraction_i * xn_i`
- PnL derives from `realized_multiple`, not `exit_price`
- If all levels hit → `final_exit` with `reason="all_levels_hit"`
- If levels not hit → `final_exit=None` (portfolio handles closing via `max_hold_minutes`)

## Portfolio configuration

### Time-based closing

Time-based position closing is handled at **portfolio level**, not strategy:

```yaml
portfolio:
  max_hold_minutes: 20160  # 14 days - maximum time to hold a position
```

- If `max_hold_minutes` is set, portfolio closes positions that exceed this limit
- Close reason: `max_hold_minutes`
- Strategy blueprints do **not** include time-based exits

### Reset policies

- **profit_reset**: triggered when `equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple`
- **capacity_prune**: triggered by capacity pressure and closes a subset of positions

Both emit:
- `PORTFOLIO_RESET_TRIGGERED`
- `POSITION_CLOSED` for each forced close

## Pipeline sequence

```bash
python main.py --signals signals/example_signals.csv --strategies-config config/runner_baseline.yaml --backtest-config config/backtest_example.yaml --reports-dir output/reports
python -m backtester.audit.run_audit --reports-dir output/reports
python -m backtester.research.run_stage_a --reports-dir output/reports
python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
```
