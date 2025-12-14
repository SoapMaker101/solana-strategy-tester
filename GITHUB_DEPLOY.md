# 🚀 Инструкция по выкладке последней версии на GitHub

**Дата:** 2025-12-14  
**Версия:** Phase 4+ (Trade Features + Trades Table Export + Reset Policy Tests)

---

## ✅ Перед началом

### 1. Проверка статуса

```bash
git status
```

Убедитесь, что видите все изменения. Должны быть:
- Модифицированные файлы (M)
- Новые файлы (??)

### 2. Проверка тестов

```bash
pytest -q
```

**Должно пройти 68 тестов.** ✅

### 3. Проверка линтера

```bash
# Если используете pylint или другой линтер
pylint backtester/
```

Или просто убедитесь, что в IDE нет ошибок.

---

## 📦 Шаг 1: Добавление файлов

### Добавить все изменения:

```bash
git add .
```

### Проверка того, что будет закоммичено:

```bash
git status
```

Должны увидеть в "Changes to be committed":
- `backtester/domain/trade_features.py` (новый)
- `tests/test_trade_features.py` (новый)
- `tests/test_reporter_trades_table.py` (новый)
- `tests/test_reset_policy_is_portfolio_only.py` (новый)
- Модифицированные файлы стратегий
- Модифицированный reporter.py
- Модифицированный main.py
- Обновленная документация

---

## 💬 Шаг 2: Создание коммита

### Вариант A: Использовать готовое сообщение из файла

```bash
git commit -F COMMIT_MESSAGE_FINAL.md
```

### Вариант B: Краткое сообщение (рекомендуется)

```bash
git commit -m "feat: add trade features, trades table export, and reset policy tests

- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta
- Reset policy tests: enforce portfolio-only reset flags
- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)
- 19 new tests, all 68 tests passing"
```

### Вариант C: Полное многострочное сообщение

```bash
git commit
```

Затем в редакторе вставьте:

```
feat: add trade features, trades table export, and reset policy tests

Major features:
- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta for analysis
- Reset policy tests: enforce portfolio-only reset flags

Trade Features:
- Added backtester/domain/trade_features.py module
- Market cap proxy: entry_mcap_proxy, exit_mcap_proxy, mcap_change_pct
- Volume features: vol_sum_5m/15m/60m (windows before entry, no leakage)
- Volatility features: range_pct_5m/15m/60m, volat_5m/15m/60m
- Integrated into RR, RRD, Runner strategies

Trades Table Export:
- Added Reporter.save_trades_table() method
- Auto-export after backtest: {strategy}_trades.csv
- Flattens meta: scalars as-is, nested dicts/lists as JSON strings

Reset Policy Tests:
- Added test_reset_policy_is_portfolio_only.py
- Ensures strategies never set reset flags in meta

Documentation:
- Updated CHANGELOG.md (2025-12-14)
- Updated README.md, TECHNICAL_REPORT.md, PROJECT_ANALYSIS.md

Tests: 19 new tests, all 68 passing
```

---

## 🔍 Шаг 3: Проверка коммита

```bash
# Посмотреть последний коммит
git log -1

# Или более подробно
git show
```

---

## 📤 Шаг 4: Отправка в GitHub

### Если ветка main уже отслеживается:

```bash
git push origin main
```

### Если нужно установить upstream (первый раз):

```bash
git push -u origin main
```

### Если возникли конфликты (редко):

```bash
# Получить последние изменения
git pull origin main --rebase

# Разрешить конфликты, затем:
git add .
git rebase --continue
git push origin main
```

---

## ✅ Шаг 5: Проверка на GitHub

1. Откройте репозиторий на GitHub
2. Проверьте последний коммит в истории
3. Убедитесь, что все файлы появились
4. Проверьте, что README.md отображается корректно

---

## 🎯 Быстрая последовательность команд (копипаста)

Если вы уверены во всех изменениях:

```bash
# 1. Проверка статуса
git status

# 2. Добавление всех изменений
git add .

# 3. Проверка что будет закоммичено
git status

# 4. Создание коммита
git commit -m "feat: add trade features, trades table export, and reset policy tests

- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta
- Reset policy tests: enforce portfolio-only reset flags
- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)
- 19 new tests, all 68 tests passing"

# 5. Отправка в GitHub
git push origin main
```

---

## ⚠️ Важные проверки перед коммитом

### ✅ Чеклист:

- [ ] Все тесты проходят (`pytest -q`)
- [ ] Нет ошибок линтера
- [ ] Проверен `.gitignore` (output/, data/candles/, .venv/ не попадут)
- [ ] Нет чувствительных данных (API ключи, пароли)
- [ ] Размер файлов приемлемый (< 50 MB)
- [ ] README.md актуален
- [ ] CHANGELOG.md обновлен
- [ ] Все новые файлы добавлены

### 🔍 Проверка .gitignore

Убедитесь, что следующие директории/файлы НЕ попадут в репозиторий:

```
.venv/
__pycache__/
*.pyc
output/
data/candles/
logs/
.vscode/
.idea/
```

Если видите эти директории в `git status`, проверьте `.gitignore`.

---

## 🐛 Решение проблем

### Проблема: "Your branch is ahead of 'origin/main' by X commits"

**Решение:** Это нормально, просто сделайте `git push`.

### Проблема: "Updates were rejected because the remote contains work"

**Решение:**

```bash
# Получить изменения
git pull origin main --rebase

# Если нет конфликтов, автоматически продолжится
# Если есть конфликты, разрешите их, затем:
git add .
git rebase --continue
git push origin main
```

### Проблема: "Large files detected"

**Решение:**

```bash
# Проверьте размер файлов
git ls-files | xargs ls -lh | sort -k5 -hr | head -10

# Если есть большие файлы в data/ или output/, они должны быть в .gitignore
# Если они уже закоммичены, нужно удалить из истории (осторожно!)
```

### Проблема: Хочу изменить последний коммит (еще не отправил)

```bash
# Изменить сообщение
git commit --amend -m "Новое сообщение"

# Добавить файлы в последний коммит
git add <файлы>
git commit --amend --no-edit
```

---

## 📊 Статистика коммита

После коммита можно посмотреть статистику:

```bash
# Статистика изменений
git diff --stat HEAD~1

# Или если это первый коммит в репозитории:
git diff --stat
```

---

## 🎉 После успешного пуша

1. ✅ Проверьте репозиторий на GitHub
2. ✅ Убедитесь, что README.md отображается
3. ✅ Проверьте, что последний коммит виден
4. ✅ При необходимости создайте release/tag на GitHub

### Создание тега (опционально):

```bash
# Создать тег
git tag -a v1.0.0 -m "Release: Phase 4+ with Trade Features"

# Отправить тег
git push origin v1.0.0
```

---

## 📝 Что дальше?

После успешного выкладывания на GitHub:

1. **Проверьте GitHub Pages** (если настроены)
2. **Обновите описания** в репозитории (если нужно)
3. **Создайте Issues** для будущих улучшений
4. **Поделитесь с командой** 🎉

---

**Удачи с выкладкой! 🚀**
