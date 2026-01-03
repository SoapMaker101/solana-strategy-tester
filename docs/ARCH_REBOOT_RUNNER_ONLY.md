# Архитектурный документ-перезагрузка: Runner-only backtest vNext

**Цель:** Зафиксировать новую целевую архитектуру с четким разделением стратегии и портфеля.

**Статус:** Архитектурный документ (не реализация).

---

## 1. Проблема текущей версии

### 1.1 Смешение уровней (strategy vs portfolio)

**Текущая ситуация:**

1. **StrategyOutput содержит поля, которые должны быть в Portfolio:**
   - `pnl` (в процентах) вычисляется на уровне стратегии, но реальный PnL в SOL зависит от размера позиции и комиссий
   - `exit_time`, `exit_price` определяются стратегией, но Portfolio применяет slippage и fees

2. **PortfolioEngine вычисляет size в SOL на основе текущего баланса:**
   - `_position_size()` зависит от `available_balance` (dynamic mode) или `initial_balance_sol` (fixed mode)
   - Это связывает trade blueprint с портфельным состоянием
   - Невозможно применить один набор стратегических трейдов к разным портфельным конфигурациям

3. **Time_stop_minutes — правило стратегии, но логика закрытия смешана:**
   - `RunnerLadderEngine` проверяет `time_stop_minutes` и закрывает остаток по времени
   - Portfolio также может закрывать позиции по reset/prune
   - Нет четкого контракта: кто и когда закрывает позицию

### 1.2 Проблемы тестируемости

**Отсутствие source-of-truth:**

- Невозможно сравнить два портфельных подхода на одном наборе стратегических трейдов
- Тесты проверяют смешанную логику (strategy + portfolio), сложно изолировать баги
- Нет контракта: что является "намерением стратегии" vs "реализацией портфеля"

**Пример проблемы:**

```python
# Текущий код: размер позиции зависит от баланса
desired_size = self._position_size(available_balance)  # зависит от текущего баланса!

# Невозможно протестировать:
# - Один набор blueprints
# - Два разных портфеля (fixed vs dynamic)
# - Сравнить equity curves
```

### 1.3 Реальная цель проекта

**Проект предназначен для:**

1. **Генерации набора стратегических трейдов (blueprints)** без учета портфеля
2. **Применения разных портфельных конфигураций** к одному набору blueprints
3. **Сравнения портфельных метрик** (equity curve, capacity management, profit reset) при одинаковых стратегических трейдах

**Текущая архитектура не позволяет это сделать**, т.к. стратегия и портфель смешаны.

---

## 2. Новый целевой контракт (TO-BE)

### 2.1 Definitions: четкие определения сущностей

#### StrategyTradeBlueprint (Trade Blueprint)

**Определение:** Unit-trade blueprint, генерируемый стратегией без учета портфеля.

```python
@dataclass
class StrategyTradeBlueprint:
    """
    Trade blueprint - результат стратегии без учета баланса/комиссий/SOL.
    """
    # Идентификаторы
    signal_id: str
    strategy_id: str  # название стратегии
    contract_address: str
    
    # Entry
    entry_time: datetime
    entry_price_raw: float  # сырая цена (без slippage)
    entry_mcap_proxy: Optional[float] = None  # marketcap на момент входа
    
    # Partial exits (ladder TP)
    partial_exits: List[PartialExitBlueprint] = field(default_factory=list)
    
    # Final exit
    final_exit: Optional[FinalExitBlueprint] = None
    
    # Агрегированные метрики
    realized_multiple: float  # Σ(fraction_i × xn_i)
    max_xn_reached: Optional[float] = None  # максимальный достигнутый XN
    
    # Причина завершения
    reason: str  # "ladder_tp", "no_entry", "error"


@dataclass
class PartialExitBlueprint:
    """Blueprint для частичного выхода."""
    time: datetime  # когда достигнут уровень
    xn: float  # целевой multiple (2.0, 5.0, 10.0)
    fraction: float  # доля позиции (0.4, 0.4, 0.2)
    raw_price: float  # сырая цена (entry_price_raw * xn)
    marketcap_proxy: Optional[float] = None  # marketcap на момент выхода


@dataclass
class FinalExitBlueprint:
    """Blueprint для финального закрытия (если есть)."""
    time: datetime  # время закрытия
    raw_price: float  # сырая цена (market close)
    reason: str  # "ladder_tp" (все уровни достигнуты) или другие причины
    marketcap_proxy: Optional[float] = None  # marketcap на момент закрытия
```

**Что НЕ содержит:**
- ❌ `size` в SOL
- ❌ `fees` (swap, LP, network)
- ❌ `slippage` (exec_price vs raw_price)
- ❌ `pnl_sol` или `pnl_pct` (зависит от размера позиции)

**Что содержит:**
- ✅ Логику стратегии: когда, на каких уровнях, какая доля
- ✅ Сырые цены (raw_price) — без slippage
- ✅ Временные метки для каждого события

#### PortfolioReplay / PortfolioEngine

**Определение:** Движок, который применяет портфельные правила к blueprints.

**Ответственность:**

1. **Allocation (размер позиции):**
   - Принимает `blueprint` и `portfolio_config`
   - Вычисляет `size` в SOL (fixed/dynamic mode, percent_per_trade, max_exposure)
   - Проверяет capacity constraints (max_open_positions, max_exposure)
   - Может заблокировать blueprint (вернуть None)

2. **Fees & Slippage:**
   - Применяет slippage к `entry_price_raw` → `exec_entry_price`
   - Применяет slippage к `partial_exits[].raw_price` → `exec_price`
   - Вычисляет fees (swap, LP, network) для каждого execution

3. **Executions (fills ledger):**
   - Создает execution для entry (qty_delta = +size, exec_price, fees)
   - Создает execution для каждого partial exit (qty_delta = -exit_size, exec_price, fees, pnl_sol_delta)
   - Создает execution для final exit (если есть)

4. **Events (canonical ledger):**
   - Эмитит `POSITION_OPENED` event
   - Эмитит `POSITION_PARTIAL_EXIT` для каждого partial exit
   - Эмитит `POSITION_CLOSED` event

