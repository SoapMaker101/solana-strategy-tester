#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Прямой запуск тестов через Python
"""
import sys
import subprocess
from pathlib import Path

# Используем текущую директорию как базовую
# Если скрипт запущен из проекта, __file__ будет указывать на него
try:
    if '__file__' in globals():
        project_root = Path(__file__).parent.resolve()
    else:
        # Если запущено через -c, пробуем найти проект
        project_root = Path.cwd()
        # Проверяем наличие ключевых файлов
        if not (project_root / "run_all_tests.py").exists():
            # Пробуем найти проект через известные файлы
            for parent in project_root.parents:
                if (parent / "run_all_tests.py").exists():
                    project_root = parent
                    break
except:
    project_root = Path.cwd()

print(f"Корневая директория проекта: {project_root}")
print(f"Python: {sys.executable}")
print("-" * 80)

# Проверяем наличие директории tests
tests_dir = project_root / "tests"
if not tests_dir.exists():
    print(f"ОШИБКА: Директория tests не найдена в {project_root}")
    sys.exit(1)

# Запускаем тест импортов
print("\n=== Тест импортов XN ===")
test_imports = project_root / "test_xn_imports.py"
if test_imports.exists():
    try:
        result = subprocess.run(
            [sys.executable, str(test_imports)],
            cwd=str(project_root),
            encoding='utf-8'
        )
    except Exception as e:
        print(f"Ошибка: {e}")
else:
    print(f"Файл test_xn_imports.py не найден")

# Запускаем pytest
print("\n=== Запуск всех тестов pytest ===")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "--color=yes"],
    cwd=str(project_root)
)

print("\n" + "=" * 80)
if result.returncode == 0:
    print("✓ Все тесты прошли успешно!")
else:
    print(f"✗ Некоторые тесты не прошли (код: {result.returncode})")

sys.exit(result.returncode)
















