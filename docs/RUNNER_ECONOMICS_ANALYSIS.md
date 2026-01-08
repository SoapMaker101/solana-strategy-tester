# Анализ экономики Runner (Partial / Final Exit)

**Дата:** 2024-12-XX  
**Дата обновления:** 2024-12-XX  
**Статус:** Анализ + Решение принято и реализовано  
**Цель:** Понять текущую механику partial/final exits и выявить проблемы

**Обновление (C + reporter fix):**
- `portfolio-derived strategy_summary` считает `fees_total_sol` только из `positions-level` (сумма `fees_total_sol` по всем позициям стратегии)
- `executions.fees_sol` — это распределение `fees_total_sol` по execution-строкам для проверки и дебага, и сумма должна сходиться
- Никаких пересчётов через executions или helper методы в strategy_summary

---

## 1️⃣ Анализ текущего состояния

### 1.1 Где создаются partial_exit и final_exit

#### Место создания: `backtester/domain/portfolio.py`

**Метод:** `_process_runner_partial_exits()` (строки 1234-1591)

**Логика:**

1. **Partial exits (TP уровни):**
   - Создаются в цикле по `levels_hit` (строки 1295-1430)
   - Для каждого достигнутого уровня:
     - Вычисляется `exit_size = original_size * fraction`
     - Ограничивается `exit_size = min(exit_size, pos.size)` (защита от превышения)
     - Эмитится `POSITION_PARTIAL_EXIT` event (строка 1360)
     - Сохраняется в `pos.meta["partial_exits"]` (строки 1385-1407)
     - `pos.size` уменьшается на `exit_size`
   - **Reason:** `"ladder_tp"` (строка 1378)

2. **Final exit (time_stop остаток):**
   - Создается после обработки всех partial exits (строки 1432-1513)
   - Условие: `pos.size > 1e-9 and pos.exit_time is not None and current_time >= pos.exit_time`
   - **Проблема:** Эмитится как `POSITION_PARTIAL_EXIT` (строка 1478), а не `POSITION_CLOSED`
   - Сохраняется в `pos.meta["partial_exits"]` с флагом `"is_remainder": True` (строка 1471)
   - **Reason в meta:** `"time_stop"` (строка 1497)
   - **Reason в event:** `"ladder_tp"` (hardcoded в `create_position_partial_exit`, строка 133 в `portfolio_events.py`)

3. **POSITION_CLOSED:**
   - Эмитится в `_process_position_exit()` (строки 1654-1697)
   - Условие: `pos.size <= 1e-9` (позиция полностью закрыта)
   - **Reason:** Определяется из `pos.meta["time_stop_triggered"]` или `pos.meta["close_reason"]` (строки 1660-1670)

### 1.2 Проблемы текущей реализации

#### ❌ Проблема 1: time_stop остаток эмитится как PARTIAL_EXIT

**Где:** `portfolio.py:1478`

```python
event = PortfolioEvent.create_position_partial_exit(
    timestamp=pos.exit_time or current_time,
    ...
    meta={
        ...
        "reason": "time_stop",  # В meta reason="time_stop"
        ...
    },
)
```

**Проблема:**
- Остаток по time_stop эмитится как `POSITION_PARTIAL_EXIT`, хотя это финальный выход
- В `portfolio_events.py:133` hardcoded `reason="ladder_tp"` для всех `POSITION_PARTIAL_EXIT`
- В meta есть `"reason": "time_stop"`, но это не используется в основном поле `event.reason`

**Последствия:**
- В `portfolio_events.csv` все partial exits имеют `reason="ladder_tp"`, даже если это time_stop остаток
- Невозможно различить TP partial exit и time_stop final exit по `event.reason`

#### ❌ Проблема 2: Двойной учет в executions

**Где:** `reporter.py:1426-1429` и `1482-1497`

**Текущая логика:**

1. **Partial exits** (строка 1414-1429):
   - Создается execution с `event_type="partial_exit"`
   - `reason="forced_close"` если `is_remainder=True`, иначе `"ladder_tp"` (строка 1426)
   - `fees_sol` = fees из partial_exit

2. **Final exit** (строка 1482-1497):
   - Создается execution с `event_type="final_exit"`
   - `qty_delta = -remaining_size` (строка 1489)
   - `fees_sol` = fees из remainder exit (если есть) или 0 (строка 1472-1477)

