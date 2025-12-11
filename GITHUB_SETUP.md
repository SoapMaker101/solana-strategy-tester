# Инструкция по подключению к GitHub

## Шаг 1: Создание репозитория на GitHub

1. Зайдите на [github.com](https://github.com) и войдите в свой аккаунт
2. Нажмите кнопку **"New"** (или **"+"** → **"New repository"**)
3. Заполните форму:
   - **Repository name**: `solana-strategy-tester` (или другое имя)
   - **Description**: "Local backtesting framework for testing trading strategies on Solana tokens"
   - Выберите **Public** или **Private**
   - **НЕ** ставьте галочки на "Initialize with README", "Add .gitignore", "Choose a license" (у нас уже есть файлы)
4. Нажмите **"Create repository"**

## Шаг 2: Настройка Git (если еще не настроено)

Проверьте, настроен ли git:

```bash
git config --global user.name "Ваше Имя"
git config --global user.email "ваш.email@example.com"
```

## Шаг 3: Инициализация репозитория локально

```bash
# Инициализация git репозитория
git init

# Добавление всех файлов
git add .

# Создание первого коммита
git commit -m "Initial commit: Solana Strategy Tester with RR/RRD strategies"
```

## Шаг 4: Подключение к GitHub

После создания репозитория на GitHub, вы увидите инструкции. Выполните:

```bash
# Добавление удаленного репозитория (замените YOUR_USERNAME на ваш username)
git remote add origin https://github.com/YOUR_USERNAME/solana-strategy-tester.git

# Или если используете SSH:
# git remote add origin git@github.com:YOUR_USERNAME/solana-strategy-tester.git

# Переименование основной ветки в main (если нужно)
git branch -M main

# Отправка кода на GitHub
git push -u origin main
```

## Шаг 5: Аутентификация

При первом push GitHub может запросить аутентификацию:

### Вариант 1: Personal Access Token (рекомендуется)
1. Зайдите в GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Нажмите "Generate new token (classic)"
3. Выберите права: `repo` (полный доступ к репозиториям)
4. Скопируйте токен
5. При push используйте токен вместо пароля

### Вариант 2: GitHub CLI
```bash
# Установите GitHub CLI и выполните:
gh auth login
```

## Команды для работы с Git

```bash
# Проверка статуса
git status

# Добавление изменений
git add .

# Создание коммита
git commit -m "Описание изменений"

# Отправка на GitHub
git push

# Получение обновлений
git pull
```


