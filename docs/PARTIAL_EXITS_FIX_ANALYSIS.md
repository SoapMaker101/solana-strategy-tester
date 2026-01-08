# Анализ проблем с Partial Exits и план исправлений

## TASK 1: Найти место, где ladder "схлопывается" в один финальный выход

### Проблема
При hit 3x нет partial_exit в executions.

### Анализ кода

1. **`_process_runner_partial_exits`** (portfolio.py:1234-1520):
   - ✅ Читает `pos.meta["fractions_exited"]` (dict level->fraction)
   - ✅ Создает `PortfolioEventType.POSITION_PARTIAL_EXIT` события
   - ✅ Сохраняет в `pos.meta["partial_exits"]` с данными для executions

2. **`_process_position_exit`** (portfolio.py:1522-1621):
   - ✅ Вызывает `_process_runner_partial_exits` если `current_time >= pos.exit_time` ИЛИ `any(hit_time <= current_time)`
   - ⚠️ Проблема: если `levels_hit` хранится как строки, парсинг может не работать

3. **`save_portfolio_executions_table`** (reporter.py:1227-1380):
   - ✅ Читает `pos.meta["partial_exits"]` для создания execution строк
   - ⚠️ Проблема: для final_exit используется `pos.size`, но это может быть неправильно если позиция уже частично закрыта

### Вывод
Код есть, но может не срабатывать из-за:
1. Проблем с парсингом `levels_hit` (строки vs datetime)
2. Неправильного `qty_delta` для final_exit (должен быть `remaining_size`, а не `pos.size`)

## TASK 2: Реализовать "fractions от initial size" на уровне Portfolio ledger

### Текущее состояние
- ✅ `original_size` сохраняется в `pos.meta["original_size"]` (portfolio.py:1874)
- ✅ `exit_size = original_size * fraction` (portfolio.py:1310)
- ⚠️ Проблема: `remaining_size_sol` не отслеживается явно (используется `pos.size`)

### Что нужно исправить
1. Явно отслеживать `remaining_size_sol = pos.size` (уменьшается после каждого partial_exit)
2. Для final_exit использовать `remaining_size_sol`, а не `pos.size`
3. Убедиться, что `exit_qty = min(initial_size * fraction, remaining_size_sol)`

## TASK 3: Починить fees accounting

### Текущее состояние
- ✅ Fees накапливаются в `pos.meta["fees_total_sol"]` (portfolio.py:1407-1415, 1495)
- ⚠️ Проблема: `fees_total_sol` может не совпадать с суммой fees по executions

### Что нужно исправить
1. В конце симуляции позиции пересчитать: `fees_total_sol = sum(executions.fees_sol)`
2. Записать это значение в `portfolio_positions.csv`
3. Добавить тест для проверки

## TASK 4: Починить realized_multiple / pnl_pct_total по ledger

### Текущее состояние
- ✅ `realized_multiple` считается из `fractions_exited` (portfolio.py:1514)
- ⚠️ Проблема: нужно считать по executions (proceeds)

### Что нужно исправить
1. Считать proceeds по executions:
   - Для partial exit: `proceeds += abs(qty_delta) * xn`
   - Для final exit: `proceeds += abs(qty_delta) * (exec_price / exec_entry_price)`
2. `realized_multiple = proceeds_total / initial_size_sol`
3. `pnl_sol = initial_size_sol * (realized_multiple - 1) - fees_total_sol`
4. `pnl_pct_total = (realized_multiple - 1) * 100`

## TASK 5: Тесты

### Что нужно добавить
1. `tests/integration/test_runner_ladder_partial_exits.py` - уже создан
2. `tests/portfolio/test_fees_total_is_sum_of_executions.py` - нужно создать


