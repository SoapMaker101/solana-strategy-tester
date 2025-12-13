# 📤 Инструкция по отправке изменений в GitHub

**Дата:** 2025-12-13  
**Версия:** Phase 4 + Технический анализ

---

## 📋 Текущий статус

Согласно `git status`, у вас есть:

### Измененные файлы (Modified):
- `docs/CHANGELOG.md`
- `COMMIT_MESSAGE_PHASE4.md`
- `COMMIT_MESSAGE_PHASE4_RU.txt`
- `backtester/application/runner.py`
- `backtester/domain/models.py`
- `backtester/domain/portfolio.py`
- `backtester/domain/position.py`
- `backtester/domain/rr_strategy.py`
- `backtester/infrastructure/price_loader.py`
- `backtester/infrastructure/reporter.py`
- `config/backtest_example.yaml`
- `config/strategies_example.yaml`
- `docs/PNL_CALCULATION_EXPLANATION.md`
- `docs/PORTFOLIO_LAYER.md`
- `main.py`
- `signals/example_signals.csv`

### Новые файлы (Untracked):
- `docs/CACHING_AND_PERFORMANCE.md`
- `docs/CACHING_IMPROVEMENTS_SUMMARY.md`
- `docs/PROJECT_ANALYSIS.md`
- `docs/TECHNICAL_ANALYSIS_2025.md` ⭐ **Новый технический анализ**
- `docs/TROUBLESHOOTING_API_404.md`
- `signals/test_signals.csv`
- `tests/test_performance.py`

---

## 🚀 Пошаговая инструкция

### Шаг 1: Проверка текущего статуса

Откройте терминал в корне проекта и выполните:

```bash
git status
```

Убедитесь, что вы видите все измененные и новые файлы.

---

### Шаг 2: Просмотр изменений (опционально, но рекомендуется)

Перед коммитом полезно посмотреть, что именно изменилось:

```bash
# Просмотр изменений в конкретном файле
git diff backtester/domain/portfolio.py

# Просмотр всех изменений
git diff

# Просмотр новых файлов
git status --short
```

---

### Шаг 3: Добавление файлов в staging area

#### Вариант A: Добавить все изменения (рекомендуется)

```bash
# Добавить все измененные и новые файлы
git add .

# Или более явно:
git add -A
```

#### Вариант B: Добавить файлы по категориям (для более структурированного коммита)

```bash
# 1. Добавить документацию
git add docs/

# 2. Добавить изменения в код
git add backtester/
git add main.py
git add config/

# 3. Добавить тесты
git add tests/

# 4. Добавить сигналы
git add signals/

# 5. Добавить CHANGELOG
git add docs/CHANGELOG.md
```

**Рекомендация:** Используйте вариант A для простоты, если все изменения логически связаны.

---

### Шаг 4: Проверка того, что будет закоммичено

```bash
git status
```

Вы должны увидеть все файлы в секции "Changes to be committed" (зеленым цветом).

---

### Шаг 5: Создание коммита

#### Рекомендуемое сообщение коммита:

```bash
git commit -m "feat: Phase 4 completion + Technical analysis

- Completed Phase 4: Portfolio layer implementation
- Added comprehensive technical analysis (TECHNICAL_ANALYSIS_2025.md)
- Improved caching in GeckoTerminalPriceLoader
- Added performance testing framework
- Updated documentation (CACHING, TROUBLESHOOTING, PROJECT_ANALYSIS)
- Added test signals and performance tests
- Updated CHANGELOG and project documentation"
```

#### Альтернативное сообщение (более краткое):

```bash
git commit -m "feat: Phase 4 + Technical analysis and improvements

- Portfolio layer with fees and constraints
- Comprehensive technical analysis document
- Performance testing and caching improvements
- Updated documentation and tests"
```

#### Если нужно многострочное сообщение:

```bash
git commit
```

Откроется редактор (обычно vim или nano), где можно написать подробное сообщение:

```
feat: Phase 4 completion + Technical analysis

Major updates:
- Completed Phase 4: Portfolio layer with realistic fee simulation
- Added comprehensive technical analysis document
- Improved GeckoTerminalPriceLoader caching
- Added performance testing framework
- Updated all documentation

Files changed:
- Portfolio engine implementation
- Technical analysis (TECHNICAL_ANALYSIS_2025.md)
- Caching improvements
- Performance tests
- Documentation updates
```

