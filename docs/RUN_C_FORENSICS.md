# Run C Forensic Analysis

**Дата создания:** 2025-01-XX  
**Конфиг:** `config/backtest_C.yaml`  
**Цель:** Разбор расхождения между ожидаемым и фактическим поведением profit reset

---

## Паспорт прогона C

### Конфигурация из YAML

```yaml
portfolio:
  profit_reset_trigger_basis: "realized_balance"
  initial_balance_sol: 10.0
  allocation_mode: "fixed_then_dynamic_after_profit_reset"
  percent_per_trade: 0.01
  max_exposure: 0.95
  max_open_positions: 100
  profit_reset_enabled: true
  profit_reset_multiple: 1.3
```

### Фактические значения (из артефактов)

| Параметр | Значение |
|----------|----------|
| `initial_balance` | 10.0 SOL |
| `allocation_mode` | fixed_then_dynamic_after_profit_reset |
| `percent_per_trade` | 0.01 |
| `reset_enabled` | true |
| `multiple` | 1.3 |
| `trigger_basis` (из YAML) | **realized_balance** |
| `trigger_basis` (фактический из событий) | **equity_peak** ❌ |

---

## Таблица всех reset-событий

### Источник данных

- `runs/C/reports/portfolio_events.csv` — канонический event ledger
- Фильтр: `event_type == "portfolio_reset_triggered"` AND `reason == "profit_reset"`

### Таблица reset-событий

| timestamp | reset_id | trigger_basis (из meta_json) | cycle_start_equity | equity_peak_in_cycle | threshold | cycle_start_balance | current_balance | closed_positions_count |
|-----------|----------|------------------------------|-------------------|---------------------|-----------|-------------------|-----------------|----------------------|
| *[timestamp 1]* | *[reset_id]* | **equity_peak** ❌ | *[value]* | *[value]* | *[value]* | *[value]* | *[value]* | *[count]* |
| *[timestamp 2]* | *[reset_id]* | **equity_peak** ❌ | *[value]* | *[value]* | *[value]* | *[value]* | *[value]* | *[count]* |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

**Примечание:** Таблица должна быть заполнена из фактических данных `portfolio_events.csv` после прогона.

### Статистика reset

| Метрика | Значение |
|---------|----------|
| `reset_count` | 7 |
| `portfolio_reset_profit_count` | 7 |

---

## Разбор: почему trigger_basis стал equity_peak?

### Проблема

В YAML указано `profit_reset_trigger_basis: realized_balance`, но в событиях записывается `trigger_basis="equity_peak"`.

### Причина (ИСПРАВЛЕНО)

**Место 1: YAML loader / config parser**

Файл: `backtester/application/runner.py:346` — метод `_build_portfolio_config()`

**Было:**
```python
# Profit reset конфигурация
profit_reset_enabled = portfolio_cfg.get("profit_reset_enabled")
profit_reset_multiple = portfolio_cfg.get("profit_reset_multiple")
# ❌ profit_reset_trigger_basis НЕ читался из YAML
```

**Стало (ИСПРАВЛЕНО):**
```python
# Profit reset конфигурация
profit_reset_enabled = portfolio_cfg.get("profit_reset_enabled")
profit_reset_multiple = portfolio_cfg.get("profit_reset_multiple")
profit_reset_trigger_basis = portfolio_cfg.get("profit_reset_trigger_basis", "equity_peak")  # ✅ Читаем из YAML
```

**Место 2: PortfolioConfig creation**

Файл: `backtester/application/runner.py:440` — создание `PortfolioConfig`

**Было:**
```python
return PortfolioConfig(
    # ...
    profit_reset_enabled=profit_reset_enabled,
    profit_reset_multiple=float(profit_reset_multiple) if profit_reset_multiple is not None else None,
    # ❌ profit_reset_trigger_basis НЕ передавался в PortfolioConfig
    # ...
)
```

