# Research Pipeline (Stage A → Stage B)

## Обзор

> **⚠️ ВАЖНО:** С декабря 2025 проект работает только с RUNNER. RR/RRD признаны неэффективными и исключены из пайплайна. Stage A/B работают только с Runner стратегиями.

Research pipeline состоит из двух этапов:

1. **Stage A** - анализ устойчивости стратегий (window-based analysis)
2. **Stage B** - отбор стратегий по критериям (strategy selection)

**Источник правды:** `portfolio_positions.csv` - единственный источник данных для research pipeline.

## Структура output папки

**ВАЖНО:** Все research артефакты сохраняются в единую папку `output/reports/`.

После запуска `main.py` создается следующая структура:

```
output/
├── reports/                          # ⭐ Единая папка для всех research артефактов
│   ├── portfolio_positions.csv      # ⭐ Источник правды для Stage A/B
│   ├── strategy_summary.csv          # Portfolio-derived summary (только из positions)
│   ├── portfolio_summary.csv         # Агрегированный портфельный summary
│   ├── portfolio_executions.csv     # Executions-level (для дебага, Stage A/B не используют)
│   ├── strategy_stability.csv       # Результат Stage A
│   ├── strategy_selection.csv        # Результат Stage B
│   ├── {strategy}_equity_curve.csv  # Equity curve для каждой стратегии
│   └── {strategy}_portfolio_stats.json  # Статистика для каждой стратегии
└── charts/
    └── ...
```

**Запрещено:** Сохранять research-артефакты в run-specific dirs типа `output/run_.../research`.

## Запуск pipeline

**ВАЖНО:** Все outputs сохраняются в `output/reports/` (единая папка для research артефактов).

### Шаг 1: Запуск бэктеста (main.py)

```bash
# Windows PowerShell
python main.py `
  --signals signals/example_signals.csv `
  --strategies-config config/strategies_example.yaml `
  --backtest-config config/backtest_example.yaml `
  --reports-dir output/reports

# Linux/macOS
python main.py \
  --signals signals/example_signals.csv \
  --strategies-config config/strategies_example.yaml \
  --backtest-config config/backtest_example.yaml \
  --reports-dir output/reports
```

**Результат:** Создается `output/reports/portfolio_positions.csv` и `output/reports/strategy_summary.csv`.

### Шаг 2: Stage A - Анализ устойчивости

```bash
# Windows PowerShell
python -m backtester.research.run_stage_a `
  --reports-dir output/reports `
  --splits 2 3 4 5

# Linux/macOS
python -m backtester.research.run_stage_a \
  --reports-dir output/reports \
  --splits 2 3 4 5
```

**Примечание:** `--splits` опционально. Если не указано, используются дефолтные splits.

**Что делает Stage A:**
- Читает `portfolio_positions.csv` (источник правды)
- Разбивает позиции на временные окна
- Считает метрики устойчивости для каждого окна
- Для Runner стратегий: читает hit rates из `portfolio_positions.csv` (max_xn/hit_x2/hit_x5)
- Генерирует `strategy_stability.csv`

**Результат:** `output/reports/strategy_stability.csv`

### Шаг 3: Stage B - Отбор стратегий

```bash
# Windows PowerShell
python -m backtester.decision.run_stage_b `
  --stability-csv output/reports/strategy_stability.csv `
  --output-csv output/reports/strategy_selection.csv

# Linux/macOS
python -m backtester.decision.run_stage_b \
  --stability-csv output/reports/strategy_stability.csv \
  --output-csv output/reports/strategy_selection.csv
```

**Что делает Stage B:**
- Читает `strategy_stability.csv` (результат Stage A) из `output/reports/`
- Для Runner стратегий: использует hit rates и tail_contribution из `strategy_stability.csv` (которые были рассчитаны из `portfolio_positions.csv`)
- Hit rates: `hit_rate_x2 = mean(hit_x2)`, `hit_rate_x5 = mean(hit_x5)` по стратегии
- Tail contribution: `tail_contribution = pnl_tail / pnl_total` где tail trades: `max_xn_reached >= 5.0`
- Применяет критерии отбора (v1 или custom)
- Генерирует `strategy_selection.csv` с колонкой `passed` (bool) и `failed_reasons` (List[str])

**Результат:** `output/reports/strategy_selection.csv`

## Важные контракты

### portfolio_positions.csv - единственный источник

**Stage A и Stage B работают ТОЛЬКО с `portfolio_positions.csv`:**

- ❌ Не используют executions-level CSV
- ❌ Не используют strategy output напрямую
- ❌ Не используют `StrategyOutput.pnl` (используется только `pnl_sol` из portfolio_positions)

