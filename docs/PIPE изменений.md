# PIPE изменений: Runner-only backtest vNext (Blueprints → Replay)

## Главная цель

1. **Сначала** получить стабильные StrategyTradeBlueprint (strategy_trades.csv)
    
2. **Потом** включить PortfolioReplay по blueprints (feature flag)
    
3. **Потом** удалить legacy путь и time_stop из стратегии
    

---

# ЭТАП 0 — Freeze / контрольная точка (обязательно)

### Цель

Зафиксировать “что было”, чтобы не бояться резать.

### Деливераблы

- git tag: `v2.0.1-legacy` (или текущий semver)
    
- README: коротко “как запустить legacy”
    
- папка `docs/` содержит якорь `ARCH_REBOOT_RUNNER_ONLY.md`
    

### Команды

- `pytest -q` (должно быть зелёным или хотя бы зафиксировать список падений)
    
- один backtest run (чтобы убедиться что проект вообще жив)
    

### Тест-требования

- **Ничего не меняем в тестах на этом этапе**, только фиксация.
    

---

# ЭТАП 1 — Blueprints как отдельный артефакт (без изменений портфеля)

> Это самый важный этап: он возвращает тебе ясность.

### Цель

RunnerStrategy начинает выдавать **StrategyTradeBlueprint**, и мы сохраняем это в `strategy_trades.csv`.  
Портфель пока работает как раньше.

### Важный инвариант

Blueprint **не содержит денег**: никакого SOL size, комиссий, pnl_sol.

### Изменения в коде

1. `backtester/domain/strategy_trade_blueprint.py` (новый)
    
    - dataclasses:
        
        - `StrategyTradeBlueprint`
            
        - `PartialExitBlueprint`
            
        - `FinalExitBlueprint`
            
    - сериализация в dict (для CSV / JSON колонок), например `.to_row()`.
        
2. `RunnerStrategy`
    
    - добавить новый метод **не ломая старый**:
        
        - `on_signal_blueprint(input) -> StrategyTradeBlueprint`
            
    - внутри использовать тот же ladder результат, но упаковка в blueprint.
        
3. Reporter
    
    - новый экспорт `strategy_trades.csv`
        
    - поля:
        
        - `signal_id, strategy_id, contract_address, entry_time, entry_price_raw, entry_mcap_proxy, partial_exits_json, final_exit_json, realized_multiple, max_xn_reached, reason`
            
    - JSON поля — строкой.
        
4. CLI / runner
    
    - после прогона стратегии сохранять `strategy_trades.csv` рядом с остальными файлами.
        

### Тесты (минимум, но железно)

- `test_strategy_blueprint_generated_basic()`
    
    - возвращается blueprint
        
    - entry_time и entry_price_raw валидны
        
    - partial_exits отсортированы по времени
        
    - realized_multiple = Σ(fraction * xn) (если xn хранится как target; если будет actual_xn — тогда по actual)
        
- `test_strategy_trades_csv_export_columns()`
    
    - файл пишется
        
    - колонки присутствуют
        
    - partial_exits_json парсится
        

### Exit criteria (готовность этапа)

- Ты можешь запустить backtest и получить:
    
    - `strategy_trades.csv`
        
    - старые `portfolio_*.csv` без изменений
        
- Тесты этапа зелёные
    

---

# ЭТАП 1.5 — “Санитарная проверка” (восстановить уверенность)

### Цель

Убедиться, что blueprints — стабильны и повторяемы.

### Деливераблы

- маленький скрипт `scripts/inspect_strategy_trades.py`
    
    - читает `strategy_trades.csv`
        
    - выводит:
        
        - сколько blueprints
            
        - сколько с final_exit
            
        - распределение по reason
            
        - среднее кол-во partial exits
            

### Тесты

не обязателен, но полезно.

### Exit criteria

- ты визуально понимаешь, что стратегия делает
    
- документально фиксируем пару “примеров трейдов” (1–2 строки JSON), чтобы потом сравнивать
    

---

# ЭТАП 2 — PortfolioReplay (feature flag), time_stop в стратегии НЕ используется в replay

### Цель

Добавить **Replay путь**, который принимает blueprints и строит portfolio ledger (positions/events/executions) сам.

Legacy путь остаётся рабочим.

### Изменения в коде

1. `backtester/domain/portfolio_replay.py` (новый)
    
    - `PortfolioReplay.replay(blueprints, portfolio_config, market_data) -> PortfolioResult`
        
    - функции:
        
        - allocation / capacity blocking
            
        - executions creation (entry + partial + final/forced)
            
        - events emission
            
        - profit reset
            
        - max_hold_minutes (режим B)
            