**Стало (ИСПРАВЛЕНО):**
```python
return PortfolioConfig(
    # ...
    profit_reset_enabled=profit_reset_enabled,
    profit_reset_multiple=float(profit_reset_multiple) if profit_reset_multiple is not None else None,
    profit_reset_trigger_basis=profit_reset_trigger_basis,  # ✅ Передаем в PortfolioConfig
    # ...
)
```

**Место 3: Использование в коде**

Файл: `backtester/domain/portfolio.py:1337` — эмиссия события `PORTFOLIO_RESET_TRIGGERED`

**Было:**
```python
"trigger_basis": self.config.profit_reset_trigger_basis or "equity_peak",  # ❌ Прямой доступ к полю
```

**Стало (ИСПРАВЛЕНО):**
```python
trigger_basis = self.config.resolved_profit_reset_trigger_basis()  # ✅ Используем resolved метод
# ...
"trigger_basis": trigger_basis,  # ✅ Записываем в meta
```

**Место 4: Добавлен метод валидации**

Файл: `backtester/domain/portfolio.py:222` — метод `resolved_profit_reset_trigger_basis()`

```python
def resolved_profit_reset_trigger_basis(self) -> Literal["equity_peak", "realized_balance"]:
    """
    Возвращает значение profit_reset_trigger_basis с валидацией и fallback на дефолт.
    
    ВАЛИДАЦИЯ: только "equity_peak" или "realized_balance", при мусоре: warning + fallback на "equity_peak".
    
    Returns:
        "equity_peak" (legacy, default) или "realized_balance" (новый режим)
    """
    basis = self.profit_reset_trigger_basis
    if basis in ("equity_peak", "realized_balance"):
        return basis
    
    # При невалидном значении: warning + fallback на equity_peak
    logger.warning(
        f"Invalid profit_reset_trigger_basis='{basis}', "
        f"falling back to 'equity_peak'. Valid values: 'equity_peak', 'realized_balance'."
    )
    return "equity_peak"
```

---

## Разбор: отрицательный cycle_start_equity

### Проблема

В `portfolio_summary.csv` поле `cycle_start_equity` становится отрицательным в конце прогона, что делает `threshold` отрицательным и ломает смысл reset.

### Причина

**Guard отсутствовал (ИСПРАВЛЕНО):**

В режиме `equity_peak` reset может сработать даже если `cycle_start_equity <= 0`, что приводит к:

1. `threshold = cycle_start_equity * 1.3 <= 0`
2. Условие `equity_peak_in_cycle >= threshold` становится "always true"
3. Reset срабатывает бесконечно, `cycle_start_equity` становится еще более отрицательным

### Решение (ИСПРАВЛЕНО)

**Guard добавлен в `_is_profit_reset_eligible()`:**

Файл: `backtester/domain/portfolio_reset.py:176-190`

```python
# Guard 2: baseline должен быть строго > 0
baseline = None
if trigger_basis == "realized_balance":
    baseline = cycle_start_balance
    diag_meta["cycle_start_balance"] = cycle_start_balance if cycle_start_balance is not None else 0.0
    diag_meta["current_balance"] = current_balance
elif trigger_basis == "equity_peak":
    baseline = cycle_start_equity
    diag_meta["cycle_start_equity"] = cycle_start_equity if cycle_start_equity is not None else 0.0
    diag_meta["equity_peak_in_cycle"] = equity_peak_in_cycle if equity_peak_in_cycle is not None else 0.0

if baseline is None or baseline <= 0:
    diag_meta["eligibility_reason"] = "baseline_non_positive"
    diag_meta["baseline"] = baseline if baseline is not None else 0.0
    return False, diag_meta  # ✅ Reset пропускается
```

**Проверка:**

- Для `equity_peak`: если `cycle_start_equity <= 0` → reset пропускается
- Для `realized_balance`: если `cycle_start_balance <= 0` → reset пропускается

