import os
import sys
import subprocess
from pathlib import Path

# Получаем путь к директории проекта (где находится этот скрипт)
script_path = Path(__file__).resolve()
project_dir = script_path.parent

# Меняем рабочую директорию
os.chdir(project_dir)
print(f"Working directory: {os.getcwd()}")
print(f"Running tests from: {project_dir / 'tests'}")

# Запускаем pytest
result = subprocess.run([sys.executable, '-m', 'pytest', 'tests/', '-v', '--tb=short'], 
                       cwd=str(project_dir))

sys.exit(result.returncode)

