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
   - fees and slippage modeling (execution profiles: realistic/stress/custom)
   - position management
   - portfolio-level reset (profit reset: close all positions when equity threshold reached)
   - capacity reset (v1.6): prevents "capacity choke" by closing all positions when portfolio is full and turnover is low
   - capacity prune (v1.7): partial position closure instead of full reset, closes ~50% of "bad" positions to free up slots
   - portfolio events (v1.9): canonical event-driven architecture with clear ATTEMPT vs EXECUTED semantics
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

## 🚀 Run v1.10 (quick)

### Установка Excel engine (рекомендуется)

```bash
# Рекомендуемый engine (предпочтительно)
pip install -U openpyxl

# Опционально (fallback)
pip install -U xlsxwriter
```

### Прогон backtest

```bash
python main.py \
  --signals signals/example_signals.csv \
  --strategies-config config/runner_baseline.yaml \
  --backtest-config config/backtest_example.yaml \
  --reports-dir output/reports
```

**При включенном `reporting.export_xlsx: true` (по умолчанию) будет создан `report_pack.xlsx`.**

### Прогон Stage A / Stage B

**Stage A (research):**
```bash
python -m backtester.research.run_stage_a \
  --reports-dir output/reports
```

**Stage B (decision):**
```bash
python -m backtester.decision.run_stage_b \
  --stability-csv output/reports/strategy_stability.csv
```

**Ожидаемые файлы:**
- CSV файлы создаются всегда (source of truth)
- XLSX файлы создаются при наличии Excel engine (best-effort)

### Где смотреть результат

**Директория:** `output/reports/`

**Файлы:**
- `portfolio_positions.csv` — позиции (source of truth для Stage A/B)
- `portfolio_events.csv` — события портфеля (v1.9)
- `portfolio_policy_summary.csv` — сводка по политикам (если есть)
- `strategy_stability.csv` — результаты Stage A
- `strategy_selection.csv` — результаты Stage B
- `report_pack.xlsx` — единый XLSX-отчёт (v1.10, если включен)

**Примечание:** XLSX — не источник истины, source of truth — CSV. XLSX создаётся для удобства анализа и передачи артефактов.

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

### report_pack.xlsx (v1.10: Report Pack)

**Единый XLSX-отчёт** со всеми ключевыми таблицами пайплайна в одном файле.

**Расположение:** `output/reports/report_pack.xlsx`

**Листы:**
- `summary` — метаданные запуска и топлайновые метрики
- `positions` — копия `portfolio_positions.csv`
- `portfolio_events` — копия `portfolio_events.csv` (v1.9)
- `stage_a_stability` — копия `strategy_stability.csv` (если запускался Stage A)
- `stage_b_selection` — копия `strategy_selection.csv` (если запускался Stage B)
- `policy_summary` — копия `portfolio_policy_summary.csv` (если существует)
- `capacity_prune_events` — опционально (если есть отдельная таблица)

**Требования:** `pip install openpyxl` (или `xlsxwriter`)

**Конфигурация (YAML):**
```yaml
reporting:
  export_xlsx: true              # включает генерацию report_pack.xlsx
  xlsx_filename: report_pack.xlsx
  xlsx_timestamped: false        # если true => добавлять timestamp к имени
  xlsx_include_csv_backups: true # CSV остаются (всегда true)
  xlsx_sheets:
    - summary
    - positions
    - portfolio_events
    - stage_a_stability
    - stage_b_selection
    - policy_summary
```

**Примечание:** Если Excel engine не установлен, XLSX-экспорт пропускается с предупреждением, CSV-файлы создаются как обычно.

### portfolio_events.csv (v1.9: Event-driven architecture)

**Semantics v1.9: ATTEMPT vs EXECUTED**

Portfolio events provide canonical event-driven semantics that clearly separate attempts (signals received) from executed trades (actual positions):

