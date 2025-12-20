# Signal Filtering Guide

## Обзор

Модуль фильтрации сигналов позволяет улучшить качество входных сигналов для бэктестинга, не изменяя стратегии. Основная идея — отфильтровать сигналы с низким market cap proxy, так как они часто показывают худшие результаты.

## Market Cap Proxy

### Зачем нужен?

Мы не можем использовать настоящий market cap, так как нет исторических данных о supply токенов. Поэтому используем детерминированную прокси:

```
market_cap_proxy = entry_price × 1_000_000_000
```

где `entry_price` — цена входа на момент сигнала или через 1 минуту.

### Как считается?

1. **Entry Price**: Цена входа определяется из свечей:
   - Режим `t+1m` (по умолчанию): берётся цена закрытия первой свечи с `timestamp >= signal_timestamp + 1 минута`
   - Fallback: если такой свечи нет, используется свеча на момент сигнала (`timestamp >= signal_timestamp`)
   - Режим `t`: берётся цена закрытия свечи на момент сигнала

2. **Market Cap Proxy**: `entry_price × 1_000_000_000`

### Важно

- Прокси используется **только** для сравнения распределений runner/non-runner и грубого фильтра сигналов
- Прокси считается **только** из данных, доступных в момент сигнала (без look-ahead bias)
- Это детерминированная метрика, не претендующая на точность реального market cap

## Пайплайн фильтрации

### Шаг 1: Извлечение признаков

Для каждого сигнала вычисляются:
- `entry_price`: цена входа
- `market_cap_proxy`: прокси market cap
- `max_xn`: максимальный множитель цены в окне анализа (например, если цена выросла до 3x, то `max_xn = 3.0`)
- `time_to_2x_minutes`, `time_to_3x_minutes`, `time_to_5x_minutes`, `time_to_7x_minutes`, `time_to_10x_minutes`: время до достижения уровней (если достигнуты)
- `lived_minutes`: сколько минут есть свечей после entry
- `status`: статус обработки (`ok`, `no_candles`, `no_entry`, `error`)

Результат сохраняется в `output/signal_analysis/signal_features.csv`.

### Шаг 2: Анализ порогов

Для разных порогов `min_market_cap_proxy` вычисляются метрики:
- `kept_signals`: сколько сигналов осталось
- `kept_pct`: процент оставшихся сигналов
- `kept_runners`: сколько runner'ов осталось (сигналы с `max_xn >= runner_xn_threshold`)
- `runner_recall_pct`: процент runner'ов, которые остались
- `non_runner_removed_pct`: процент non-runner'ов, которые были отрезаны
- `runner_share_before`, `runner_share_after`: доля runner'ов до и после фильтрации

Результат сохраняется в `output/signal_analysis/cap_threshold_report.csv`.

### Шаг 3: Фильтрация сигналов

Применяется фильтр:
- `market_cap_proxy >= min_market_cap_proxy`
- `status == "ok"` (опционально)

Результат сохраняется в `output/signal_analysis/signals_filtered.csv`.

### Шаг 4: Summary

Генерируется summary с метриками фильтрации:
- Количество исходных и отфильтрованных сигналов
- Процент удалённых сигналов
- Количество валидных сигналов до и после фильтрации

Результат сохраняется в `output/signal_analysis/signal_filter_summary.json`.

## Запуск пайплайна

### Команда запуска

```powershell
python -m backtester.research.signal_quality.run_signal_filter_pipeline `
  --signals signals/signals_2025-07-01_to_2025-12-14_filtered.csv `
  --candles-dir data/candles `
  --timeframe 1m `
  --entry-mode t+1m `
  --horizon-days 14 `
  --use-high true `
  --runner-xn-threshold 3 `
  --thresholds 10000 20000 30000 40000 50000 60000 80000 100000 150000 200000 `
  --min-market-cap-proxy 40000 `
  --output-dir output/signal_analysis
```

### Параметры

- `--signals`: Путь к CSV файлу с сигналами (обязательно)
- `--candles-dir`: Базовая директория со свечами (default: `data/candles`)
- `--timeframe`: Таймфрейм свечей: `1m`, `5m`, `15m` (default: `1m`)
- `--entry-mode`: Режим поиска entry_price: `t` или `t+1m` (default: `t+1m`)
- `--horizon-days`: Горизонт анализа в днях (default: `14`)
- `--use-high`: Использовать high цену для max_xn: `true` или `false` (default: `true`)
- `--runner-xn-threshold`: Порог для определения runner'а (default: `3.0`)
- `--thresholds`: Список порогов для анализа (default: `10k, 20k, 30k, 40k, 50k, 60k, 80k, 100k, 150k, 200k`)
- `--min-market-cap-proxy`: Минимальный порог market cap proxy для фильтрации (обязательно)
- `--output-dir`: Директория для сохранения результатов (default: `output/signal_analysis`)

