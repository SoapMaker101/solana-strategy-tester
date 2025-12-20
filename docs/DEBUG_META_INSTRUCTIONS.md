# Инструкции по отладке meta и поиску root cause

## Добавленные debug-хелперы

### `_dbg_meta(pos, label)`
Печатает диагностическую информацию о позиции:
- `label` - метка события/места в коде
- `pos.signal_id` - идентификатор позиции
- `pos.status` - статус позиции
- `id(pos)` - идентификатор объекта Position
- `id(pos.meta)` - идентификатор объекта meta (если не None)
- `meta_keys` - список ключей в meta (отсортированный)
- `closed_by_reset` - значение флага
- `triggered_portfolio_reset` - значение флага

Включение только через `PORTFOLIO_DEBUG_RESET=1`.

## Места, где добавлен `_dbg_meta()`

### В `_process_portfolio_level_reset()`:
1. **Перед установкой флагов** (строка ~260):
   - `BEFORE_SETTING_FLAGS_in_process_portfolio_level_reset`
2. **После установки флагов** (строка ~262):
   - `AFTER_SETTING_FLAGS_in_process_portfolio_level_reset`
3. **В конце функции** (строка ~293):
   - `FINAL_CHECK_marker_pos_at_end_of_process_portfolio_level_reset`

### В `simulate()` - Основной цикл закрытия позиций:
4. **Перед `pos.meta = pos.meta or {}`** (строка 799):
   - `BEFORE_pos.meta_or_EMPTY_line_797_main_loop_close`
5. **После `pos.meta = pos.meta or {}`** (строка 801):
   - `AFTER_pos.meta_or_EMPTY_line_797_main_loop_close`
6. **После `_process_portfolio_level_reset`** (строка 851):
   - `AFTER_process_portfolio_level_reset_line_846_main_loop`

### В `simulate()` - Runner reset в основном цикле:
7. **Перед `pos.meta = pos.meta or {}`** (строка 709):
   - `BEFORE_pos.meta_or_EMPTY_line_709_runner_reset_trigger`
8. **После `pos.meta = pos.meta or {}`** (строка 711):
   - `AFTER_pos.meta_or_EMPTY_line_709_runner_reset_trigger`
9. **Перед `other_pos.meta = other_pos.meta or {}`** (строка 741):
   - `BEFORE_other_pos.meta_or_EMPTY_line_741_runner_reset_force_close`
10. **После `other_pos.meta = other_pos.meta or {}`** (строка 743):
    - `AFTER_other_pos.meta_or_EMPTY_line_741_runner_reset_force_close`

### В `simulate()` - Portfolio reset с last_closed_position:
11. **После `_process_portfolio_level_reset`** (строка 911):
    - `AFTER_process_portfolio_level_reset_line_911_main_loop_last_closed`

### В `simulate()` - Финальное закрытие позиций (блок "8"):
12. **После `_process_portfolio_level_reset`** (строка 1124):
    - `AFTER_process_portfolio_level_reset_line_1118_final_close`
13. **Перед `pos.meta = pos.meta or {}`** (строка 1145):
    - `BEFORE_pos.meta_or_EMPTY_line_1139_runner_reset`
14. **После `pos.meta = pos.meta or {}`** (строка 1147):
    - `AFTER_pos.meta_or_EMPTY_line_1139_runner_reset`
15. **Перед `other_pos.meta = other_pos.meta or {}`** (строка 1174):
    - `BEFORE_other_pos.meta_or_EMPTY_line_1166_runner_reset`
16. **После `other_pos.meta = other_pos.meta or {}`** (строка 1176):
    - `AFTER_other_pos.meta_or_EMPTY_line_1166_runner_reset`
17. **Перед `pos.meta = pos.meta or {}`** (строка 1223):
    - `BEFORE_pos.meta_or_EMPTY_line_1213_final_close` ⚠️ **КРИТИЧЕСКОЕ МЕСТО**
18. **После `pos.meta = pos.meta or {}`** (строка 1225):
    - `AFTER_pos.meta_or_EMPTY_line_1213_final_close` ⚠️ **КРИТИЧЕСКОЕ МЕСТО**

### В `_process_portfolio_level_reset()` - Force close:
19. **Перед `other_pos.meta = other_pos.meta or {}`** (строка 238):
    - `BEFORE_other_pos.meta_or_EMPTY_line_238_force_close_in_reset`
20. **После `other_pos.meta = other_pos.meta or {}`** (строка 240):
    - `AFTER_other_pos.meta_or_EMPTY_line_238_force_close_in_reset`

