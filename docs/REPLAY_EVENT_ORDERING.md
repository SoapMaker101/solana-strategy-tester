# REPLAY_EVENT_ORDERING.md

Правила порядка событий и timestamp'ов для PortfolioReplay.

## Общие правила

### Монотонный Timestamp
Все события в `portfolio_events` должны быть монотонны по `timestamp` (неубывающая последовательность).

### Tie-Breaker для одинаковых Timestamp
При одинаковом `timestamp` порядок событий определяется порядком добавления в список (FIFO - first in, first out).

**Важно**: В реализации replay события добавляются в порядке обработки blueprints и логики портфеля, что гарантирует детерминированный порядок.

## Порядок событий внутри position_id

Для одного `position_id` события должны идти в строгом порядке:

```
POSITION_OPENED → POSITION_PARTIAL_EXIT* → POSITION_CLOSED
```

Где `POSITION_PARTIAL_EXIT*` означает ноль или более partial exit событий.

### Пример корректной цепочки:
1. `POSITION_OPENED` (timestamp=T1)
2. `POSITION_PARTIAL_EXIT` (timestamp=T2, T2 >= T1)
3. `POSITION_PARTIAL_EXIT` (timestamp=T3, T3 >= T2)
4. `POSITION_CLOSED` (timestamp=T4, T4 >= T3)

### Недопустимые случаи:
- `POSITION_CLOSED` до `POSITION_OPENED`
- `POSITION_PARTIAL_EXIT` до `POSITION_OPENED`
- `POSITION_CLOSED` между `POSITION_PARTIAL_EXIT` событиями (для одной позиции)
- Два `POSITION_OPENED` для одного `position_id`
- Два `POSITION_CLOSED` для одного `position_id`

## Порядок событий при Reset

При срабатывании profit reset или capacity reset:

### Порядок событий:
1. Сначала создаются `POSITION_CLOSED` события для всех закрываемых позиций (timestamp=T_reset)
2. Затем создается `PORTFOLIO_RESET_TRIGGERED` событие (timestamp=T_reset)

**Аргумент**: Все закрытые позиции должны иметь свои `POSITION_CLOSED` события до эмита `PORTFOLIO_RESET_TRIGGERED`, чтобы цепочка событий для каждой позиции была полной.

### Пример reset chain:
```
T_reset: POSITION_CLOSED (position_id=pos1, reason="profit_reset")
T_reset: POSITION_CLOSED (position_id=pos2, reason="profit_reset")
T_reset: POSITION_CLOSED (position_id=pos3, reason="profit_reset")
T_reset: PORTFOLIO_RESET_TRIGGERED (reason="profit_reset", marker_position_id=pos1)
```

Все события имеют одинаковый timestamp (T_reset), порядок определяется порядком добавления.

## Порядок событий между разными position_id

События разных `position_id` могут пересекаться по времени. Порядок определяется глобальным монотонным timestamp.

### Пример:
```
T1: POSITION_OPENED (position_id=pos1)
T2: POSITION_OPENED (position_id=pos2)
T3: POSITION_PARTIAL_EXIT (position_id=pos1)
T4: POSITION_CLOSED (position_id=pos2)
T5: POSITION_CLOSED (position_id=pos1)
```

Это корректно, если T1 <= T2 <= T3 <= T4 <= T5.

## Специальные случаи

### Max Hold Minutes Close
При закрытии позиции по `max_hold_minutes`:
- Создается `POSITION_CLOSED` событие с `reason="max_hold_minutes"`
- Timestamp = entry_time + max_hold_minutes

### Forced Close при Reset
При forced close во время reset:
- Создается `POSITION_CLOSED` событие с `reason="profit_reset"` или `reason="capacity_prune"`
- Timestamp = reset_time
- `meta.execution_type = "forced_close"`

### Partial Exit
При partial exit:
- Создается `POSITION_PARTIAL_EXIT` событие
- Timestamp = timestamp из `PartialExitBlueprint`
- `reason="ladder_tp"` (всегда)
- `meta` содержит: level_xn, fraction, raw_price, exec_price, pnl_pct_contrib, pnl_sol_contrib

## Валидация

Инварианты проверяются в:
- `tests/audit/test_invariants.py` → `check_time_ordering`, `MISSING_EVENTS_CHAIN`
- `tests/audit/test_p1_executions.py` → linkage проверки

Если тесты падают:
- `TIME_ORDER_INVALID` → нарушение монотонности timestamp или порядка событий внутри position_id
- `MISSING_EVENTS_CHAIN` → отсутствует событие в цепочке position_id
- `EXECUTION_TIME_BEFORE_EVENT` → execution timestamp раньше соответствующего события