5. **Portfolio state:**
   - Ведет баланс (cash)
   - Ведет open_positions список
   - Ведет equity_curve
   - Применяет profit reset / capacity prune / capacity reset

**Вход:**
- `List[StrategyTradeBlueprint]` — набор blueprints от стратегии
- `PortfolioConfig` — конфигурация портфеля

**Выход:**
- `PortfolioResult` (positions, events, executions, equity_curve, stats)

#### Canonical outputs

**1. portfolio_positions.csv**
- Source of truth для позиций
- Содержит: position_id, signal_id, entry_time, entry_price, exit_time, exit_price, size_sol, pnl_pct, pnl_sol, status, reason
- Связь: position_id → events (через position_id)

**2. portfolio_events.csv**
- Source of truth для событий портфеля
- Содержит: event_id, event_type, timestamp, position_id, signal_id, strategy, contract_address, reason, meta
- Типы событий: POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED, PORTFOLIO_RESET_TRIGGERED
- Связь: event_id → executions (через event_id)

**3. portfolio_executions.csv**
- Source of truth для fills ledger
- Содержит: execution_id, event_id, position_id, timestamp, qty_delta, raw_price, exec_price, fees_sol, pnl_sol_delta
- Связь: execution_id → event_id → position_id

**4. strategy_trades.csv (optional)**
- Blueprints (до применения портфеля)
- Содержит: signal_id, strategy_id, entry_time, entry_price_raw, partial_exits (JSON), final_exit (JSON), realized_multiple, reason
- Используется для анализа стратегии без портфеля

### 2.2 Source of truth (таблица)

| Данные | Источник | Формат | Использование |
|--------|----------|--------|---------------|
| **Цены рынка (raw_price)** | Market data (candles) | `float` | Вход для стратегии и портфеля |
| **exec_price** | Portfolio (slippage model) | `raw_price ± slippage` | Реальная цена исполнения |
| **PnL в SOL** | Portfolio (executions) | `Σ(pnl_sol_delta) - Σ(fees_sol)` | Source of truth для PnL |
| **Events** | Portfolio (canonical ledger) | `PortfolioEvent` | Каноническая история решений портфеля |
| **Blueprints** | Strategy (RunnerStrategy) | `StrategyTradeBlueprint` | Только "намерение стратегии" |
| **Position size** | Portfolio (allocation) | `SOL` | Зависит от баланса и конфигурации портфеля |

**Формулы:**

```python
# Entry execution
exec_entry_price = entry_price_raw * (1 + slippage_entry)
qty_delta = size  # в SOL
fees_entry = network_fee + (size * swap_fee_pct) + (size * lp_fee_pct)

# Partial exit execution
exec_price = partial_exit.raw_price * (1 - slippage_exit)
exit_size = size * partial_exit.fraction
qty_delta = -exit_size
pnl_sol_delta = exit_size * ((exec_price - exec_entry_price) / exec_entry_price)
fees_exit = network_fee + (notional_returned * swap_fee_pct) + (notional_returned * lp_fee_pct)

# Final exit execution (если есть)
exec_exit_price = final_exit.raw_price * (1 - slippage_exit)
remaining_size = size - sum(partial_exits[].exit_size)
qty_delta = -remaining_size
pnl_sol_delta = remaining_size * ((exec_exit_price - exec_entry_price) / exec_entry_price)
fees_exit = network_fee + (notional_returned * swap_fee_pct) + (notional_returned * lp_fee_pct)

# Итоговый pnl_sol для позиции
total_pnl_sol = sum(executions[].pnl_sol_delta) - sum(executions[].fees_sol)
```

---

## 3. Политики закрытия позиций

### 3.1 Удаление time_stop из стратегии

**Текущее состояние:**

- `RunnerConfig.time_stop_minutes` — параметр стратегии
- `RunnerLadderEngine` проверяет `time_stop_time = entry_time + time_stop_minutes` и закрывает остаток
- Это смешивает стратегию (логика ladder) с портфельным правилом (максимальное время удержания)

**Новое состояние:**

- **Стратегия Runner НЕ закрывает по времени**
- Стратегия определяет только ladder logic (fractions, уровни), но не обязательное закрытие по минутам
- Если все уровни достигнуты → `final_exit` с `reason="ladder_tp"`
- Если уровни не достигнуты → `final_exit = None` (портфель решает, когда закрывать)

**Изменения в RunnerLadderEngine:**

```python
# СТАРО (удалить):
time_stop_time = entry_time + timedelta(minutes=config.time_stop_minutes)
if candle_time >= time_stop_time:
    # закрываем остаток

# НОВО (только ladder):
# Проходим по свечам и закрываем доли на достигнутых уровнях
# Если все уровни достигнуты → final_exit с reason="ladder_tp"
# Если не достигнуты → final_exit = None (портфель решает)
```

### 3.2 Portfolio-level close rules

**Три варианта режима закрытия (выбрать один как default):**

#### Режим A: Close only on ladder completion OR portfolio reset/prune

**Описание:**
- Позиция закрывается только если:
  1. Все уровни ladder достигнуты (blueprint.final_exit.reason="ladder_tp")
  2. Произошел portfolio reset (profit_reset, capacity_reset)
  3. Произошел capacity prune (частичное/полное закрытие плохих позиций)

**Плюсы:**
- ✅ Максимально "верен" стратегии (не вмешивается в логику ladder)
- ✅ Позиции могут быть открыты долго (если уровни не достигнуты)
- ✅ Простая логика (нет дополнительных правил)

**Минусы:**
- ❌ Риск "вечных позиций" (если уровни не достигнуты, позиция остается открытой до конца backtest)
- ❌ Может не соответствовать реальности (на практике нужны safety limits)

**Риски:**
- 🟡 **"Вечные позиции":** Если уровень 10x не достигнут, позиция остается открытой
- 🟡 **Сравнимость:** Разные портфели могут иметь разные "вечные позиции" → метрики несопоставимы

**Влияние на метрики:**
- Equity curve может не закрываться (остаются open positions)
- Max drawdown может быть недооценен (не учитываются unrealized losses)
- Capacity может быть забит "вечными позициями"

