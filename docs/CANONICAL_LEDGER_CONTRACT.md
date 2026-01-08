# CANONICAL_LEDGER_CONTRACT.md

Спецификация канонического ledger контракта для Runner-only vNext (Blueprints → Replay).

## Сущности

### StrategyTradeBlueprint
**Strategy intent без портфеля и денег.**

Обязательные поля:
- `signal_id: str`
- `strategy_id: str`
- `contract_address: str`
- `entry_time: datetime`
- `entry_price_raw: float`
- `partial_exits: list[PartialExitBlueprint]`
- `final_exit: Optional[FinalExitBlueprint]`
- `realized_multiple: float`
- `max_xn_reached: float`
- `reason: str`

Смысл: описывает "что хотела стратегия" (entry/partial exits/final exit), но не содержит SOL size, комиссий, pnl_sol.

### Position
**Состояние позиции в портфеле.**

Обязательные поля:
- `position_id: str` (uuid4 hex, генерируется автоматически)
- `signal_id: Any`
- `contract_address: str`
- `entry_time: datetime`
- `entry_price: float`
- `size: float` (SOL номинал)
- `status: str` ("open" | "closed")
- `meta: Dict[str, Any]` (всегда существует, никогда не None)

Опциональные поля (для closed):
- `exit_time: Optional[datetime]`
- `exit_price: Optional[float]`
- `pnl_pct: Optional[float]`

Инварианты:
- Position - это identity: один объект живет от entry до финального result
- `meta` всегда существует (никогда не None)
- `position_id` уникальный идентификатор позиции

### PortfolioEvent
**Каноническое событие ledger (v2.0.1).**

Типы событий:
- `POSITION_OPENED`
- `POSITION_PARTIAL_EXIT`
- `POSITION_CLOSED`
- `PORTFOLIO_RESET_TRIGGERED`

Обязательные поля:
- `event_id: str` (uuid4 hex, генерируется автоматически)
- `timestamp: datetime`
- `event_type: PortfolioEventType`
- `strategy: str`
- `signal_id: str`
- `contract_address: str`
- `position_id: str` (для reset событий может быть marker position_id)
- `reason: Optional[str]` (каноническая таксономия)
- `meta: Dict[str, Any]` (execution данные: raw_price, exec_price, execution_type, etc.)

Смысл: бизнес-события портфеля (открытие/закрытие позиций, reset).

### PortfolioExecution
**Концепция исполнения (не отдельный класс).**

Execution данные хранятся в `PortfolioEvent.meta` и экспортируются в `portfolio_executions.csv`.

Обязательные поля (в meta события):
- `execution_type: str` ("entry" | "partial_exit" | "final_exit" | "forced_close")
- `raw_price: float` (цена до slippage)
- `exec_price: float` (цена после slippage)
- `qty_delta: float` (изменение размера, для entry положительное, для exit отрицательное)
- `fees_sol: float` (комиссии, включая network_fee если она учитывается в fees_total_sol позиции)
- `pnl_sol_delta: float` (изменение PnL для этого execution)

Смысл: исполнение (цены, комиссии, slippage) для каждого события торговли.

**Важно:** В `portfolio_executions.csv` поле `fees_sol` включает network_fee (если она учитывается в `fees_total_sol` позиции), чтобы сумма `fees_sol` по всем executions позиции совпадала с `fees_total_sol` в `portfolio_positions.csv`.

## Linkage

### Events ↔ Executions
- Каждое trade-related событие (POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED) имеет execution данные в `meta`
- Execution данные извлекаются из `event.meta` и экспортируются в `portfolio_executions.csv`
- Связь: `execution.event_id` ссылается на `event.event_id`

### Events ↔ Positions
- Каждое событие ссылается на `position_id`
- Порядок событий для одного `position_id`: OPENED → PARTIAL_EXIT* → CLOSED
- Reset события могут ссылаться на marker `position_id`

### Executions ↔ Positions
- Execution ссылается на `position_id` (через event)
- Execution содержит `qty_delta`, который изменяет размер позиции

## Source of Truth

### Executions (в meta events)
- Источник цен (raw_price, exec_price)
- Источник комиссий (fees_sol)
- Источник slippage (raw_price → exec_price)
- Источник PnL delta для каждого execution (pnl_sol_delta)

### Events
- Источник бизнес-событий (когда что произошло)
- Источник причин закрытий (reason)
- Источник timestamp'ов для ordering

### Positions
- Итоговое состояние позиций (size, status, pnl_pct)
- Агрегат по всем executions для позиции
- Source of truth для portfolio-level метрик

## Инварианты

### Monotonic Timestamps
Все события в `portfolio_events` имеют монотонный порядок по `timestamp`.

### Events ↔ Executions Bijection
Для каждого trade-related события (POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED) должно быть одно соответствующее execution (в meta).

### Reset Chain Correctness
При reset:
1. PORTFOLIO_RESET_TRIGGERED событие эмитится ПОСЛЕ закрытий всех позиций
2. Все закрытые позиции имеют POSITION_CLOSED событие с `reason="profit_reset"` или `reason="capacity_prune"`
3. Marker position_id в PORTFOLIO_RESET_TRIGGERED ссылается на реальную позицию

### Position Chain Correctness
Для каждого position_id:
- Ровно одно POSITION_OPENED событие
- Ноль или более POSITION_PARTIAL_EXIT событий
- Ровно одно POSITION_CLOSED событие (для closed позиций)
- Порядок: OPENED → PARTIAL_EXIT* → CLOSED (по timestamp)

### Runner Exits Semantics

**Partial Exits (TP уровни):**
- Создаются при достижении TP уровня (например, 3x, 7x, 15x)
- `event_type = "position_partial_exit"`
- `reason = "ladder_tp"`
- В `portfolio_executions.csv`: `event_type = "partial_exit"`, `reason = "ladder_tp"`

**Final Exit (time_stop остаток):**
- Создается при закрытии остатка позиции по time_stop
- В событиях: `POSITION_PARTIAL_EXIT` с `meta["is_remainder"] = True` и `reason = "time_stop"`
- В `portfolio_executions.csv`: `event_type = "final_exit"`, `reason = "time_stop"` (или из `pos.meta["close_reason"]`)
- **Важно:** Remainder exit НЕ дублируется как `partial_exit` execution, только как `final_exit`

**Правило:**
- `partial_exit` execution → только TP-уровни (reason="ladder_tp")
- `final_exit` execution → ровно 1 на позицию (reason="time_stop" для remainder, или "ladder_tp" для полного закрытия на уровнях)
- time_stop остаток → всегда отражается как `final_exit` в executions, но как `POSITION_PARTIAL_EXIT` с `reason="time_stop"` в events

**Пример:**
- TP partial exit на 3x (20%) → `POSITION_PARTIAL_EXIT` (reason="ladder_tp") + `partial_exit` execution
- time_stop остаток (80%) → `POSITION_PARTIAL_EXIT` (reason="time_stop", is_remainder=True) + `final_exit` execution (НЕ `partial_exit`)

