README.md

# Solana Strategy Tester

> Snapshot as of **2025-12-14**

Local backtesting framework for testing trading strategies on Solana tokens based on external signals (Telegram, narrative feeds, etc.).  
The goal: batch-test different strategies (RR, RRD, runner, etc.) on historical candles and find robust behaviour patterns.

---

## High-level idea

Pipeline:

1. **Signals** — incoming events like “MadApes posted token X at time T”.
2. **Price data** — candles for token (from local CSVs for now).
3. **Strategies** — pure Python logic that decides:
   - enter / not enter,
   - where to place TP / SL,
   - when to exit.
4. **Runner** — orchestrates:
   - loads signals,
   - loads candles window around each signal,
   - runs all strategies,
   - collects results.

Current focus (Phase 2):  
Clean architecture + stable pipeline: *signal → candles → StrategyInput → Strategy → StrategyOutput*.

---

## Project structure

```text
backtester/
├── application/
│   └── runner.py           # BacktestRunner: orchestrates signals → prices → strategies
│
├── domain/
│   ├── models.py           # Signal, Candle, StrategyInput, StrategyOutput dataclasses
│   ├── position.py         # Position model (for portfolio management)
│   ├── portfolio.py        # PortfolioEngine with risk management & runner reset
│   ├── strategy_base.py    # StrategyConfig + abstract Strategy interface
│   ├── rr_strategy.py      # RR strategy (TP/SL on first candle after signal)
│   ├── rrd_strategy.py     # RRD strategy (entry on drawdown, then TP/SL)
│   ├── runner_strategy.py  # Runner strategy (buy & hold from first to last candle)
│   ├── rr_utils.py         # Common RR logic (TP/SL, volatility, etc.)
│   └── trade_features.py   # Trade features: market cap proxy, volume/volatility windows
│
├── infrastructure/
│   ├── signal_loader.py    # CsvSignalLoader → List[Signal]
│   ├── price_loader.py     # CsvPriceLoader + GeckoTerminalPriceLoader (CSV/API)
│   └── reporter.py         # Full reporting: metrics, CSV, HTML, trades table export
│
└── __init__.py


Other dirs:

config/
  backtest_example.yaml     # Global backtest config (window, paths)
  strategies_example.yaml   # Strategy configs (name/type/params)

data/
  candles/
    TESTTOKEN_1m.csv        # Fake candles for TESTTOKEN (for local testing)

signals/
  example_signals.csv       # Test signals for TESTTOKEN

Data contracts
Signal

Normalized signal format used across the project:

@dataclass
class Signal:
    id: str
    contract_address: str
    timestamp: datetime  # UTC
    source: str          # e.g. "madapes"
    narrative: str       # e.g. "memecoin"
    extra: Dict[str, Any] = field(default_factory=dict)


Loaded by CsvSignalLoader from signals/*.csv.

Expected CSV columns:

id

contract_address

timestamp (ISO8601, e.g. 2024-06-01T10:00:00Z)

source

narrative

optional: extra_json (JSON string, parsed into extra)

Candle

Normalized candle format:

@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


Loaded by CsvPriceLoader from:

data/candles/<contract_address>_<timeframe>.csv


Expected columns:

timestamp

open

high

low

close

volume

Strategy API
StrategyInput

What a strategy receives:

@dataclass
class StrategyInput:
    signal: Signal
    candles: List[Candle]
    global_params: Dict[str, Any]

StrategyOutput

What a strategy returns for one signal:

@dataclass
class StrategyOutput:
    entry_time: Optional[datetime]
    entry_price: Optional[float]
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    pnl: float
    reason: Literal["tp", "sl", "timeout", "no_entry", "error"]
    meta: Dict[str, Any] = field(default_factory=dict)
    # meta contains trade features:
    # - Market cap proxy: entry_mcap_proxy, exit_mcap_proxy, mcap_change_pct, total_supply_used
    # - Volume features: vol_sum_5m, vol_sum_15m, vol_sum_60m
    # - Volatility features: range_pct_5m/15m/60m, volat_5m/15m/60m

Base strategy
class Strategy(ABC):
    def __init__(self, config: StrategyConfig):
        self.config = config

    @abstractmethod
    def on_signal(self, data: StrategyInput) -> StrategyOutput:
        ...

Implemented strategies (Phase 2)

RRStrategy (domain/rr_strategy.py)

Enter on first candle after signal.

Exit on TP/SL or end of window.

RRDStrategy (domain/rrd_strategy.py)

Entry on drawdown (waits for price to drop by X% from first candle after signal).
Then applies TP/SL logic.

RunnerStrategy (domain/runner_strategy.py)

Simple buy & hold: enters on first candle, exits on last candle in window.

Runner

BacktestRunner (application/runner.py) does:

SignalLoader → List[Signal]

For each signal:

compute time window:

start = timestamp - before_minutes

end = timestamp + after_minutes

PriceLoader → List[Candle]

build StrategyInput

run all strategies: strategy.on_signal(data)

Collect results into List[Dict] with fields:

signal_id

contract_address

strategy

timestamp

result (StrategyOutput)

Reports & Exports

After backtest, Reporter generates:

1. Strategy-level reports (JSON, CSV, HTML, charts):
   - Metrics: winrate, Sharpe ratio, max drawdown, profit factor, etc.
   - Equity curves, PnL distributions, exit reasons

2. Portfolio-level reports:
   - Final balance, total return, max drawdown
   - Position history with fees and slippage
   - Equity curve over time

3. Trades table (NEW):
   - Unified CSV with all trades: `{strategy}_trades.csv`
   - Includes flattened meta (trade features) for easy filtering/analysis
   - Market cap proxy, volume windows (5m/15m/60m), volatility metrics

All reports are saved to `output/reports/` and `output/charts/`.

Trade Features

Each StrategyOutput.meta now includes:

Market Cap Proxy:
- `entry_mcap_proxy`, `exit_mcap_proxy`, `mcap_change_pct`
- `total_supply_used` (from Signal.extra["total_supply"] or default 1B)

Volume & Volatility (windows before entry, no data leakage):
- `vol_sum_5m`, `vol_sum_15m`, `vol_sum_60m` — sum of volumes
- `range_pct_5m`, `range_pct_15m`, `range_pct_60m` — price range (max-min)/entry_price
- `volat_5m`, `volat_15m`, `volat_60m` — volatility (std of returns)

How to run
1. Create virtualenv & install deps
python -m venv .venv
.\.venv\Scripts\activate   # Windows PowerShell
pip install -r requirements.txt

2. Make sure you have:

signals/example_signals.csv

data/candles/TESTTOKEN_1m.csv

(For now fake candles are generated by a helper script like generate_fake_candles.py.)

3. Run backtest
python main.py


You should see output like:

Backtest finished. Results count: 6
{... first result ...}
{... second result ...}
{... third result ...}


By default it uses:

config/backtest_example.yaml

config/strategies_example.yaml

signals/example_signals.csv

## Reporting Modes

Для больших объемов данных (тысячи сигналов × тысячи стратегий) можно управлять генерацией отчетов через параметр `--report-mode`:

### Режимы отчетности

- **`none`** — сохраняет только `results.json`, никаких отчетов/графиков
- **`summary`** (по умолчанию) — генерирует только агрегированные summary файлы (`strategy_summary.csv`, `portfolio_summary.csv`)
- **`top`** — генерирует отчеты только для top-N стратегий (N задается через `--report-top-n`)
- **`all`** — генерирует все отчеты для всех стратегий (как раньше)

### Примеры использования

**Быстрый массовый прогон без отчетов:**
```bash
python main.py \
  --signals signals/signals_2025-07-01_to_2025-12-14.csv \
  --strategies-config config/strategies_rr_rrd_grid.yaml \
  --report-mode summary
