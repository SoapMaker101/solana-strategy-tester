# Инструкция по исправлению ошибок линтера basedpyright

## Обзор ошибок

Обнаружены следующие проблемы типизации:

1. **`tests/portfolio/test_portfolio_runner_reset.py`**: операции с потенциально `None` значениями
2. **`tests/test_performance.py`**: несоответствие типов при присваивании

---

## Ошибки в `test_portfolio_runner_reset.py`

### Проблема 1: Деление на None (строки 98, 435, 499)

**Ошибка:** `Operator "/" not supported for "None"`

**Причина:** `Position.exit_price` и `Position.entry_price` могут быть `None` (хотя `entry_price` по определению не должен быть `None` для закрытых позиций, линтер видит, что тип `exit_price: Optional[float]`).

**Места:**
- Строка 98: `trigger_position.exit_price / trigger_position.entry_price`
- Строка 435: `position1.exit_price / position1.entry_price`
- Строка 499: `xn_position.exit_price / xn_position.entry_price`

**Решение:** Добавить проверку на `None` перед делением:

```python
# БЫЛО:
multiplying_return = trigger_position.exit_price / trigger_position.entry_price

# ДОЛЖНО БЫТЬ:
assert trigger_position.exit_price is not None, "exit_price не должен быть None для закрытой позиции"
assert trigger_position.entry_price is not None, "entry_price не должен быть None"
multiplying_return = trigger_position.exit_price / trigger_position.entry_price
```

Или использовать более безопасный вариант:

```python
if trigger_position.exit_price is None or trigger_position.entry_price is None:
    raise AssertionError("Цены не должны быть None для закрытой позиции")
multiplying_return = trigger_position.exit_price / trigger_position.entry_price
```

---

### Проблема 2: Сравнение datetime с None (строки 121, 412)

**Ошибка:** `Operator "<=" not supported for types "datetime" and "datetime | None"`

**Причина:** `Position.exit_time` имеет тип `Optional[datetime]`, поэтому прямое сравнение с `datetime` небезопасно.

**Места:**
- Строка 121: `pos.exit_time <= reset_time`
- Строка 412: `position2.exit_time <= reset_time`

**Решение:** Добавить проверку на `None` перед сравнением:

```python
# БЫЛО:
assert pos.exit_time <= reset_time

# ДОЛЖНО БЫТЬ:
assert pos.exit_time is not None, f"Позиция {pos.signal_id} должна иметь exit_time"
assert pos.exit_time <= reset_time
```

Или использовать более лаконичный вариант:

```python
assert pos.exit_time is not None and pos.exit_time <= reset_time, \
    f"Позиция {pos.signal_id} должна быть закрыта не позже reset времени"
```

---

## Ошибка в `test_performance.py`

### Проблема 3: Несоответствие типов (строка 163)

**Ошибка:** `Type "Any | None" is not assignable to declared type "StrategyOutput"`

**Причина:** `result.get("result")` возвращает `Any | None`, а переменная типизирована как `StrategyOutput`.

**Место:** Строка 163

**Решение:** Добавить проверку типа и обработку `None`:

```python
# БЫЛО:
output: StrategyOutput = result.get("result")

# ДОЛЖНО БЫТЬ:
output_raw = result.get("result")
if not isinstance(output_raw, StrategyOutput):
    stats["errors"] += 1
    continue
output: StrategyOutput = output_raw
```

Или более компактно:

```python
output = result.get("result")
if not isinstance(output, StrategyOutput):
    stats["errors"] += 1
    continue
```

---

## Дополнительные замечания

### Предупреждение о pytest (строка 7 в test_portfolio_runner_reset.py)

**Сообщение:** `Import "pytest" could not be resolved`

**Причина:** Модуль `pytest` не установлен в окружении, которое использует линтер.

**Решение:** Это предупреждение (severity: 4), не ошибка. Если тесты запускаются, это можно игнорировать. Или установить `pytest`:

```bash
pip install pytest
```

---

## Резюме исправлений

1. **test_portfolio_runner_reset.py:**
   - Добавить проверки `is not None` перед делением (3 места)
   - Добавить проверки `is not None` перед сравнением datetime (2 места)

2. **test_performance.py:**
   - Добавить проверку типа `isinstance()` перед присваиванием (1 место)

3. **Опционально:**
   - Установить `pytest` для устранения предупреждения об импорте

---

## Рекомендуемый порядок исправления

1. Сначала исправить все операции деления (строки 98, 435, 499)
2. Затем исправить сравнения datetime (строки 121, 412)
3. Исправить присваивание типа в test_performance.py (строка 163)
4. Проверить, что все ошибки исправлены, запустив линтер

---

## Проверка исправлений

После внесения изменений убедитесь, что:

1. Линтер не выдает ошибок типа `reportOptionalOperand` и `reportOperatorIssue`
2. Тесты все еще проходят (логика не нарушена)
3. Проверки на `None` логически корректны (в тестах позиции должны быть закрыты, поэтому `exit_price` и `exit_time` не должны быть `None`)


