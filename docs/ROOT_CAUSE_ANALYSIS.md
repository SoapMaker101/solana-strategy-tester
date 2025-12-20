# Root Cause Analysis: Почему нет closed_by_reset

## Тип C: marker_pos попадает в result.positions, но meta теряется/перетирается

### Конкретное место/ветка кода:

**Файл:** `backtester/domain/portfolio.py`  
**Функция:** `simulate()`  
**Блок:** "8. Закрываем все оставшиеся открытые позиции" (строки 1024-1194)  
**Конкретная строка:** 1180

### Проблема:

В блоке финального закрытия позиций (строка 1180) выполняется:
```python
pos.meta = pos.meta or {}
```

Эта строка выполняется **ПОСЛЕ** того, как `_process_portfolio_level_reset()` уже установил флаги `closed_by_reset=True` и `triggered_portfolio_reset=True` на `marker_pos` (строки 259-260).

Хотя `pos.meta = pos.meta or {}` технически не должно перезаписывать существующий dict (если `pos.meta` уже существует, он остается тем же объектом), проблема возникает в следующем сценарии:

1. Portfolio reset срабатывает в блоке "8. Закрываем все оставшиеся открытые позиции" (строка 1062)
2. Вызывается `_process_portfolio_level_reset()` с `marker_pos=pos`, где `pos` еще открыта (строка 1084)
3. В `_process_portfolio_level_reset()` устанавливаются флаги на `marker_position.meta` (строки 258-260):
   ```python
   marker_position.meta = marker_position.meta or {}
   marker_position.meta["closed_by_reset"] = True
   marker_position.meta["triggered_portfolio_reset"] = True
   ```
4. Затем позиция закрывается нормально (строка 1164-1190)
5. **ПРОБЛЕМА:** В строке 1180 снова выполняется `pos.meta = pos.meta or {}`

Хотя это не должно перезаписывать dict, но если где-то в коде `pos.meta` был установлен в `None` или пустой dict, то флаги теряются.

### Почему именно в этом тесте это случается:

В тесте `test_debug_reset.py`:
- `trade_1` закрывается в основном цикле (может вызвать portfolio reset)
- `trade_2` открывается после `trade_1` и закрывается в блоке "8. Закрываем все оставшиеся открытые позиции"
- Если portfolio reset срабатывает для `trade_2` в блоке "8", то флаги устанавливаются, но затем могут быть потеряны при нормальном закрытии

### Правильная правка:

**Вариант 1 (рекомендуемый):** Убрать избыточную строку `pos.meta = pos.meta or {}` в блоке финального закрытия, если позиция уже имеет установленные флаги reset:

```python
# Строка 1180 - ИЗМЕНИТЬ:
# pos.meta = pos.meta or {}
# НА:
if pos.meta is None:
    pos.meta = {}
# ИЛИ просто убрать эту строку, так как meta всегда инициализируется через default_factory=dict
```

**Вариант 2:** Использовать `pos.meta.update()` вместо перезаписи, если нужно обновить только определенные ключи:

```python
# Вместо:
pos.meta = pos.meta or {}
pos.meta["pnl_sol"] = trade_pnl_sol
pos.meta["fees_total_sol"] = fees_total

# Использовать:
if pos.meta is None:
    pos.meta = {}
pos.meta.setdefault("pnl_sol", trade_pnl_sol)
pos.meta.setdefault("fees_total_sol", fees_total)
```

**Вариант 3 (самый безопасный):** Проверять, не установлены ли уже флаги reset, и не перезаписывать их:

```python
# Строка 1180 - ИЗМЕНИТЬ:
if pos.meta is None:
    pos.meta = {}
# Сохраняем существующие флаги reset, если они есть
existing_reset_flags = {
    "closed_by_reset": pos.meta.get("closed_by_reset", False),
    "triggered_portfolio_reset": pos.meta.get("triggered_portfolio_reset", False),
}
pos.meta["pnl_sol"] = trade_pnl_sol
pos.meta["fees_total_sol"] = fees_total
# Восстанавливаем флаги reset, если они были установлены
if existing_reset_flags["closed_by_reset"]:
    pos.meta["closed_by_reset"] = True
if existing_reset_flags["triggered_portfolio_reset"]:
    pos.meta["triggered_portfolio_reset"] = True
```

### Инварианты, которые должны соблюдаться:

1. **Инвариант 1:** Если `_process_portfolio_level_reset()` установил флаги на `marker_pos`, эти флаги должны сохраниться до возврата результата
2. **Инвариант 2:** `pos.meta` никогда не должен быть `None` после создания Position (инициализируется через `default_factory=dict`)
3. **Инвариант 3:** При обновлении `pos.meta` в разных местах кода, существующие ключи не должны теряться (использовать `update()` или проверять перед установкой)

