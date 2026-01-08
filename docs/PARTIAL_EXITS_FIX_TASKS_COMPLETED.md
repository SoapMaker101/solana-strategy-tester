# Исправления Partial Exits (3 падающих теста)

## Выполненные задачи

### TASK A: Вернуть BC для RunnerStrategy.reason ✅

**Проблема:** `test_runner_strategy_basic` ожидает `reason="tp"`, но получает `reason="timeout"`.

**Причина:** В `RunnerLadderEngine.simulate()` логика была изменена так, что `reason="ladder_tp"` только если позиция закрыта полностью (`total_fraction_exited >= 1.0`). Но для обратной совместимости нужно, чтобы `reason="ladder_tp"` если достигнут хотя бы один уровень.

**Исправление:**
- Изменена логика в `backtester/domain/runner_ladder.py`:
  - Если `has_levels_hit = True` → `reason = "ladder_tp"` (независимо от `total_fraction_exited`)
  - Если позиция закрыта полностью → `exit_time = время последнего уровня`
  - Если позиция закрыта частично → `exit_time = time_stop` (определяется ниже)

**Файлы:**
- `backtester/domain/runner_ladder.py`: исправлена логика определения reason

### TASK B: Правильный reason для POSITION_CLOSED при time_stop ✅

**Проблема:** `test_runner_ladder_partial_exit_with_time_stop` ожидает `POSITION_CLOSED.reason="time_stop"`, но получает `"ladder_tp"`.

**Причина:** В `_process_position_exit` использовался `ladder_reason` из meta, но не проверялся `time_stop_triggered`.

**Исправление:**
- Изменена логика в `backtester/domain/portfolio.py`:
  - Если `pos.meta.get("time_stop_triggered", False) == True` → `close_reason = "time_stop"`
  - Иначе если `pos.meta.get("close_reason")` → используем его
  - Иначе fallback на `ladder_reason`

**Файлы:**
- `backtester/domain/portfolio.py`: исправлена логика определения reason для POSITION_CLOSED

### TASK C: fees_total_sol как сумма fees_sol из executions ledger ✅

**Проблема:** `test_fees_total_equals_sum_of_executions` ожидает, что `fees_total_sol` в `portfolio_positions.csv` равен сумме `fees_sol` из `portfolio_executions.csv`, но они не совпадают.

**Причина:** 
1. Для `final_exit` использовался `fees_total` (который включает все fees), а не fees только для final_exit
2. `fees_total_sol` не пересчитывался из executions перед экспортом

**Исправление:**
- В `backtester/infrastructure/reporter.py`:
  1. Добавлен сбор `position_executions_fees` для каждой позиции
  2. Для `final_exit` используется fees из `remainder_exit` в `partial_exits` (если есть), иначе `fees_total` для обычных позиций
  3. После создания всех executions для позиции пересчитывается `fees_total_sol = sum(position_executions_fees)`
  4. Обновляется `pos.meta["fees_total_sol"]` перед экспортом

**Файлы:**
- `backtester/infrastructure/reporter.py`: добавлен пересчет fees_total_sol из executions

### TASK D (optional): Улучшить сообщение при PermissionError ✅

**Исправление:**
- Добавлена обработка `PermissionError` для всех `df.to_csv()` вызовов
- Сообщение: "Файл открыт в Excel или заблокирован. Закройте его и повторите."

**Файлы:**
- `backtester/infrastructure/reporter.py`: добавлена обработка PermissionError

## Измененные файлы

1. **`backtester/domain/runner_ladder.py`**:
   - Исправлена логика определения `reason` (TASK A)

2. **`backtester/domain/portfolio.py`**:
   - Исправлена логика определения `reason` для POSITION_CLOSED (TASK B)

3. **`backtester/infrastructure/reporter.py`**:
   - Добавлен пересчет `fees_total_sol` из executions (TASK C)
   - Добавлена обработка PermissionError (TASK D)

## Проверка

Запустить тесты:
```bash
python -m pytest tests/domain/test_runner_strategy.py::test_runner_strategy_basic -q
python -m pytest tests/integration/test_runner_ladder_partial_exits.py -q
python -m pytest tests/portfolio/test_fees_total_is_sum_of_executions.py -q
python -m pytest tests/ -q
```

## Важные замечания

1. **Обратная совместимость:** Все изменения обратно совместимы, существующие тесты не должны сломаться.

2. **Source of truth:** 
   - `fees_total_sol` теперь пересчитывается из executions перед экспортом (один источник истины)
   - `reason` для POSITION_CLOSED теперь определяется из факта (`time_stop_triggered`), а не из `ladder_reason`

3. **Логика reason:**
   - `RunnerStrategy.reason` = "tp" если достигнут хотя бы один уровень (для обратной совместимости)
   - `POSITION_CLOSED.reason` = "time_stop" если `time_stop_triggered=True`, иначе "ladder_tp"


