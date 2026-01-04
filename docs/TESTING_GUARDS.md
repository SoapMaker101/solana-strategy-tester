# TESTING_GUARDS.md

Какие тесты защищают какой кусок контракта.

## Структура тестов

### tests/audit/
Проверяют инварианты и linkage после генерации данных.

#### test_p1_executions.py
**Защищает**: Events ↔ Executions linkage

Тесты:
- `test_trade_event_without_execution` → проверяет, что каждое trade event имеет execution
- `test_execution_without_trade_event` → проверяет, что каждый execution имеет событие
- `test_execution_time_before_event` → проверяет, что execution timestamp >= event timestamp
- `test_execution_price_out_of_range` → проверяет разумность цен execution

**Нарушение контракта**: 
- `TRADE_EVENT_WITHOUT_EXECUTION` → событие без execution данных в meta
- `EXECUTION_WITHOUT_TRADE_EVENT` → execution без соответствующего события
- `EXECUTION_TIME_BEFORE_EVENT` → execution timestamp раньше события

#### test_invariants.py
**Защищает**: Монотонность timestamp, цепочки событий, формула PnL, consistency reason/PnL

Тесты:
- `test_tz_aware_ordering` → проверяет монотонность timestamp
- `test_invariant_checker_detects_time_order_invalid` → нарушение порядка времени
- `test_invariant_checker_detects_missing_events` → отсутствие событий в цепочке
- `test_pnl_formula_long_basic` → формула PnL корректна
- `test_tp_reason_requires_non_negative_pnl` → reason=tp требует неотрицательный PnL
- `test_sl_reason_requires_negative_pnl` → reason=sl требует отрицательный PnL

**Нарушение контракта**:
- `TIME_ORDER_INVALID` → нарушение монотонности timestamp или порядка событий внутри position_id
- `MISSING_EVENTS_CHAIN` → отсутствует событие в цепочке position_id (нет OPENED или CLOSED)
- `TP_REASON_BUT_NEGATIVE_PNL` → reason=tp при отрицательном PnL
- `ENTRY_PRICE_INVALID` → entry_price <= 0

#### test_p1_checks.py
**Защищает**: P1 критические проверки (linkage, reset chain)

**Нарушение контракта**: P1 аномалии (критические)

### tests/infrastructure/
Проверяют экспорт и схемы CSV.

#### test_reporter_exports_events_csv.py
**Защищает**: Схему portfolio_events.csv

Проверяет:
- Колонки присутствуют и в правильном порядке
- Типы данных корректны
- JSON поля валидны

**Нарушение контракта**: Отсутствие обязательной колонки, неправильный тип данных

#### test_reporter_strategy_trades_export.py
**Защищает**: Схему strategy_trades.csv

Проверяет:
- Колонки присутствуют
- `final_exit_json` пустая строка когда final_exit=None
- JSON поля валидны

**Нарушение контракта**: `final_exit_json` не пустая строка для None, неправильный формат JSON

#### test_reporter_dual_tables.py
**Защищает**: Консистентность между portfolio_positions.csv и portfolio_executions.csv

Проверяет:
- Количество executions соответствует позициям
- Суммы execution данных совпадают с positions данными

**Нарушение контракта**: Несоответствие данных между positions и executions

### tests/portfolio/
Проверяют бизнес-логику портфеля.

#### test_portfolio_replay.py
**Защищает**: Бизнес-логику PortfolioReplay

Тесты:
- `test_replay_two_configs_same_blueprints_different_equity` → разные конфиги дают разные результаты
- `test_replay_capacity_blocking_skips_positions` → capacity blocking работает
- `test_replay_profit_reset_emits_chain` → reset chain корректна
- `test_replay_max_hold_closes_positions` → max_hold_minutes работает

**Нарушение контракта**: Нарушение бизнес-логики replay (capacity, reset, max_hold)

### tests/domain/
Проверяют доменные модели.

#### test_position_id_and_event_ledger.py
**Защищает**: Position identity и event ledger консистентность

**Нарушение контракта**: Нарушение identity позиций или event ledger

## Таблица: Падение теста → Нарушение контракта