#### Режим B: Close on ladder completion OR reset/prune OR portfolio max_hold_minutes (safety)

**Описание:**
- Позиция закрывается если:
  1. Все уровни ladder достигнуты (blueprint.final_exit.reason="ladder_tp")
  2. Произошел portfolio reset (profit_reset, capacity_reset)
  3. Произошел capacity prune
  4. **Истекло max_hold_minutes с момента entry** (safety limit)

**Плюсы:**
- ✅ Безопасность: нет "вечных позиций"
- ✅ Реалистично: соответствует практике (есть максимальное время удержания)
- ✅ Гибкость: max_hold_minutes настраивается в portfolio_config

**Минусы:**
- ❌ Может закрывать позиции до достижения уровней (если max_hold_minutes истек)
- ❌ Может конфликтовать со стратегией (стратегия "думала", что позиция может быть открыта дольше)

**Риски:**
- 🟡 **Конфликт со стратегией:** Если max_hold_minutes=14 дней, а стратегия "ожидала" 21 день для достижения 10x
- 🟡 **Сравнимость:** Нужно использовать одинаковый max_hold_minutes для сравнения портфелей

**Влияние на метрики:**
- Все позиции закрываются (нет "вечных")
- Equity curve корректная (учитываются все закрытия)
- Max drawdown корректный
- Capacity управляем (старые позиции закрываются)

**Реализация:**

```python
# В PortfolioEngine.replay()
for blueprint in blueprints:
    if blueprint.final_exit and blueprint.final_exit.reason == "ladder_tp":
        # Закрываем по ladder completion
        close_position(blueprint, current_time)
    elif portfolio_config.max_hold_minutes:
        max_hold_time = blueprint.entry_time + timedelta(minutes=portfolio_config.max_hold_minutes)
        if current_time >= max_hold_time:
            # Закрываем по max_hold_minutes (forced close)
            close_position(blueprint, current_time, reason="max_hold_minutes")
```

#### Режим C: Close always at end-of-backtest (forced close last candle) + reset/prune

**Описание:**
- Позиция закрывается если:
  1. Все уровни ladder достигнуты (blueprint.final_exit.reason="ladder_tp")
  2. Произошел portfolio reset (profit_reset, capacity_reset)
  3. Произошел capacity prune
  4. **Достигнут конец backtest** (forced close на последней свече)

**Плюсы:**
- ✅ Гарантирует, что все позиции закрыты к концу backtest
- ✅ Нет "вечных позиций" (все закрыты)
- ✅ Простая логика (нет дополнительных параметров)

**Минусы:**
- ❌ Может закрывать позиции "внезапно" в конце (не соответствует реальности)
- ❌ Equity curve может резко измениться в конце (forced close всех открытых позиций)
- ❌ Может не соответствовать стратегии (стратегия "думала", что позиция может быть открыта дольше)

**Риски:**
- 🟡 **Реалистичность:** В реальности позиции не закрываются все сразу в конце периода
- 🟡 **Сравнимость:** Зависит от длины backtest периода (разные периоды → разные forced closes)

**Влияние на метрики:**
- Все позиции закрыты (нет "вечных")
- Equity curve может быть искажена в конце (forced close)
- Max drawdown может быть переоценен (forced close на плохих ценах)

**Реализация:**

```python
# В PortfolioEngine.replay()
end_of_backtest_time = max(b.entry_time for b in blueprints) + timedelta(days=30)  # или из config

for blueprint in blueprints:
    if blueprint.final_exit and blueprint.final_exit.reason == "ladder_tp":
        close_position(blueprint, current_time)
    elif current_time >= end_of_backtest_time:
        # Forced close на последней свече
        close_position(blueprint, current_time, reason="end_of_backtest")
```

### 3.3 Рекомендация default режима

**Рекомендация: Режим B (Close on ladder completion OR reset/prune OR portfolio max_hold_minutes)**

**Обоснование:**

1. **Безопасность:** Нет "вечных позиций", все позиции закрываются
2. **Реалистичность:** Соответствует практике (есть максимальное время удержания)
3. **Гибкость:** max_hold_minutes настраивается в portfolio_config
4. **Сравнимость:** Можно использовать одинаковый max_hold_minutes для сравнения портфелей
5. **Управляемость:** Capacity управляем (старые позиции закрываются)

**Параметры:**

- `portfolio_config.max_hold_minutes: Optional[int] = None`
  - Если `None` → Режим A (close only on ladder/reset/prune)
  - Если `int` → Режим B (close on ladder/reset/prune/max_hold_minutes)

**Пример конфигурации:**

```yaml
portfolio:
  max_hold_minutes: 20160  # 14 дней (как было в стратегии time_stop_minutes)
  # или
  max_hold_minutes: null  # Режим A (без safety limit)
```

---

## 4. Алгоритм replay (псевдокод)

### 4.1 Общая структура