| Event Type | Category | Description |
|------------|----------|-------------|
| `ATTEMPT_ACCEPTED_OPEN` | ATTEMPT | Strategy wanted to enter, portfolio accepted and opened position |
| `ATTEMPT_REJECTED_CAPACITY` | ATTEMPT | Strategy wanted to enter, portfolio rejected (max_open_positions reached) |
| `ATTEMPT_REJECTED_RISK` | ATTEMPT | Strategy wanted to enter, portfolio rejected (risk rules: max_exposure, etc.) |
| `ATTEMPT_REJECTED_STRATEGY_NO_ENTRY` | ATTEMPT | Strategy decided not to enter (no_entry) |
| `ATTEMPT_REJECTED_NO_CANDLES` | ATTEMPT | No candles available for entry |
| `EXECUTED_CLOSE` | EXECUTED | Position closed normally (tp/sl/timeout) |
| `CLOSED_BY_CAPACITY_PRUNE` | EXECUTED | Position closed by capacity prune |
| `CLOSED_BY_PROFIT_RESET` | EXECUTED | Position closed by profit reset |
| `CAPACITY_PRUNE_TRIGGERED` | TRIGGER | Capacity prune was triggered |
| `PROFIT_RESET_TRIGGERED` | TRIGGER | Profit reset was triggered |

**Capacity Window Formula (signals-based):**

For `capacity_window_type="signals"`, capacity pressure is calculated from events:
```
attempted = accepted_open_count + rejected_capacity_count
blocked_ratio = rejected_capacity_count / attempted
```

Capacity pressure triggers if:
- `open_ratio >= capacity_open_ratio_threshold` (portfolio filled)
- `blocked_ratio >= capacity_max_blocked_ratio` (too many rejections)
- `avg_hold_days >= capacity_max_avg_hold_days` (positions held too long)

**Key Principles:**
- **Events = source of truth**: All portfolio decisions (capacity pressure, prune/reset triggers) are derived from events
- **Stage A/B use executed only**: Research pipeline (`portfolio_positions.csv`) contains only executed positions, not attempts
- **Backward compatibility**: Legacy counters (`portfolio_reset_count`, `portfolio_capacity_prune_count`) are recomputed from events at the end of simulation

**CSV columns:**
- `timestamp` — event time (ISO)
- `event_type` — type of event
- `strategy` — strategy name
- `signal_id` — signal identifier
- `contract_address` — contract address
- `position_id` — position identifier (if applicable)
- `meta_json` — JSON string with additional metadata

**Export:**
- Generated automatically: `output/reports/portfolio_events.csv`
- **XLSX optional**: CSV is mandatory, XLSX export is optional (skipped if engine unavailable)
- Fail-safe: Export continues even if events CSV fails to write

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
  
  # Capacity reset (v1.6) - prevents "capacity choke"
  capacity_reset:
    enabled: true
    window_type: "time"  # "time" or "signals"
    window_size: 7d      # Window size (days for "time", count for "signals")
    max_blocked_ratio: 0.7    # Max ratio of blocked signals in window
    max_avg_hold_days: 20.0   # Max average hold time for open positions
    # Capacity prune (v1.7) - partial closure instead of full reset
    mode: "close_all"         # "close_all" (old behavior) or "prune" (partial closure)
    prune_fraction: 0.5       # Fraction of candidates to close (0.5 = 50%)
    prune_min_hold_days: 1.0  # Min hold time for candidate (days)
    prune_max_mcap_usd: 20000 # Max mcap for candidate (USD)
    prune_max_current_pnl_pct: -0.30  # Max current PnL for candidate (-0.30 = -30%)
  
  # Execution profiles with reason-based slippage
  execution_profile: "realistic"  # "realistic", "stress", or "custom"
  fee:
    profiles:
      realistic:
        base_slippage_pct: 0.03
        slippage_multipliers:
          entry: 1.0
          exit_tp: 0.6
          exit_sl: 1.3
          exit_timeout: 0.25
          exit_manual: 0.5
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
- ✅ Phase 5.5: Capacity reset (v1.6) - prevents capacity choke
- ✅ Phase 5.6: Execution profiles with reason-based slippage
- ✅ Phase 5.7: Capacity prune (v1.7) - partial position closure instead of full reset

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
