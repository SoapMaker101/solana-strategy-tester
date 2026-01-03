# ЭТАП 2.5 — Compare Legacy vs Replay (RUN Guide)

## Зачем этот этап?

**Цель:** Не "свести результаты" legacy и replay к идентичности, а **понять и объяснить различия**.

После реализации Этапа 2 (PortfolioReplay) у нас есть два пути исполнения портфеля:
- **Legacy путь** (`use_replay_mode=False`): оригинальный `PortfolioEngine` с event-driven симуляцией
- **Replay путь** (`use_replay_mode=True`): новый `PortfolioReplay`, который строит portfolio ledger на основе `StrategyTradeBlueprint`

Этот этап нужен для:
1. **Контроля качества**: убедиться, что replay путь работает корректно
2. **Понимания различий**: объяснить, почему результаты могут отличаться
3. **Валидации инвариантов**: проверить, что MUST KEEP инварианты соблюдаются в обоих путях

---

## Как получить legacy-dir и replay-dir?

### Шаг 1: Запуск Legacy прогона

Создайте или модифицируйте конфиг (`config/backtest_example.yaml` или новый):

```yaml
portfolio:
  initial_balance_sol: 10.0
  allocation_mode: "fixed"
  percent_per_trade: 0.01
  max_exposure: 0.95
  max_open_positions: 100
  profit_reset_enabled: true
  profit_reset_multiple: 1.3
  # Важно: use_replay_mode НЕ указывается или = false (по умолчанию)
```

Запустите backtest:

```bash
python main.py \
  --signals signals/example_signals.csv \
  --backtest-config config/backtest_example.yaml \
  --reports-dir output/reports/legacy
```

**Результат:** В `output/reports/legacy/` появятся файлы:
- `*_portfolio_positions.csv`
- `*_portfolio_stats.json`
- `*_portfolio_events.csv` (если есть)
- `*_equity_curve.csv` (если есть)

---

### Шаг 2: Запуск Replay прогона

**Важно:** Для replay нужен тот же `strategy_trades.csv`, который был сгенерирован в legacy прогоне!

Просто добавьте поля в `config/backtest_example.yaml` (или создайте новый конфиг):

```yaml
portfolio:
  initial_balance_sol: 10.0
  allocation_mode: "fixed"
  percent_per_trade: 0.01
  max_exposure: 0.95
  max_open_positions: 100
  profit_reset_enabled: true
  profit_reset_multiple: 1.3
  # Новые поля для PortfolioReplay (ЭТАП 2)
  use_replay_mode: true    # Включить PortfolioReplay
  max_hold_minutes: 4320   # Опционально: максимальное время удержания в минутах (30 дней = 4320 минут)
```

Запустите backtest:

```bash
python main.py \
  --signals signals/example_signals.csv \
  --backtest-config config/backtest_example.yaml \
  --reports-dir output/reports/replay
```

**Результат:** В `output/reports/replay/` появятся файлы:
- `*_portfolio_positions.csv`
- `*_portfolio_stats.json`
- `*_portfolio_events.csv`
- `*_equity_curve.csv`

---

## Как запускать compare script?

### Базовый запуск

```bash
python scripts/compare_legacy_vs_replay.py \
  --legacy-dir output/reports/legacy \
  --replay-dir output/reports/replay
```

### С сохранением результата в файл

```bash
python scripts/compare_legacy_vs_replay.py \
  --legacy-dir output/reports/legacy \
  --replay-dir output/reports/replay \
  --out output/comparison_diff.md
```

### Для конкретной стратегии

```bash
python scripts/compare_legacy_vs_replay.py \
  --legacy-dir output/reports/legacy \
  --replay-dir output/reports/replay \
  --strategy my_strategy_name \
  --out output/comparison_diff.md
```

### С детальными предупреждениями

```bash
python scripts/compare_legacy_vs_replay.py \
  --legacy-dir output/reports/legacy \
  --replay-dir output/reports/replay \
  --verbose \
  --out output/comparison_diff_verbose.md
```

---

## Как интерпретировать diff?

### Формат вывода

```
========================================
Legacy vs Replay — Summary Diff
========================================

Paths:
- legacy: output/reports/legacy
- replay: output/reports/replay

Core metrics:
- positions_opened: legacy X | replay Y | diff (Y-X)
- positions_closed: legacy X | replay Y | diff (Y-X)
- unique_positions: legacy X | replay Y | diff (Y-X)
- total_pnl_sol: legacy X.XXXX SOL | replay Y.YYYY SOL | diff +/-Z.ZZZZ SOL
- resets: legacy X | replay Y | diff (Y-X)
- max_drawdown: legacy X.XX% | replay Y.YY% | diff +/-Z.ZZ%

Close reasons (top):
Legacy:
  - ladder_tp: 742
  - time_stop: 183
Replay:
  - ladder_tp: 720
  - max_hold_minutes: 205

Only in legacy:
  - time_stop: 183
Only in replay:
  - max_hold_minutes: 205

Sanity checks:
- monotonic timestamps: OK
- reset chain: OK
- positions/events: OK

Explanations hint:
- Different close triggers (time_stop vs max_hold_minutes)
- Legacy: time_stop (183), Replay: max_hold (205)
========================================
```