```

**Совсем без репортов (только results.json):**
```bash
python main.py \
  --signals signals/signals_2025-07-01_to_2025-12-14.csv \
  --strategies-config config/strategies_rr_rrd_grid.yaml \
  --report-mode none
```

**Отчёты только для top 30 стратегий (без графиков/HTML):**
```bash
python main.py \
  --signals signals/signals_2025-07-01_to_2025-12-14.csv \
  --strategies-config config/strategies_rr_rrd_grid.yaml \
  --report-mode top \
  --report-top-n 30 \
  --report-metric portfolio_return \
  --no-charts \
  --no-html
```

**Генерация детальных отчетов после Stage B:**
```bash
python tools/generate_reports.py \
  --input output/results.json \
  --strategies output/strategy_selection.csv \
  --with-charts \
  --with-html
```

**Генерация отчетов для top-N из summary:**
```bash
python tools/generate_reports.py \
  --input output/results.json \
  --summary-csv output/reports/strategy_summary.csv \
  --top-n 50 \
  --metric portfolio_return \
  --with-charts \
  --with-html \
  --signals signals/signals_2025-07-01_to_2025-12-14.csv
```

### Параметры CLI

- `--report-mode` — режим генерации отчетов (`none`, `summary`, `top`, `all`, по умолчанию `summary`)
- `--report-top-n` — количество топ стратегий для режима `top` (по умолчанию 50)
- `--report-metric` — метрика для выбора top-N (`portfolio_return`, `strategy_total_pnl`, `sharpe`, по умолчанию `portfolio_return`)
- `--no-charts` — не генерировать PNG графики (по умолчанию True для `none`/`summary`/`top`)
- `--no-html` — не генерировать HTML отчеты (по умолчанию True для `none`/`summary`/`top`)

## Current Status

✅ **Phase 2 Complete:** Clean architecture, stable pipeline  
✅ **Phase 3 Complete:** Full RR/RRD implementation, commission & slippage  
✅ **Phase 4 Complete:** Portfolio layer with risk management, runner reset  
✅ **Trade Features:** Market cap proxy, volume/volatility windows  
✅ **Export:** Unified trades table for analysis  

Next steps (roadmap)

Planned phases:

Phase 5 — Advanced features:

- More data sources (DexScreener / GMGN / Axiom adapters)
- Advanced portfolio strategies
- Multi-strategy portfolio optimization

Phase 6+ — Integration:

- n8n / Telegram pipelines writing signals CSV/DB
- Running batch backtests over large signal datasets
- Real-time monitoring & alerting
