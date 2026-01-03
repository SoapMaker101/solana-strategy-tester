# StrategyTradeBlueprint — Эталонные Примеры

## Назначение документа

**Зачем фиксируются примеры:**
Этот документ содержит эталонные примеры `StrategyTradeBlueprint` — артефактов, которые описывают стратегический intent без привязки к портфелю или деньгам.

**Что это "эталон" перед Replay:**
Примеры показывают, как стратегия **ДОЛЖНА** выглядеть на уровне intent (Этап 1). При переходе к Этапу 2 (PortfolioReplay) эти примеры помогут:
- Понять, что изменилось в структуре blueprints (если изменилось)
- Проверить, что Replay правильно интерпретирует intent
- Убедиться, что стратегия генерирует стабильные и повторяемые blueprints

**Когда использовать:**
- После первого запуска backtest на Этапе 1 — сравнить реальные blueprints с эталонами
- Перед началом Этапа 2 — понять ожидаемую структуру данных
- При отладке — если blueprint выглядит странно, сравнить с эталоном

---

## Пример 1: Обычный Ladder Trade (с final_exit)

**Сценарий:** Стратегия полностью закрыла позицию через ladder exits. Все уровни достигнуты, позиция закрыта на уровне 10x.

```json
{
  "signal_id": "signal_2024_01_15_12_00_token_abc123",
  "strategy_id": "runner_baseline_v1",
  "contract_address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
  "entry_time": "2024-01-15T12:00:00+00:00",
  "entry_price_raw": 0.001234,
  "entry_mcap_proxy": 1234000.0,
  "partial_exits_json": "[{\"timestamp\":\"2024-01-15T12:05:00+00:00\",\"xn\":2.0,\"fraction\":0.3},{\"timestamp\":\"2024-01-15T12:15:00+00:00\",\"xn\":5.0,\"fraction\":0.4},{\"timestamp\":\"2024-01-15T12:30:00+00:00\",\"xn\":10.0,\"fraction\":0.3}]",
  "final_exit_json": "{\"timestamp\":\"2024-01-15T12:30:00+00:00\",\"reason\":\"all_levels_hit\"}",
  "realized_multiple": 5.6,
  "max_xn_reached": 10.0,
  "reason": "all_levels_hit"
}
```

**Расшифровка partial_exits_json:**
```json
[
  {
    "timestamp": "2024-01-15T12:05:00+00:00",
    "xn": 2.0,
    "fraction": 0.3
  },
  {
    "timestamp": "2024-01-15T12:15:00+00:00",
    "xn": 5.0,
    "fraction": 0.4
  },
  {
    "timestamp": "2024-01-15T12:30:00+00:00",
    "xn": 10.0,
    "fraction": 0.3
  }
]
```

**Расшифровка final_exit_json:**
```json
{
  "timestamp": "2024-01-15T12:30:00+00:00",
  "reason": "all_levels_hit"
}
```

### Анализ примера:

**Почему это нормально:**
- ✅ `partial_exits` отсортированы по времени (12:05 → 12:15 → 12:30)
- ✅ `realized_multiple = 0.3×2.0 + 0.4×5.0 + 0.3×10.0 = 0.6 + 2.0 + 3.0 = 5.6` — корректный расчет
- ✅ `max_xn_reached = 10.0` — соответствует максимальному уровню из partial_exits
- ✅ `final_exit.reason = "all_levels_hit"` — стратегия сама закрыла позицию, все уровни пройдены
- ✅ `final_exit.timestamp` совпадает с последним partial_exit — позиция закрылась полностью

**Что это означает:**
Стратегия последовательно закрыла 30% позиции на уровне 2x, затем 40% на 5x, и оставшиеся 30% на 10x. Итоговый realized_multiple = 5.6x (средневзвешенный multiple всех exits).

---

## Пример 2: Ladder Trade без final_exit

**Сценарий:** Стратегия частично закрыла позицию через ladder exits, но не закрыла полностью. Ожидается закрытие на уровне портфеля (в Этапе 2 через max_hold_minutes или другие правила).

```json
{
  "signal_id": "signal_2024_01_15_14_30_token_xyz789",
  "strategy_id": "runner_baseline_v1",
  "contract_address": "So11111111111111111111111111111111111111112",
  "entry_time": "2024-01-15T14:30:00+00:00",
  "entry_price_raw": 0.000567,
  "entry_mcap_proxy": 567000.0,
  "partial_exits_json": "[{\"timestamp\":\"2024-01-15T14:35:00+00:00\",\"xn\":2.0,\"fraction\":0.3},{\"timestamp\":\"2024-01-15T14:45:00+00:00\",\"xn\":5.0,\"fraction\":0.4}]",
  "final_exit_json": "",
  "realized_multiple": 2.6,
  "max_xn_reached": 5.0,
  "reason": "all_levels_hit"
}
```

**Расшифровка partial_exits_json:**
```json
[
  {
    "timestamp": "2024-01-15T14:35:00+00:00",
    "xn": 2.0,
    "fraction": 0.3
  },
  {
    "timestamp": "2024-01-15T14:45:00+00:00",
    "xn": 5.0,
    "fraction": 0.4
  }
]
```

**Расшифровка final_exit_json:**
```
(пустая строка)
```

### Анализ примера:

**Почему это нормально:**
- ✅ `partial_exits` есть (2 частичных выхода)
- ✅ `final_exit_json = ""` (пустая строка) — стратегия не закрыла позицию полностью
- ✅ `realized_multiple = 0.3×2.0 + 0.4×5.0 = 0.6 + 2.0 = 2.6` — учитывает только закрытые части
- ✅ `max_xn_reached = 5.0` — максимальный достигнутый уровень
- ✅ `reason = "all_levels_hit"` — все доступные уровни достигнуты, но позиция не закрыта полностью

**Что это означает:**
Стратегия закрыла 30% позиции на уровне 2x и 40% на уровне 5x, но оставшиеся 30% не закрыла. В Этапе 2 (PortfolioReplay) эти оставшиеся 30% будут закрыты по правилам портфеля:
- По `max_hold_minutes` (если задан)
- При forced close по другим причинам (capacity, reset и т.д.)

**Почему `reason = "all_levels_hit"` если позиция не закрыта:**
Это нормально для Этапа 1 — стратегия достигла всех доступных уровней из конфигурации (2x, 5x), но не закрыла позицию полностью (возможно, не все уровни были заданы, или стратегия использует другую логику закрытия остатка).

---

## Общие замечания

### Структура данных:
- **Нет денежных величин:** blueprint не содержит `size`, `pnl_sol`, `fees`, `slippage`, `allocation` — это intent, а не execution
- **JSON поля:** `partial_exits_json` и `final_exit_json` хранятся как строки в CSV, но парсятся как JSON
- **ISO8601 timestamps:** все временные метки в формате ISO8601 с timezone

### Валидация:
- `partial_exits` всегда отсортированы по `timestamp` (автоматически при сериализации)
- `final_exit_json` либо пустая строка, либо валидный JSON с `timestamp` и `reason`
- `realized_multiple = Σ(partial_exit.fraction × partial_exit.xn)` для всех частичных выходов
- `max_xn_reached` равен максимальному `xn` из всех `partial_exits` (или 0.0 если нет partial_exits)

### Переход к Этапу 2:
При PortfolioReplay (Этап 2) эти blueprints будут использоваться для:
- Создания executions (entry + partial + final/forced)
- Применения portfolio правил (capacity, max_hold_minutes)
- Генерации portfolio events

Если blueprint без `final_exit`, портфель сам закроет остаток по своим правилам.

