@echo off
REM Скрипт для выкладки последней версии на GitHub (Windows)
REM Использование: DEPLOY.bat

echo 🚀 Начинаем выкладку на GitHub...
echo.

REM Проверка статуса
echo 📋 Проверка статуса Git...
git status --short
echo.

REM Проверка тестов
echo 🧪 Запуск тестов...
pytest -q
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Тесты не прошли! Исправьте ошибки перед коммитом.
    pause
    exit /b 1
)
echo ✅ Все тесты прошли!
echo.

REM Добавление всех изменений
echo 📦 Добавление файлов...
git add .
echo ✅ Файлы добавлены
echo.

REM Показываем что будет закоммичено
echo 📋 Файлы для коммита:
git status --short
echo.

REM Запрашиваем подтверждение
set /p confirm="Продолжить с коммитом? (y/n): "
if /i not "%confirm%"=="y" (
    echo Отменено.
    pause
    exit /b 1
)

REM Создание коммита
echo 💬 Создание коммита...
git commit -m "feat: add trade features, trades table export, and reset policy tests" -m "- Trade features: market cap proxy, volume/volatility windows in strategy meta" -m "- Trades table export: unified CSV with flattened meta" -m "- Reset policy tests: enforce portfolio-only reset flags" -m "- Updated documentation (CHANGELOG, README, TECHNICAL_REPORT)" -m "- 19 new tests, all 68 tests passing"
echo ✅ Коммит создан
echo.

REM Показываем последний коммит
echo 📝 Последний коммит:
git log -1 --oneline
echo.

REM Запрашиваем подтверждение для пуша
set /p push_confirm="Отправить на GitHub? (y/n): "
if /i not "%push_confirm%"=="y" (
    echo Коммит создан, но не отправлен. Используйте 'git push origin main' когда будете готовы.
    pause
    exit /b 0
)

REM Отправка на GitHub
echo 📤 Отправка на GitHub...
git push origin main
echo.
echo ✅ Готово! Проверьте репозиторий: https://github.com/SoapMaker101/solana-strategy-tester
pause