### Ключевые секции

1. **Core metrics**: Основные метрики с разницей (diff = replay - legacy)
   - Положительный diff = replay больше legacy
   - Отрицательный diff = replay меньше legacy

2. **Close reasons (top)**: Топ-5 причин закрытия в каждом режиме
   - Показывает распределение `reason` для `POSITION_CLOSED`

3. **Only in legacy/replay**: Уникальные причины закрытия
   - **Ожидаемо**: `time_stop` только в legacy, `max_hold_minutes` только в replay

4. **Sanity checks**: Диагностика корректности CSV
   - `OK` = нарушений не найдено
   - `WARN` = найдены проблемы (при `--verbose` покажет детали)

5. **Explanations hint**: Короткий список объяснений различий

---

## Какие различия считаются нормальными?

### ✅ Нормальные различия (ожидаемы)

#### 1. **time_stop vs max_hold_minutes**

**Legacy:**
- Стратегия сама закрывает позиции по `time_stop` (через `FinalExitBlueprint`)
- `POSITION_CLOSED` с `reason="time_stop"`

**Replay:**
- Портфель закрывает позиции по `max_hold_minutes` (если задан в `PortfolioConfig`)
- `POSITION_CLOSED` с `reason="max_hold_minutes"`

**Почему различается:**
- Разное время срабатывания (strategy-level vs portfolio-level)
- Разные exit prices из-за разного момента закрытия
- Разное количество закрытых позиций

**Ожидаемо в diff:**
```
Only in legacy:
  - time_stop: N

Only in replay:
  - max_hold_minutes: M
```

#### 2. **Разное количество positions_opened/closed**

**Причины:**
- Capacity blocking работает по-разному (timing checks)
- Разное количество resets приводит к разному количеству открытий
- Разные close triggers (time_stop vs max_hold_minutes)

**Ожидаемо:**
- `positions_opened` может отличаться на 5-20%
- `positions_closed` может отличаться значительно (если много time_stop в legacy)

#### 3. **Разный total_pnl_sol**

**Причины:**
- Разные exit prices из-за timing differences
- Разное количество позиций → разный суммарный PnL
- Разное время закрытия → разные цены выхода

**Ожидаемо:**
- PnL может отличаться на 10-30% (особенно если много time_stop закрытий)
- **Важно**: Тренд должен быть похожим (оба должны быть в плюсе или в минусе)

#### 4. **Разное количество resets**

**Причины:**
- Разные equity curves → разные моменты пересечения порогов
- Разное время закрытия позиций → разная динамика баланса

**Ожидаемо:**
- Количество resets может отличаться на ±1-2
- Большие различия (>5) требуют проверки

---

## Какие различия считаются красными флагами?

### 🚩 Красные флаги (требуют немедленного внимания)

#### 1. **Sanity checks: WARN**

**Монотонность timestamps:**
```
[WARNING] LEGACY: Found 15 timestamp violations (events not sorted)
```

**Проблема:** События не отсортированы по времени
**Действие:** Проверить логику генерации событий

---

**Reset chain violation:**
```
[WARNING] LEGACY: Reset chain violation at 2024-06-15 10:00:00: 
  3 positions not closed before/at reset
```

**Проблема:** Перед `PORTFOLIO_RESET_TRIGGERED` не все позиции закрыты
**Действие:** Проверить логику reset в `PortfolioEngine` / `PortfolioReplay`

---

**Positions-events inconsistency:**
```
[WARNING] LEGACY: Found 5 positions closed without POSITION_OPENED
[WARNING] REPLAY: Position abc123 is closed but has no events
```

**Проблема:** Нарушение связности позиций и событий
**Действие:** Проверить linkage logic (position_id → events)

---

#### 2. **Критические метрики: хаос**

**Максимальная просадка отличается в разы:**
```
max_drawdown: legacy 15.23% | replay 45.67% | diff +30.44%
```

**Проблема:** Replay показывает в 3 раза больше просадку
**Возможные причины:**
- Неправильная логика reset в replay
- Неправильное вычисление equity curve
- Баги в capacity blocking

**Действие:**
1. Проверить equity curves вручную (графики)
2. Проверить логи reset events
3. Сравнить количество resets

---

**Количество открытых позиций отличается кардинально:**
```
positions_opened: legacy 1000 | replay 50 | diff -950
```

