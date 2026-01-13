# Отчет о реорганизации репозитория

**Дата:** 2025-01-XX  
**Версия:** 2.2  
**Цель:** Упорядочивание структуры документации и очистка репозитория

## Выполненные задачи

### 1. Реорганизация документации

Создана структура подкаталогов в `docs/`:

- **`docs/architecture/`** — Документация по архитектуре (5 файлов)
  - ARCHITECTURE.md
  - CANONICAL_LEDGER_CONTRACT.md
  - ARCH_FREEZE_RUNNER_v2.2.md
  - ARCH_REBOOT_RUNNER_ONLY.md
  - DATA_PIPELINE_RUNNER_ONLY.md

- **`docs/usage/`** — Руководства пользователя (4 файла)
  - PIPELINE_GUIDE.md
  - VARIABLES_REFERENCE.md
  - SignalFiltering.md
  - runner_config_example.yaml

- **`docs/releases/`** — Релизы и изменения (10 файлов)
  - RELEASE_2.1.9.md
  - RELEASE_NOTES.md
  - CHANGELOG.md
  - KNOWN_ISSUES_2.1.9.md
  - V2.2_IMPLEMENTATION_STATUS.md
  - V1.9_IMPLEMENTATION_STATUS.md
  - V1.6_IMPLEMENTATION_SUMMARY.md
  - V2.0.1_REFACTOR_REPORT.md
  - V2_RUN_CHECKLIST.md
  - RELEASE_V1.10_TAG_INSTRUCTIONS.md

- **`docs/testing/`** — Документация по тестированию (4 файла)
  - TESTING_GUARDS.md
  - TEST_FIX_STAGE_2025-01-06.md
  - TEST_GREEN_BASELINE_2025-01-06.md
  - ETAP_4_TEST_MAP.md

- **`docs/analysis/`** — Внутренние аналитические отчеты (23 файла)
  - Все ETAP_*_COMPLETION_REPORT.md
  - PARTIAL_EXITS_FIX_*.md
  - ROOT_CAUSE_ANALYSIS.md
  - RUN_C_FORENSICS.md
  - PRODUCT_ANALYSIS.md
  - TECHNICAL_ANALYSIS.md
  - И другие аналитические документы

**Всего перемещено:** 46 файлов из корня `docs/` в подкаталоги

### 2. Перемещение корневых файлов

- `REFACTORING_REPORT.md` → `docs/analysis/`
- `RELEASE_V1.10_TAG_INSTRUCTIONS.md` → `docs/releases/`
- `analysis/strategy_trades_refactor.md` → `docs/analysis/`

### 3. Очистка тестовых файлов

Перемещены корневые тестовые файлы в `tests/`:
- `test_debug_reset.py`
- `test_missing_events_manual.py`
- `test_report_mode_logic.py`
- `test_xn_imports.py`
- `test_config_parsing_check.py`

**Всего перемещено:** 5 файлов

### 4. Очистка дубликатов и временных файлов

Удалены:
- `scripts/compare_legacy_vs_replay.py` (пустой файл)
- `scripts/compare_legacy_vs_replay.py.tmp` (временный файл)
- `signals/example_signals — копия.csv` (дубликат)
- `signals/signals_2025-07-01_to_2025-12-14 — копия.csv` (дубликат)
- `temp_run_tests.py` (временный скрипт)
- `run_tests_direct.py` (дубликат)
- `run_tests_fixed.py` (дубликат)
- `run_tests_here.py` (дубликат)
- `run_tests.py` (дубликат, оставлен `run_all_tests.py`)

**Всего удалено:** 9 файлов

### 5. Удаление пустых директорий

- Удалена пустая директория `analysis/` (после перемещения файла)

### 6. Обновление документации

- Обновлен `README.md` с новыми путями к документации
- Добавлен раздел "Documentation Structure" в README.md

## Итоговая статистика

- **Создано подкаталогов:** 5
- **Перемещено файлов документации:** 49
- **Перемещено тестовых файлов:** 5
- **Удалено файлов:** 9
- **Удалено директорий:** 1

## Структура после реорганизации

```
docs/
├── architecture/     # Архитектура и доменные контракты
├── usage/            # Руководства пользователя
├── releases/         # Релизы и изменения
├── testing/         # Документация по тестированию
└── analysis/        # Внутренние аналитические отчеты
```

## Следующие шаги (опционально)

1. Проверить и обновить внутренние ссылки в документах (если есть ссылки на старые пути)
2. Рассмотреть возможность архивации устаревших аналитических отчетов
3. Проверить актуальность отладочных скриптов в `scripts/` и решить, нужны ли они

## Примечания

- Все перемещения сохранены в истории Git
- Структура согласована с README.md
- Обратная совместимость: старые пути могут быть обновлены постепенно
