# Solana Strategy Tester

> **Snapshot as of 2025-12-XX**  
> **⚠️ ВАЖНО:** С декабря 2025 проект работает только с **RUNNER** стратегиями. RR/RRD признаны неэффективными и исключены из пайплайна. Они остаются только как legacy-код для обратной совместимости.

Local backtesting framework for testing **Runner** trading strategies on Solana tokens based on external signals (Telegram, narrative feeds, etc.).  
The goal: batch-test different Runner configurations on historical candles and find robust behaviour patterns through research pipeline (Stage A → Stage B).

---

## 🎯 High-level idea

**Runner Strategy** — это стратегия с лестницей тейк-профитов (ladder strategy), которая:
- Входит в позицию на первой свече после сигнала
- Удерживает позицию длительное время (14-21 день)
- Частично закрывает позицию на разных уровнях прибыли (например, 40% на 2x, 40% на 5x, 20% на 10x)
- Автоматически закрывает остаток по time_stop или portfolio-level reset

**Pipeline:**

1. **Signals** — incoming events like "MadApes posted token X at time T"
2. **Price data** — candles for token (from local CSVs or GeckoTerminal API)
3. **Runner Strategy** — pure Python logic that decides:
   - enter / not enter,
   - partial exits at different XN levels (2x, 5x, 10x),
   - time stop and portfolio-level reset
4. **Portfolio Engine** — realistic simulation with:
   - fees and slippage modeling
   - position management
   - portfolio-level reset (close all positions when equity threshold reached)
5. **Research Pipeline** — two-stage analysis:
   - **Stage A**: Window-based stability analysis → `strategy_stability.csv`
   - **Stage B**: Strategy selection by criteria → `strategy_selection.csv`

---

## 📁 Project structure

```text
backtester/
├── application/
│   └── runner.py              # BacktestRunner: orchestrates signals → prices → strategies → portfolio
│
├── domain/
│   ├── models.py              # Signal, Candle, StrategyInput, StrategyOutput dataclasses
│   ├── position.py            # Position model with partial exits support
│   ├── portfolio.py           # PortfolioEngine: realistic trading simulation (Phase 4)
│   ├── strategy_base.py       # StrategyConfig + abstract Strategy interface
│   ├── runner_config.py       # RunnerConfig: ladder TP levels configuration
│   ├── runner_ladder.py       # RunnerLadderEngine: core ladder simulation logic
│   ├── runner_strategy.py     # RunnerStrategy: adapter between ladder and Strategy interface
│   ├── portfolio_reset.py     # Portfolio-level reset logic
│   ├── trade_features.py      # Trade features: market cap proxy, volume/volatility windows
│   ├── rr_strategy.py         # LEGACY: RR strategy (deprecated)
│   └── rrd_strategy.py        # LEGACY: RRD strategy (deprecated)
│
├── infrastructure/
│   ├── signal_loader.py       # CsvSignalLoader → List[Signal]
│   ├── price_loader.py        # CsvPriceLoader + GeckoTerminalPriceLoader → List[Candle]
│   └── reporter.py            # Reporter: saves portfolio_positions.csv, strategy_summary.csv, etc.
│
├── research/
│   ├── run_stage_a.py         # Stage A: Window-based stability analysis
│   ├── strategy_stability.py  # Runner metrics calculation (hit_rate_x2, hit_rate_x5, tail_contribution)
│   ├── window_aggregator.py   # Window-based aggregation logic
│   └── xn_analysis/           # XN analysis tools (research phase)
│
└── decision/
    ├── run_stage_b.py         # Stage B: Strategy selection
    ├── strategy_selector.py   # Applies selection criteria
    └── selection_rules.py     # Runner criteria (min_hit_rate_x2, min_hit_rate_x5, etc.)

config/
  backtest_example.yaml        # Global backtest config (portfolio, execution, fees)
  runner_baseline.yaml         # Baseline Runner configuration
  strategies_example.yaml      # Strategy configs (only RUNNER type)

data/
  candles/                     # Historical candles (CSV format)
  sol_price/                   # SOL/USD price history

signals/
  example_signals.csv          # Test signals

output/
  reports/                     # ⭐ Unified directory for all research artifacts
    ├── portfolio_positions.csv      # ⭐ Source of truth for Stage A/B
    ├── strategy_summary.csv         # Portfolio-derived summary
    ├── portfolio_summary.csv        # Aggregated portfolio stats
    ├── strategy_stability.csv       # Stage A output
    └── strategy_selection.csv       # Stage B output
```

---

## 🚀 Quick start

### 1. Setup

```bash
# Create virtualenv
python -m venv .venv
.\.venv\Scripts\activate   # Windows PowerShell
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Prepare data

Ensure you have:
- `signals/example_signals.csv` — signals with columns: `id`, `contract_address`, `timestamp`, `source`, `narrative`
- `data/candles/<contract_address>_<timeframe>.csv` — candles with columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`

### 3. Run backtest

```bash
python main.py \
  --signals signals/example_signals.csv \
  --strategies-config config/runner_baseline.yaml \
  --backtest-config config/backtest_example.yaml \
  --reports-dir output/reports
```

**Output:**
- `output/reports/portfolio_positions.csv` — positions-level data (source of truth)
- `output/reports/strategy_summary.csv` — portfolio-derived summary
- `output/reports/portfolio_summary.csv` — aggregated portfolio stats