```python
def PortfolioEngine.replay(
    blueprints: List[StrategyTradeBlueprint],
    portfolio_config: PortfolioConfig,
    market_data: PriceLoader  # для получения цен при reset/prune
) -> PortfolioResult:
    """
    Применяет портфельные правила к blueprints.
    """
    # Инициализация состояния
    state = PortfolioState(
        balance=portfolio_config.initial_balance_sol,
        open_positions=[],
        closed_positions=[],
        equity_curve=[],
        ...
    )
    
    events: List[PortfolioEvent] = []
    executions: List[ExecutionRecord] = []
    
    # Создаем timeline событий из blueprints
    timeline = build_timeline(blueprints, portfolio_config)
    
    # Проходим по timeline
    for event_time, event_type, blueprint in timeline:
        if event_type == "ENTRY":
            position = apply_allocation(blueprint, state, portfolio_config)
            if position:
                apply_fees_slippage(position, blueprint, portfolio_config)
                create_entry_execution(position, blueprint, executions)
                create_position_opened_event(position, events)
                state.open_positions.append(position)
        
        elif event_type == "PARTIAL_EXIT":
            position = find_position(blueprint.signal_id, state.open_positions)
            if position:
                apply_partial_exit(position, blueprint, event_time, state, portfolio_config)
                create_partial_exit_execution(position, blueprint, executions)
                create_partial_exit_event(position, blueprint, events)
        
        elif event_type == "FINAL_EXIT":
            position = find_position(blueprint.signal_id, state.open_positions)
            if position:
                apply_final_exit(position, blueprint, event_time, state, portfolio_config)
                create_final_exit_execution(position, blueprint, executions)
                create_position_closed_event(position, blueprint, events)
                state.open_positions.remove(position)
                state.closed_positions.append(position)
        
        elif event_type == "PORTFOLIO_RESET":
            apply_portfolio_reset(state, event_time, portfolio_config, market_data, events, executions)
        
        elif event_type == "CAPACITY_PRUNE":
            apply_capacity_prune(state, event_time, portfolio_config, market_data, events, executions)
        
        # Проверяем max_hold_minutes (если включен)
        if portfolio_config.max_hold_minutes:
            check_and_close_expired_positions(state, event_time, portfolio_config, events, executions, market_data)
        
        # Обновляем equity curve
        update_equity_curve(state, event_time, equity_curve)
    
    # Forced close всех открытых позиций (если Режим C)
    if portfolio_config.force_close_at_end:
        force_close_all_positions(state, end_time, market_data, events, executions)
    
    return PortfolioResult(
        positions=state.closed_positions,
        events=events,
        executions=executions,
        equity_curve=state.equity_curve,
        stats=compute_stats(state, events)
    )
```

### 4.2 Построение timeline

```python
def build_timeline(
    blueprints: List[StrategyTradeBlueprint],
    portfolio_config: PortfolioConfig
) -> List[Tuple[datetime, str, StrategyTradeBlueprint]]:
    """
    Строит timeline событий из blueprints.
    
    События:
    - ENTRY: момент входа (blueprint.entry_time)
    - PARTIAL_EXIT: момент partial exit (blueprint.partial_exits[].time)
    - FINAL_EXIT: момент final exit (blueprint.final_exit.time, если есть)
    """
    timeline = []
    
    for blueprint in blueprints:
        # ENTRY событие
        timeline.append((blueprint.entry_time, "ENTRY", blueprint))
        
        # PARTIAL_EXIT события (сортируем по времени)
        for partial_exit in sorted(blueprint.partial_exits, key=lambda e: e.time):
            timeline.append((partial_exit.time, "PARTIAL_EXIT", blueprint))
        
        # FINAL_EXIT событие (если есть)
        if blueprint.final_exit:
            timeline.append((blueprint.final_exit.time, "FINAL_EXIT", blueprint))
    
    # Сортируем по времени
    timeline.sort(key=lambda x: x[0])
    
    return timeline
```

### 4.3 Allocation (размер позиции)

```python
def apply_allocation(
    blueprint: StrategyTradeBlueprint,
    state: PortfolioState,
    portfolio_config: PortfolioConfig
) -> Optional[Position]:
    """
    Применяет allocation правила и создает Position.
    
    Возвращает None, если blueprint заблокирован capacity constraints.
    """
    # Вычисляем желаемый размер
    if portfolio_config.allocation_mode == "fixed":
        base = portfolio_config.initial_balance_sol
    else:  # dynamic
        base = state.balance
    
    desired_size = base * portfolio_config.percent_per_trade
    
    # Проверяем capacity constraints
    total_open_notional = sum(p.size for p in state.open_positions)
    total_capital = state.balance + total_open_notional
    max_allowed_notional = (
        (portfolio_config.max_exposure * total_capital - total_open_notional) 
        / (1 - portfolio_config.max_exposure)
    )
    
    # Проверяем max_open_positions
    if len(state.open_positions) >= portfolio_config.max_open_positions:
        return None  # Заблокировано capacity
    
    # Ограничиваем размер
    if desired_size > max_allowed_notional:
        return None  # Заблокировано capacity
    
    actual_size = min(desired_size, max_allowed_notional)
    
    # Создаем Position (без fees/slippage пока)
    position = Position(
        position_id=generate_position_id(),
        signal_id=blueprint.signal_id,
        contract_address=blueprint.contract_address,
        entry_time=blueprint.entry_time,
        entry_price=blueprint.entry_price_raw,  # пока raw
        size=actual_size,
        status="open",
        ...
    )
    
    return position
```

### 4.4 Fees & Slippage

```python
def apply_fees_slippage(
    position: Position,
    blueprint: StrategyTradeBlueprint,
    portfolio_config: PortfolioConfig
) -> None:
    """
    Применяет fees и slippage к позиции.
    """
    execution_model = ExecutionModel.from_config(portfolio_config)
    
    # Entry: применяем slippage
    exec_entry_price = execution_model.apply_entry(blueprint.entry_price_raw)
    position.meta["exec_entry_price"] = exec_entry_price
    
    # Вычитаем size из баланса (с network fee)
    network_fee_entry = execution_model.network_fee()
    state.balance -= position.size
    state.balance -= network_fee_entry
    
    # Сохраняем fees для entry (будут в execution)
    position.meta["fees_entry_sol"] = (
        network_fee_entry + 
        (position.size * portfolio_config.fee_model.swap_fee_pct) +
        (position.size * portfolio_config.fee_model.lp_fee_pct)
    )
```

### 4.5 Executions

```python
def create_entry_execution(
    position: Position,
    blueprint: StrategyTradeBlueprint,
    executions: List[ExecutionRecord]
) -> None:
    """
    Создает execution для entry.
    """
    execution = ExecutionRecord(
        execution_id=generate_execution_id(),
        event_id=None,  # будет установлен при создании event
        position_id=position.position_id,
        timestamp=blueprint.entry_time,
        qty_delta=position.size,  # +size
        raw_price=blueprint.entry_price_raw,
        exec_price=position.meta["exec_entry_price"],
        fees_sol=position.meta["fees_entry_sol"],
        pnl_sol_delta=0.0,  # нет PnL при entry
        ...
    )
    executions.append(execution)
```

### 4.6 Events

