#!/usr/bin/env python3
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

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd=str(project_root)
)

sys.exit(result.returncode)









