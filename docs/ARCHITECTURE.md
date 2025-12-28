# Architecture — Runner-only v2.0

## Domain contracts

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
`ladder_tp`, `stop_loss`, `time_stop`, `capacity_prune`, `profit_reset`, `manual_close`.

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
backtester/application/runner.py    # BacktestRunner orchestration
backtester/domain/runner_ladder.py  # Runner ladder simulation
backtester/domain/portfolio.py      # PortfolioEngine + event emission
backtester/domain/portfolio_reset.py# Reset semantics (profit reset / capacity prune)
backtester/infrastructure/reporter.py # CSV exports (positions/events/executions)
backtester/audit/                   # Audit v2 (invariants + audit_trade)
```
