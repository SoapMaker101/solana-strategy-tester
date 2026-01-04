# REPORTING_SCHEMA.md

Схемы CSV файлов для отчетности (v2.0.1).

## portfolio_events.csv

**Сгенерирован**: Reporter (из `PortfolioResult.stats.portfolio_events`)  
**Источник данных**: PortfolioReplay или legacy PortfolioEngine

### Колонки (порядок):
1. `event_id` (str, обязательное) - UUID события
2. `timestamp` (str, обязательное) - ISO8601 timestamp
3. `event_type` (str, обязательное) - "position_opened" | "position_partial_exit" | "position_closed" | "portfolio_reset_triggered"
4. `strategy` (str, обязательное) - название стратегии
5. `signal_id` (str, обязательное) - идентификатор сигнала
6. `contract_address` (str, обязательное) - адрес контракта
7. `position_id` (str, обязательное) - идентификатор позиции (для reset может быть marker)
8. `reason` (str, опциональное) - каноническая причина (ladder_tp, stop_loss, profit_reset, etc.)
9. `meta_json` (str, обязательное) - JSON строка с метаданными (execution данные, etc.)

### JSON поля в meta_json:
- `execution_type`: "entry" | "partial_exit" | "final_exit" | "forced_close"
- `raw_price`: float (цена до slippage)
- `exec_price`: float (цена после slippage)
- `level_xn`: float (для partial_exit)
- `fraction`: float (для partial_exit)
- `pnl_pct_contrib`: float (для partial_exit)
- `pnl_sol_contrib`: float (для partial_exit)
- `pnl_pct`: float (для closed)
- `pnl_sol`: float (для closed)

## portfolio_executions.csv

**Сгенерирован**: Reporter (из `Position` объектов, извлекает execution данные)  
**Источник данных**: PortfolioReplay или legacy PortfolioEngine (из positions meta и events meta)

### Колонки (порядок):
1. `position_id` (str, обязательное) - идентификатор позиции
2. `signal_id` (str, обязательное) - идентификатор сигнала
3. `strategy` (str, обязательное) - название стратегии
4. `event_time` (str, обязательное) - ISO8601 timestamp
5. `event_type` (str, обязательное) - "POSITION_OPENED" | "POSITION_PARTIAL_EXIT" | "POSITION_CLOSED"
6. `event_id` (str, опциональное) - ссылка на PortfolioEvent.event_id
7. `qty_delta` (float, обязательное) - изменение размера (положительное для entry, отрицательное для exit)
8. `raw_price` (float, обязательное) - цена до slippage
9. `exec_price` (float, обязательное) - цена после slippage
10. `fees_sol` (float, обязательное) - комиссии в SOL
11. `pnl_sol_delta` (float, обязательное) - изменение PnL в SOL для этого execution
12. `reason` (str, опциональное) - каноническая причина
13. `xn` (float, опциональное) - target multiple (для ladder exits)
14. `fraction` (float, опциональное) - доля выхода (для ladder exits)

### Правила:
- Одна строка = один execution
- Для каждой позиции: entry execution + N partial exit executions + 1 final exit execution
- `qty_delta` для entry = `size` позиции (положительное)
- `qty_delta` для exit = отрицательное значение (exit_size)
- `pnl_sol_delta` для entry = 0.0
- `pnl_sol_delta` для exit = реализованный PnL для этой части

## portfolio_positions.csv

**Сгенерирован**: Reporter (из `Position` объектов)  
**Источник данных**: PortfolioReplay или legacy PortfolioEngine

