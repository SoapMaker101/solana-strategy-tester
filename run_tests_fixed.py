#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для запуска всех тестов проекта
"""
import sys
import subprocess
from pathlib import Path

# Определяем корневую директорию проекта (где находится этот скрипт)
project_root = Path(__file__).parent.resolve()

# Запускаем pytest
print(f"Запуск тестов из директории: {project_root}")
print(f"Используется Python: {sys.executable}")
print("-" * 80)

# Также запускаем тест импортов
print("\n=== Тест импортов XN ===")
try:
    import subprocess as sp
    result_imports = sp.run(
        [sys.executable, "test_xn_imports.py"],
        cwd=str(project_root),
        capture_output=True,
        text=True
    )
    print(result_imports.stdout)
    if result_imports.stderr:
        print(result_imports.stderr)
except Exception as e:
    print(f"Ошибка при запуске test_xn_imports.py: {e}")

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