### Перед возвратом результата:
21. **Для всех позиций** (строка ~1292):
    - `FINAL_CHECK_before_return_signal_id={pos.signal_id}`

## Список подозрительных мест (где `pos.meta` может перезаписываться)

### Найдено 7 мест с `pos.meta = pos.meta or {}`:

1. **Строка 238** - `_process_portfolio_level_reset()` - force close других позиций
2. **Строка 709** - Runner reset trigger в основном цикле
3. **Строка 741** - Runner reset force close в основном цикле
4. **Строка 800** - Нормальное закрытие в основном цикле
5. **Строка 1146** - Runner reset trigger в финальном закрытии
6. **Строка 1175** - Runner reset force close в финальном закрытии
7. **Строка 1224** - Нормальное закрытие в финальном блоке ⚠️ **САМОЕ ПОДОЗРИТЕЛЬНОЕ**

### Критическое место:

**Строка 1224** - это место, где `pos.meta = pos.meta or {}` выполняется **ПОСЛЕ** того, как `_process_portfolio_level_reset()` уже установил флаги на `marker_pos` (строка 1110-1123).

Последовательность:
1. Portfolio reset срабатывает в блоке "8. Закрываем все оставшиеся открытые позиции" (строка 1100)
2. Вызывается `_process_portfolio_level_reset()` с `marker_pos=pos` (строка 1110-1123)
3. В `_process_portfolio_level_reset()` устанавливаются флаги на `marker_position.meta` (строки 260-261)
4. Затем позиция закрывается нормально (строка 1207-1235)
5. **В строке 1224 выполняется `pos.meta = pos.meta or {}`** - это может быть проблемой!

## Команда для запуска теста

### Windows PowerShell:
```powershell
$env:PORTFOLIO_DEBUG_RESET="1"
python -m pytest tests/portfolio/test_portfolio_runner_reset_portfolio_level.py::test_portfolio_reset_triggered_when_threshold_reached -xvs
```

### Windows CMD:
```cmd
set PORTFOLIO_DEBUG_RESET=1
python -m pytest tests/portfolio/test_portfolio_runner_reset_portfolio_level.py::test_portfolio_reset_triggered_when_threshold_reached -xvs
```

### Linux/Mac:
```bash
export PORTFOLIO_DEBUG_RESET=1
python -m pytest tests/portfolio/test_portfolio_runner_reset_portfolio_level.py::test_portfolio_reset_triggered_when_threshold_reached -xvs
```

## Что искать в логах

1. **Момент установки флагов:**
   - Ищите `AFTER_SETTING_FLAGS_in_process_portfolio_level_reset`
   - Проверьте, что `closed_by_reset=True` и `triggered_portfolio_reset=True`
   - Запомните `id(pos)` и `id(meta)`

2. **Момент потери флагов:**
   - Ищите `BEFORE_pos.meta_or_EMPTY_line_1213_final_close` и `AFTER_pos.meta_or_EMPTY_line_1213_final_close`
   - Проверьте, изменился ли `id(meta)` (если да, то создан новый dict!)
   - Проверьте, остались ли флаги `closed_by_reset` и `triggered_portfolio_reset`

3. **Критический момент:**
   - Если `id(meta)` изменился между `AFTER_SETTING_FLAGS` и `AFTER_pos.meta_or_EMPTY_line_1213_final_close`, значит `pos.meta = pos.meta or {}` создал новый dict
   - Это может произойти, если `pos.meta` был `None` или пустым dict `{}` (что не должно происходить, но возможно)

## Ожидаемый результат

В логах должно быть видно:
1. ✅ Флаги установлены: `AFTER_SETTING_FLAGS_in_process_portfolio_level_reset` показывает `closed_by_reset=True`
2. ❌ Флаги потеряны: `AFTER_pos.meta_or_EMPTY_line_1213_final_close` показывает `closed_by_reset=False`
3. 🔍 Причина: `id(meta)` изменился или флаги отсутствуют в `meta_keys`

## Доказательство root cause

После запуска теста нужно найти в логах:
- **Когда флаг был установлен:** строка с `AFTER_SETTING_FLAGS_in_process_portfolio_level_reset`
- **Когда флаг пропал:** строка с `AFTER_pos.meta_or_EMPTY_line_1213_final_close` (или другая)
- **Какая строка это сделала:** сравнить `id(meta)` до и после `pos.meta = pos.meta or {}`

Если `id(meta)` изменился, значит `pos.meta = pos.meta or {}` создал новый dict, и флаги потеряны.