```python
def create_position_opened_event(
    position: Position,
    events: List[PortfolioEvent]
) -> None:
    """
    Создает POSITION_OPENED event.
    """
    event = PortfolioEvent.create_position_opened(
        timestamp=position.entry_time,
        strategy=position.meta.get("strategy", "unknown"),
        signal_id=position.signal_id,
        contract_address=position.contract_address,
        position_id=position.position_id,
        size=position.size,
        exec_entry_price=position.meta["exec_entry_price"],
        ...
    )
    events.append(event)
    
    # Связываем execution с event
    execution.event_id = event.event_id
```

### 4.7 Profit reset

```python
def apply_portfolio_reset(
    state: PortfolioState,
    reset_time: datetime,
    portfolio_config: PortfolioConfig,
    market_data: PriceLoader,
    events: List[PortfolioEvent],
    executions: List[ExecutionRecord]
) -> None:
    """
    Применяет profit reset: закрывает все открытые позиции.
    """
    if not portfolio_config.profit_reset_enabled:
        return
    
    # Проверяем условие reset
    current_equity = state.balance + sum(p.size for p in state.open_positions)
    threshold = state.cycle_start_equity * portfolio_config.profit_reset_multiple
    
    if current_equity < threshold:
        return  # Reset не срабатывает
    
    # Эмитим PORTFOLIO_RESET_TRIGGERED event
    reset_event = PortfolioEvent.create_portfolio_reset_triggered(
        timestamp=reset_time,
        reason="profit_reset",
        equity_before=current_equity,
        equity_after=state.cycle_start_equity,  # будет обновлен после reset
        ...
    )
    events.append(reset_event)
    
    # Закрываем все открытые позиции
    for position in state.open_positions[:]:  # копируем список
        # Получаем mark price
        raw_exit_price = get_mark_price_for_position(position, reset_time, market_data)
        
        # Применяем forced close
        forced_close_result = forced_close_position(
            position, reset_time, raw_exit_price, portfolio_config, "profit_reset"
        )
        
        # Создаем executions и events
        create_forced_close_execution(position, forced_close_result, executions, reset_event.event_id)
        create_position_closed_event(position, forced_close_result, events, reset_event.event_id, "profit_reset")
        
        # Обновляем состояние
        state.balance += forced_close_result["notional_returned"]
        state.open_positions.remove(position)
        state.closed_positions.append(position)
    
    # Обновляем cycle_start_equity
    state.cycle_start_equity = state.balance
    state.equity_peak_in_cycle = state.balance
    state.portfolio_reset_count += 1
    state.portfolio_reset_profit_count += 1
```

### 4.8 State management

```python
def update_equity_curve(
    state: PortfolioState,
    event_time: datetime,
    equity_curve: List[Dict[str, Any]]
) -> None:
    """
    Обновляет equity curve.
    """
    current_equity = state.balance + sum(p.size for p in state.open_positions)
    
    equity_curve.append({
        "timestamp": event_time,
        "balance": state.balance,
        "equity": current_equity,
        "open_positions_count": len(state.open_positions),
    })
    
    # Обновляем equity_peak_in_cycle
    if current_equity > state.equity_peak_in_cycle:
        state.equity_peak_in_cycle = current_equity
```

---

## 5. Миграционный план

### Этап 0: Заморозить текущую версию

**Действия:**
- Создать git tag: `v2.0.1-legacy` (или текущая версия)
- Задокументировать текущее состояние (этот документ)

**Цель:** Возможность откатиться к рабочей версии.

### Этап 1: Добавить генерацию strategy_trades.csv (blueprints) без изменения портфеля

**Действия:**

1. **Создать `StrategyTradeBlueprint` data model:**
   - Файл: `backtester/domain/strategy_trade_blueprint.py`
   - Классы: `StrategyTradeBlueprint`, `PartialExitBlueprint`, `FinalExitBlueprint`

2. **Изменить `RunnerStrategy.on_signal()` для генерации blueprints:**
   - Файл: `backtester/domain/runner_strategy.py`
   - Метод: `on_signal()` → возвращает `StrategyTradeBlueprint` (или конвертер `StrategyOutput` → `StrategyTradeBlueprint`)
   - **Важно:** Пока НЕ убираем `time_stop_minutes` из стратегии (это будет в Этапе 2)

3. **Добавить экспорт strategy_trades.csv:**
   - Файл: `backtester/infrastructure/reporter.py`
   - Метод: `save_strategy_trades_table()` (новый)
   - Вызывается из `BacktestRunner.run()` после генерации blueprints

4. **Тесты:**
   - `test_strategy_trade_blueprint_generation()` — проверяет генерацию blueprints
   - `test_strategy_trades_csv_export()` — проверяет экспорт CSV

**Результат:**
- Генерируется `strategy_trades.csv` с blueprints
- Портфель НЕ изменен (продолжает работать как раньше)
- Обратная совместимость сохранена

### Этап 2: Сделать replay-режим портфеля по blueprints (feature flag)

**Действия:**

1. **Создать `PortfolioReplay` класс:**
   - Файл: `backtester/domain/portfolio_replay.py` (новый)
   - Методы: `replay()`, `apply_allocation()`, `apply_fees_slippage()`, `create_executions()`, `create_events()`

2. **Добавить feature flag:**
   - Файл: `backtester/domain/portfolio.py`
   - Параметр: `PortfolioConfig.use_replay_mode: bool = False`
   - Метод: `PortfolioEngine.simulate()` → если `use_replay_mode=True`, использует `PortfolioReplay.replay()`

3. **Убрать time_stop_minutes из стратегии (только для replay mode):**
   - Файл: `backtester/domain/runner_ladder.py`
   - Убрать проверку `time_stop_time` в `RunnerLadderEngine.simulate()`
   - Если все уровни достигнуты → `final_exit` с `reason="ladder_tp"`
   - Если не достигнуты → `final_exit = None`

4. **Добавить portfolio-level close rules:**
   - Файл: `backtester/domain/portfolio_config.py`
   - Параметр: `max_hold_minutes: Optional[int] = None`
   - Логика: в `PortfolioReplay.replay()` проверять max_hold_minutes и закрывать позиции

5. **Интегрировать в BacktestRunner:**
   - Файл: `backtester/application/runner.py`
   - Если `portfolio_config.use_replay_mode=True`, собирать blueprints и передавать в `PortfolioEngine.simulate()`