| Тест падает | Нарушение контракта | Раздел контракта |
|------------|---------------------|------------------|
| `test_trade_event_without_execution` | Событие без execution данных в meta | Events ↔ Executions linkage |
| `test_execution_without_trade_event` | Execution без соответствующего события | Events ↔ Executions bijection |
| `test_execution_time_before_event` | Execution timestamp раньше события | REPLAY_EVENT_ORDERING (монотонность) |
| `test_invariant_checker_detects_time_order_invalid` | Нарушение порядка времени (entry_time > exit_time или события не по порядку) | REPLAY_EVENT_ORDERING |
| `test_invariant_checker_detects_missing_events` | Отсутствует событие в цепочке position_id | CANONICAL_LEDGER_CONTRACT (position chain correctness) |
| `test_tp_reason_requires_non_negative_pnl` | reason=tp при отрицательном PnL | CANONICAL_LEDGER_CONTRACT (reason consistency) |
| `test_sl_reason_requires_negative_pnl` | reason=sl при неотрицательном PnL | CANONICAL_LEDGER_CONTRACT (reason consistency) |
| `test_reporter_exports_events_csv` | Отсутствует колонка или неправильный тип | REPORTING_SCHEMA (portfolio_events.csv) |
| `test_reporter_strategy_trades_export` | final_exit_json не пустая строка для None | REPORTING_SCHEMA (strategy_trades.csv JSON правила) |
| `test_reporter_dual_tables` | Несоответствие данных между positions и executions | REPORTING_SCHEMA (консистентность) |
| `test_replay_profit_reset_emits_chain` | Reset chain неправильная (события не в том порядке) | REPLAY_EVENT_ORDERING (reset chain) |
| `test_replay_capacity_blocking_skips_positions` | Capacity blocking не работает | PortfolioReplay бизнес-логика |

## Как читать падения

1. **Смотрим имя теста** → определяем раздел контракта
2. **Смотрим assert/проверку** → определяем конкретное нарушение
3. **Смотрим AnomalyType** (для audit тестов) → определяем тип нарушения
4. **Читаем соответствующую секцию контракта**:
   - `CANONICAL_LEDGER_CONTRACT.md` → для linkage, source of truth, инварианты
   - `REPLAY_EVENT_ORDERING.md` → для порядка событий, timestamp
   - `REPORTING_SCHEMA.md` → для схемы CSV, JSON полей
5. **Исправляем нарушение** → код должен соответствовать контракту

## Примеры

### Пример 1: Тест падает `test_execution_time_before_event`
```
AssertionError: EXECUTION_TIME_BEFORE_EVENT detected
```

**Анализ**:
- Тест: `tests/audit/test_p1_executions.py::test_execution_time_before_event`
- Нарушение: Execution timestamp раньше события
- Контракт: `REPLAY_EVENT_ORDERING.md` → "Монотонный Timestamp" + Events ↔ Executions linkage
- Исправление: Убедиться, что execution timestamp >= event timestamp

### Пример 2: Тест падает `test_invariant_checker_detects_missing_events`
```
AssertionError: MISSING_EVENTS_CHAIN detected for position_id=pos1
```

**Анализ**:
- Тест: `tests/audit/test_invariants.py::test_invariant_checker_detects_missing_events`
- Нарушение: Отсутствует событие в цепочке position_id
- Контракт: `CANONICAL_LEDGER_CONTRACT.md` → "Position Chain Correctness"
- Исправление: Убедиться, что для каждого position_id есть OPENED и CLOSED события

### Пример 3: Тест падает `test_reporter_strategy_trades_export`
```
AssertionError: final_exit_json should be empty string for None, got "null"
```

**Анализ**:
- Тест: `tests/infrastructure/test_reporter_strategy_trades_export.py`
- Нарушение: final_exit_json не пустая строка для None
- Контракт: `REPORTING_SCHEMA.md` → "strategy_trades.csv" → "final_exit_json пустая строка если final_exit=None"
- Исправление: Убедиться, что `StrategyTradeBlueprint.to_row()` возвращает `""` для final_exit_json когда final_exit=None