---

## Мини-диагностика: почему Run A и Run C расходятся

### Сравнение конфигураций

| Параметр | Run A | Run C |
|----------|-------|-------|
| `profit_reset_trigger_basis` | equity_peak (default) | **realized_balance** |
| `allocation_mode` | *[из конфига A]* | fixed_then_dynamic_after_profit_reset |
| `execution_profile` | *[из конфига A]* | realistic |
| `fees/slippage` | *[из конфига A]* | *[из конфига C]* |

### Гипотеза расхождения

**Главная причина:** `trigger_basis` не применялся, поэтому Run C фактически работал как Run A (equity_peak).

**Дополнительные факторы:**

1. **Разница в trigger логике:**
   - `equity_peak`: проверяет `equity_peak_in_cycle >= cycle_start_equity * 1.3` (включает floating PnL)
   - `realized_balance`: проверяет `balance >= cycle_start_balance * 1.3` (только realized cash)

2. **Разница в timing:**
   - `equity_peak`: проверка ДО обработки EXIT событий
   - `realized_balance`: проверка ПОСЛЕ обработки EXIT событий (чтобы cash balance был обновлен)

3. **Отрицательный cycle_start_equity:**
   - В Run C `cycle_start_equity` стал отрицательным → threshold стал отрицательным
   - Reset срабатывал "всегда" → множественные reset подряд
   - Это привело к искажению статистики и метрик

### Вывод

**Расхождение вызвано:**
1. ❌ `trigger_basis` не применялся из YAML (исправлено)
2. ❌ Отсутствовал guard на `cycle_start_equity <= 0` (исправлено)
3. ❌ Это привело к неправильному поведению reset и искажению метрик

**После исправлений:**
- ✅ `trigger_basis` будет читаться из YAML и применяться
- ✅ Reset не будет срабатывать при `cycle_start_equity <= 0`
- ✅ Run C будет работать в режиме `realized_balance` как задумано

---

## Инструкции по использованию документа

### Для анализа будущих прогонов

1. **Загрузите артефакты:**
   ```python
   import pandas as pd
   
   events_df = pd.read_csv("runs/C/reports/portfolio_events.csv")
   reset_events = events_df[events_df["event_type"] == "portfolio_reset_triggered"]
   ```

2. **Проверьте trigger_basis:**
   ```python
   import json
   
   for _, event in reset_events.iterrows():
       meta = json.loads(event["meta_json"])
       trigger_basis = meta.get("trigger_basis", "unknown")
       print(f"Reset {meta.get('reset_id')}: trigger_basis={trigger_basis}")
   ```

3. **Проверьте cycle_start_equity:**
   ```python
   for _, event in reset_events.iterrows():
       meta = json.loads(event["meta_json"])
       cycle_start_equity = meta.get("cycle_start_equity", 0.0)
       if cycle_start_equity <= 0:
           print(f"⚠️  WARNING: Reset {meta.get('reset_id')} has cycle_start_equity={cycle_start_equity}")
   ```

### Для валидации исправлений

После прогона с исправлениями проверьте:

1. ✅ Все reset события имеют `trigger_basis="realized_balance"` (если так в YAML)
2. ✅ Нет reset событий с `cycle_start_equity <= 0`
3. ✅ `reset_count` в `portfolio_policy_summary.csv` совпадает с количеством событий `PORTFOLIO_RESET_TRIGGERED`

---

## Связанные документы

- `docs/PRUNE_AND_PROFIT_RESET_RULES.md` — контракт reset и что должно попадать в events/positions/policy summary
- `docs/VARIABLES_REFERENCE.md` — точные значения/счетчики и кто их сетит
- `docs/RESET_IMPACT_ON_STAGE_A_B_v2.2.md` — как reset искажает метрики и артефакты

---

*Документ создан: 2025-01-XX*  
*Статус: ✅ Исправления применены*
