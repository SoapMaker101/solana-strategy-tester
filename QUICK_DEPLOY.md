# ⚡ Быстрая выкладка на GitHub

**Версия:** Phase 4+ (2025-12-14)

---

## 🚀 Одна команда (для опытных)

```bash
git add . && git commit -m "feat: add trade features, trades table export, and reset policy tests" -m "- Trade features: market cap proxy, volume/volatility windows" -m "- Trades table export: unified CSV with flattened meta" -m "- Reset policy tests: enforce portfolio-only reset flags" -m "- Updated documentation, 19 new tests, all 68 passing" && git push origin main
```

---

## 📋 Пошагово (рекомендуется)

### 1. Проверка

```bash
# Проверить что все тесты проходят
pytest -q

# Проверить статус
git status
```

### 2. Добавить файлы

```bash
git add .
```

### 3. Создать коммит

```bash
git commit -m "feat: add trade features, trades table export, and reset policy tests

- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta
- Reset policy tests: enforce portfolio-only reset flags
- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)
- 19 new tests, all 68 tests passing"
```

### 4. Отправить на GitHub

```bash
git push origin main
```

---

## ✅ Проверка на GitHub

После пуша проверьте:
- https://github.com/SoapMaker101/solana-strategy-tester
- Последний коммит в истории
- README.md отображается корректно

---

**Готово! 🎉**
