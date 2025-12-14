# ⚡ ВЫКЛАДКА НА GITHUB - СЕЙЧАС

**Версия:** Phase 4+ (2025-12-14)

---

## 🚀 Быстрая выкладка (3 шага)

### Шаг 1: Проверка тестов
```bash
pytest -q
```
✅ Должно пройти 68 тестов

### Шаг 2: Добавить и закоммитить
```bash
git add .
git commit -m "feat: add trade features, trades table export, and reset policy tests

- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta
- Reset policy tests: enforce portfolio-only reset flags
- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)
- 19 new tests, all 68 tests passing"
```

### Шаг 3: Отправить на GitHub
```bash
git push origin main
```

---

## ✅ ГОТОВО!

Проверьте: https://github.com/SoapMaker101/solana-strategy-tester

---

**Или используйте автоматический скрипт:**

Windows: `DEPLOY.bat`  
Linux/Mac: `bash DEPLOY.sh`
