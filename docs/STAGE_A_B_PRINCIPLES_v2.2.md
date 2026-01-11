# Stage A/B Principles (low-N evolution) v2.2

**Версия:** 2.2  
**Дата:** 2025-01-XX  
**Статус:** Спецификация документации (без изменения кода)

---

## Содержание

1. [Контекст и терминология](#1-контекст-и-терминология)
2. [Stage A — назначение и инварианты](#2-stage-a--назначение-и-инварианты)
3. [Stage B — назначение и контракты](#3-stage-b--назначение-и-контракты)
4. [Low-N evolution — правила и статусы](#4-low-n-evolution--правила-и-статусы)
5. [Debug cookbook](#5-debug-cookbook)
6. [Привязка к исходникам](#6-привязка-к-исходникам)
7. [Acceptance criteria](#7-acceptance-criteria)

---

## 1. Контекст и терминология

### 1.1 Что такое Stage A и Stage B

**Stage A (Research Layer)** — этап агрегации метрик по временным окнам. Работает на исполненных портфельных позициях (`portfolio_positions.csv`), вычисляет метрики устойчивости стратегий, но **не принимает решений**. Это чистый исследовательский слой.

**Stage B (Decision Layer)** — этап отбора стратегий по критериям. Читает результаты Stage A (`strategy_stability.csv`), применяет формализованные критерии отбора (V1 core + опционально Runner/V2), выдает `strategy_selection.csv` с булевым флагом `passed`.

### 1.2 Runner-only аксиомы

- Система работает только со стратегиями типа `Runner` (v2.0+)
- Все стратегии используют `RunnerStrategy` и `RunnerLadderEngine`
- Источник данных для Stage A/B: `portfolio_positions.csv` (executed positions, positions-level агрегат)
- Stage A/B **не работают** со strategy-level trades (устаревший подход)

### 1.3 Audit gate (P0 блокирует Stage A/B)

**Аксиома безопасности:** Если audit обнаружил P0 аномалии, Stage A и Stage B **блокируются** и отказываются запускаться (exit code 2).

**Файлы проверки:**
- `backtester/audit/run_audit.py` — функция `audit_run()` возвращает `(p0_count, p1_count)`
- `backtester/research/run_stage_a.py` — проверка P0 перед запуском (строка 104-107)
- `backtester/decision/run_stage_b.py` — проверка P0 перед запуском (строка 96-99)

**Почему это важно:** P0 аномалии означают некорректные данные (например, невалидные цены, неправильный PnL). Метрики Stage A на таких данных будут неверными, а решения Stage B — необоснованными.

### 1.4 Термины: window, split_count, windows_total/min_windows

**Window (окно)** — временной период, на который разбиваются все сделки стратегии. Окна равны по длительности (time-based split).

**split_count** — количество окон для разбиения всего периода сделок. Например, `split_count=3` означает деление периода на 3 равных окна. По умолчанию используется `DEFAULT_SPLITS = [2, 3, 4, 5]`.

**windows_total** — общее количество окон для стратегии (равно `split_count`). **ВАЖНО:** Включаются **все** окна, даже пустые (для корректного расчёта `survival_rate`).

**min_windows** — минимальное количество окон, необходимое для честного анализа. Это критерий Stage B. По умолчанию `DEFAULT_CRITERIA_V1.min_windows = 3`.

**windows_positive** — количество окон с положительным PnL (`total_pnl_sol > 0`).

### 1.5 Разделение статусов: reject vs insufficient_data

**`passed`** — стратегия прошла все критерии отбора (hard-gate и soft-gate).

**`rejected`** (в будущем: `rejected`) — данных достаточно, но стратегия **не проходит** критерии отбора:
- `survival_rate < min_survival_rate`
- `pnl_variance > max_pnl_variance`
- `worst_window_pnl < min_worst_window_pnl`
- и т.д.

**`insufficient_data`** (будущий статус) — данных **недостаточно** для честного решения:
- `windows_total < min_windows`
- `trades_total < min_trades` (будущий критерий)
- метрики нестабильны из-за малой выборки

**Ключевое различие:**
- `rejected` = честное отклонение на основе данных
- `insufficient_data` = "мы не можем принять решение, данных мало" (не ошибка стратегии, а ограничение данных)

---

## 2. Stage A — назначение и инварианты

### 2.1 Назначение

Stage A агрегирует метрики по временным окнам для каждой стратегии. Это **исследовательский слой** — он не отбирает, не режет, не принимает решений. Stage A только считает и сохраняет метрики.

### 2.2 Точка входа

**Файл:** `backtester/research/run_stage_a.py`  
**Функция:** `main()`  
**CLI команда:**
```bash
python -m backtester.research.run_stage_a --reports-dir output/reports --splits 2 3 4 5
```

**Параметры:**
- `--trades` (опционально): путь к `portfolio_positions.csv` (по умолчанию ищется в `--reports-dir`)
- `--reports-dir`: директория для выходных файлов (по умолчанию `output/reports`)
- `--splits`: список значений `split_count` (по умолчанию `DEFAULT_SPLITS = [2, 3, 4, 5]`)

### 2.3 Входные данные

**Основной вход:** `portfolio_positions.csv` (positions-level, executed positions)

**Обязательные колонки** (валидируются в `window_aggregator.validate_trades_table()`):
- `strategy` — название стратегии
- `signal_id` — идентификатор сигнала
- `contract_address` — адрес контракта
- `entry_time` — время входа (ISO, UTC)
- `exit_time` — время выхода (ISO, UTC)
- `status` — статус (должен быть `"closed"`)
- `pnl_sol` — портфельный PnL в SOL (**обязательно**)
- `exec_entry_price`, `exec_exit_price` — исполненные цены

**ВАЖНО:** Stage A **отклоняет** executions-level CSV (колонка `event_type`). Используется только positions-level агрегат.

### 2.4 Выходные данные

**Основной выход:** `strategy_stability.csv`

**Колонки базовых метрик:**
- `strategy` — название стратегии
- `split_count` — количество окон
- `survival_rate` — доля окон с положительным PnL
- `pnl_variance` — дисперсия PnL по окнам
- `worst_window_pnl` — наихудший PnL окна
- `best_window_pnl` — наилучший PnL окна
- `median_window_pnl` — медианный PnL окна
- `windows_positive` — количество окон с положительным PnL
- `windows_total` — общее количество окон (равно `split_count`)
- `trades_total` — общее количество исполненных сделок стратегии

**Опциональные Runner-метрики** (если стратегия Runner и есть `portfolio_positions.csv`):
- `hit_rate_x2` — доля сделок, достигших x2
- `hit_rate_x5` — доля сделок, достигших x5
- `hit_rate_x4` — доля сделок, достигших x4 (tail threshold)
- `p90_hold_days` — 90-й перцентиль времени удержания (дни)
- `tail_contribution` — доля PnL от сделок с `max_xn_reached >= 5.0` (legacy)
- `tail_pnl_share` — доля realized PnL от tail сделок (`max_xn_reached >= 4.0`)
- `non_tail_pnl_share` — доля realized PnL от non-tail сделок (может быть отрицательной)
- `max_drawdown_pct` — максимальная просадка портфеля (из `portfolio_summary.csv`)

**Дополнительные выходы:**
- `stage_a_summary.csv` — детальная таблица по каждому окну (для дебага)
- `stage_a_report.xlsx` — Excel отчёт с несколькими листами

### 2.4.1 Aggregated outputs (across split_count)

Stage A генерирует два типа выходных данных:

**Per-split outputs (diagnostic/sensitivity view):**
- `strategy_stability.csv` — по одной строке на (strategy, split_count)
- Используется для анализа чувствительности к разбиению на окна
- Показывает метрики для каждого значения `split_count` отдельно

**Aggregated outputs (robustness view):**
- `strategy_stability_agg.csv` — **1 строка на стратегию** (агрегировано по всем `split_count`)
- Генерируется автоматически, если в `strategy_stability.csv` присутствует колонка `split_count`
- Вычисляет метрики робастности стратегии по всем разбиениям

**Агрегированные метрики в `strategy_stability_agg.csv`:**
- `splits_total` — количество значений `split_count`, по которым агрегирована стратегия
- `median_survival_rate` — медианный `survival_rate` по всем `split_count`
- `median_median_window_pnl` — медиана медианных PnL окон по всем `split_count`
- `worst_case_window_pnl` — минимальный `worst_window_pnl` по всем `split_count` (худший случай)
- `max_pnl_variance` — максимальный `pnl_variance` по всем `split_count`
- `max_pnl_variance_norm` — максимальный `pnl_variance_norm` по всем `split_count` (если присутствует)

**Важно:**
- Aggregated файл **НЕ заменяет** per-split файл, а **дополняет** его
- Aggregation выполняется по всем значениям `split_count` из `strategy_stability.csv`
- **Stage A is a research layer. Aggregation is a robustness view, not a decision.**

**Модуль агрегации:**
- `backtester/decision/selection_aggregator.py` — функция `aggregate_stability()`
- Вызывается автоматически в `backtester/research/run_stage_a.py` после генерации `strategy_stability.csv`

### 2.5 Метрики Stage A — формулы и смысл

#### 2.5.1 Window-based метрики

**survival_rate** (доля выживших окон):
```
survival_rate = windows_positive / windows_total
```
- `windows_positive` = количество окон с `total_pnl_sol > 0`
- `windows_total` = общее количество окон (равно `split_count`)
- **Важно:** Пустые окна (0 сделок) имеют `total_pnl_sol = 0.0`, поэтому считаются невыжившими

**pnl_variance** (дисперсия PnL по окнам, legacy):
```
pnl_variance = variance([window_pnl_1, window_pnl_2, ..., window_pnl_N])
```
- Используется `statistics.variance()` из Python stdlib
- Показывает стабильность результатов по окнам
- **Единицы измерения:** SOL² (не нормализовано к размеру портфеля)
- **Ограничение:** Зависит от абсолютных значений PnL, что затрудняет сравнение стратегий с разными начальными балансами

#### 2.5.2 Normalized PnL variance

**pnl_variance_norm** (нормализованная дисперсия PnL по окнам):
```
pnl_variance_norm = variance([window_pnl_1 / initial_balance_sol, window_pnl_2 / initial_balance_sol, ..., window_pnl_N / initial_balance_sol])
```
- `initial_balance_sol` берётся из portfolio configuration (initial balance)
- Единицы измерения: **безразмерная величина** (доля капитала)
- Показывает стабильность результатов по окнам, нормализованную к размеру портфеля

**Преимущества нормализации:**
- Устранение несоответствия единиц измерения (SOL² → безразмерная доля)
- Корректное сравнение стратегий с разными начальными балансами
- Согласованность с порогами Stage B (например, `max_pnl_variance = 0.15` интерпретируется как 15% от начального баланса)

**Приоритет использования:**
- `pnl_variance_norm` — **предпочтительная метрика** для Stage B decision
- `pnl_variance` (legacy) — остаётся для обратной совместимости и диагностики
- Stage B использует `pnl_variance_norm` если она присутствует, иначе fallback на `pnl_variance`

**worst_window_pnl** (наихудший PnL окна):
```
worst_window_pnl = min([window_pnl_1, window_pnl_2, ..., window_pnl_N])
```
- Минимальный `total_pnl_sol` среди всех окон

**median_window_pnl** (медианный PnL окна):
```
median_window_pnl = median([window_pnl_1, window_pnl_2, ..., window_pnl_N])
```
- Медианный `total_pnl_sol` среди всех окон

**best_window_pnl** (наилучший PnL окна):
```
best_window_pnl = max([window_pnl_1, window_pnl_2, ..., window_pnl_N])
```

#### 2.5.2 Runner-метрики (из portfolio_positions.csv)

**hit_rate_x2, hit_rate_x5, hit_rate_x4:**
```
hit_rate_xN = count(positions where max_xn_reached >= N) / total_positions
```
- Вычисляются из `portfolio_positions.csv` по колонкам `hit_x2`, `hit_x5` или `max_xn_reached`
- Источник: `strategy_stability.calculate_runner_metrics()`

**tail_pnl_share, non_tail_pnl_share:**
```
tail_pnl_share = realized_tail_pnl_sol / realized_total_pnl_sol
non_tail_pnl_share = (realized_total_pnl_sol - realized_tail_pnl_sol) / realized_total_pnl_sol
```
- `realized_tail_pnl_sol` = сумма `pnl_sol` для позиций с `max_xn_reached >= 4.0`
- `realized_total_pnl_sol` = сумма всех `pnl_sol` (или сумма `realized_total_pnl_sol` из `portfolio_positions.csv`)
- **Tail threshold:** `TAIL_XN_THRESHOLD = 4.0` (x4)

**p90_hold_days:**
```
p90_hold_days = percentile(hold_days_array, 90) / (24 * 60)  # конвертация минут в дни
```
- Вычисляется из `hold_minutes` в `portfolio_positions.csv`

### 2.6 Деградация survival_rate при малом N

**Важное наблюдение:** При малом количестве сделок (`trades_total` мало) и росте `split_count` метрика `survival_rate` естественным образом **деградирует**.

**Причина:** При разбиении на больше окон каждое окно содержит меньше сделок. Вероятность того, что окно будет пустым или с отрицательным PnL, возрастает.

**Пример:**
- `trades_total = 10`, `split_count = 2` → 2 окна по ~5 сделок
- `trades_total = 10`, `split_count = 5` → 5 окон по ~2 сделки (высокий шанс пустых/отрицательных окон)

**Это ожидаемо и корректно.** Stage A не "подгоняет" метрики — он честно показывает, что при малых данных устойчивость падает. Stage B должен учитывать это через критерии `min_windows` и будущий статус `insufficient_data`.

### 2.7 Что Stage A НЕ делает

- ❌ Не отбирает стратегии (это делает Stage B)
- ❌ Не фильтрует по критериям (это делает Stage B)
- ❌ Не сортирует по PnL (Stage A сохраняет исходный порядок)
- ❌ Не меняет данные (Stage A только читает и агрегирует)
- ❌ Не принимает решений (Stage A — чистый исследовательский слой)

### 2.8 Модули Stage A

**Основные модули:**
- `backtester/research/run_stage_a.py` — CLI entry point
- `backtester/research/window_aggregator.py` — агрегация по окнам
  - `split_into_equal_windows()` — разбиение на равные окна
  - `calculate_window_metrics()` — метрики одного окна
  - `validate_trades_table()` — валидация входных данных
- `backtester/research/strategy_stability.py` — генерация stability table
  - `generate_stability_table_from_portfolio_trades()` — основной метод
  - `calculate_stability_metrics()` — метрики устойчивости
  - `calculate_runner_metrics()` — Runner-метрики из `portfolio_positions.csv`

---

## 3. Stage B — назначение и контракты

### 3.1 Назначение

Stage B применяет формализованные критерии отбора к стратегиям из Stage A. Это **decision layer** — он принимает решения: прошла стратегия критерии или нет.

### 3.2 Точка входа

**Файл:** `backtester/decision/run_stage_b.py`  
**Функция:** `main()`  
**CLI команда:**
```bash
python -m backtester.decision.run_stage_b --stability-csv output/reports/strategy_stability.csv
```

**Параметры:**
- `--stability-csv`: путь к `strategy_stability.csv` из Stage A (по умолчанию `output/reports/strategy_stability.csv`)
- `--output-csv`: путь для сохранения `strategy_selection.csv` (по умолчанию в той же директории как `strategy_stability.csv`)

### 3.3 Входные данные

**Основной вход:** `strategy_stability.csv` из Stage A

**Обязательные колонки (V1 core):**
- `strategy` — название стратегии
- `split_count` — количество окон
- `survival_rate` — доля выживших окон
- `pnl_variance` — дисперсия PnL
- `worst_window_pnl` — наихудший PnL окна
- `median_window_pnl` — медианный PnL окна
- `windows_total` или `windows` — общее количество окон (алиас)

**Опциональные колонки (Runner метрики):**
- `hit_rate_x2`, `hit_rate_x5` — для V1 критериев
- `hit_rate_x4`, `tail_pnl_share`, `non_tail_pnl_share` — для V2 критериев
- `p90_hold_days`, `max_drawdown_pct` — дополнительные критерии

### 3.4 Выходные данные

Stage B генерирует два типа выходных данных:

**Per-split outputs (explainability/debug view):**
- `strategy_selection.csv` — по одной строке на (strategy, split_count)
- Используется для диагностики и анализа чувствительности к разбиению на окна
- Показывает результаты отбора для каждого значения `split_count` отдельно

**Aggregated outputs (primary decision artifact):**
- `strategy_selection_agg.csv` — **1 строка на стратегию** (агрегировано по всем `split_count`)
- Генерируется автоматически, если в `strategy_selection.csv` присутствует колонка `split_count`
- **Decision about a strategy SHOULD be made using aggregated selection (`strategy_selection_agg.csv`).**
- **Per-split selection exists for diagnostics and sensitivity analysis.**

**Колонки в `strategy_selection.csv`:**
- Все колонки из `strategy_stability.csv` (копируются как есть)
- `passed` (bool) — прошла ли стратегия все критерии для данного `split_count`
- `failed_reasons` (List[str]) — список причин отклонения (если `passed=False`)
- `selection_status` (optional) — статус отбора (`passed`, `rejected`, `insufficient_data`)

**Колонки в `strategy_selection_agg.csv`:**
- `splits_total` — количество значений `split_count`, по которым агрегирована стратегия
- `robust_pass_rate` — средний `passed` по всем `split_count` (доля разбиений, где стратегия прошла)
- `passed_any` — прошла ли стратегия хотя бы при одном `split_count`
- `passed_all` — прошла ли стратегия при всех `split_count`
- `worst_case_window_pnl` — минимальный `worst_window_pnl` по всем `split_count`
- `median_survival_rate` — медианный `survival_rate` по всем `split_count`
- `median_median_window_pnl` — медиана медианных PnL окон по всем `split_count`
- `max_pnl_variance` — максимальный `pnl_variance` по всем `split_count`
- `max_pnl_variance_norm` — максимальный `pnl_variance_norm` по всем `split_count` (если присутствует)
- `insufficient_data_rate` — доля разбиений со статусом `insufficient_data` (если `selection_status` присутствует)
- `rejected_rate` — доля разбиений со статусом `rejected` (если `selection_status` присутствует)
- Дополнительные метрики из `strategy_stability.csv` (медиана если варьируется, значение если постоянно)

**Дополнительные выходы:**
- `stage_b_selection.xlsx` — Excel отчёт с листами `selection` и `criteria_snapshot`

**Модуль агрегации:**
- `backtester/decision/selection_aggregator.py` — функция `aggregate_selection()`
- Вызывается автоматически в `backtester/decision/run_stage_b.py` после генерации `strategy_selection.csv`

### 3.5 Критерии windows_total/min_windows

**Критерий:** `windows_total >= min_windows`

**Значения по умолчанию:**
- `DEFAULT_CRITERIA_V1.min_windows = 3`

**Логика:**
- Если `windows_total < min_windows` → `failed_reasons.append("windows_total {N} < {min_windows}")`
- Это **hard-gate** критерий (всегда блокирует)

**Важно:** В текущей реализации это проверяется как обычный критерий. В будущем (low-N evolution) это может стать soft-gate, который маркирует стратегию как `insufficient_data`, а не `rejected`.

### 3.6 Selector: структура и логика

#### 3.6.1 Файлы и функции

**Основной файл:** `backtester/decision/strategy_selector.py`

**Ключевые функции:**
- `load_stability_csv()` — загрузка и нормализация `strategy_stability.csv`
- `normalize_stability_schema()` — нормализация схемы для обратной совместимости (алиасы `split_count`/`split_n`, `windows_total`/`windows`)
- `check_strategy_criteria()` — проверка критериев для одной стратегии
- `select_strategies()` — применение критериев ко всем стратегиям
- `generate_selection_table_from_stability()` — генерация таблицы отбора из CSV

#### 3.6.2 Логика check_strategy_criteria()

**Сигнатура:**
```python
def check_strategy_criteria(
    row: pd.Series,
    criteria: SelectionCriteria,  # Базовые критерии V1
    runner_criteria: Optional[SelectionCriteria] = None,  # Опциональные Runner критерии
) -> tuple[bool, List[str]]:
    """Возвращает (passed: bool, failed_reasons: List[str])"""
```

**Порядок проверок:**

1. **Базовые критерии V1 (обязательные):**
   - `survival_rate >= criteria.min_survival_rate`
   - **Variance criterion (resolution order):**
     - If `pnl_variance_norm` exists and is valid → use `pnl_variance_norm <= criteria.max_pnl_variance`
     - Else → fall back to legacy `pnl_variance <= criteria.max_pnl_variance`
     - **Это не "смягчение критериев" — это исправление единиц измерения**
   - `worst_window_pnl >= criteria.min_worst_window_pnl`
   - `median_window_pnl >= criteria.min_median_window_pnl`
   - `windows_total >= criteria.min_windows`

2. **Runner критерии V1 (если заданы и есть колонки):**
   - `hit_rate_x2 >= runner_criteria.min_hit_rate_x2` (если задано)
   - `hit_rate_x5 >= runner_criteria.min_hit_rate_x5` (если задано)
   - `max_p90_hold_days <= runner_criteria.max_p90_hold_days` (если задано)
   - `tail_contribution <= runner_criteria.max_tail_contribution` (если задано)
   - `max_drawdown_pct >= runner_criteria.max_drawdown_pct` (если задано, отрицательное значение)

3. **Runner критерии V2 (если обнаружены V2 колонки):**
   - Проверка наличия V2 колонок: `{"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}`
   - Если есть V2 колонки и отсутствуют V1 (`hit_rate_x2`, `hit_rate_x5`), применяется V2 логика:
     - `hit_rate_x4 >= 0.10`
     - `tail_pnl_share >= 0.30`
     - `non_tail_pnl_share >= -0.20`
     - `max_drawdown_pct >= -0.60` (если задано)

4. **Missing fields:**
   - Если обязательная колонка отсутствует или NaN → `failed_reasons.append("missing_{field_name}")`
   - Если есть хотя бы один `missing_*` → стратегия не проходит (hard-fail)

**Возвращаемое значение:**
- `passed = True` только если все критерии пройдены и нет missing полей
- `failed_reasons` содержит список всех нарушенных критериев и missing полей

#### 3.6.3 Логика select_strategies()

**Сигнатура:**
```python
def select_strategies(
    stability_df: pd.DataFrame,
    criteria: SelectionCriteria = DEFAULT_CRITERIA_V1,
    runner_criteria: Optional[SelectionCriteria] = None,
) -> pd.DataFrame:
```

**Порядок выполнения:**

1. Валидация обязательных колонок (базовые V1)
2. Для каждой строки `stability_df`:
   - Вызов `check_strategy_criteria(row, criteria, runner_criteria)`
   - Добавление колонок `passed` (bool) и `failed_reasons` (List[str])
3. **ВАЖНО:** DataFrame **не сортируется** по PnL или другим метрикам. Сохраняется исходный порядок.

**Хак для V2:** Если `runner_criteria is None`, но в `stability_df` есть V2 колонки, `criteria` используется как `runner_criteria`, а базовые критерии берутся из `DEFAULT_CRITERIA_V1`.

### 3.7 Критерии: V1 vs Runner vs V2

#### 3.7.1 Базовые критерии V1 (DEFAULT_CRITERIA_V1)

**Файл:** `backtester/decision/selection_rules.py`

**Значения по умолчанию:**
```python
DEFAULT_CRITERIA_V1 = SelectionCriteria(
    min_survival_rate=0.60,        # 60% окон должны быть положительными
    max_pnl_variance=0.15,         # Дисперсия не более 0.15
    min_worst_window_pnl=-0.25,    # Наихудший PnL не хуже -0.25
    min_median_window_pnl=0.00,    # Медианный PnL не меньше 0.0
    min_windows=3,                 # Минимум 3 окна
)
```

**Применяются:** Всегда (обязательные для всех стратегий)

#### 3.7.2 Runner критерии V1 (DEFAULT_RUNNER_CRITERIA_V1)

**Значения по умолчанию:**
```python
DEFAULT_RUNNER_CRITERIA_V1 = SelectionCriteria(
    min_survival_rate=0.0,           # Window критерии не используются
    max_pnl_variance=float('inf'),
    min_worst_window_pnl=-float('inf'),
    min_median_window_pnl=-float('inf'),
    min_windows=1,                   # Минимум 1 окно (ослаблено)
    # Runner критерии v1
    min_hit_rate_x2=0.35,            # 35% сделок должны достичь x2
    min_hit_rate_x5=0.08,            # 8% сделок должны достичь x5
    max_p90_hold_days=35.0,          # Максимум 35 дней (90-й перцентиль)
    max_tail_contribution=0.80,      # Максимум 80% PnL от сделок с realized_multiple >= 5x
    max_drawdown_pct=-0.60,          # Максимальная просадка не более 60%
)
```

**Применяются:** Только если в `strategy_stability.csv` есть Runner метрики (`hit_rate_x2`, `hit_rate_x5`, и т.д.)

#### 3.7.3 Runner критерии V2 (hardcoded в check_strategy_criteria)

**Обнаружение V2:** Наличие колонок `{"hit_rate_x4", "tail_pnl_share", "non_tail_pnl_share"}` и отсутствие V1 колонок.

**Hardcoded пороги (в коде):**
```python
min_hit_rate_x4 = 0.10              # 10% сделок должны достичь x4
min_tail_pnl_share = 0.30           # Минимум 30% PnL от tail сделок
min_non_tail_pnl_share = -0.20      # Минимум -20% (допускается leak)
max_drawdown_pct = -0.60            # Максимальная просадка не более 60%
```

**Применяются:** Автоматически, если обнаружены V2 колонки.

**Примечание:** V2 критерии hardcoded в `check_strategy_criteria()` (строки 122-174). В будущем они должны быть вынесены в `DEFAULT_RUNNER_CRITERIA_V2` или `DEFAULT_RUNNER_CRITERIA_V3`.

### 3.8 Модули Stage B

**Основные модули:**
- `backtester/decision/run_stage_b.py` — CLI entry point
- `backtester/decision/strategy_selector.py` — логика отбора
- `backtester/decision/selection_rules.py` — формализованные критерии (`SelectionCriteria`, `DEFAULT_CRITERIA_V1`, `DEFAULT_RUNNER_CRITERIA_V1`)

---

## 4. Low-N evolution — правила и статусы

### 4.1 Что такое low-N

**Low-N (малая выборка)** — ситуация, когда данных недостаточно для честного статистического решения.

**Предлагаемые пороги:**
- `trades_total < 20` — недостаточно сделок для анализа
- `windows_total < 3` (уже есть как `min_windows`) — недостаточно окон
- `windows_positive < 2` — слишком мало положительных окон (при `windows_total >= 3`)

**Примечание:** Это исследовательская спецификация. Конкретные пороги должны быть определены на основе анализа исторических данных и требований продукта.

### 4.2 Hard-gate vs Soft-gate

#### 4.2.1 Hard-gate (всегда блокирует)

Hard-gate условия **всегда** блокируют стратегию, независимо от других факторов:

1. **P0 audit anomalies** — некорректные данные (блокирует на уровне Stage A/B entry point)
2. **Missing required columns** — отсутствуют обязательные колонки в `strategy_stability.csv`
3. **Invalid data types** — невалидные типы данных (NaN в обязательных полях, некорректные значения)

**Логика:** Hard-gate означает, что данные неконсистентны или некорректны. Принимать решение невозможно.

#### 4.2.2 Soft-gate (помечает как insufficient_data)

Soft-gate условия означают, что данных **недостаточно** для честного решения, но данные корректны:

1. **`windows_total < min_windows`** — недостаточно окон
2. **`trades_total < min_trades`** (будущий критерий) — недостаточно сделок
3. **`windows_positive < min_positive_windows`** (будущий критерий) — слишком мало положительных окон

**Логика:** Soft-gate означает, что данных мало, но они корректны. Мы не можем принять решение, но это не ошибка стратегии — это ограничение данных.

### 4.3 Разделение статусов: passed / rejected / insufficient_data

**Текущая модель (v2.2):**
- `passed` (bool) — `True` если все критерии пройдены, `False` иначе
- `failed_reasons` (List[str]) — список причин отклонения
- `selection_status` (optional) — статус отбора (если присутствует)

**Статусы `selection_status` (если присутствует):**
- `"passed"` — стратегия прошла все критерии
- `"rejected"` — данных достаточно, но стратегия не проходит критерии
  - `failed_reasons` содержит причины отклонения (например, `survival_rate 0.45 < 0.60`)
- `"insufficient_data"` — данных недостаточно для честного решения
  - Причины: `windows_total < min_windows`, `trades_total < min_trades`, и т.д.

**Связь между статусами:**
- `selection_status` — **основной статус** (enum/string)
- `passed` — backward-compatible boolean (`True` iff `selection_status == "passed"`)
- `failed_reasons` — только для `rejected` (список нарушенных критериев)
- `data_sufficiency_reasons` — только для `insufficient_data` (список причин недостаточности данных)

**Желаемая модель (low-N evolution, частично реализовано в v2.2):**

**`selection_status` (enum/string):**
- `"passed"` — стратегия прошла все критерии
- `"rejected"` — данных достаточно, но стратегия не проходит критерии
- `"insufficient_data"` — данных недостаточно для честного решения

**Пример CSV контракта (желаемый, будущий):**

| strategy | split_count | survival_rate | ... | selection_status | failed_reasons | data_sufficiency_reasons |
|----------|-------------|---------------|-----|------------------|----------------|-------------------------|
| Strategy_A | 3 | 0.67 | ... | passed | | |
| Strategy_B | 5 | 0.40 | ... | rejected | survival_rate 0.40 < 0.60 | |
| Strategy_C | 2 | 0.50 | ... | insufficient_data | | windows_total 2 < 3 |

**Примечание:** В текущей версии v2.2 `selection_status` опционален и может отсутствовать в CSV. Если он присутствует, используется для вычисления `insufficient_data_rate` и `rejected_rate` в aggregated selection. Если отсутствует, используется только `passed` (bool) и `failed_reasons` (List[str]).

### 4.4 Как это поможет сохранить честность

**Проблема текущей модели:** При малых данных стратегия может быть отклонена по критерию `windows_total < min_windows`, что несправедливо — это не ошибка стратегии, а ограничение данных.

**Решение low-N evolution:**
1. Разделить `rejected` (ошибка стратегии) и `insufficient_data` (ограничение данных)
2. Soft-gate условия → `insufficient_data`, а не `rejected`
3. Hard-gate условия → `rejected` (или блокировка на уровне entry point)

**Результат:** Мы не "режем" стратегии на малых данных, а честно признаем, что данных недостаточно для решения. Это позволяет:
- Не терять потенциально хорошие стратегии из-за малой выборки
- Избежать подгонки критериев под малые данные
- Сохранить статистическую честность

### 4.5 Будущие расширения (не в v2.2)

**Планируемые улучшения:**
1. Добавить статус `insufficient_data` в `selection_status`
2. Вынести soft-gate условия в отдельную функцию
3. Добавить критерий `min_trades_total` для минимального количества сделок
4. Добавить критерий `min_positive_windows` для минимального количества положительных окон
5. Расширить `SelectionCriteria` для поддержки soft-gate порогов

---

## 5. Debug cookbook

### 5.1 Stage B зарезал стратегию — как проверить

**Шаг 1:** Открыть `strategy_selection.csv` и найти строку с `passed=False`

**Шаг 2:** Посмотреть `failed_reasons` (колонка с разделителем `; `)

**Пример:**
```
strategy,split_count,survival_rate,...,passed,failed_reasons
Strategy_A,3,0.45,...,False,"survival_rate 0.45 < 0.60; windows_total 2 < 3"
```

**Шаг 3:** Открыть `strategy_stability.csv` и проверить конкретные значения:

```python
import pandas as pd
df = pd.read_csv("output/reports/strategy_stability.csv")
row = df[(df["strategy"] == "Strategy_A") & (df["split_count"] == 3)]
print(row[["strategy", "split_count", "survival_rate", "windows_total", "trades_total"]])
```

**Шаг 4:** Сравнить с критериями из `backtester/decision/selection_rules.py`:
- `DEFAULT_CRITERIA_V1.min_survival_rate = 0.60`
- `DEFAULT_CRITERIA_V1.min_windows = 3`

**Шаг 5:** Если причина в `windows_total < min_windows`, это может быть low-N проблема (недостаточно данных, а не ошибка стратегии).

### 5.2 Survival_rate низкий — как посмотреть window breakdown

**Шаг 1:** Открыть `stage_a_summary.csv` (детальная таблица по окнам)

**Шаг 2:** Фильтровать по стратегии и `split_count`:

```python
import pandas as pd
df = pd.read_csv("output/reports/stage_a_summary.csv")
strategy_windows = df[(df["strategy"] == "Strategy_A") & (df["split_count"] == 3)]
print(strategy_windows[["window_index", "window_start", "window_end", "window_trades", "window_pnl"]])
```

**Шаг 3:** Найти проблемные окна:
- Окна с `window_pnl < 0` — отрицательные окна
- Окна с `window_trades = 0` — пустые окна

**Шаг 4:** Проверить временное распределение:
- Все ли окна покрывают период сделок?
- Есть ли пропуски во времени?

**Шаг 5:** Если `window_trades` мало в каждом окне → это low-N проблема. Нужно:
- Увеличить период данных (больше сделок)
- Уменьшить `split_count` (меньше окон, больше сделок на окно)

### 5.3 Windows_total мало — что делать

**Проблема:** `windows_total = 2`, но критерий требует `min_windows = 3`

**Возможные решения:**

1. **Увеличить данные:**
   - Добавить больше исторических сделок (расширить период бэктеста)
   - Убедиться, что все сделки попали в `portfolio_positions.csv`

2. **Изменить split_count:**
   - Уменьшить `split_count` (например, с `[2,3,4,5]` на `[2,3]`)
   - Это увеличит количество сделок на окно, но уменьшит `windows_total`

3. **Изменить min_windows (только для исследования):**
   - Временно снизить `DEFAULT_CRITERIA_V1.min_windows` для тестирования
   - **ВАЖНО:** Это не должно быть в production — критерии должны быть стабильными

4. **Принять как insufficient_data (будущее):**
   - В low-N evolution это будет автоматически помечаться как `insufficient_data`
   - Пока можно вручную проверить метрики и решить, стоит ли стратегия дальнейшего анализа

**Проверка:**
```python
import pandas as pd
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
print(stability_df[["strategy", "split_count", "windows_total", "trades_total"]].sort_values("trades_total"))
```

Если `trades_total < 20` и `windows_total < 3`, это классический low-N случай.

### 5.4 Проверка Runner метрик вручную

**Шаг 1:** Открыть `portfolio_positions.csv` и отфильтровать по стратегии:

```python
import pandas as pd
positions_df = pd.read_csv("output/reports/portfolio_positions.csv")
strategy_positions = positions_df[positions_df["strategy"] == "Strategy_A"]
print(f"Total positions: {len(strategy_positions)}")
```

**Шаг 2:** Проверить hit rates:

```python
hit_x2_count = strategy_positions["hit_x2"].sum() if "hit_x2" in strategy_positions.columns else 0
hit_x5_count = strategy_positions["hit_x5"].sum() if "hit_x5" in strategy_positions.columns else 0
total = len(strategy_positions)
print(f"hit_rate_x2: {hit_x2_count / total if total > 0 else 0:.2%}")
print(f"hit_rate_x5: {hit_x5_count / total if total > 0 else 0:.2%}")
```

**Шаг 3:** Проверить tail_pnl_share:

```python
if "realized_total_pnl_sol" in strategy_positions.columns and "realized_tail_pnl_sol" in strategy_positions.columns:
    total_pnl = strategy_positions["realized_total_pnl_sol"].sum()
    tail_pnl = strategy_positions["realized_tail_pnl_sol"].sum()
    tail_share = tail_pnl / total_pnl if abs(total_pnl) > 1e-6 else 0.0
    print(f"tail_pnl_share: {tail_share:.2%}")
```

**Шаг 4:** Сравнить со значениями в `strategy_stability.csv`:

```python
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
row = stability_df[(stability_df["strategy"] == "Strategy_A") & (stability_df["split_count"] == 3)]
print(row[["hit_rate_x2", "hit_rate_x5", "tail_pnl_share"]])
```

### 5.5 Проверка audit перед Stage A/B

**Проблема:** Stage A/B блокируются с сообщением "ERROR: Audit P0 anomalies detected"

**Решение:**

1. Запустить audit вручную:
```bash
python -m backtester.audit.run_audit --reports-dir output/reports
```

2. Проверить `audit_anomalies.csv`:
```python
import pandas as pd
anomalies_df = pd.read_csv("output/reports/audit_anomalies.csv")
p0_anomalies = anomalies_df[anomalies_df["severity"] == "P0"]
print(p0_anomalies[["code", "message", "severity"]])
```

3. Исправить проблемы в исходных данных или в коде бэктеста

4. Повторить бэктест и audit

**Важно:** Stage A/B не должны запускаться при P0 > 0. Это защита от некорректных метрик.

### 5.6 Стратегия rejected по variance — как проверить

**Проблема:** Стратегия отклонена с причиной `pnl_variance > max_pnl_variance` или `pnl_variance_norm > max_pnl_variance`.

**Шаг 1:** Проверить, есть ли `pnl_variance_norm` в `strategy_stability.csv`:
```python
import pandas as pd
stability_df = pd.read_csv("output/reports/strategy_stability.csv")
print("Columns:", stability_df.columns.tolist())
has_norm = "pnl_variance_norm" in stability_df.columns
print(f"Has pnl_variance_norm: {has_norm}")
```

**Шаг 2:** Проверить `initial_balance_sol_used` (если присутствует):
```python
if "initial_balance_sol_used" in stability_df.columns:
    print(stability_df[["strategy", "split_count", "initial_balance_sol_used"]].head())
```

**Шаг 3:** Сравнить legacy и normalized variance:
```python
strategy_row = stability_df[(stability_df["strategy"] == "Strategy_A") & (stability_df["split_count"] == 3)].iloc[0]
print(f"pnl_variance (legacy): {strategy_row['pnl_variance']}")
if "pnl_variance_norm" in strategy_row:
    print(f"pnl_variance_norm: {strategy_row['pnl_variance_norm']}")
    if "initial_balance_sol_used" in strategy_row:
        print(f"initial_balance_sol_used: {strategy_row['initial_balance_sol_used']}")
        # Проверка: pnl_variance_norm ≈ pnl_variance / (initial_balance_sol_used^2)
        expected_norm = strategy_row['pnl_variance'] / (strategy_row['initial_balance_sol_used'] ** 2)
        print(f"Expected pnl_variance_norm: {expected_norm}")
```

**Шаг 4:** Проверить, какая метрика реально использовалась (по `failed_reasons`):
```python
selection_df = pd.read_csv("output/reports/strategy_selection.csv")
strategy_selection = selection_df[(selection_df["strategy"] == "Strategy_A") & (selection_df["split_count"] == 3)].iloc[0]
print(f"passed: {strategy_selection['passed']}")
print(f"failed_reasons: {strategy_selection['failed_reasons']}")
# Если в failed_reasons есть "pnl_variance_norm" → использовалась нормализованная метрика
# Если есть "pnl_variance" → использовалась legacy метрика
```

**Шаг 5:** Проверить порог критерия:
```python
from backtester.decision.selection_rules import DEFAULT_CRITERIA_V1
print(f"max_pnl_variance threshold: {DEFAULT_CRITERIA_V1.max_pnl_variance}")
# Если используется pnl_variance_norm, порог 0.15 означает 15% от initial_balance_sol
# Если используется legacy pnl_variance, порог 0.15 означает 0.15 SOL²
```

**Важно:** Если стратегия отклонена по `pnl_variance_norm`, это корректное сравнение долей капитала. Если по legacy `pnl_variance`, сравнение может быть некорректным для стратегий с разными начальными балансами.

### 5.7 Timeout exit candle alignment check (optional validation)

**Проблема:** Для позиций с `reason=timeout` (или `time_stop`) в `portfolio_positions.csv` значение `raw_exit_price` может не соответствовать свече на момент `exit_time`. Вместо этого может быть использована свеча, которая была после `exit_time`.

**Решение:** Использовать диагностический инструмент для проверки выравнивания timeout exit prices:

1. Запустить проверку:
```bash
python -m backtester.tools.check_timeout_exit_price \\
    --reports-dir runs/A/reports \\
    --candles-dir runs/A/candles \\
    --out runs/A/reports/timeout_exit_price_check.csv
```

2. Параметры:
- `--reports-dir`: директория с `portfolio_positions.csv` (обязательно)
- `--candles-dir`: директория со свечами (опционально, graceful skip если отсутствует)
- `--out`: путь к выходному CSV файлу с результатами проверки (обязательно)
- `--timeframe`: таймфрейм свечей (по умолчанию "1m")

3. Результаты проверки:
Инструмент создаёт CSV отчёт `timeout_exit_price_check.csv` со следующими колонками:
- `position_id`: ID позиции
- `contract_address`: адрес контракта
- `exit_time`: время выхода (ISO)
- `stored_raw_exit_price`: значение `raw_exit_price` из `portfolio_positions.csv`
- `expected_exit_close`: ожидаемое значение `close` свечи на момент `exit_time` (или первая после)
- `abs_diff_pct`: абсолютная разница в процентах
- `status`: статус проверки

4. Интерпретация статусов:
- `ok`: `raw_exit_price` совпадает с ожидаемой ценой свечи (в пределах tolerance 1%)
- `suspect_exit_price_after_exit_time`: `raw_exit_price` не соответствует свече на `exit_time` (разница > 1%)
- `missing_candles_file`: файл свечей не найден (graceful skip)
- `no_candle_after_exit_time`: нет свечей после `exit_time` в файле свечей

5. Summary в stdout:
```
============================================================
Timeout Exit Price Check Summary
============================================================
Total timeout positions: 150
  ✓ OK: 145
  ⚠ Suspect: 3
  ✗ Missing candles file: 2
  ✗ No candle after exit_time: 0
============================================================
```

**Важно:** Это опциональный инструмент диагностики. Он не блокирует Stage A/B и не изменяет данные. Используйте его для проверки корректности timeout exit prices после бэктеста.

---

## 6. Привязка к исходникам

### 6.1 Stage A — точки входа и модули

| Компонент | Файл | Функция/Класс | Описание |
|-----------|------|---------------|----------|
| **CLI entry point** | `backtester/research/run_stage_a.py` | `main()` | Точка входа Stage A, проверка P0, вызов генерации stability table |
| **Window aggregation** | `backtester/research/window_aggregator.py` | `split_into_equal_windows()` | Разбиение сделок на равные окна по времени |
| | | `calculate_window_metrics()` | Метрики одного окна (total_pnl_sol, trades_count, и т.д.) |
| | | `validate_trades_table()` | Валидация входных данных (обязательные колонки, формат) |
| | | `load_trades_csv()` | Загрузка portfolio_positions.csv |
| | | `DEFAULT_SPLITS` | Константа: `[2, 3, 4, 5]` — значения split_count по умолчанию |
| **Stability generation** | `backtester/research/strategy_stability.py` | `generate_stability_table_from_portfolio_trades()` | Основной метод генерации stability table из portfolio_positions.csv |
| | | `calculate_stability_metrics()` | Метрики устойчивости (survival_rate, pnl_variance, и т.д.) |
| | | `calculate_runner_metrics()` | Runner-метрики из portfolio_positions.csv (hit_rate_x2/x5/x4, tail_pnl_share, и т.д.) |
| | | `build_stability_table()` | Построение DataFrame с метриками для всех стратегий |
| | | `build_detailed_windows_table()` | Детальная таблица по каждому окну (stage_a_summary.csv) |

### 6.2 Stage B — точки входа и модули

| Компонент | Файл | Функция/Класс | Описание |
|-----------|------|---------------|----------|
| **CLI entry point** | `backtester/decision/run_stage_b.py` | `main()` | Точка входа Stage B, проверка P0, вызов генерации selection table |
| **Strategy selector** | `backtester/decision/strategy_selector.py` | `load_stability_csv()` | Загрузка и нормализация strategy_stability.csv |
| | | `normalize_stability_schema()` | Нормализация схемы для обратной совместимости (алиасы колонок) |
| | | `check_strategy_criteria()` | Проверка критериев для одной стратегии (возвращает passed, failed_reasons) |
| | | `select_strategies()` | Применение критериев ко всем стратегиям в DataFrame |
| | | `generate_selection_table_from_stability()` | Генерация таблицы отбора из CSV файла |
| | | `save_selection_table()` | Сохранение strategy_selection.csv |
| **Selection rules** | `backtester/decision/selection_rules.py` | `SelectionCriteria` | Dataclass с формализованными критериями отбора |
| | | `DEFAULT_CRITERIA_V1` | Базовые критерии V1 (min_survival_rate=0.60, min_windows=3, и т.д.) |
| | | `DEFAULT_RUNNER_CRITERIA_V1` | Runner критерии V1 (min_hit_rate_x2=0.35, max_tail_contribution=0.80, и т.д.) |

### 6.3 Audit gate

| Компонент | Файл | Функция/Класс | Описание |
|-----------|------|---------------|----------|
| **Audit entry point** | `backtester/audit/run_audit.py` | `audit_run()` | Проверка инвариантов, возвращает (p0_count, p1_count) |
| **Invariant checker** | `backtester/audit/invariant_checker.py` | `InvariantChecker.check()` | Проверка всех инвариантов, возвращает список Anomaly |
| **Invariant definitions** | `backtester/audit/invariants.py` | `AnomalyType` | Enum с типами аномалий (P0, P1) |
| | | `Anomaly` | Dataclass с описанием аномалии (code, message, severity) |

### 6.4 CSV outputs / Reporter

| Компонент | Файл | Функция/Класс | Описание |
|-----------|------|---------------|----------|
| **Portfolio positions** | `backtester/infrastructure/reporter.py` | `save_portfolio_positions_table()` | Сохранение portfolio_positions.csv (positions-level, executed) |
| **Portfolio events** | | `save_portfolio_events_table()` | Сохранение portfolio_events.csv (events-level, canonical ledger) |
| **Portfolio executions** | | `save_portfolio_executions_table()` | Сохранение portfolio_executions.csv (executions-level) |
| **Portfolio summary** | | `save_portfolio_summary_table()` | Сохранение portfolio_summary.csv (агрегированная статистика) |

### 6.5 CSV контракты

| Файл | Источник | Назначение | Изменяемость |
|------|----------|------------|--------------|
| `portfolio_positions.csv` | `Reporter.save_portfolio_positions_table()` | Stage A, Audit, Reporting | Нельзя (source of truth) |
| `portfolio_events.csv` | `Reporter.save_portfolio_events_table()` | Audit, Debug | Нельзя (canonical ledger) |
| `portfolio_executions.csv` | `Reporter.save_portfolio_executions_table()` | Audit, Debug | Нельзя (execution ledger) |
| `strategy_stability.csv` | Stage A (`generate_stability_table_from_portfolio_trades()`) | Stage B | Нельзя (для Stage B) |
| `strategy_selection.csv` | Stage B (`generate_selection_table_from_stability()`) | Пользователь | Можно (результат Stage B) |
| `stage_a_summary.csv` | Stage A (`build_detailed_windows_table()`) | Debug, анализ окон | Нельзя (для анализа) |

**Примечание:** "Нельзя" означает, что эти файлы являются выходными артефактами пайплайна и не должны редактироваться вручную. Они генерируются автоматически из предыдущих этапов.

---

## 7. Acceptance criteria

### 7.1 Документ создан

- ✅ Файл `docs/STAGE_A_B_PRINCIPLES_v2.2.md` создан
- ✅ Документ содержит все обязательные разделы:
  - Контекст и терминология
  - Stage A — назначение и инварианты
  - Stage B — назначение и контракты
  - Low-N evolution — правила и статусы (спецификация без реализации)
  - Debug cookbook
  - Привязка к исходникам
  - Acceptance criteria

### 7.2 Чёткое разграничение Stage A vs Stage B

- ✅ Stage A описан как research layer (не принимает решений)
- ✅ Stage B описан как decision layer (принимает решения)
- ✅ Указано, что Stage A не отбирает, не фильтрует, не сортирует
- ✅ Указано, что Stage B применяет критерии и выдает `passed`/`failed_reasons`

### 7.3 Low-N evolution spec

- ✅ Описаны hard-gate vs soft-gate условия
- ✅ Описано разделение статусов: `passed` / `rejected` / `insufficient_data`
- ✅ Описан желаемый CSV контракт с `selection_status` и `data_sufficiency_reasons`
- ✅ Указано, что это исследовательская спецификация без реализации в v2.2

### 7.4 Debug cookbook

- ✅ Пошаговые инструкции для проверки отклонённых стратегий
- ✅ Инструкции для анализа низкого survival_rate
- ✅ Инструкции для работы с малым windows_total
- ✅ Инструкции для проверки Runner метрик
- ✅ Инструкции для проверки audit перед Stage A/B

### 7.5 Прямые ссылки на реальные файлы/функции

- ✅ Указаны все реальные пути к файлам:
  - `backtester/research/run_stage_a.py`
  - `backtester/decision/run_stage_b.py`
  - `backtester/decision/strategy_selector.py`
  - `backtester/decision/selection_rules.py`
  - `backtester/audit/run_audit.py`
  - `backtester/audit/invariants.py`
  - `backtester/infrastructure/reporter.py`
- ✅ Указаны ключевые функции и классы:
  - `check_strategy_criteria()`
  - `select_strategies()`
  - `calculate_stability_metrics()`
  - `calculate_runner_metrics()`
- ✅ Указаны константы:
  - `DEFAULT_SPLITS = [2, 3, 4, 5]`
  - `DEFAULT_CRITERIA_V1`
  - `DEFAULT_RUNNER_CRITERIA_V1`

### 7.6 Тесты и логика не изменены

- ✅ Никакие тесты не изменены
- ✅ Никакая логика Stage A/B не изменена
- ✅ Только документация создана

### 7.7 Форматирование

- ✅ Markdown формат с оглавлением
- ✅ Таблицы для "метрика → смысл → источник"
- ✅ Инженерный стиль, без "воды"
- ✅ Чёткая структура с нумерацией разделов

---

## Примечания

- **Версия документа:** 2.2
- **Статус:** Спецификация документации (без изменения кода)
- **Дата:** 2025-01-XX
- **Связанные документы:**
  - `docs/PIPELINE_GUIDE.md` — общий гайд по пайплайну
  - `docs/ARCHITECTURE.md` — архитектура системы
  - `docs/RELEASE_2.1.9.md` — документация релиза

---

## История изменений

| Версия | Дата | Изменения |
|--------|------|-----------|
| 2.2 | 2025-01-XX | Первая версия документа с полной спецификацией Stage A/B и low-N evolution |
