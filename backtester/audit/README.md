# Audit Module

Global Audit: Pricing, PnL, Exit Reasons, Policy Decisions (Runner-only)

> 📖 **Полное руководство по использованию:** [USAGE.md](USAGE.md)

## Overview

Модуль аудита для системной проверки корректности:
- Расчётов цены (entry/exit, TP/SL уровни)
- Расчётов PnL (формула, единицы, комиссии/слиппедж)
- Причин закрытия (reason consistency)
- Политик ресетов (reset/prune events)
- Инвариантов и "красных флагов"

## Usage

### CLI Commands

#### Запуск аудита на прогоне

```bash
python -m backtester.cli.audit_run --run-dir output/reports
```

#### Детальный разбор одной позиции

```bash
python -m backtester.cli.audit_trade \
  --run-dir output/reports \
  --position-id <position_id>
```

Или по signal_id:

```bash
python -m backtester.cli.audit_trade \
  --run-dir output/reports \
  --signal-id <signal_id> \
  --strategy Runner_Baseline \
  --contract-address <contract>
```

### Programmatic Usage

```python
from pathlib import Path
from backtester.audit import run_audit, replay_position

# Запуск аудита
report = run_audit(
    run_dir=Path("output/reports"),
    output_dir=Path("output/reports/audit"),
    verbose=True,
)

# Детальный разбор позиции
replay = replay_position(
    run_dir=Path("output/reports"),
    position_id="pos_123",
)
```

## Output Files

Аудит создаёт следующие файлы в `run_dir/audit/`:

- `audit_anomalies.csv` — список всех аномалий
- `audit_summary.md` — человеческий отчёт
- `audit_metrics.csv` — агрегированные метрики

## Anomaly Types

- `PNL_CAP_OR_MAGIC` — магическое значение PnL (например, 920%)
- `TP_REASON_BUT_NEGATIVE_PNL` — reason=tp, но pnl < 0
- `SL_REASON_BUT_POSITIVE_PNL` — reason=sl, но pnl > 0
- `ENTRY_PRICE_INVALID` — entry_price <= 0 или NaN
- `EXIT_PRICE_INVALID` — exit_price <= 0 или NaN
- `TIME_ORDER_INVALID` — entry_time > exit_time
- `MISSING_EVENTS_CHAIN` — нет цепочки событий для позиции
- `RESET_WITHOUT_EVENTS` — reset без соответствующих событий
- И другие...

## Invariants

Модуль проверяет следующие инварианты:

1. **PnL формула**: `pnl_pct = (exit_price - entry_price) / entry_price`
2. **Reason consistency**: reason=tp требует pnl >= 0, reason=sl требует pnl <= 0
3. **Magic values**: запрет значений типа 920%
4. **Time ordering**: entry_time <= exit_time
5. **Events chain**: наличие событий для каждой позиции
6. **Policy consistency**: reset/prune должны иметь соответствующие события

## Tests

```bash
python -m pytest tests/audit/ -v
```