**Проблема:**
- Если есть remainder exit (`is_remainder=True`), то:
  - В `partial_exits` есть запись с `is_remainder=True` → создается execution `partial_exit`
  - В `final_exit` создается еще один execution с `qty_delta = -remaining_size`
  - **Риск:** Остаток может быть учтен дважды (как `partial_exit` и как `final_exit`)

**Проверка кода:**
- В `reporter.py:1449-1453` есть логика поиска `remainder_exits` для определения `remaining_size`
- Но execution для `partial_exit` с `is_remainder=True` все равно создается (строка 1414-1429)
- Execution для `final_exit` создается всегда, если `pos.exit_time and pos.status == "closed"` (строка 1436)

#### ❌ Проблема 3: Семантика событий

**Текущая семантика:**

| Событие | Когда создается | reason | event_id |
|---------|----------------|--------|----------|
| `POSITION_PARTIAL_EXIT` | TP уровень достигнут | `"ladder_tp"` (hardcoded) | Уникальный |
| `POSITION_PARTIAL_EXIT` | time_stop остаток | `"ladder_tp"` (hardcoded), но в meta `"time_stop"` | Уникальный |
| `POSITION_CLOSED` | Позиция полностью закрыта | `"time_stop"` или `"ladder_tp"` | Уникальный |

**Проблемы:**
1. `POSITION_PARTIAL_EXIT` используется и для TP partial exit, и для time_stop final exit
2. `reason` в `POSITION_PARTIAL_EXIT` всегда `"ladder_tp"`, даже для time_stop остатка
3. Невозможно различить "частичный выход по TP" и "финальный выход по time_stop" по типу события

### 1.3 Учет комиссий

**Где:** `portfolio.py:1409-1424` (partial exits) и `1503-1508` (remainder exit)

**Текущая логика:**

1. **Partial exit:**
   - `fees_partial = notional_returned - notional_after_fees` (строка 1333)
   - `network_fee_exit = self.execution_model.network_fee()` (строка 1336)
   - Сохраняется в `pos.meta["partial_exits"][i]["fees_sol"]` и `"network_fee_sol"` (строки 1392-1393)
   - Накапливается в `pos.meta["fees_total_sol"]` (строки 1412-1417)

2. **Remainder exit:**
   - `fees_remainder = notional_returned - notional_after_fees` (строка 1452)
   - `network_fee_exit = self.execution_model.network_fee()` (строка 1453)
   - Сохраняется в `pos.meta["partial_exits"][-1]["fees_sol"]` и `"network_fee_sol"` (строки 1469-1470)
   - Добавляется в `pos.meta["fees_total_sol"]` (строка 1504)

3. **Пересчет в конце:**
   - В `portfolio.py:1524-1542` пересчитывается `fees_total_sol` из всех `partial_exits`
   - В `reporter.py:1355-1500` собираются fees из executions для пересчета

**Вывод:**
- Комиссии считаются один раз для каждого exit (partial или remainder)
- В конце пересчитываются из `partial_exits` для консистентности
- **Потенциальная проблема:** Если remainder exit создает и `partial_exit` execution, и `final_exit` execution, fees могут быть учтены дважды в `portfolio_executions.csv`

### 1.4 Где экономически "последний выход"

**Текущая логика:**

1. **Если позиция закрыта полностью на уровнях:**
   - Последний partial exit закрывает остаток
   - `POSITION_CLOSED` эмитится в `_process_position_exit()` (строка 1678)
   - **Экономически последний выход:** Последний `POSITION_PARTIAL_EXIT` с `reason="ladder_tp"`

2. **Если позиция закрыта по time_stop:**
   - Partial exits обрабатываются в `_process_runner_partial_exits()`
   - Remainder exit создается как `POSITION_PARTIAL_EXIT` с `is_remainder=True` (строка 1478)
   - `POSITION_CLOSED` эмитится в `_process_position_exit()` (строка 1678)
   - **Экономически последний выход:** `POSITION_PARTIAL_EXIT` с `is_remainder=True` (но это не очевидно из типа события)

**Проблема:**
- Невозможно определить "последний выход" по типу события (`POSITION_PARTIAL_EXIT` может быть и partial, и final)
- Нужно проверять `meta["is_remainder"]` или `meta["reason"]` для различения

---

## 2️⃣ Семантика событий (текущая)

### 2.1 POSITION_PARTIAL_EXIT

**Создается:**
- При достижении TP уровня (строка 1360)
- При закрытии остатка по time_stop (строка 1478)

