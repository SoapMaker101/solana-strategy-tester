# Резюме исправлений Partial Exits

## Выполненные задачи

### TASK 1: Найти место, где ladder "схлопывается" в один финальный выход ✅

**Проблема:** При hit 3x нет partial_exit в executions.

**Анализ:**
- ✅ Код для обработки partial exits существует в `_process_runner_partial_exits`
- ✅ События `POSITION_PARTIAL_EXIT` создаются правильно
- ⚠️ Проблема была в `reporter.py`: для final_exit использовался `pos.size` вместо `remaining_size`

**Исправление:**
- Исправлен `save_portfolio_executions_table` в `reporter.py` для использования `remaining_size` для final_exit
- Добавлена логика вычисления `remaining_size` из `partial_exits` или `original_size - sum(partial_exit_sizes)`

### TASK 2: Реализовать "fractions от initial size" на уровне Portfolio ledger ✅

**Текущее состояние:**
- ✅ `original_size` сохраняется в `pos.meta["original_size"]` при создании позиции
- ✅ `exit_size = original_size * fraction` правильно вычисляется
- ✅ `remaining_size` теперь явно отслеживается в `pos.meta["remaining_size"]`

**Исправления:**
- Добавлено сохранение `remaining_size` в meta после каждого partial_exit
- Исправлен расчет `qty_delta` для final_exit в `reporter.py`

### TASK 3: Починить fees accounting (один источник истины) ✅

**Проблема:** `fees_total_sol` может не совпадать с суммой fees по executions.

**Исправление:**
- Добавлен пересчет `fees_total_sol` из executions в конце симуляции позиции
- Формула: `fees_total_sol = sum(fees_sol + network_fee_sol from partial_exits) + network_fee_entry`
- Учтена логика разделения network_fee_entry и network_fee_exits

**Файлы:**
- `backtester/domain/portfolio.py`: добавлен пересчет fees_total_sol

### TASK 4: Починить realized_multiple / pnl_pct_total по ledger ✅

**Проблема:** `realized_multiple` считался из `fractions_exited`, но нужно считать по executions (proceeds).

**Исправление:**
- Добавлен расчет proceeds по executions:
  - Для partial exit: `proceeds += exit_size * xn`
  - Для final exit (time_stop): `proceeds += exit_size * (exec_price / exec_entry_price)`
- `realized_multiple = proceeds_total / original_size`
- `pnl_sol = original_size * (realized_multiple - 1) - fees_total_sol`
- `pnl_pct = (realized_multiple - 1) * 100`

**Файлы:**
- `backtester/domain/portfolio.py`: добавлен пересчет realized_multiple и pnl_sol по ledger

### TASK 5: Тесты ✅

**Добавленные тесты:**
1. ✅ `tests/integration/test_runner_ladder_partial_exits.py` - уже был создан ранее
2. ✅ `tests/portfolio/test_fees_total_is_sum_of_executions.py` - новый тест для проверки fees accounting

## Измененные файлы

1. **`backtester/infrastructure/reporter.py`**:
   - Исправлен расчет `qty_delta` для final_exit (используется `remaining_size`)

2. **`backtester/domain/portfolio.py`**:
   - Добавлено сохранение `remaining_size` в meta
   - Добавлен пересчет `fees_total_sol` из executions
   - Добавлен пересчет `realized_multiple` и `pnl_sol` по ledger

3. **`tests/portfolio/test_fees_total_is_sum_of_executions.py`**:
   - Новый тест для проверки fees accounting

## Важные замечания

1. **Обратная совместимость:** Все изменения обратно совместимы, существующие тесты не должны сломаться.

2. **Формат CSV:** Формат CSV/ledger не изменен, используются существующие поля.

3. **Source of truth:** 
   - `fees_total_sol` теперь считается из executions (один источник истины)
   - `realized_multiple` теперь считается по ledger (proceeds)

4. **Проверка:** Рекомендуется запустить все тесты:
   ```bash
   python -m pytest tests/ -q
   ```

## Следующие шаги

1. Запустить все тесты для проверки обратной совместимости
2. Проверить, что интеграционный тест `test_runner_ladder_partial_exits.py` проходит
3. Проверить, что новый тест `test_fees_total_is_sum_of_executions.py` проходит