2. `PortfolioConfig`
    
    - `use_replay_mode: bool = False`
        
    - `max_hold_minutes: Optional[int] = None` (для режима B)
        
3. `PortfolioEngine.simulate()`
    
    - `if config.use_replay_mode: return PortfolioReplay.replay(...)`
        
    - else legacy
        
4. RunnerLadderEngine (только для replay path)
    
    - при генерации blueprint:
        
        - стратегия **не делает time_stop**
            
        - если уровни не достигнуты: `final_exit=None`
            
    - закрытия по времени делает только portfolio (max_hold_minutes).
        

### Тесты (обязательные)

Новые тесты именно для replay:

1. `test_replay_two_configs_same_blueprints_different_equity()`
    
    - один набор blueprints
        
    - 2 portfolio config (fixed vs dynamic)
        
    - equity curves разные
        
2. `test_replay_capacity_blocking_skips_positions()`
    
    - blueprints > capacity
        
    - часть не применяется
        
    - для неприменённых нет POSITION_OPENED
        
3. `test_replay_profit_reset_emits_chain()`
    
    - reset срабатывает
        
    - есть `PORTFOLIO_RESET_TRIGGERED`
        
    - после него позиции закрыты и есть `POSITION_CLOSED`
        
4. `test_replay_max_hold_closes_positions()`
    
    - blueprint без final_exit
        
    - max_hold_minutes задан
        
    - позиция закрыта с reason=`max_hold_minutes`
        

### MUST KEEP инварианты (должны проходить и в replay)

- linkage events↔executions
    
- pnl source-of-truth equality
    
- monotonic timestamps
    
- reset chain correctness
    
- positions-events consistency  
    (эти пункты прямо описаны в якорном документе)
    
    ARCH_REBOOT_RUNNER_ONLY
    

### Exit criteria

- replay работает под флагом
    
- legacy не сломан
    
- можно прогнать один и тот же `strategy_trades.csv` под разными portfolio configs и получить разные результаты
    

---

# ЭТАП 2.5 — Compare legacy vs replay (контроль)

### Цель

Не “совпасть”, а **понять и объяснить различия**.

### Деливерабл

- `scripts/compare_legacy_vs_replay.py`
    
    - сравнить:
        
        - count positions
            
        - total pnl_sol
            
        - number of resets
            
        - max drawdown
            
    - вывести summary diff
        

### Exit criteria

- различия объяснимы (в первую очередь из-за time_stop vs max_hold и логики forced closes)
    
- нет “хаотических” расхождений типа сломанного linkage
    

---

# ЭТАП 3 — Удаление legacy, вынос time_stop из стратегии полностью

### Цель

Replay становится единственным путём.

### Изменения

- удалить legacy ветку
    
- убрать `time_stop_minutes` из RunnerConfig (breaking)
    
- обновить README/PIPELINE_GUIDE/ARCHITECTURE
    

### Тесты

- удалить legacy-тесты
    
- оставить:
    
    - replay tests
        
    - MUST KEEP инварианты
        

### Exit criteria

- “один путь” без флагов
    
- минимальный набор тестов зелёный
    
- pipeline понятен и стабилен
    

---

# ЭТАП 4 — Чистка тестов (только после этапа 2)

### Цель

Убрать мусор и оставить только то, что защищает архитектуру.

### Правило

Удаляем всё, что:

- тестирует legacy,
    
- тестирует детали реализации вместо инвариантов,
    
- проверяет “старый PnL” или time_stop.
    

Оставляем:

- MUST KEEP
    
- replay tests
    
- 1–2 интеграционных e2e
    

---

# Как работать “не уставая” (режим выполнения)

**Один этап = 1 ветка = 1 PR/мердж = 1 релизная запись.**  
Никаких “по пути ещё чуть-чуть”.

Перед стартом этапа:

- чеклист “что делаем”
    
- критерии выхода
    

После:

- короткий отчет (3–5 строк) “что изменилось / как проверить”
    

---

# Готовый следующий шаг для нового чата

В новом чате ты вставляешь:

1. ссылку/контент якоря `docs/ARCH_REBOOT_RUNNER_ONLY.md`
    
    ARCH_REBOOT_RUNNER_ONLY
    
2. этот PIPE
    
3. и говоришь: **“Начинаем с Этапа 1. Дай Cursor-задачи по файлам/функциям.”**