# Описание изменений для коммита

## Основные изменения

### 🎯 Execution Profiles & Reason-based Slippage
- **Новый модуль:** `backtester/domain/execution_model.py`
  - Реализована система execution profiles с reason-based slippage multipliers
  - Поддержка разных профилей: `realistic`, `stress`, `custom`
  - Slippage применяется к ценам входа/выхода в зависимости от причины выхода (TP, SL, timeout)
  - CLI опция `--execution-profile` для переопределения профиля

### 📊 Trade Features & Export Improvements
- **Новый модуль:** `backtester/domain/trade_features.py`
  - Market cap proxy (entry/exit mcap, mcap_change_pct)
  - Volume & volatility windows (5m/15m/60m) до входа (без data leakage)
  - Автоматический экспорт trades table в CSV с расплющенным meta

### 🔧 Reporting Modes
- **Обновлен:** `main.py`
  - Новые режимы отчетности: `none`, `summary`, `top`, `all`
  - Параметры `--report-mode`, `--report-top-n`, `--report-metric`
  - Флаги `--no-charts` и `--no-html` для управления генерацией отчетов

### 🛡️ Global Deterministic Warning Deduplication
- **Обновлен:** `backtester/domain/rr_utils.py`
  - Module-level singleton для дедупликации предупреждений
  - Thread-safe реализация с детерминированными ключами
  - Автоматический вывод summary в конце прогона

### 📈 Multi-scale Window Stability Analysis
- **Обновлен:** `backtester/research/window_aggregator.py`
  - Поддержка мульти-масштабного разбиения по времени (split_counts)
  - CLI опция `--split-counts` в `run_stage_a.py`

### 🐛 Bugfixes
- Исправлена валидация pool_id (принимает 43-44 символа для Solana addresses)
- Добавлена защита от изменения pool_id в многопоточной среде
- Реализован cache-only режим (`prefer_cache_if_exists`)
- Исправлена формула расчета `max_exposure` в портфеле
- Исправлена обработка меток runner reset

### 📚 Документация
- **Новый файл:** `docs/VARIABLES_REFERENCE.md` (1059 строк)
  - Полный справочник всех переменных проекта
  - Описание параметров портфеля, стратегий, данных, CLI аргументов
  - Статус параметров и связи между ними
- **Обновлен:** `docs/CHANGELOG.md` - добавлена история всех изменений
- **Обновлен:** `README.md` - актуализирована структура проекта и описание функций
- **Обновлен:** `RELEASE_NOTES.md` - описание релиза Phase 4+

### ⚙️ Конфигурация
- **Обновлен:** `config/backtest_example.yaml`
  - Добавлены execution profiles (realistic, stress)
  - Обновлены параметры портфеля
- **Обновлен:** `config/strategies_example.yaml`
  - Расширены примеры стратегий

### 🧪 Тесты
- Добавлены тесты для execution profiles
- Обновлены тесты для trade features
- Добавлены защитные тесты для reset policy
- Исправлены тесты rate limiter

## Статистика изменений

- **53 файла изменено**
- **+4106 строк добавлено**
- **-3068 строк удалено**
- **Новые файлы:**
  - `backtester/domain/execution_model.py`
  - `backtester/domain/trade_features.py`
  - `docs/VARIABLES_REFERENCE.md`
  - `tests/portfolio/test_execution_profiles.py`

## Обратная совместимость

✅ Все изменения обратно совместимы:
- Legacy конфиги с `slippage_pct` продолжают работать (с предупреждением)
- Дефолтный realistic профиль применяется автоматически
- Существующие скрипты и конфигурации работают без изменений

## Рекомендуемое сообщение коммита

```
feat: Execution Profiles, Trade Features, Reporting Modes & Bugfixes

Major features:
- Execution profiles with reason-based slippage multipliers (realistic/stress/custom)
- Trade features: market cap proxy, volume/volatility windows (5m/15m/60m)
- Reporting modes: none/summary/top/all with CLI controls
- Global deterministic warning deduplication (thread-safe)
- Multi-scale window stability analysis (split_counts)

Bugfixes:
- Fixed pool_id validation (43-44 chars for Solana addresses)
- Fixed max_exposure calculation formula
- Fixed runner reset flags handling
- Added cache-only mode (prefer_cache_if_exists)

Documentation:
- Added VARIABLES_REFERENCE.md (1059 lines) - complete variable reference
- Updated CHANGELOG.md with full change history
- Updated README.md and RELEASE_NOTES.md

Tests:
- Added execution profiles tests
- Updated trade features tests
- Fixed rate limiter tests

53 files changed: +4106 -3068
All changes are backward compatible.
```










