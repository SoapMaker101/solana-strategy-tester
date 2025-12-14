#!/bin/bash
# Скрипт для выкладки последней версии на GitHub
# Использование: ./DEPLOY.sh

set -e  # Остановить при ошибке

echo "🚀 Начинаем выкладку на GitHub..."
echo ""

# Проверка статуса
echo "📋 Проверка статуса Git..."
git status --short
echo ""

# Проверка тестов
echo "🧪 Запуск тестов..."
if pytest -q; then
    echo "✅ Все тесты прошли!"
else
    echo "❌ Тесты не прошли! Исправьте ошибки перед коммитом."
    exit 1
fi
echo ""

# Добавление всех изменений
echo "📦 Добавление файлов..."
git add .
echo "✅ Файлы добавлены"
echo ""

# Показываем что будет закоммичено
echo "📋 Файлы для коммита:"
git status --short
echo ""

# Запрашиваем подтверждение
read -p "Продолжить с коммитом? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Отменено."
    exit 1
fi

# Создание коммита
echo "💬 Создание коммита..."
git commit -m "feat: add trade features, trades table export, and reset policy tests

- Trade features: market cap proxy, volume/volatility windows in strategy meta
- Trades table export: unified CSV with flattened meta
- Reset policy tests: enforce portfolio-only reset flags
- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)
- 19 new tests, all 68 tests passing"
echo "✅ Коммит создан"
echo ""

# Показываем последний коммит
echo "📝 Последний коммит:"
git log -1 --oneline
echo ""

# Запрашиваем подтверждение для пуша
read -p "Отправить на GitHub? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Коммит создан, но не отправлен. Используйте 'git push origin main' когда будете готовы."
    exit 0
fi

# Отправка на GitHub
echo "📤 Отправка на GitHub..."
git push origin main
echo ""
echo "✅ Готово! Проверьте репозиторий: https://github.com/SoapMaker101/solana-strategy-tester"