## Выбор порога

### Как выбрать min_market_cap_proxy?

1. Запустите пайплайн с разными порогами в `--thresholds`
2. Откройте `cap_threshold_report.csv`
3. Анализируйте метрики:
   - `runner_recall_pct`: сколько runner'ов осталось (чем выше, тем лучше)
   - `non_runner_removed_pct`: сколько non-runner'ов отрезали (чем выше, тем лучше)
   - `runner_share_after`: доля runner'ов после фильтрации (чем выше, тем лучше)
   - `kept_pct`: сколько сигналов осталось (баланс между качеством и количеством)

4. Выберите порог, который:
   - Сохраняет достаточно runner'ов (высокий `runner_recall_pct`)
   - Удаляет много non-runner'ов (высокий `non_runner_removed_pct`)
   - Оставляет разумное количество сигналов (не слишком низкий `kept_pct`)

### Пример

Если в `cap_threshold_report.csv`:
- При пороге 30000: `runner_recall_pct=85%`, `non_runner_removed_pct=60%`, `kept_pct=45%`
- При пороге 40000: `runner_recall_pct=80%`, `non_runner_removed_pct=70%`, `kept_pct=35%`
- При пороге 50000: `runner_recall_pct=70%`, `non_runner_removed_pct=80%`, `kept_pct=25%`

Можно выбрать порог 40000 как баланс между качеством и количеством.

## Использование отфильтрованных сигналов

### Запуск бэктеста на отфильтрованных сигналах

```powershell
python main.py `
  --signals output/signal_analysis/signals_filtered.csv `
  --strategies-config config/runner_baseline.yaml `
  --backtest-config config/backtest_example.yaml `
  --execution-profile realistic
```

### Интеграция в workflow

1. Запустите пайплайн фильтрации сигналов
2. Проверьте `signal_filter_summary.json` для понимания, сколько сигналов осталось
3. Запустите бэктест на отфильтрованных сигналах
4. Сравните результаты с исходными сигналами

## Предупреждения

### Look-ahead bias

⚠️ **Важно**: Прокси market cap считается только из данных, доступных в момент сигнала. Это означает:
- Используется цена на момент сигнала или через 1 минуту (не будущие данные)
- Прокси не использует информацию о будущем поведении цены
- Фильтрация не создаёт look-ahead bias

### Точность прокси

⚠️ **Ограничения**:
- Прокси не является точным market cap (нет реального supply)
- Прокси используется только для сравнения и фильтрации
- Не используйте прокси для точных расчётов market cap

### Пустые/битые свечи

Система корректно обрабатывает:
- Отсутствие свечей для контракта (`status="no_candles"`)
- Отсутствие подходящей свечи для entry_price (`status="no_entry"`)
- Ошибки при загрузке свечей (`status="error"`)

Такие сигналы автоматически исключаются из фильтрации (если `require_status_ok=True`).

## Структура файлов

```
output/signal_analysis/
├── signal_features.csv          # Признаки всех сигналов
├── cap_threshold_report.csv     # Отчёт по порогам
├── signals_filtered.csv         # Отфильтрованные сигналы
└── signal_filter_summary.json   # Summary фильтрации
```

## Примеры использования

### Базовый запуск

```powershell
python -m backtester.research.signal_quality.run_signal_filter_pipeline `
  --signals signals/my_signals.csv `
  --min-market-cap-proxy 40000
```

### С кастомными параметрами

```powershell
python -m backtester.research.signal_quality.run_signal_filter_pipeline `
  --signals signals/my_signals.csv `
  --candles-dir data/candles/cached `
  --timeframe 1m `
  --entry-mode t `
  --horizon-days 7 `
  --use-high false `
  --runner-xn-threshold 5 `
  --thresholds 50000 100000 150000 200000 `
  --min-market-cap-proxy 100000 `
  --output-dir output/my_analysis
```

## Тестирование

Запуск тестов:

```powershell
pytest tests/research/signal_quality/
```

Тесты покрывают:
- Вычисление market_cap_proxy
- Получение entry_price (режимы t и t+1m)
- Вычисление max_xn и time_to_xn
- Анализ порогов
- Фильтрацию сигналов