6. **Тесты:**
   - `test_portfolio_replay_basic()` — базовый replay
   - `test_portfolio_replay_capacity_blocking()` — блокировка capacity
   - `test_portfolio_replay_max_hold_minutes()` — закрытие по max_hold_minutes
   - `test_portfolio_replay_profit_reset()` — profit reset
   - `test_portfolio_replay_two_configs_same_blueprints()` — сравнение двух портфелей

**Результат:**
- Replay-режим работает (с feature flag)
- Legacy режим продолжает работать (обратная совместимость)
- Можно сравнить два режима на одних данных

### Этап 3: Удалить legacy путь, если replay стабилен

**Действия:**

1. **Сравнить результаты legacy и replay:**
   - Скрипт: `scripts/compare_legacy_vs_replay.py` (новый)
   - Запустить оба режима на одних данных
   - Сравнить `portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv`
   - Убедиться, что различия ожидаемы (например, из-за time_stop vs max_hold_minutes)

2. **Удалить legacy код:**
   - Убрать `PortfolioConfig.use_replay_mode` (всегда True)
   - Удалить старую логику из `PortfolioEngine.simulate()`
   - Удалить `time_stop_minutes` из `RunnerConfig` (breaking change)

3. **Обновить тесты:**
   - Удалить тесты для legacy режима
   - Обновить тесты для replay режима (теперь по умолчанию)

4. **Обновить документацию:**
   - `docs/ARCHITECTURE.md` — обновить описание архитектуры
   - `docs/PIPELINE_GUIDE.md` — обновить примеры конфигурации
   - `README.md` — обновить описание

**Результат:**
- Legacy код удален
- Replay режим — единственный путь
- Архитектура соответствует этому документу

---

## 6. Тесты: что оставить, что снести, что добавить

### 6.1 MUST KEEP (инварианты)

**Эти тесты проверяют критические инварианты и должны остаться:**

1. **`test_events_executions_linkage()` (или аналогичный)**
   - Проверяет: каждое событие имеет execution (через event_id)
   - Файл: `tests/audit/test_invariants.py` или `tests/domain/test_position_id_and_event_ledger.py`
   - **Важно:** Должен работать и для replay режима

2. **`test_pnl_source_of_truth()` (или аналогичный)**
   - Проверяет: `pnl_sol` в positions = сумма `pnl_sol_delta` из executions - fees
   - Файл: `tests/audit/test_invariants.py` или `tests/portfolio/test_portfolio_*.py`
   - **Важно:** Должен работать и для replay режима

3. **`test_reset_chain()` (или `test_reset_emits_full_event_chain()`)**
   - Проверяет: при reset эмитится PORTFOLIO_RESET_TRIGGERED + N POSITION_CLOSED events
   - Файл: `tests/domain/test_position_id_and_event_ledger.py`
   - **Важно:** Должен работать и для replay режима

4. **`test_monotonic_timestamps()` (или аналогичный)**
   - Проверяет: timestamps в events монотонно возрастают
   - Файл: `tests/audit/test_invariants.py` или новый тест
   - **Важно:** Должен работать и для replay режима

5. **`test_positions_events_consistency()` (или аналогичный)**
   - Проверяет: если позиция закрыта, есть POSITION_CLOSED event
   - Файл: `tests/portfolio/test_portfolio_*.py` или новый тест
   - **Важно:** Должен работать и для replay режима

### 6.2 REMOVE / MOVE

**Тесты, которые станут нерелевантны после развязки:**

1. **Тесты, которые проверяют вычисление size в SOL на уровне стратегии:**
   - Таких тестов нет (size всегда вычисляется в Portfolio)
   - **Действие:** Ничего не делать (тестов нет)

2. **Тесты, которые проверяют применение fees/slippage в стратегии:**
   - Таких тестов нет (fees/slippage всегда в Portfolio)
   - **Действие:** Ничего не делать (тестов нет)

3. **Тесты, которые проверяют time_stop_minutes в стратегии:**
   - Файлы: `tests/domain/test_runner_ladder.py` или аналогичные
   - Тесты: `test_runner_ladder_time_stop_*()`
   - **Действие:** Удалить или переместить в тесты PortfolioReplay (проверять max_hold_minutes)

4. **Тесты, которые проверяют PnL на уровне StrategyOutput:**
   - Если есть тесты, которые сравнивают `StrategyOutput.pnl` с реальным PnL в SOL
   - **Действие:** Удалить (StrategyOutput больше не содержит PnL в SOL)

5. **Тесты, которые проверяют смешанную логику (strategy + portfolio):**
   - Если есть интеграционные тесты, которые проверяют и стратегию, и портфель вместе
   - **Действие:** Разделить на два теста: тест стратегии (blueprints) + тест портфеля (replay)

### 6.3 NEW TESTS

**Новые тесты для replay режима:**

1. **`test_portfolio_replay_same_blueprints_different_configs()`**
   ```python
   def test_portfolio_replay_same_blueprints_different_configs():
       """
       Тест: один набор blueprints + два разных portfolio_config => разные equity curves.
       """
       blueprints = generate_test_blueprints()  # фиксированный набор
       
       config1 = PortfolioConfig(initial_balance_sol=10.0, allocation_mode="fixed")
       config2 = PortfolioConfig(initial_balance_sol=10.0, allocation_mode="dynamic")
       
       result1 = PortfolioReplay.replay(blueprints, config1)
       result2 = PortfolioReplay.replay(blueprints, config2)
       
       # Equity curves должны быть разные
       assert result1.equity_curve != result2.equity_curve
       
       # Но blueprints одинаковые
       assert len(result1.positions) == len(result2.positions)  # одинаковое количество позиций
   ```