**Совет:** Используйте [Conventional Commits](https://www.conventionalcommits.org/) формат:
- `feat:` - новая функциональность
- `fix:` - исправление бага
- `docs:` - изменения в документации
- `test:` - добавление тестов

---

### Шаг 6: Проверка коммита

```bash
# Посмотреть последний коммит
git log -1

# Или более подробно
git show
```

---

### Шаг 7: Отправка в GitHub

#### Если это первый push в ветку:

```bash
# Отправить изменения в удаленный репозиторий
git push origin main
```

#### Если ветка уже существует на GitHub:

```bash
# Просто push
git push
```

#### Если нужно установить upstream (первый раз):

```bash
git push -u origin main
```

---

### Шаг 8: Проверка на GitHub

1. Откройте ваш репозиторий на GitHub
2. Проверьте, что все файлы появились
3. Убедитесь, что коммит виден в истории

---

## 🔄 Если что-то пошло не так

### Отменить последний коммит (но сохранить изменения):

```bash
git reset --soft HEAD~1
```

### Отменить добавление файлов в staging:

```bash
# Отменить все
git reset

# Отменить конкретный файл
git reset HEAD <filename>
```

### Изменить последний коммит (если еще не отправили):

```bash
# Изменить сообщение
git commit --amend -m "Новое сообщение"

# Добавить файлы в последний коммит
git add <filename>
git commit --amend --no-edit
```

---

## 📝 Полная последовательность команд (копипаста)

Если вы уверены в изменениях, можете выполнить все команды подряд:

```bash
# 1. Проверка статуса
git status

# 2. Добавление всех изменений
git add .

# 3. Проверка что будет закоммичено
git status

# 4. Создание коммита
git commit -m "feat: Phase 4 completion + Technical analysis

- Completed Phase 4: Portfolio layer implementation
- Added comprehensive technical analysis (TECHNICAL_ANALYSIS_2025.md)
- Improved caching in GeckoTerminalPriceLoader
- Added performance testing framework
- Updated documentation (CACHING, TROUBLESHOOTING, PROJECT_ANALYSIS)
- Added test signals and performance tests
- Updated CHANGELOG and project documentation"

# 5. Отправка в GitHub
git push origin main
```

---

## ⚠️ Важные замечания

### 1. Проверьте .gitignore

Убедитесь, что в `.gitignore` правильно настроены исключения:
- `output/` - не должен попадать в репозиторий
- `data/candles/` - не должен попадать в репозиторий
- `.venv/` - не должен попадать в репозиторий

### 2. Не коммитьте чувствительные данные

Проверьте, что в коммите нет:
- API ключей
- Паролей
- Личных данных

### 3. Размер файлов

GitHub имеет ограничения:
- Максимальный размер файла: 100 MB
- Рекомендуется: < 50 MB

Если у вас большие файлы данных, используйте Git LFS или не коммитьте их.

### 4. Конфликты

Если при `git push` возникнут конфликты:

```bash
# Получить последние изменения
git pull origin main

# Разрешить конфликты вручную
# Затем:
git add .
git commit -m "Merge conflicts resolved"
git push origin main
```

---

## 🎯 Рекомендуемый workflow для будущих изменений

1. **Создайте ветку для новой функции:**
   ```bash
   git checkout -b feature/new-feature
   ```

2. **Делайте изменения и коммитьте:**
   ```bash
   git add .
   git commit -m "feat: описание функции"
   ```

3. **Отправьте ветку:**
   ```bash
   git push origin feature/new-feature
   ```

4. **Создайте Pull Request на GitHub**

5. **После мерджа удалите ветку:**
   ```bash
   git checkout main
   git pull origin main
   git branch -d feature/new-feature
   ```

---

## 📚 Дополнительные ресурсы

- [Git Documentation](https://git-scm.com/doc)
- [GitHub Guides](https://guides.github.com/)
- [Conventional Commits](https://www.conventionalcommits.org/)

---

## ✅ Чеклист перед коммитом

- [ ] Проверил `git status` - все нужные файлы видны
- [ ] Проверил `.gitignore` - лишние файлы исключены
- [ ] Просмотрел изменения (`git diff`) - все корректно
- [ ] Написал понятное сообщение коммита
- [ ] Убедился, что нет чувствительных данных
- [ ] Проверил размер файлов
- [ ] Готов отправить в GitHub

---

**Удачи с коммитом! 🚀**
