# Архитектура проекта Solana Strategy Tester v2.1.9

**Версия фиксации:** 2.1.9 (Frozen Baseline)  
**Дата фиксации:** 2025-01-06  
**Режим:** Runner-only  
**Статус:** Stable / Frozen

---

## 1. Введение

### Что это за проект

Solana Strategy Tester — это backtesting framework для торговых стратегий на блокчейне Solana. Система предназначена для тестирования стратегий на исторических данных с использованием внешних торговых сигналов.

### Почему режим Runner-only

Версия 2.1.9 работает исключительно в режиме Runner-only. Это означает:

- Поддерживается только тип стратегии `Runner` (лестница тейк-профитов)
- Все стратегии используют единый контракт `RunnerLadderEngine`
- Legacy стратегии (RR, RRD) удалены из кодовой базы
- Архитектура упрощена для поддержки только одного типа стратегий

### Почему архитектура считается стабилизированной, но не финальной

Версия 2.1.9 фиксирует стабильное рабочее состояние проекта:

- ✅ Тесты зелёные: 306 passed, 0 warnings
- ✅ Архитектура стабилизирована: Runner-only режим зафиксирован
- ✅ Контракты защищены: Guard-тесты добавлены
- ✅ Legacy API сохранён: Обратная совместимость гарантирована

Но есть известные технические проблемы, которые осознанно не исправлялись в этой версии (см. `docs/KNOWN_ISSUES_2.1.9.md`). Версия 2.2 будет посвящена cleanup и typing improvements.

---

## 2. Архитектурные принципы

### Separation of concerns

Система разделена на четкие слои с явно определенными ответственностями:

- **Application layer** — координация и загрузка данных
- **Domain layer** — бизнес-логика и модели данных
- **Execution layer** — применение slippage и комиссий
- **Portfolio / Replay layer** — симуляция портфеля и событий
- **Audit layer** — проверка инвариантов и консистентности
- **Decision layer** — отбор стратегий по критериям
- **Reporting layer** — экспорт результатов

### Event-driven portfolio

Портфель работает на основе событий (event-driven):

