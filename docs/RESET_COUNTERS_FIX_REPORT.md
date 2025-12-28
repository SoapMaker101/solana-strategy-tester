# Fix: Разделение счетчиков runner и portfolio reset

## Root Cause

**Проблема:** В `apply_portfolio_reset()` (строка 179) `state.reset_count += 1` увеличивался для ВСЕХ типов reset'ов (и RUNNER_XN, и EQUITY_THRESHOLD). 

**Последствие:** В диагностическом тесте `test_debug_portfolio_reset_marker.py` срабатывали 2 runner reset'а (обе позиции достигли XN >= 2.0), что приводило к `reset_count=2`, но при этом НЕ было позиций с `closed_by_reset=True` или `triggered_portfolio_reset=True`, потому что runner reset не устанавливает эти флаги на триггерной позиции.

**Инвариант нарушался:** `reset_count > 0 => есть closed_by_reset` был корректным только для portfolio-level reset, но не для runner reset.

## Решение

### 1. Добавлены раздельные поля в PortfolioStats

```python
# Runner reset tracking (по XN)
runner_reset_count: int = 0
last_runner_reset_time: Optional[datetime] = None

# Portfolio-level reset tracking (по equity threshold)
portfolio_reset_count: int = 0
last_portfolio_reset_time: Optional[datetime] = None

# Обратная совместимость через @property
@property
def reset_count(self) -> int:
    """Обратная совместимость: reset_count = portfolio_reset_count"""
    return self.portfolio_reset_count

@property
def last_reset_time(self) -> Optional[datetime]:
    """Обратная совместимость: last_reset_time = last_portfolio_reset_time"""
    return self.last_portfolio_reset_time
```

### 2. Обновлены поля в PortfolioState

Аналогично добавлены раздельные счетчики в `PortfolioState` (в `portfolio_reset.py`).

### 3. Логика инкрементации в apply_portfolio_reset()

```python
if context.reason == ResetReason.RUNNER_XN:
    # Runner reset по XN
    state.runner_reset_count += 1
    if state.last_runner_reset_time is None or context.reset_time > state.last_runner_reset_time:
        state.last_runner_reset_time = context.reset_time
    state.reset_until = context.reset_time
elif context.reason == ResetReason.EQUITY_THRESHOLD:
    # Portfolio-level reset по equity
    state.portfolio_reset_count += 1
    if state.last_portfolio_reset_time is None or context.reset_time > state.last_portfolio_reset_time:
        state.last_portfolio_reset_time = context.reset_time
    # Portfolio reset обновляет cycle tracking
    state.cycle_start_equity = state.balance
    state.equity_peak_in_cycle = state.cycle_start_equity
```

**Важно:** `cycle_start_equity` и `equity_peak_in_cycle` обновляются ТОЛЬКО при portfolio-level reset, а не при runner reset.

### 4. Исправлен тест test_debug_portfolio_reset_marker.py

**Вариант A (выбран):** Отключен runner reset в тесте (`runner_reset_enabled=False`), чтобы тест проверял именно portfolio-level reset, а не runner reset.

**Обновлены проверки:**
```python
# Было:
if result.stats.reset_count > 0:
    assert len(reset_positions) > 0

# Стало:
if result.stats.portfolio_reset_count > 0:
    assert len(reset_positions) > 0
    assert len(marker_positions) > 0
```

## Инварианты

### Runner Reset (RUNNER_XN)
- ✅ `runner_reset_count > 0` НЕ требует `closed_by_reset` позиций
- ✅ Триггерная позиция имеет только `triggered_reset=True` (без `closed_by_reset`)
- ✅ Остальные позиции force-close получают `closed_by_reset=True`

### Portfolio Reset (EQUITY_THRESHOLD)
- ✅ `portfolio_reset_count > 0` => существует хотя бы одна позиция с:
  - `meta["closed_by_reset"]=True`
  - `meta["triggered_portfolio_reset"]=True` (на marker позиции)
- ✅ Marker позиция всегда помечается обоими флагами

## Обратная совместимость

- ✅ `reset_count` (property) → `portfolio_reset_count`
- ✅ `last_reset_time` (property) → `last_portfolio_reset_time`
- ✅ Все существующие тесты продолжают работать через property

## Изменённые файлы

1. `backtester/domain/portfolio.py` - PortfolioStats с новыми полями и properties
2. `backtester/domain/portfolio_reset.py` - PortfolioState с новыми полями, обновлена логика инкрементации
3. `tests/portfolio/test_debug_portfolio_reset_marker.py` - отключен runner reset, обновлены проверки

## Commit Message

```
refactor: split runner vs portfolio reset counters and fix debug test semantics

- Add separate counters: runner_reset_count and portfolio_reset_count
- Add separate timestamps: last_runner_reset_time and last_portfolio_reset_time
- Keep reset_count and last_reset_time as properties for backward compatibility
- Update apply_portfolio_reset() to increment correct counter based on ResetReason
- Fix test_debug_portfolio_reset_marker: disable runner reset to test portfolio reset only
- Fix invariant: portfolio_reset_count > 0 => exists position with closed_by_reset=True

Root cause: reset_count was incremented for both runner and portfolio resets,
but the invariant "reset_count > 0 => closed_by_reset exists" only applies to
portfolio-level resets. Runner resets don't set closed_by_reset on trigger position.
```












