# Исправление Runner-XN Reset в PortfolioEngine

**Дата:** 2025-12-17  
**Версия:** После рефакторинга проекта

## Проблема

Runner reset триггерился слишком рано (на этапе открытия сделки), используя будущие exit_price/exit_time из StrategyOutput. Это приводило к тому, что сделки, которые должны были открыться до reset, пропускались.

**Симптомы:**
- `trades_executed` меньше ожидаемого (1 вместо 3 / 2 вместо 3)
- Сделки, которые должны были быть открыты ДО reset и закрыты принудительно, пропускались как `skipped_by_reset`
- `positions` содержит только 1 позицию, хотя должно быть 3
- Тесты падали на проверке `multiplying_return >= runner_reset_multiple` из-за использования исполненных цен (с slippage)

## Решение

### 1. Удалена ранняя проверка reset при открытии сделки

**Удалено:**
- Проверка reset на этапе открытия сделки (использовала будущие exit_price/exit_time)
- Portfolio-level reset на этапе открытия
- Проверка `entry_time <= reset_until` на этапе открытия, которая пропускала сделки

**Результат:** Сделки больше не пропускаются на этапе открытия из-за будущего reset.

### 2. Проверка reset перенесена на момент закрытия позиции

**Реализовано:**
- Reset проверяется **ТОЛЬКО при закрытии позиции** (exit_time), а не при открытии
- Проверка по **raw ценам** (raw_exit_price / raw_entry_price), slippage не влияет на XN
- При срабатывании reset закрываются **ВСЕ остальные открытые позиции** с установкой:
  - `status="closed"`
  - `exit_time=reset_time` (время закрытия триггерной позиции)
  - `meta["closed_by_reset"]=True`
  - PnL = 0 (закрытие по exec_entry_price)

### 3. Разделение RAW и исполненных цен

**Критически важно:** Для целей reset и тестов `Position.entry_price` и `Position.exit_price` должны отражать RAW цены из StrategyOutput, а не исполненные цены после slippage.

**Решение:**
- `Position.entry_price` = `raw_entry_price` (из StrategyOutput)
- `Position.exit_price` = `raw_exit_price` (из StrategyOutput)
- Исполненные цены (с slippage) сохранены в `meta["exec_entry_price"]` и `meta["exec_exit_price"]`
- Все расчеты PnL и баланса используют исполненные цены из meta

**Почему это важно:**
- Reset проверяется по формуле: `position.exit_price / position.entry_price >= runner_reset_multiple`
- Если использовать исполненные цены (с slippage), reset может не сработать при realistic profile
- Например: raw цены 1.0 → 2.0 (x2), но после slippage 1.1 → 1.8 (x1.63), reset не сработает

### 4. Логика закрытия позиций

**В цикле обработки сделок (при открытии новой сделки):**
1. Проверяем, какие позиции должны закрыться (exit_time <= entry_time)
2. Если позиция достигает XN (по raw ценам), триггерим reset:
   - Закрываем все остальные открытые позиции (из `still_open`)
   - Устанавливаем `reset_until = reset_time` для пропуска входов ПОСЛЕ reset
3. Закрываем триггерную позицию нормально (с правильным PnL по исполненным ценам)

**В финальном блоке (после обработки всех входов):**
1. Сортируем оставшиеся открытые позиции по exit_time
2. Закрываем по порядку
3. При закрытии проверяем reset по raw ценам и закрываем остальные позиции при необходимости

### 5. Инварианты сохранены

- ✅ Reset-флаги появляются ТОЛЬКО в `Position.meta`, `StrategyOutput.meta` остается чистым
- ✅ `trades_executed` = количество открытых позиций (len(closed_positions))
- ✅ `trades_skipped_by_reset` = только сделки, которые не были открыты из-за reset-window (entry_time <= reset_until)
- ✅ Экономика портфеля не изменена: все расчеты баланса и PnL используют исполненные цены (с slippage) через meta
- ✅ Reset проверяется по raw ценам, что соответствует требованиям тестов

## Ожидаемое поведение

1. Сделки с `entry_time < момент reset` должны открываться нормально и считаться executed.
2. Когда триггерная позиция закрывается и достигает XN (raw_exit/raw_entry >= runner_reset_multiple):
   - Портфель помечает эту позицию `meta["triggered_reset"]=True`
   - Немедленно закрывает ВСЕ остальные ОТКРЫТЫЕ позиции на reset_time (exit_time триггерной)
   - Устанавливает `meta["closed_by_reset"]=True` для закрытых позиций
   - Устанавливает `reset_until = reset_time`
3. Входы должны пропускаться только если `entry_time <= reset_until` (т.е. после reset до "следующего сигнала").
4. **Важно:** Критерий XN считается по RAW ценам (как в тестах): `raw_exit_price/raw_entry_price`, а не по исполненным (после slippage).

## Измененные файлы

- `backtester/domain/portfolio.py` - основной файл с логикой reset

## Тесты

Исправления должны проходить следующие тесты:
- `tests/portfolio/test_portfolio_runner_reset.py::test_runner_reset_closes_all_positions_on_xn`
- `tests/portfolio/test_portfolio_runner_reset.py::test_runner_reset_with_three_trades_first_triggers_reset`
- `tests/test_reset_policy_is_portfolio_only.py::test_reset_flags_appear_only_in_portfolio_positions`

## Технические детали

### Структура Position после исправления

```python
Position(
    entry_price=raw_entry_price,      # RAW цена для reset проверки
    exit_price=raw_exit_price,        # RAW цена для reset проверки
    pnl_pct=effective_pnl_pct,        # PnL по исполненным ценам
    meta={
        "exec_entry_price": effective_entry_price,  # Исполненная цена (с slippage)
        "exec_exit_price": effective_exit_price,    # Исполненная цена (с slippage)
        "raw_entry_price": raw_entry_price,         # RAW цена (дублирование для удобства)
        "raw_exit_price": raw_exit_price,           # RAW цена (дублирование для удобства)
        # ... другие поля
    }
)
```

### Проверка reset

```python
# Правильно: проверка по raw ценам из Position
multiplying_return = position.exit_price / position.entry_price
if multiplying_return >= config.runner_reset_multiple:
    # Триггерим reset

# Неправильно: проверка по исполненным ценам (НЕ ДЕЛАТЬ!)
# multiplying_return = meta["exec_exit_price"] / meta["exec_entry_price"]
```

### Расчет PnL и баланса

```python
# Всегда используем exec цены для расчета баланса
exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price
exit_pnl_sol = exit_size * exit_pnl_pct
```

## Ограничения

- ❌ НЕ менять бизнес-логику комиссий/проскальзывания
- ❌ НЕ менять ExecutionModel
- ❌ НЕ менять Stage A/B
- ✅ Исправление только в PortfolioEngine (`backtester/domain/portfolio.py`)