2. **`test_portfolio_replay_capacity_blocking()`**
   ```python
   def test_portfolio_replay_capacity_blocking():
       """
       Тест: blueprint существует, но не применяется (нет Position/Events) из-за capacity.
       """
       blueprints = generate_many_blueprints(count=100)
       
       config = PortfolioConfig(
           initial_balance_sol=10.0,
           max_open_positions=5,  # маленький лимит
           max_exposure=0.5
       )
       
       result = PortfolioReplay.replay(blueprints, config)
       
       # Некоторые blueprints заблокированы
       assert len(result.positions) < len(blueprints)
       
       # Проверяем, что заблокированные blueprints не имеют Position/Events
       applied_signal_ids = {p.signal_id for p in result.positions}
       all_signal_ids = {b.signal_id for b in blueprints}
       blocked_signal_ids = all_signal_ids - applied_signal_ids
       
       assert len(blocked_signal_ids) > 0  # есть заблокированные
       
       # Проверяем, что для заблокированных нет events
       event_signal_ids = {e.signal_id for e in result.events if e.event_type == "POSITION_OPENED"}
       assert blocked_signal_ids.isdisjoint(event_signal_ids)
   ```

3. **`test_portfolio_replay_profit_reset()`**
   ```python
   def test_portfolio_replay_profit_reset():
       """
       Тест: profit reset происходит и закрывает все позиции с корректной цепочкой событий.
       """
       blueprints = generate_profitable_blueprints()  # прибыльные blueprints
       
       config = PortfolioConfig(
           initial_balance_sol=10.0,
           profit_reset_enabled=True,
           profit_reset_multiple=1.1  # низкий порог для гарантии reset
       )
       
       result = PortfolioReplay.replay(blueprints, config)
       
       # Должен быть PORTFOLIO_RESET_TRIGGERED event
       reset_events = [e for e in result.events if e.event_type == "PORTFOLIO_RESET_TRIGGERED"]
       assert len(reset_events) > 0
       
       # Все позиции, открытые до reset, должны быть закрыты с reason="profit_reset"
       reset_time = reset_events[0].timestamp
       closed_by_reset = [
           p for p in result.positions
           if p.exit_time <= reset_time and p.meta.get("close_reason") == "profit_reset"
       ]
       assert len(closed_by_reset) > 0
       
       # Проверяем цепочку событий
       for position in closed_by_reset:
           closed_event = next(
               (e for e in result.events 
                if e.event_type == "POSITION_CLOSED" and e.position_id == position.position_id),
               None
           )
           assert closed_event is not None
           assert closed_event.reason == "profit_reset"
   ```

4. **`test_portfolio_replay_max_hold_minutes()`**
   ```python
   def test_portfolio_replay_max_hold_minutes():
       """
       Тест: позиции закрываются по max_hold_minutes, если уровни не достигнуты.
       """
       blueprints = generate_long_holding_blueprints()  # blueprints, которые не достигают всех уровней
       
       config = PortfolioConfig(
           initial_balance_sol=10.0,
           max_hold_minutes=1440  # 1 день
       )
       
       result = PortfolioReplay.replay(blueprints, config)
       
       # Позиции, которые не достигли всех уровней, должны быть закрыты по max_hold_minutes
       closed_by_max_hold = [
           p for p in result.positions
           if p.meta.get("close_reason") == "max_hold_minutes"
       ]
       assert len(closed_by_max_hold) > 0
       
       # Проверяем, что время удержания <= max_hold_minutes
       for position in closed_by_max_hold:
           hold_minutes = (position.exit_time - position.entry_time).total_seconds() / 60
           assert hold_minutes <= config.max_hold_minutes + 1  # допуск на округление
   ```

5. **`test_strategy_trade_blueprint_generation()`**
   ```python
   def test_strategy_trade_blueprint_generation():
       """
       Тест: RunnerStrategy генерирует корректные blueprints.
       """
       strategy = RunnerStrategy(config=runner_config)
       signal = create_test_signal()
       candles = create_test_candles()
       
       blueprint = strategy.on_signal(StrategyInput(signal=signal, candles=candles))
       
       assert isinstance(blueprint, StrategyTradeBlueprint)
       assert blueprint.signal_id == signal.id
       assert blueprint.entry_time is not None
       assert blueprint.entry_price_raw > 0
       assert len(blueprint.partial_exits) > 0
       
       # Проверяем монотонность timestamps
       timestamps = [e.time for e in blueprint.partial_exits]
       assert timestamps == sorted(timestamps)
       
       # Проверяем формулу realized_multiple
       expected_multiple = sum(e.fraction * e.xn for e in blueprint.partial_exits)
       assert abs(blueprint.realized_multiple - expected_multiple) < 1e-6
   ```

---

## 7. Критерии приемки (Definition of Done)

### 7.1 Функциональные требования

1. **Пайплайн Runner-only отрабатывает end-to-end на blueprints:**
   - `BacktestRunner.run()` генерирует `List[StrategyTradeBlueprint]`
   - `PortfolioEngine.replay()` применяет портфельные правила к blueprints
   - Генерируются канонические CSV: `portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv`

2. **Можно прогнать 2 портфеля на одном наборе blueprints и сравнить метрики:**
   - Генерируются blueprints один раз
   - Применяются два разных `PortfolioConfig`
   - Получаются два разных `PortfolioResult`
   - Equity curves различаются (ожидаемо)

3. **Все MUST KEEP тесты проходят:**
   - `test_events_executions_linkage()` ✅
   - `test_pnl_source_of_truth()` ✅
   - `test_reset_chain()` ✅
   - `test_monotonic_timestamps()` ✅
   - `test_positions_events_consistency()` ✅

4. **Экспорты стабильны и читаемы:**
   - CSV файлы имеют стабильную структуру (колонки не меняются между запусками)
   - CSV файлы читаются pandas без ошибок
   - Все обязательные поля присутствуют

### 7.2 Технические требования

1. **Обратная совместимость (до Этапа 3):**
   - Legacy режим продолжает работать (если `use_replay_mode=False`)
   - Существующие тесты проходят (кроме удаленных)

2. **Производительность:**
   - Replay режим не медленнее legacy режима (или приемлемо медленнее, если есть улучшения)

3. **Документация:**
   - Обновлены `docs/ARCHITECTURE.md`, `docs/PIPELINE_GUIDE.md`
   - Добавлены примеры конфигурации для replay режима

### 7.3 Критерии качества

1. **Четкое разделение ответственности:**
   - Стратегия не знает о портфеле (не вычисляет size, fees, slippage)
   - Портфель не знает о логике стратегии (только применяет blueprints)