**Поля:**
- `event_type`: `"position_partial_exit"`
- `reason`: `"ladder_tp"` (hardcoded в `portfolio_events.py:133`)
- `meta["reason"]`: `"ladder_tp"` для TP, `"time_stop"` для remainder
- `meta["is_remainder"]`: `True` только для time_stop остатка
- `event_id`: Уникальный UUID

**Проблема:**
- `reason` всегда `"ladder_tp"`, даже для time_stop остатка
- Невозможно различить partial и final exit по типу события

### 2.2 POSITION_CLOSED

**Создается:**
- Когда `pos.size <= 1e-9` (позиция полностью закрыта)
- В `_process_position_exit()` (строка 1678)

**Поля:**
- `event_type`: `"position_closed"`
- `reason`: `"time_stop"` или `"ladder_tp"` (определяется из `pos.meta["time_stop_triggered"]`)
- `meta`: Содержит `fees_total_sol`, `pnl_sol`, `entry_time`, `exit_time`

**Проблема:**
- `POSITION_CLOSED` не содержит информации о том, был ли это remainder exit или полное закрытие на уровнях
- Нужно проверять наличие `partial_exits` с `is_remainder=True` для понимания

### 2.3 event_id

**Текущая логика:**
- Каждое событие имеет уникальный `event_id` (UUID)
- `event_id` сохраняется в `pos.meta["partial_exits"][i]["event_id"]` (строка 1394)
- В `portfolio_executions.csv` есть колонка `event_id` (строка 1373, 1420, 1488)

**Вывод:**
- `event_id` уникален и обязателен
- Связь между events и executions через `event_id` работает

### 2.4 fees_sol

**Текущая логика:**
- В `portfolio_executions.csv`: `fees_sol` для каждого execution (строка 1377, 1424, 1492)
- В `portfolio_positions.csv`: `fees_total_sol` = сумма всех `fees_sol` из executions (строка 1500-1510 в `reporter.py`)

**Вывод:**
- Комиссии считаются один раз для каждого execution
- `fees_total_sol` агрегируется из executions (один источник истины)

### 2.5 pnl_sol

**Текущая логика:**
- В `portfolio_executions.csv`: `pnl_sol_delta` для каждого execution (строка 1378, 1425, 1493)
- В `portfolio_positions.csv`: `pnl_sol` пересчитывается из `realized_multiple` (строка 1581-1586 в `portfolio.py`)

**Вывод:**
- PnL считается для каждого execution отдельно
- Итоговый PnL пересчитывается из `realized_multiple` для консистентности

---

## 3️⃣ Предложение целевой модели (БЕЗ реализации)

### 3.1 Целевая логика

**Правила:**

1. **partial_exit → только TP-уровни**
   - Создается только при достижении TP уровня
   - `event_type = "position_partial_exit"`
   - `reason = "ladder_tp"`

2. **final_exit → ровно 1 на позицию**
   - Создается только при закрытии остатка (time_stop или полное закрытие на последнем уровне)
   - `event_type = "position_closed"` (или новый тип `"position_final_exit"`?)
   - `reason = "time_stop"` если time_stop, `"ladder_tp"` если полное закрытие на уровнях

3. **time_stop → всегда final_exit**
   - Остаток по time_stop НЕ должен эмититься как `POSITION_PARTIAL_EXIT`
   - Должен эмититься как `POSITION_CLOSED` (или отдельный тип `POSITION_FINAL_EXIT`)

### 3.2 event_id

**Требования:**
- Уникален для каждого события
- Обязателен для executions
- Связь между events и executions через `event_id`

**Текущее состояние:** ✅ Уже реализовано

### 3.3 reason

**Целевая семантика:**

| Сценарий | partial_exit reason | final_exit reason |
|----------|---------------------|-------------------|
| TP уровень достигнут | `"ladder_tp"` | - |
| time_stop остаток | - | `"time_stop"` |
| Полное закрытие на уровнях | `"ladder_tp"` | `"ladder_tp"` (или не эмитится, если последний partial закрыл всё) |

**Проблема текущей реализации:**
- `POSITION_PARTIAL_EXIT` для time_stop остатка имеет `reason="ladder_tp"` (hardcoded)
- Нужно изменить на `reason="time_stop"` или эмитить как `POSITION_CLOSED`

### 3.4 Потенциальные конфликты

**Если изменить текущую модель:**

1. **Изменение типа события для time_stop остатка:**
   - Сейчас: `POSITION_PARTIAL_EXIT` с `is_remainder=True`
   - Целевое: `POSITION_CLOSED` (или новый тип)
   - **Риск:** Может сломать существующие тесты или контракты

