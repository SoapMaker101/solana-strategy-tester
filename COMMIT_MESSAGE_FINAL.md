# 🚀 Финальный коммит: Trade Features + Export + Tests

**Дата:** 2025-12-14  
**Версия:** Phase 4+ (Trade Features + Trades Table Export + Reset Policy Tests)

---

## 📦 Что включено в этот коммит

### ✨ Новые функции

1. **Trade Features** — добавлены дополнительные фичи сделки:
   - Market cap proxy (entry/exit mcap, mcap_change_pct)
   - Volume windows (5m/15m/60m) — сумма объёмов до входа
   - Volatility windows (5m/15m/60m) — волатильность до входа
   - Все фичи доступны в StrategyOutput.meta для RR/RRD/Runner стратегий

2. **Trades Table Export** — единая CSV таблица всех сделок:
   - Автоматический экспорт после бэктеста
   - Расплющенный meta для удобного анализа
   - Сохраняется как `{strategy}_trades.csv` в `output/reports/`

3. **Reset Policy Tests** — защитные тесты:
   - Гарантируют, что reset-флаги устанавливаются только PortfolioEngine
   - Стратегии не должны устанавливать reset-флаги

### 📝 Обновления документации

- Обновлен CHANGELOG.md с полным описанием всех изменений
- Обновлен README.md с информацией о новых функциях
- Обновлен TECHNICAL_REPORT.md
- Обновлен PROJECT_ANALYSIS.md

### 🧪 Новые тесты

- `tests/test_trade_features.py` — 10 тестов для trade features
- `tests/test_reporter_trades_table.py` — 5 тестов для trades table export
- `tests/test_reset_policy_is_portfolio_only.py` — 4 теста для reset policy

---

## 📋 Полное сообщение коммита

```
feat: add trade features, trades table export, and reset policy tests

Major features:
- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta for analysis
- Reset policy tests: enforce portfolio-only reset flags

Trade Features:
- Added backtester/domain/trade_features.py module
- Market cap proxy: entry_mcap_proxy, exit_mcap_proxy, mcap_change_pct
- Volume features: vol_sum_5m/15m/60m (windows before entry, no leakage)
- Volatility features: range_pct_5m/15m/60m, volat_5m/15m/60m
- Integrated into RR, RRD, Runner strategies

Trades Table Export:
- Added Reporter.save_trades_table() method
- Auto-export after backtest: {strategy}_trades.csv
- Flattens meta: scalars as-is, nested dicts/lists as JSON strings
- Filters only valid trades (entry_time != None, reason != no_entry/error)

Reset Policy Tests:
- Added test_reset_policy_is_portfolio_only.py
- Ensures strategies never set triggered_reset/closed_by_reset in meta
- Integration test verifies flags appear only in Position.meta after PortfolioEngine

Documentation:
- Updated CHANGELOG.md (2025-12-14)
- Updated README.md with new features
- Updated TECHNICAL_REPORT.md
- Updated PROJECT_ANALYSIS.md

Tests:
- test_trade_features.py: 10 tests
- test_reporter_trades_table.py: 5 tests  
- test_reset_policy_is_portfolio_only.py: 4 tests
- All 68 tests passing

Files changed:
- New: backtester/domain/trade_features.py
- New: tests/test_trade_features.py
- New: tests/test_reporter_trades_table.py
- New: tests/test_reset_policy_is_portfolio_only.py
- Modified: backtester/domain/rr_strategy.py
- Modified: backtester/domain/rrd_strategy.py
- Modified: backtester/domain/runner_strategy.py
- Modified: backtester/infrastructure/reporter.py
- Modified: main.py
- Modified: docs/CHANGELOG.md
- Modified: README.md
- Modified: docs/TECHNICAL_REPORT.md
- Modified: docs/PROJECT_ANALYSIS.md
```

---

## 🎯 Краткое сообщение коммита (для GitHub)

```
feat: add trade features, trades table export, and reset policy tests

- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta
- Reset policy tests: enforce portfolio-only reset flags
- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)
- 19 new tests, all 68 tests passing
```
