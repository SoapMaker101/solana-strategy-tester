# ЭТАП 1.5 — Инструкция по самопроверке

## Цель проверки

Визуально и количественно понять, что именно делают стратегии.
Проверить повторяемость и адекватность blueprints перед переходом к Этапу 2.

## Шаги проверки

### 1. Запустить backtest

```bash
python main.py --signals signals/test_signals.csv --strategies-config config/runner_baseline.yaml --backtest-config config/backtest_example.yaml --report-mode summary
```

**Ожидаемый результат:**
- Backtest завершается успешно
- В `output/reports/` появляется файл `strategy_trades.csv`

### 2. Запустить inspection скрипт

```bash
python scripts/inspect_strategy_trades.py output/reports/strategy_trades.csv
```

**Ожидаемый вывод:**
```
===================================
Strategy Trades Inspection
===================================

Total blueprints: <число>
With final exit: <число>
Without final exit: <число>

Reasons distribution:
- <reason>: <count>
- ...

Partial exits:
- avg: <число>
- min: <число>
- max: <число>

Realized multiple:
- min: <число>
- max: <число>

Top max_xn_reached:
- <число>
- <число>
- <число>

===================================
```

### 3. Проверить вывод (ответить на вопросы)

#### ✅ Понятно ли, что делают стратегии?
- **Ожидаемо:** Видны разные типы стратегий (Fast, Balanced, Tail, Conservative)
- **Ожидаемо:** Разные time_stop (7d, 10d, 14d, 21d, 30d и т.д.)
- **Ожидаемо:** Разные уровни ladder (2x, 3x, 5x, 7x, 10x, 15x, 20x)

#### ✅ Нет ли странных reason?
**Ожидаемые reasons:**
- `all_levels_hit` — все уровни достигнуты, позиция закрыта стратегией
- `time_stop` — позиция закрыта по таймауту стратегии
- `no_entry` — нет входа (нет свечей или других причин)

**Красные флаги:**
- ❌ Неожиданные reason (например, "error", странные значения)
- ❌ Все blueprints с `reason = "no_entry"` (проблема с данными)

#### ✅ Нет ли unrealistically high realized_multiple?
**Ожидаемые значения:**
- `min`: от 0.5 до 1.0 (позиции закрытые по time_stop или с частичной прибылью)
- `max`: от 2.0 до 20.0 (в зависимости от уровней в стратегии)

**Красные флаги:**
- ❌ `max > 100.0` без очевидной причины (возможно, ошибка в расчетах)
- ❌ Все `realized_multiple = 0.0` (проблема с генерацией)

#### ✅ Есть ли трейды без final_exit?
**Ожидаемо:** Да, должны быть.

**Почему это нормально:**
- Стратегия достигла всех доступных уровней, но не закрыла позицию полностью
- Оставшаяся часть будет закрыта портфелем в Этапе 2 (max_hold_minutes или другие правила)
- Это соответствует дизайну: стратегия описывает intent, портфель управляет execution

**Проверка:**
- `Without final exit: <число > 0>` — должно быть > 0 (если есть стратегии с неполным закрытием)
- Если все blueprints имеют `final_exit` — это тоже нормально (все позиции закрыты стратегией)

### 4. Визуальный осмотр CSV

Открыть `output/reports/strategy_trades.csv` и проверить:

**Структура:**
- 11 колонок присутствуют
- `partial_exits_json` и `final_exit_json` — валидный JSON или пустая строка
- `entry_time` в ISO формате
- `entry_price_raw > 0`

**Примеры строк:**
- Есть строки с несколькими partial_exits
- Есть строки с `final_exit_json = ""`
- Есть строки с `final_exit_json` содержащим JSON

**Распарсить пример JSON:**
```python
import json
# partial_exits_json из CSV
exits = json.loads(row["partial_exits_json"])
# Должен быть список dict с timestamp, xn, fraction
```

## Критерии успеха

✅ **Визуально понятно:**
- Видно распределение по стратегиям
- Видно разные паттерны (fast/balanced/tail)

✅ **Стабильно и повторяемо:**
- Одинаковый вход → одинаковый blueprint (при повторном запуске)
- Нет случайных/хаотических значений

✅ **Адекватно:**
- `realized_multiple` соответствует уровням стратегии
- `reason` объяснимые
- `partial_exits` отсортированы по времени

## Если что-то не так

**Проблема:** Все `realized_multiple = 0.0`
- **Проверка:** Посмотреть в CSV, возможно все позиции закрыты по time_stop с убытком

**Проблема:** Нет `partial_exits`
- **Проверка:** Возможно все позиции закрыты по time_stop до достижения уровней

**Проблема:** Странные `reason`
- **Проверка:** Открыть CSV, посмотреть конкретные строки

**Проблема:** `max_xn_reached` не соответствует уровням стратегии
- **Проверка:** Проверить конфигурацию стратегий (xn в take_profit_levels)

## Зафиксировать результаты

После проверки зафиксировать в commit message или комментарии:

```
Этап 1.5 самопроверка:

✅ Понятно ли, что делают стратегии: ДА
  - Видны стратегии: Runner_Fast, Runner_Balanced, Runner_Tail, Runner_Conservative
  - Time_stop от 7d до 60d
  - Ladder уровни от 2x до 20x

✅ Нет ли странных reason: ДА
  - Только: all_levels_hit, time_stop, no_entry
  - Распределение: all_levels_hit (60%), time_stop (35%), no_entry (5%)

✅ Нет ли unrealistically high realized_multiple: ДА
  - min: 0.45 (time_stop закрытия)
  - max: 12.5 (соответствует стратегиям с уровнем 15x-20x)

✅ Есть ли трейды без final_exit: ДА
  - Without final exit: 245 (18% от общего)
  - Это ожидаемо - остаток будет закрыт портфелем в Этапе 2

Вывод: Blueprints стабильны и адекватны. Готов к Этапу 2.
```