2. **Изменение reason в POSITION_PARTIAL_EXIT:**
   - Сейчас: `reason="ladder_tp"` (hardcoded)
   - Целевое: `reason="time_stop"` для remainder exit
   - **Риск:** Может сломать логику, которая ожидает `reason="ladder_tp"` для всех partial exits

3. **Удаление двойного учета в executions:**
   - Сейчас: remainder exit создает и `partial_exit` execution, и `final_exit` execution
   - Целевое: только `final_exit` execution
   - **Риск:** Может изменить `fees_total_sol` и `pnl_sol` в существующих тестах

---

## 4️⃣ Точка принятия решения (СТОП)

### ❗ Вопросы для обсуждения:

1. **Можно ли изменить тип события для time_stop остатка?**
   - Вариант A: Эмитить `POSITION_CLOSED` вместо `POSITION_PARTIAL_EXIT` для remainder exit
   - Вариант B: Создать новый тип `POSITION_FINAL_EXIT`
   - Вариант C: Оставить `POSITION_PARTIAL_EXIT`, но изменить `reason` на `"time_stop"`

2. **Можно ли изменить reason в POSITION_PARTIAL_EXIT?**
   - Сейчас: `reason="ladder_tp"` (hardcoded)
   - Целевое: `reason="time_stop"` для remainder exit
   - **Риск:** Может сломать логику, которая ожидает `reason="ladder_tp"` для всех partial exits

3. **Можно ли убрать двойной учет в executions?**
   - Сейчас: remainder exit создает и `partial_exit` execution, и `final_exit` execution
   - Целевое: только `final_exit` execution
   - **Риск:** Может изменить `fees_total_sol` и `pnl_sol` в существующих тестах

4. **Можно ли изменить формат CSV?**
   - Сейчас: `portfolio_executions.csv` содержит и `partial_exit`, и `final_exit` для remainder
   - Целевое: только `final_exit` для remainder
   - **Риск:** Может сломать Stage A/B или audit

### ⚠️ Рекомендация:

**НЕ вносить изменения без явного согласия**, так как:
1. Текущая модель работает (все тесты зелёные)
2. Изменения могут затронуть Stage A/B и audit
3. Нужно согласовать семантику событий с потребителями данных

---

## 5️⃣ Следующие шаги

1. **Обсудить предложенную модель** с командой
2. **Выбрать вариант** из предложенных (A/B/C)
3. **Обновить документацию** после согласия
4. **Реализовать изменения** только после явного согласия

---

## 6️⃣ Решение принято и реализовано

**Дата реализации:** 2024-12-XX  
**Вариант:** C + reporter fix

### Изменения:

1. **Events: reason для remainder**
   - Добавлен параметр `reason: Optional[str] = None` в `PortfolioEvent.create_position_partial_exit()`
   - Если `reason=None`, используется `"ladder_tp"` по умолчанию (BC)
   - При создании remainder exit передаётся `reason="time_stop"`
   - **Результат:** В `portfolio_events.csv` remainder exit имеет `reason="time_stop"`, а TP partial exits имеют `reason="ladder_tp"`

2. **Reporter: убрана двойная запись remainder в executions**
   - В `reporter.py` добавлен фильтр: remainder exit (`is_remainder=True`) не записывается как `partial_exit` execution
   - Remainder exit отражается только в `final_exit` execution
   - `event_id` для `final_exit` ссылается на remainder exit event
   - **Результат:** В `portfolio_executions.csv` remainder отражён только одним `final_exit`, без дублирования как `partial_exit`

### Что изменилось в леджере:

**portfolio_events.csv:**
- Remainder exit (`POSITION_PARTIAL_EXIT` с `is_remainder=True`) теперь имеет `reason="time_stop"` вместо `reason="ladder_tp"`
- TP partial exits остаются с `reason="ladder_tp"`

**portfolio_executions.csv:**
- Исчезла лишняя строка `partial_exit` для remainder (была с `reason="forced_close"`)
- Remainder отражён только в `final_exit` execution
- `event_id` в `final_exit` ссылается на remainder exit event

**portfolio_positions.csv:**
- Без изменений (формат и структура не менялись)

### Обратная совместимость:

- ✅ Все существующие вызовы `create_position_partial_exit()` работают без изменений (параметр `reason` опциональный)
- ✅ Формат CSV не изменился (колонки/имена/структура остались прежними)
- ✅ Тесты должны остаться зелёными (проверка обязательна)

---

**Статус:** Решение реализовано, ожидание проверки тестов

