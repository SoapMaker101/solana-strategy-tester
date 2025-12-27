"""Временный скрипт для проверки тестов"""
import subprocess
import sys
from pathlib import Path

# Устанавливаем рабочую директорию
workspace = Path(__file__).parent
os.chdir(workspace)

# Запускаем тесты
tests = [
    "tests/portfolio/test_portfolio_capacity_reset.py",
    "tests/research/test_stage_a_format_validation.py",
    "tests/test_stage_a_pipeline.py",
]

for test_file in tests:
    print(f"\n{'='*60}")
    print(f"Running: {test_file}")
    print('='*60)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-v"],
        cwd=workspace,
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    print(f"Exit code: {result.returncode}")

print(f"\n{'='*60}")
print("Running all tests")
print('='*60)
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-q"],
    cwd=workspace,
    capture_output=True,
    text=True
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print(f"Exit code: {result.returncode}")