**Обязательные колонки для Stage A/B (Runner-only):**

**ID и времена:**
- `strategy` - название стратегии
- `signal_id` - идентификатор сигнала
- `contract_address` - адрес контракта
- `entry_time`, `exit_time` - времена входа/выхода (ISO)
- `status` - статус позиции ("open" или "closed")

**PnL и комиссии:**
- `pnl_sol` - портфельный PnL в SOL (обязательно!)
- `fees_total_sol` - суммарные комиссии в SOL

**Цены:**
- `exec_entry_price`, `exec_exit_price` - исполненные цены (с slippage)
- `raw_entry_price`, `raw_exit_price` - сырые цены (без slippage)

**Hold:**
- `hold_minutes` - длительность удержания позиции в минутах

**Reset flags:**
- `closed_by_reset` - закрыта ли позиция по reset (bool)
- `triggered_portfolio_reset` - триггернула ли portfolio-level reset (bool)
- `reset_reason` - причина reset ("profit"/"capacity"/"runner"/"manual"/"none")

**Runner hits:**
- `max_xn_reached` - максимальный XN достигнутый (из levels_hit или fallback на цены)
- `hit_x2` - достигнут ли XN >= 2.0 (bool)
- `hit_x5` - достигнут ли XN >= 5.0 (bool)

### Hit rates для Runner стратегий

**Расчет hit rates:**
- Stage A читает `max_xn_reached` и `hit_x2`/`hit_x5` из `portfolio_positions.csv`
- `max_xn_reached` рассчитывается по приоритету:
  1. `Position.meta["levels_hit"]` (Runner truth) - dict вида {"2.0": "...", "7.0": "..."}
  2. Fallback: `raw_exit_price / raw_entry_price` или `exec_exit_price / exec_entry_price`
- Считает `hit_rate_x2 = mean(hit_x2)` по стратегии
- Считает `hit_rate_x5 = mean(hit_x5)` по стратегии
- Записывает в `strategy_stability.csv`
- Stage B использует hit rates из `strategy_stability.csv` для критериев отбора

**Важно:** Hit rates считаются из `max_xn_reached` в `portfolio_positions.csv`, который приоритетно берется из `levels_hit`, а не из цен выхода.

### Reset flags

**Reset flags появляются только на portfolio уровне:**
- `Position.meta` содержит `closed_by_reset`, `triggered_portfolio_reset`, `reset_reason`
- `StrategyOutput.meta` **НЕ содержит** reset flags
- Reset flags записываются в `portfolio_positions.csv` из `Position.meta`

## Примеры команд (PowerShell one-liners)

### Полный pipeline

```powershell
# 1. Запуск бэктеста
python main.py --signals signals/example_signals.csv --strategies-config config/strategies_example.yaml --backtest-config config/backtest_example.yaml

# 2. Stage A
python -m backtester.research.run_stage_a --reports-dir output/reports

# 3. Stage B
python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
```

### Только Stage B (если Stage A уже выполнен)

```powershell
python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
```

## Troubleshooting

### Ошибка: "portfolio_positions.csv not found"

**Причина:** Бэктест не был запущен или файл не был создан.

**Решение:** Запустите `main.py` сначала.

### Ошибка: "hit_rate_x2/x5 is 0" для Runner стратегий

**Причина:** `portfolio_positions.csv` не содержит `max_xn_reached` или `hit_x2`/`hit_x5` колонок, либо `levels_hit` отсутствует в `Position.meta`.

**Решение:** 
1. Убедитесь, что используется последняя версия кода, которая добавляет эти колонки
2. Проверьте что Runner стратегии сохраняют `levels_hit` в `Position.meta`
3. Проверьте что `Reporter.save_portfolio_positions_table()` использует `compute_max_xn_reached()`

### Ошибка: "portfolio_positions.csv not found" в Stage A

**Причина:** Stage A требует `portfolio_positions.csv` в `--reports-dir` (по умолчанию `output/reports/`).

**Решение:** 
1. Запустите `main.py` сначала для генерации `portfolio_positions.csv`
2. Убедитесь что файл находится в `output/reports/portfolio_positions.csv`
3. Если используете другой путь, укажите `--reports-dir` в Stage A

### Ошибка: "strategy_stability.csv not found"

**Причина:** Stage A не был запущен.

**Решение:** Запустите Stage A перед Stage B.

## Quality Gates

Перед мерджем проверьте:

1. ✅ `python -m pytest tests/ -q` → 0 failed
2. ✅ `python -m pytest tests/reports -q` → all pass
3. ✅ `python -m pytest tests/decision -q` → all pass
4. ✅ `python scripts/smoke_research_pipeline.py --run-dir output/reports` → OK