### Колонки (порядок, основные):
1. `position_id` (str, обязательное)
2. `strategy` (str, обязательное)
3. `signal_id` (str, обязательное)
4. `contract_address` (str, обязательное)
5. `entry_time` (str, обязательное) - ISO8601
6. `exit_time` (str, опциональное) - ISO8601 (для closed)
7. `status` (str, обязательное) - "open" | "closed"
8. `size` (float, обязательное) - размер в SOL
9. `pnl_sol` (float, обязательное) - общий PnL в SOL
10. `pnl_pct_total` (float, обязательное) - общий PnL в процентах
11. `realized_multiple` (float, обязательное) - реализованный multiple
12. `reason` (str, обязательное) - каноническая причина закрытия
13. `fees_total_sol` (float, обязательное) - общие комиссии
14. `exec_entry_price` (float, обязательное) - цена входа (после slippage)
15. `exec_exit_price` (float, опциональное) - цена выхода (после slippage, для closed)
16. `raw_entry_price` (float, обязательное) - сырая цена входа
17. `raw_exit_price` (float, опциональное) - сырая цена выхода (для closed)
18. `closed_by_reset` (bool, обязательное) - закрыта ли по reset
19. `triggered_portfolio_reset` (bool, обязательное) - триггернула ли reset
20. `reset_reason` (str, опциональное) - причина reset (если применимо)
21. `hold_minutes` (float, обязательное) - время удержания в минутах
22. `max_xn_reached` (float, обязательное) - максимальный XN достигнут
23. `hit_x2` (bool, обязательное) - достигнут ли 2x
24. `hit_x5` (bool, обязательное) - достигнут ли 5x
25. `realized_total_pnl_sol` (float, обязательное) - реализованный total PnL
26. `realized_tail_pnl_sol` (float, обязательное) - реализованный tail PnL

### Правила:
- Одна строка = одна позиция (positions-level агрегат)
- Для open позиций: `exit_time`, `exec_exit_price`, `raw_exit_price` = None/пусто
- `pnl_sol` и `pnl_pct_total` для open позиций = unrealized PnL
- `fees_total_sol` = сумма комиссий по всем executions для позиции

## strategy_trades.csv

**Сгенерирован**: Reporter (из `StrategyTradeBlueprint` объектов)  
**Источник данных**: RunnerStrategy (blueprints)

### Колонки (порядок):
1. `signal_id` (str, обязательное)
2. `strategy_id` (str, обязательное)
3. `contract_address` (str, обязательное)
4. `entry_time` (str, обязательное) - ISO8601
5. `entry_price_raw` (float, обязательное) - сырая цена входа
6. `entry_mcap_proxy` (float, опциональное) - proxy для market cap
7. `partial_exits_json` (str, обязательное) - JSON строка с массивом PartialExitBlueprint
8. `final_exit_json` (str, обязательное) - **пустая строка если final_exit=None, иначе JSON объект**
9. `realized_multiple` (float, обязательное) - реализованный multiple
10. `max_xn_reached` (float, обязательное) - максимальный XN достигнут
11. `reason` (str, обязательное) - причина (no_entry, ladder_tp, stop_loss, etc.)

### JSON поля:

#### partial_exits_json
Массив объектов:
```json
[
  {"timestamp": "2025-01-01T12:00:00Z", "xn": 2.0, "fraction": 0.4},
  {"timestamp": "2025-01-01T13:00:00Z", "xn": 5.0, "fraction": 0.3}
]
```
Всегда отсортирован по timestamp.

#### final_exit_json
Если `final_exit` существует:
```json
{"timestamp": "2025-01-01T14:00:00Z", "reason": "stop_loss"}
```

Если `final_exit` = None:
- **Пустая строка `""`** (НЕ `"null"`, НЕ `"{}"`, НЕ `null`)

### Правила:
- `final_exit_json` пустая строка (`""`) когда `final_exit=None`
- `partial_exits_json` всегда валидный JSON (пустой массив `[]` если нет partial exits)
- Все timestamp в ISO8601 формате

## Кто генерит что

### PortfolioReplay / PortfolioEngine
- Генерит `PortfolioEvent` объекты → попадают в `PortfolioResult.stats.portfolio_events`
- Генерит `Position` объекты → попадают в `PortfolioResult.positions`
- Execution данные хранятся в `event.meta` и `position.meta`

### Reporter
- Экспортирует `portfolio_events.csv` из `stats.portfolio_events`
- Экспортирует `portfolio_executions.csv` из `positions` (извлекает execution данные из meta)
- Экспортирует `portfolio_positions.csv` из `positions`
- Экспортирует `strategy_trades.csv` из `StrategyTradeBlueprint` списка

## Валидация схемы

Тесты проверяют:
- `tests/infrastructure/test_reporter_exports_events_csv.py` → schema portfolio_events.csv
- `tests/infrastructure/test_reporter_strategy_trades_export.py` → schema strategy_trades.csv
- `tests/infrastructure/test_reporter_dual_tables.py` → consistency между positions и executions

Если тесты падают:
- Отсутствует обязательная колонка → нарушение схемы
- Неправильный тип данных → нарушение схемы
- `final_exit_json` не пустая строка для None → нарушение правила JSON полей