### 4. Run research pipeline

**Stage A (Aggregation):**
```bash
python -m backtester.research.run_stage_a \
  --reports-dir output/reports
```

**Output:** `output/reports/strategy_stability.csv` with Runner metrics:
- `hit_rate_x2`, `hit_rate_x5` — hit rates for 2x and 5x levels
- `p90_hold_days` — 90th percentile holding time
- `tail_contribution` — PnL contribution from trades with `max_xn_reached >= 5.0`
- `max_drawdown_pct` — maximum drawdown

**Stage B (Selection):**
```bash
python -m backtester.decision.run_stage_b \
  --stability-csv output/reports/strategy_stability.csv
```

**Output:** `output/reports/strategy_selection.csv` with `passed` flag for each strategy.

---

## 📊 Data contracts

### Signal

Normalized signal format:

```python
@dataclass
class Signal:
    id: str
    contract_address: str
    timestamp: datetime  # UTC
    source: str          # e.g. "madapes"
    narrative: str       # e.g. "memecoin"
    extra: Dict[str, Any] = field(default_factory=dict)
```

**CSV columns:**
- `id`, `contract_address`, `timestamp` (ISO8601), `source`, `narrative`
- Optional: `extra_json` (JSON string)

### Candle

Normalized candle format:

```python
@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
```

**CSV path:** `data/candles/<contract_address>_<timeframe>.csv`

### portfolio_positions.csv (Source of truth)

**Required columns:**
- `strategy`, `signal_id`, `contract_address`
- `pnl_sol`, `fees_total_sol`, `hold_minutes`
- `max_xn_reached` — maximum XN achieved (from `levels_hit` in meta, fallback to price ratios)
- `hit_x2`, `hit_x5` — boolean flags (max_xn_reached >= 2.0 or 5.0)
- `closed_by_reset`, `triggered_portfolio_reset`, `reset_reason`

**Calculation priority for `max_xn_reached`:**
1. `levels_hit` from `Position.meta` (Runner truth) — parse keys as floats, take max
2. `raw_exit_price / raw_entry_price` (if raw prices available)
3. `exec_exit_price / exec_entry_price` (fallback)

---

## 🔧 Runner Strategy Configuration

**Example (`config/runner_baseline.yaml`):**

```yaml
- name: Runner_Baseline
  type: RUNNER
  params:
    take_profit_levels:
      - { xn: 2.0, fraction: 0.4 }   # 40% закрывается на 2x
      - { xn: 5.0, fraction: 0.4 }   # 40% закрывается на 5x
      - { xn: 10.0, fraction: 0.2 }  # 20% закрывается на 10x
    time_stop_minutes: 20160  # 14 дней
    use_high_for_targets: true
    exit_on_first_tp: false
    allow_partial_fills: true
```

**Portfolio-level reset (`config/backtest_example.yaml`):**

```yaml
portfolio:
  profit_reset_enabled: true
  profit_reset_multiple: 2.0  # Close all positions when equity >= cycle_start_equity * 2.0
```

---

## 📚 Documentation

**Key documents:**
- [`docs/RESEARCH_PIPELINE.md`](docs/RESEARCH_PIPELINE.md) — Research pipeline (Stage A/B) guide
- [`docs/PORTFOLIO_LAYER.md`](docs/PORTFOLIO_LAYER.md) — Portfolio layer documentation
- [`docs/RUNNER_COMPLETE_GUIDE.md`](docs/RUNNER_COMPLETE_GUIDE.md) — Complete Runner strategy guide
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Architecture overview
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — Change history

**Research & Analysis:**
- [`docs/XN_RUNNER_RESEARCH.md`](docs/XN_RUNNER_RESEARCH.md) — XN analysis methodology
- [`docs/PROJECT_ANALYSIS.md`](docs/PROJECT_ANALYSIS.md) — Full project analysis

---

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -q

# Run specific test suite
python -m pytest tests/domain/test_runner_ladder.py -v
python -m pytest tests/research/ -v
python -m pytest tests/decision/ -v
```

---

## 🗺️ Roadmap

**Completed:**
- ✅ Phase 2: Clean architecture + stable pipeline
- ✅ Phase 3: Full Runner implementation (ladder TP, partial exits)
- ✅ Phase 4: Portfolio layer (fees, slippage, portfolio-level reset)
- ✅ Phase 4.5: Trade features (market cap proxy, volume/volatility windows)
- ✅ Phase 5: Research pipeline (Stage A/B) for Runner strategies

**Planned:**
- Phase 6: Data sources integration (DexScreener, GMGN, Axiom adapters)
- Phase 7: Real-time signal integration (Telegram, n8n pipelines)
- Phase 8: Parameter optimization and grid search
- Phase 9: Advanced risk management (position sizing, correlation analysis)

---

## ⚠️ Legacy code

**RR/RRD strategies** (`rr_strategy.py`, `rrd_strategy.py`) are marked as **LEGACY** and excluded from:
- Research pipeline (Stage A/B)
- Example configurations
- Documentation (moved to legacy sections)
- Active development

They remain in codebase for backward compatibility only.

---

## 📝 License

[Add your license here]

---

## 🤝 Contributing

[Add contributing guidelines here]