- Каждое действие портфеля эмитит каноническое событие (`PortfolioEvent`)
- События имеют фиксированные типы: `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- События хранятся в каноническом ledger (`portfolio_events.csv`)
- Порядок событий детерминирован и проверяется аудитом

### Canonical ledger как source of truth

Канонический ledger (`portfolio_events.csv`) является источником истины для всех решений портфеля:

- CSV файлы (`portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv`) — source of truth
- XLSX файлы — best-effort экспорт, не являются каноникой
- Все расчеты PnL основаны на fills ledger, а не на `exit_price` напрямую
- `realized_multiple` вычисляется из fills ledger для каждой позиции

### Legacy compatibility как ограничение

Система поддерживает обратную совместимость с legacy API:

- Legacy reasons (`tp`, `sl`, `timeout`) автоматически маппятся в canonical
- `StrategyOutput.canonical_reason` — optional, auto-computed в `__post_init__`
- Legacy reasons сохраняются в поле `reason` для совместимости
- Маппинг: `"tp"` → `"ladder_tp"`, `"sl"` → `"stop_loss"`, `"timeout"` → `"time_stop"`

---

## 3. Слои системы (строго AS-IS)

### Application Layer

**Файлы:** `backtester/application/runner.py`

**Назначение:**
- Загрузка сигналов из CSV через `SignalLoader`
- Загрузка свечей через `PriceLoader` (CSV или GeckoTerminal API)
- Координация стратегий для обработки сигналов
- Сбор результатов от всех стратегий
- Парсинг конфигурации из YAML

**Входы:**
- CSV файл с сигналами (`signal_id`, `contract_address`, `timestamp`)
- YAML конфигурация стратегий и бэктеста
- Свечи (из кеша или API)

**Выходы:**
- Список `StrategyOutput` для каждой стратегии и сигнала
- Результаты передаются в Portfolio Engine

**Ключевые файлы:**
- `backtester/application/runner.py` — `BacktestRunner` класс

**Чего слой НЕ делает:**
- Не вычисляет PnL (это делает Portfolio Engine)
- Не применяет slippage (это делает ExecutionModel)
- Не создает события (это делает Portfolio Engine)
- Не проверяет инварианты (это делает Audit layer)

**Контракты:**
- `_parse_bool` — парсит `"true"/"false"`, `1/0`, `True/False` → `bool`
- `_parse_int_optional` — парсит `"4320"`, `0`, `None` → `int` или `None`
- **Критично:** `0 != None` — `max_hold_minutes=0` это валидное значение, не отсутствие

### Domain Layer

**Файлы:** `backtester/domain/`

**Назначение:**
- Модели данных (`StrategyOutput`, `Position`, `PortfolioEvent`, `StrategyTradeBlueprint`)
- Runner стратегии (`RunnerStrategy`, `RunnerLadderEngine`)
- Execution модели (`ExecutionModel`, slippage, fees)
- Portfolio engine (`PortfolioEngine`, `PortfolioReplay`)

**Входы:**
- `StrategyInput` (сигнал + свечи + глобальные параметры)
- Конфигурация портфеля (`PortfolioConfig`)

**Выходы:**
- `StrategyOutput` с результатами симуляции
- `Position` объекты для портфеля
- `PortfolioEvent` события

**Ключевые файлы:**
- `backtester/domain/models.py` — модели данных
- `backtester/domain/runner_strategy.py` — `RunnerStrategy`
- `backtester/domain/runner_ladder.py` — `RunnerLadderEngine`
- `backtester/domain/portfolio.py` — `PortfolioEngine`
- `backtester/domain/execution_model.py` — `ExecutionModel`
- `backtester/domain/strategy_trade_blueprint.py` — blueprints для replay

**Чего слой НЕ делает:**
- Не загружает данные (это делает Application layer)
- Не проверяет инварианты (это делает Audit layer)
- Не отбирает стратегии (это делает Decision layer)
- Не экспортирует CSV (это делает Reporting layer)

**Контракты:**
- `StrategyOutput.canonical_reason` — optional, auto-computed в `__post_init__`
- Legacy reasons (`tp`/`sl`/`timeout`) → canonical mapping
- `position_id` — UUID, уникальный идентификатор
- `realized_multiple` — из fills ledger, не из `exit_price`

### Execution Layer

**Файлы:** `backtester/domain/execution_model.py`

**Назначение:**
- Применение slippage к ценам входа и выхода
- Применение комиссий (swap fee, LP fee, network fee)
- Нормализация reason в exit type для execution profiles
- Поддержка execution profiles (realistic, stress, custom)

**Входы:**
- Цены (entry/exit) без slippage
- Reason выхода (legacy или canonical)
- Execution profile конфигурация

**Выходы:**
- Эффективные цены с учетом slippage
- Комиссии в SOL

**Ключевые файлы:**
- `backtester/domain/execution_model.py` — `ExecutionModel`, `ExecutionProfileConfig`

**Чего слой НЕ делает:**
- Не создает позиции (это делает Portfolio Engine)
- Не эмитит события (это делает Portfolio Engine)
- Не проверяет инварианты (это делает Audit layer)

**Контракты:**
- `_normalize_reason_to_exit_type` — нормализует reason в exit type для slippage
- Exit types: `exit_tp`, `exit_sl`, `exit_timeout`, `exit_manual`
- `network_fee()` — возвращает `float` (0.0 если `None`)

### Portfolio / Replay Layer

**Файлы:** `backtester/domain/portfolio.py`, `backtester/domain/replay.py`

**Назначение:**
- Симуляция портфеля с учетом баланса и capacity rules
- Создание позиций и событий
- Replay mode (blueprint → position conversion)
- Execution ledger (fills для каждой позиции)
- Profit reset и capacity prune логика

**Входы:**
- `StrategyOutput` от стратегий
- `PortfolioConfig` с настройками портфеля
- `StrategyTradeBlueprint` для replay mode

**Выходы:**
- `Position` объекты
- `PortfolioEvent` события
- `PortfolioResult` с итоговой статистикой

**Ключевые файлы:**
- `backtester/domain/portfolio.py` — `PortfolioEngine`, `PortfolioConfig`, `PortfolioStats`
- `backtester/domain/portfolio_replay.py` — `PortfolioReplay`
- `backtester/domain/portfolio_events.py` — `PortfolioEvent`, `PortfolioEventType`
- `backtester/domain/position.py` — `Position`

**Чего слой НЕ делает:**
- Не проверяет инварианты (это делает Audit layer)
- Не отбирает стратегии (это делает Decision layer)
- Не экспортирует CSV (это делает Reporting layer)

**Контракты:**
- Канонические события: `POSITION_OPENED`, `POSITION_PARTIAL_EXIT`, `POSITION_CLOSED`, `PORTFOLIO_RESET_TRIGGERED`
- Market close price — `candles[-1].close`
- Partial exits — `PartialExitBlueprint` с `fraction` и `level`
- `position_id` — UUID, генерируется автоматически

### Audit Layer

**Файлы:** `backtester/audit/invariants.py`, `backtester/audit/run_audit.py`

**Назначение:**
- Проверка инвариантов (P0/P1/P2)
- Reason consistency checks
- Event chain validation
- Missing events detection
- Блокировка Stage A/B при P0 аномалиях

**Входы:**
- `portfolio_positions.csv`
- `portfolio_events.csv`
- `portfolio_executions.csv`

**Выходы:**
- CSV файл с аномалиями (`audit_anomalies.csv`)
- Статистика по P0/P1/P2 аномалиям
- Exit code 2 при P0 > 0 (блокирует Stage A/B)

**Ключевые файлы:**
- `backtester/audit/invariants.py` — `InvariantChecker`, `Anomaly`, `AnomalyType`
- `backtester/audit/run_audit.py` — CLI entry point

**Чего слой НЕ делает:**
- Не исправляет ошибки (только обнаруживает)
- Не изменяет данные (только читает)
- Не принимает решения (только блокирует при P0)

**Контракты:**
- `normalize_reason` — family-based нормализация
- `check_reason_consistency` — epsilon rules для TP/SL
- P0 anomalies блокируют Stage A/B

### Decision Layer (Stage A / Stage B)

**Файлы:** `backtester/research/run_stage_a.py`, `backtester/decision/run_stage_b.py`

**Назначение Stage A:**
- Агрегация сделок по временным окнам
- Расчет метрик устойчивости стратегий
- Генерация `strategy_stability.csv`

**Назначение Stage B:**
- Отбор стратегий по критериям (V1/V2)
- Gate логика для V2 критериев
- Генерация `strategy_selection.csv`

**Входы Stage A:**
- `portfolio_positions.csv` (executed positions)

**Входы Stage B:**
- `strategy_stability.csv` из Stage A

**Выходы Stage A:**
- `strategy_stability.csv` с метриками устойчивости

**Выходы Stage B:**
- `strategy_selection.csv` с результатами отбора

**Ключевые файлы:**
- `backtester/research/run_stage_a.py` — CLI entry point для Stage A
- `backtester/research/strategy_stability.py` — расчет метрик устойчивости
- `backtester/research/window_aggregator.py` — агрегация по окнам
- `backtester/decision/run_stage_b.py` — CLI entry point для Stage B
- `backtester/decision/strategy_selector.py` — логика отбора
- `backtester/decision/selection_rules.py` — критерии отбора

**Чего слой НЕ делает:**
- Не изменяет execution (decision не влияет на execution)
- Не проверяет инварианты (это делает Audit layer)
- Не экспортирует XLSX (это делает Reporting layer)

**Контракты:**
- V1 criteria (base) — обязательные: `survival_rate`, `pnl_variance`, `worst_window_pnl`, `median_window_pnl`, `windows_total`
- V2 Runner criteria — опциональные (только если есть колонки): `hit_rate_x4 >= 0.10`, `tail_pnl_share >= 0.30`, `non_tail_pnl_share >= -0.20`
- V2 gate: проверка наличия колонок перед применением
- `select_strategies` — валидация обязательных колонок, `ValueError` если отсутствуют

### Reporting Layer

**Файлы:** `backtester/infrastructure/reporter.py`, `backtester/infrastructure/xlsx_writer.py`

**Назначение:**
- Экспорт CSV (positions, events, executions)
- Экспорт XLSX (report pack)
- Column ordering, empty string handling
- Best-effort экспорт (XLSX не является каноникой)

**Входы:**
- `Position` объекты
- `PortfolioEvent` события
- `PortfolioResult` статистика

**Выходы:**
- `portfolio_positions.csv`
- `portfolio_events.csv`
- `portfolio_executions.csv`
- `portfolio_summary.csv` / `strategy_summary.csv`
- XLSX report pack (best-effort)

**Ключевые файлы:**
- `backtester/infrastructure/reporter.py` — `Reporter` класс
- `backtester/infrastructure/xlsx_writer.py` — XLSX экспорт
- `backtester/infrastructure/reporting/report_pack.py` — сборка report pack

**Чего слой НЕ делает:**
- Не проверяет инварианты (это делает Audit layer)
- Не принимает решения (это делает Decision layer)
- Не изменяет данные (только экспортирует)

**Контракты:**
- `portfolio_events.csv` — фиксированный порядок колонок: `["timestamp", "event_type", "strategy", "signal_id", "contract_address", "position_id", "event_id", "reason", "meta_json"]`
- `final_exit_json` — `""` вместо `NaN`
- `quoting=csv.QUOTE_ALL` для CSV

---

## 4. Canonical Ledger

### Зачем введён

Canonical ledger (`portfolio_events.csv`) введен для:

- Единого источника истины для всех решений портфеля
- Детерминированного порядка событий
- Возможности replay симуляции
- Аудита и проверки инвариантов

### Какие события существуют

Канонические типы событий:

- `POSITION_OPENED` — открытие позиции
- `POSITION_PARTIAL_EXIT` — частичное закрытие позиции (ladder TP)
- `POSITION_CLOSED` — полное закрытие позиции
- `PORTFOLIO_RESET_TRIGGERED` — срабатывание portfolio-level reset

### Что считается каноникой

Канонические данные:

- `portfolio_events.csv` — канонический event ledger
- `portfolio_positions.csv` — positions-level source of truth
- `portfolio_executions.csv` — execution ledger (fills)

Канонические причины закрытия:

- `ladder_tp` — лестница тейк-профитов
- `stop_loss` — стоп-лосс
- `time_stop` — таймаут
- `capacity_prune` — принудительное закрытие по capacity
- `profit_reset` — принудительное закрытие по profit reset
- `manual_close` — ручное закрытие
- `no_entry` — вход не состоялся
- `error` — ошибка
- `max_hold_minutes` — превышение максимального времени удержания

### Почему CSV / XLSX не source of truth

CSV файлы (`portfolio_positions.csv`, `portfolio_events.csv`, `portfolio_executions.csv`) являются source of truth.

XLSX файлы являются best-effort экспортом:

- Могут содержать агрегации и вычисления
- Могут иметь форматирование и дополнительные колонки
- Не гарантируют детерминированность
- Используются для удобства просмотра, но не для программной обработки

---

## 5. StrategyOutput и совместимость

### Legacy reason

Поле `reason` в `StrategyOutput` может содержать legacy значения:

- `"tp"` — legacy take profit
- `"sl"` — legacy stop loss
- `"timeout"` — legacy timeout

Legacy reasons сохраняются для обратной совместимости со старыми тестами и кодом.

### Canonical canonical_reason

Поле `canonical_reason` содержит каноническую причину выхода:

- `"ladder_tp"` — лестница тейк-профитов
- `"stop_loss"` — стоп-лосс
- `"time_stop"` — таймаут
- И другие канонические причины (см. раздел 4)

### Почему canonical_reason optional

`canonical_reason` является optional, потому что:

- Автоматически вычисляется в `__post_init__` если не задан
- Позволяет использовать legacy reasons без явного указания canonical
- Обеспечивает обратную совместимость

### Как работает auto-mapping

Автоматический маппинг legacy → canonical:

1. Проверяется `meta["ladder_reason"]` (имеет приоритет)
2. Если `reason` уже канонический — используется как есть
3. Иначе применяется маппинг:
   - `"tp"` → `"ladder_tp"`
   - `"sl"` → `"stop_loss"`
   - `"timeout"` → `"time_stop"`
4. Если reason не найден в маппинге — используется `"error"`

Код маппинга находится в `backtester/domain/models.py`, метод `__post_init__` класса `StrategyOutput`.

---

## 6. ExecutionModel

### Exit types

ExecutionModel нормализует reason в exit type для применения slippage:

- TP family (`tp`, `tp_*`, `ladder_tp`) → `"exit_tp"`
- SL family (`sl`, `stop_loss`) → `"exit_sl"`
- Timeout family (`timeout`, `time_stop`, `max_hold_minutes`) → `"exit_timeout"`
- Manual/forced (`manual_close`, `profit_reset`, `capacity_prune`) → `"exit_manual"`

### Reason families

Reason families используются для:

- Нормализации reason в exit type
- Применения правильного slippage multiplier
- Группировки причин выхода в аудите

### Network fee

Network fee — фиксированная комиссия сети в SOL:

- Вычитается отдельно от процентных комиссий
- `network_fee()` возвращает `float` (0.0 если `None`)
- Применяется к каждому swap/round-trip

### Execution profiles

Execution profiles позволяют задавать разные slippage multipliers для разных типов событий:

- `realistic` — реалистичные slippage multipliers
- `stress` — стрессовые slippage multipliers
- `custom` — пользовательские настройки

Профили задаются в `PortfolioConfig.fee_model.profiles`.

---

## 7. Архитектурные ограничения v2.1.9

### Runner-only

Версия 2.1.9 работает только с Runner стратегиями:

- Все стратегии используют `RunnerStrategy`
- Все стратегии используют `RunnerLadderEngine` для симуляции
- Legacy стратегии (RR, RRD) удалены

### Нет live-trading

Система предназначена только для backtesting:

- Нет подключения к реальным биржам
- Нет отправки ордеров
- Нет управления реальным портфелем

### Нет ML

Система не содержит компонентов машинного обучения:

- Нет обучения моделей
- Нет предсказаний
- Нет оптимизации гиперпараметров через ML

### Нет stateful orchestration

Система не имеет stateful orchestration:

- Каждый запуск независим
- Нет сохранения состояния между запусками
- Нет распределенной обработки

---

## 8. Что намеренно не включено

### Планы

Документ не содержит планов на будущее:

- Нет roadmap
- Нет TODO списков
- Нет описания будущих версий

### Улучшения

Документ не предлагает улучшений:

- Нет рекомендаций по рефакторингу
- Нет предложений по оптимизации
- Нет альтернативных подходов

### Рефакторинг

Документ не описывает рефакторинг:

- Нет планов по изменению архитектуры
- Нет описания технического долга (это в `TECHNICAL_ANALYSIS.md`)
- Нет миграционных путей

### Версия 2.2

Документ не описывает версию 2.2:

- Нет планов на следующую версию
- Нет описания изменений
- Нет breaking changes

---

## Ссылки

- `docs/RELEASE_2.1.9.md` — полное описание релиза
- `docs/KNOWN_ISSUES_2.1.9.md` — известные проблемы
- `docs/TEST_GREEN_BASELINE_2025-01-06.md` — контракты и guard-тесты
- `docs/CANONICAL_LEDGER_CONTRACT.md` — спецификация канонического ledger
- `docs/PIPELINE_GUIDE.md` — описание пайплайна данных
