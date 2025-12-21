#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Временный скрипт для запуска всех тестов проекта
"""
import sys
import subprocess
from pathlib import Path

# Используем путь из workspace
workspace_path = Path(r"C:\Прочее\Крипта\Тестер соланы")

if not workspace_path.exists():
    print(f"Ошибка: Директория проекта не найдена: {workspace_path}")
    sys.exit(1)

print(f"Запуск тестов из директории: {workspace_path}")
print(f"Используется Python: {sys.executable}")
print("-" * 80)

# Запускаем pytest
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd=str(workspace_path)
)

sys.exit(result.returncode)





