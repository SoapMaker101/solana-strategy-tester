#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для запуска всех тестов проекта
Использует путь из workspace_path
"""
import sys
import subprocess
import os
from pathlib import Path

# Определяем корневую директорию проекта
# Сначала пробуем найти через текущий файл
if '__file__' in globals():
    project_root = Path(__file__).parent.resolve()
else:
    # Если файл запущен напрямую, используем текущую рабочую директорию
    # или пробуем найти через известные пути
    project_root = Path.cwd()
    # Проверяем, есть ли в текущей директории файлы проекта
    if not (project_root / "run_all_tests.py").exists():
        # Пробуем использовать путь из workspace (может не работать из-за кодировки)
        try:
            workspace_path = r"C:\Прочее\Крипта\Тестер соланы"
            test_path = Path(workspace_path)
            if test_path.exists():
                project_root = test_path
        except:
            pass

print(f"Используется путь проекта: {project_root}")

print(f"Запуск тестов из директории: {project_root}")
print(f"Используется Python: {sys.executable}")
print("-" * 80)

# Запускаем тест импортов
print("\n=== Тест импортов XN ===")
test_imports_path = project_root / "test_xn_imports.py"
if test_imports_path.exists():
    try:
        result_imports = subprocess.run(
            [sys.executable, str(test_imports_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        print(result_imports.stdout)
        if result_imports.stderr:
            print(result_imports.stderr, file=sys.stderr)
    except Exception as e:
        print(f"Ошибка при запуске test_xn_imports.py: {e}")
else:
    print(f"Файл test_xn_imports.py не найден: {test_imports_path}")

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
    print(f"✗ Некоторые тесты не прошли (код возврата: {result.returncode})")

sys.exit(result.returncode)