**Проблема:** Replay открыл в 20 раз меньше позиций
**Возможные причины:**
- Capacity blocking слишком агрессивный
- Баг в логике проверки capacity в `PortfolioReplay`
- Неправильная интерпретация blueprints

**Действие:**
1. Проверить `trades_skipped_by_risk` в stats
2. Проверить логи capacity checks
3. Сравнить количество blueprints vs opened positions

---

**PnL кардинально отличается (разные знаки или порядки величины):**
```
total_pnl_sol: legacy +5.2345 SOL | replay -15.6789 SOL | diff -20.9134 SOL
```

**Проблема:** Legacy в плюсе, replay в минусе
**Возможные причины:**
- Неправильное вычисление PnL в replay
- Неправильная логика fees/slippage
- Баги в allocation logic

**Действие:**
1. Проверить несколько позиций вручную (entry/exit prices, fees)
2. Сравнить PnL на уровне отдельных позиций
3. Проверить fee_model и slippage calculation

---

#### 3. **Linkage violations**

**Позиции без связанных событий:**
```
[WARNING] LEGACY: Position xyz789 is closed but has no events
```

**Проблема:** Нет связи между позицией и событиями
**Действие:** Проверить логику создания событий (position_id linkage)

---

**События без связанных позиций:**
```
[WARNING] REPLAY: Found 10 positions closed without POSITION_OPENED
```

**Проблема:** Есть `POSITION_CLOSED`, но нет `POSITION_OPENED`
**Действие:** Проверить логику открытия позиций в replay

---

#### 4. **Неожиданные close reasons**

**Неизвестные причины закрытия:**
```
Only in replay:
  - unknown_reason: 50
  - error_closure: 20
```

**Проблема:** Появились причины, которых не должно быть
**Действие:** Проверить логику закрытия позиций в `PortfolioReplay`

---

### ✅ Что делать при обнаружении красных флагов?

1. **Сохранить diff в файл** для детального анализа:
   ```bash
   python scripts/compare_legacy_vs_replay.py \
     --legacy-dir output/reports/legacy \
     --replay-dir output/reports/replay \
     --verbose \
     --out output/comparison_diff_with_issues.md
   ```

2. **Проверить equity curves** (если есть графики):
   - Должны быть похожи по форме
   - Разница в абсолютных значениях допустима

3. **Проверить отдельные позиции** вручную:
   - Выбрать несколько позиций из `portfolio_positions.csv`
   - Проверить entry/exit prices, fees, PnL
   - Найти расхождения

4. **Проверить логи прогона**:
   - Искать ERROR/WARNING сообщения
   - Проверить количество skipped trades

5. **Создать issue/bug report** с:
   - Полным diff файлом
   - Примером проблемной позиции
   - Описанием ожидаемого vs фактического поведения

---

## Примеры интерпретации

### Пример 1: Нормальные различия (OK)

```
Core metrics:
- positions_opened: legacy 1000 | replay 950 | diff -50
- positions_closed: legacy 950 | replay 920 | diff -30
- total_pnl_sol: legacy +2.3456 SOL | replay +2.1234 SOL | diff -0.2222 SOL

Only in legacy:
  - time_stop: 183
Only in replay:
  - max_hold_minutes: 205

Sanity checks:
- monotonic timestamps: OK
- reset chain: OK
- positions/events: OK
```

**Интерпретация:** ✅ Нормально
- Небольшие различия в метриках (5-10%)
- Ожидаемые различия в close reasons (time_stop vs max_hold_minutes)
- Sanity checks проходят

---

### Пример 2: Красные флаги (WARN)

```
Core metrics:
- positions_opened: legacy 1000 | replay 50 | diff -950
- total_pnl_sol: legacy +2.3456 SOL | replay -10.5678 SOL | diff -12.9134 SOL
- max_drawdown: legacy 15.23% | replay 67.89% | diff +52.66%

Sanity checks:
- monotonic timestamps: OK
- reset chain: WARN
- positions/events: WARN

[WARNING] REPLAY: Reset chain violation at 2024-06-15 10:00:00: 
  10 positions not closed before/at reset
```

**Интерпретация:** 🚩 Критично
- Кардинальное различие в количестве позиций
- Разные знаки PnL
- Нарушения в reset chain
- Требуется немедленная проверка кода

---

## Заключение

Этап 2.5 — это **контроль качества** перед переходом к Этапу 3 (удаление legacy).

**Критерии успеха:**
- ✅ Sanity checks: все OK
- ✅ Метрики различаются, но объяснимо (time_stop vs max_hold_minutes)
- ✅ Нет linkage violations
- ✅ Нет критических различий (разные знаки PnL, порядки величины)

**Если все OK:** Можно переходить к Этапу 3.

**Если есть красные флаги:** Исправить проблемы в `PortfolioReplay` перед переходом к Этапу 3.

