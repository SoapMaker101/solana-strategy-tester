# Architecture — Runner-only v2.0

## Architecture overview

The system follows a clear separation: **strategy intent** (blueprints) → **portfolio execution** (PortfolioReplay).

```
Signals → StrategyTradeBlueprint (strategy_trades.csv) → PortfolioReplay → Portfolio Reports
```

1. **Strategy layer**: Generates trade blueprints without portfolio logic
2. **Portfolio layer**: Applies portfolio rules (sizing, capacity, resets, time limits)

## Domain contracts

### StrategyTradeBlueprint

Strategy intent without portfolio execution:

- `signal_id`, `strategy_id`, `contract_address`
- `entry_time`, `entry_price_raw` (raw price, no slippage)
- `partial_exits`: List of ladder exits (xn, fraction, timestamp)
- `final_exit`: Only if all levels hit (`reason="all_levels_hit"`), otherwise `None`
- `realized_multiple`: Σ(fraction_i × xn_i)
- `max_xn_reached`: Maximum xn achieved

**Note:** No position sizing, fees, or time-based closing at strategy level.

### Position

- `position_id` (uuid4 hex) is mandatory and stable for the position lifetime.
- `entry_time`, `exit_time`, `entry_price`, `exit_price` are always recorded.
- `exit_price` is the market close price at `exit_time` (informational).
- `meta` contains ladder fills:
  - `levels_hit`, `fractions_exited`, `realized_multiple`
  - partial fills ledger in `partial_exits`

### PortfolioEvent

Canonical event types:

```
POSITION_OPENED
POSITION_PARTIAL_EXIT
POSITION_CLOSED
PORTFOLIO_RESET_TRIGGERED
```

Every position event includes:
`position_id`, `strategy`, `signal_id`, `timestamp`, `contract_address`.

Close events include canonical `reason`:
`ladder_tp`, `stop_loss`, `max_hold_minutes`, `capacity_prune`, `profit_reset`, `manual_close`.

**Note:** `time_stop` removed. Time-based closing uses `max_hold_minutes` reason.

### ExecutionRecord (portfolio_executions.csv)
- Always includes `position_id`
- Uses `event_id` when available to link to PortfolioEvent
- Every execution is explainable by a PortfolioEvent

### Source of truth for PnL
- Runner ladder PnL is computed from fills ledger:
  `realized_multiple = Σ (fraction_i * xn_i)`
- `pnl_pct_total = (realized_multiple - 1) * 100`
- `exit_price` is informational only

## Event chain

```
POSITION_OPENED
 ├─ POSITION_PARTIAL_EXIT (xn=2, fraction=0.4)
 ├─ POSITION_PARTIAL_EXIT (xn=5, fraction=0.4)
 ├─ POSITION_PARTIAL_EXIT (xn=10, fraction=0.2)
 └─ POSITION_CLOSED (reason=ladder_tp)
```

### Portfolio reset chain

```
PORTFOLIO_RESET_TRIGGERED (reason=profit_reset | capacity_prune)
 ├─ POSITION_CLOSED (position_id=...)
 ├─ POSITION_CLOSED (position_id=...)
 └─ ...
```

## Core modules

```
backtester/application/runner.py           # BacktestRunner orchestration
backtester/domain/runner_strategy.py       # RunnerStrategy (generates blueprints)
backtester/domain/runner_ladder.py         # Runner ladder simulation (strategy logic)
backtester/domain/strategy_trade_blueprint.py # Blueprint domain model
backtester/domain/portfolio.py             # PortfolioEngine (wrapper over PortfolioReplay)
backtester/domain/portfolio_replay.py      # PortfolioReplay (blueprint → portfolio execution)
backtester/domain/portfolio_reset.py       # Reset semantics (profit reset / capacity prune)
backtester/infrastructure/reporter.py      # CSV exports (blueprints, positions, events, executions)
backtester/audit/                          # Audit v2 (invariants + audit_trade)
```

## Portfolio execution flow

1. **Strategy** generates `StrategyTradeBlueprint` per signal
2. **PortfolioReplay** processes blueprints:
   - Checks capacity limits
   - Applies position sizing (fixed/dynamic allocation)
   - Executes partial exits from blueprint
   - Handles final exit (if present) or closes by `max_hold_minutes` (if set)
   - Applies profit/capacity resets
3. **Reporter** saves all artifacts (blueprints, positions, events, executions)