2. **Тестируемость:**
   - Можно тестировать стратегию отдельно (генерация blueprints)
   - Можно тестировать портфель отдельно (replay blueprints)

3. **Расширяемость:**
   - Легко добавить новую стратегию (генерирует blueprints)
   - Легко добавить новый портфельный режим (новый PortfolioConfig)

---

## 8. TODO Checklist

### Этап 0: Заморозить текущую версию

- [ ] Создать git tag: `v2.0.1-legacy` (или текущая версия)
- [ ] Задокументировать текущее состояние (этот документ создан)

### Этап 1: Добавить генерацию strategy_trades.csv

- [ ] **Создать `StrategyTradeBlueprint` data model**
  - [ ] Файл: `backtester/domain/strategy_trade_blueprint.py`
  - [ ] Классы: `StrategyTradeBlueprint`, `PartialExitBlueprint`, `FinalExitBlueprint`
  - [ ] Тесты: `tests/domain/test_strategy_trade_blueprint.py`

- [ ] **Изменить `RunnerStrategy.on_signal()` для генерации blueprints**
  - [ ] Файл: `backtester/domain/runner_strategy.py`
  - [ ] Метод: `on_signal()` → возвращает `StrategyTradeBlueprint`
  - [ ] Или: конвертер `StrategyOutput` → `StrategyTradeBlueprint`
  - [ ] Тесты: `test_strategy_trade_blueprint_generation()`

- [ ] **Добавить экспорт strategy_trades.csv**
  - [ ] Файл: `backtester/infrastructure/reporter.py`
  - [ ] Метод: `save_strategy_trades_table()` (новый)
  - [ ] Интеграция: вызвать из `BacktestRunner.run()`
  - [ ] Тесты: `test_strategy_trades_csv_export()`

### Этап 2: Сделать replay-режим портфеля (feature flag)

- [ ] **Создать `PortfolioReplay` класс**
  - [ ] Файл: `backtester/domain/portfolio_replay.py` (новый)
  - [ ] Методы: `replay()`, `apply_allocation()`, `apply_fees_slippage()`, `create_executions()`, `create_events()`
  - [ ] Тесты: `tests/domain/test_portfolio_replay.py`

- [ ] **Добавить feature flag**
  - [ ] Файл: `backtester/domain/portfolio.py`
  - [ ] Параметр: `PortfolioConfig.use_replay_mode: bool = False`
  - [ ] Логика: `PortfolioEngine.simulate()` → если `use_replay_mode=True`, использует `PortfolioReplay.replay()`

- [ ] **Убрать time_stop_minutes из стратегии (только для replay mode)**
  - [ ] Файл: `backtester/domain/runner_ladder.py`
  - [ ] Убрать проверку `time_stop_time` в `RunnerLadderEngine.simulate()`
  - [ ] Если все уровни достигнуты → `final_exit` с `reason="ladder_tp"`
  - [ ] Если не достигнуты → `final_exit = None`

- [ ] **Добавить portfolio-level close rules**
  - [ ] Файл: `backtester/domain/portfolio_config.py`
  - [ ] Параметр: `max_hold_minutes: Optional[int] = None`
  - [ ] Логика: в `PortfolioReplay.replay()` проверять max_hold_minutes и закрывать позиции
  - [ ] Тесты: `test_portfolio_replay_max_hold_minutes()`

- [ ] **Интегрировать в BacktestRunner**
  - [ ] Файл: `backtester/application/runner.py`
  - [ ] Если `portfolio_config.use_replay_mode=True`, собирать blueprints и передавать в `PortfolioEngine.simulate()`

- [ ] **Новые тесты для replay режима**
  - [ ] `test_portfolio_replay_same_blueprints_different_configs()`
  - [ ] `test_portfolio_replay_capacity_blocking()`
  - [ ] `test_portfolio_replay_profit_reset()`
  - [ ] `test_portfolio_replay_max_hold_minutes()`

### Этап 3: Удалить legacy путь

- [ ] **Сравнить результаты legacy и replay**
  - [ ] Скрипт: `scripts/compare_legacy_vs_replay.py` (новый)
  - [ ] Запустить оба режима на одних данных
  - [ ] Сравнить CSV файлы
  - [ ] Убедиться, что различия ожидаемы

- [ ] **Удалить legacy код**
  - [ ] Убрать `PortfolioConfig.use_replay_mode` (всегда True)
  - [ ] Удалить старую логику из `PortfolioEngine.simulate()`
  - [ ] Удалить `time_stop_minutes` из `RunnerConfig` (breaking change)

- [ ] **Обновить тесты**
  - [ ] Удалить тесты для legacy режима
  - [ ] Обновить тесты для replay режима (теперь по умолчанию)

- [ ] **Обновить документацию**
  - [ ] `docs/ARCHITECTURE.md` — обновить описание архитектуры
  - [ ] `docs/PIPELINE_GUIDE.md` — обновить примеры конфигурации
  - [ ] `README.md` — обновить описание

### Общие задачи

- [ ] **Обновить MUST KEEP тесты для replay режима**
  - [ ] `test_events_executions_linkage()` — убедиться, что работает для replay
  - [ ] `test_pnl_source_of_truth()` — убедиться, что работает для replay
  - [ ] `test_reset_chain()` — убедиться, что работает для replay
  - [ ] `test_monotonic_timestamps()` — добавить, если нет
  - [ ] `test_positions_events_consistency()` — добавить, если нет

- [ ] **Удалить/переместить тесты (из раздела 6.2)**
  - [ ] Удалить тесты для time_stop_minutes в стратегии (или переместить в PortfolioReplay)
  - [ ] Удалить тесты для PnL на уровне StrategyOutput (если есть)
  - [ ] Разделить интеграционные тесты на тесты стратегии и портфеля

- [ ] **Проверить критерии приемки (раздел 7)**
  - [ ] Пайплайн Runner-only отрабатывает end-to-end ✅
  - [ ] Можно прогнать 2 портфеля на одном наборе blueprints ✅
  - [ ] Все MUST KEEP тесты проходят ✅
  - [ ] Экспорты стабильны и читаемы ✅

---

**Конец документа.**

