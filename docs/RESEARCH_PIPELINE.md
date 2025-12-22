# Research Pipeline (Stage A → Stage B)

## Обзор

Research pipeline состоит из двух этапов:

1. **Stage A** - анализ устойчивости стратегий (window-based analysis)
2. **Stage B** - отбор стратегий по критериям (strategy selection)

**Источник правды:** `portfolio_positions.csv` - единственный источник данных для research pipeline.

## Структура output папки

После запуска `main.py` создается следующая структура:

```
output/
├── reports/
│   ├── portfolio_positions.csv      # ⭐ Источник правды для Stage A/B
│   ├── strategy_summary.csv         # Portfolio-derived summary
│   ├── portfolio_summary.csv        # Агрегированный портфельный summary
│   ├── {strategy}_equity_curve.csv  # Equity curve для каждой стратегии
│   ├── {strategy}_portfolio_stats.json  # Статистика для каждой стратегии
│   └── ...
└── charts/
    └── ...
```

## Запуск pipeline

### Шаг 1: Запуск бэктеста (main.py)

```bash
# Windows PowerShell
python main.py `
  --signals signals/example_signals.csv `
  --strategies-config config/strategies_example.yaml `
  --backtest-config config/backtest_example.yaml `
  --json-output output/results.json

# Linux/macOS
python main.py \
  --signals signals/example_signals.csv \
  --strategies-config config/strategies_example.yaml \
  --backtest-config config/backtest_example.yaml \
  --json-output output/results.json
```

**Результат:** Создается `output/reports/portfolio_positions.csv` и другие файлы.

### Шаг 2: Stage A - Анализ устойчивости

```bash
# Windows PowerShell
python -m backtester.research.run_stage_a `
  --reports-dir output/reports `
  --output-csv output/reports/strategy_stability.csv

# Linux/macOS
python -m backtester.research.run_stage_a \
  --reports-dir output/reports \
  --output-csv output/reports/strategy_stability.csv
```

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
- Читает `strategy_stability.csv` (результат Stage A)
- Для Runner стратегий: использует hit rates из `strategy_stability.csv` (которые были рассчитаны из `portfolio_positions.csv`)
- Применяет критерии отбора (v1 или custom)
- Генерирует `strategy_selection.csv` с колонкой `passed` (bool)

**Результат:** `output/reports/strategy_selection.csv`

## Важные контракты

### portfolio_positions.csv - единственный источник

**Stage A и Stage B работают ТОЛЬКО с `portfolio_positions.csv`:**

- ❌ Не используют executions-level CSV
- ❌ Не используют strategy output напрямую
- ❌ Не используют `StrategyOutput.pnl` (используется только `pnl_sol` из portfolio_positions)

**Обязательные колонки для Stage A/B:**
- `strategy`, `signal_id`, `contract_address`
- `entry_time`, `exit_time`, `status`
- `pnl_sol`, `fees_total_sol` (в SOL!)
- `max_xn`, `hit_x2`, `hit_x5` (для Runner hit rates)
- `closed_by_reset`, `triggered_portfolio_reset`, `reset_reason` (для reset analysis)

### Hit rates для Runner стратегий

**Расчет hit rates:**
- Stage A читает `max_xn` из `portfolio_positions.csv`
- Считает `hit_rate_x2 = count(hit_x2=True) / total_positions`
- Считает `hit_rate_x5 = count(hit_x5=True) / total_positions`
- Записывает в `strategy_stability.csv`
- Stage B использует hit rates из `strategy_stability.csv` для критериев отбора

**Важно:** Hit rates считаются из `max_xn` в `portfolio_positions.csv`, а не из `StrategyOutput.meta` или `levels_hit`.

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

**Причина:** `portfolio_positions.csv` не содержит `max_xn` или `hit_x2`/`hit_x5` колонок.

**Решение:** Убедитесь, что используется последняя версия кода, которая добавляет эти колонки.

### Ошибка: "strategy_stability.csv not found"

**Причина:** Stage A не был запущен.

**Решение:** Запустите Stage A перед Stage B.

## Quality Gates

Перед мерджем проверьте:

1. ✅ `python -m pytest tests/ -q` → 0 failed
2. ✅ `python -m pytest tests/reports -q` → all pass
3. ✅ `python -m pytest tests/decision -q` → all pass
4. ✅ `python scripts/smoke_research_pipeline.py --run-dir output/reports` → OK

