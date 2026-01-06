"""
Тесты для проверки CLI backward compatibility в main.py.

T4: CLI backward compatibility main.py
"""
import pytest
import sys
from pathlib import Path

# Импортируем parse_args из main.py
# Если parse_args не экспортируется, нужно будет вынести его или использовать subprocess
from main import parse_args


def test_cli_config_alias():
    """
    Тест: --config парсится как alias для --backtest-config.
    """
    # Симулируем аргументы командной строки
    test_args = [
        "main.py",
        "--config", "config/backtest_example.yaml",
        "--signals", "signals/test.csv",
        "--strategies-config", "config/strategies.yaml",
    ]
    
    # Сохраняем оригинальные аргументы
    original_argv = sys.argv.copy()
    
    try:
        # Устанавливаем тестовые аргументы
        sys.argv = test_args
        
        # Парсим аргументы
        args = parse_args()
        
        # Проверяем что backtest_config установлен корректно
        assert args.backtest_config == "config/backtest_example.yaml", \
            f"backtest_config должен быть 'config/backtest_example.yaml', получен '{args.backtest_config}'"
        
    finally:
        # Восстанавливаем оригинальные аргументы
        sys.argv = original_argv


def test_cli_output_dir_alias():
    """
    Тест: --output-dir парсится как alias для --json-output.
    """
    # Симулируем аргументы командной строки
    test_args = [
        "main.py",
        "--output-dir", "output/run1",
        "--signals", "signals/test.csv",
        "--strategies-config", "config/strategies.yaml",
        "--backtest-config", "config/backtest.yaml",
    ]
    
    # Сохраняем оригинальные аргументы
    original_argv = sys.argv.copy()
    
    try:
        # Устанавливаем тестовые аргументы
        sys.argv = test_args
        
        # Парсим аргументы
        args = parse_args()
        
        # Проверяем что json_output установлен корректно
        assert args.json_output == "output/run1", \
            f"json_output должен быть 'output/run1', получен '{args.json_output}'"
        
    finally:
        # Восстанавливаем оригинальные аргументы
        sys.argv = original_argv


def test_cli_both_aliases():
    """
    Тест: оба алиаса работают одновременно.
    """
    # Симулируем аргументы командной строки
    test_args = [
        "main.py",
        "--config", "config/backtest_example.yaml",
        "--output-dir", "output/run1",
        "--signals", "signals/test.csv",
        "--strategies-config", "config/strategies.yaml",
    ]
    
    # Сохраняем оригинальные аргументы
    original_argv = sys.argv.copy()
    
    try:
        # Устанавливаем тестовые аргументы
        sys.argv = test_args
        
        # Парсим аргументы
        args = parse_args()
        
        # Проверяем оба параметра
        assert args.backtest_config == "config/backtest_example.yaml", \
            f"backtest_config должен быть 'config/backtest_example.yaml', получен '{args.backtest_config}'"
        assert args.json_output == "output/run1", \
            f"json_output должен быть 'output/run1', получен '{args.json_output}'"
        
    finally:
        # Восстанавливаем оригинальные аргументы
        sys.argv = original_argv


def test_cli_priority_new_over_alias():
    """
    Тест: новые параметры имеют приоритет над алиасами.
    """
    # Симулируем аргументы командной строки (оба указаны)
    test_args = [
        "main.py",
        "--config", "config/old.yaml",
        "--backtest-config", "config/new.yaml",
        "--output-dir", "output/old",
        "--json-output", "output/new",
        "--signals", "signals/test.csv",
        "--strategies-config", "config/strategies.yaml",
    ]
    
    # Сохраняем оригинальные аргументы
    original_argv = sys.argv.copy()
    
    try:
        # Устанавливаем тестовые аргументы
        sys.argv = test_args
        
        # Парсим аргументы
        args = parse_args()
        
        # Проверяем что новые параметры имеют приоритет
        assert args.backtest_config == "config/new.yaml", \
            f"backtest_config должен быть 'config/new.yaml' (приоритет), получен '{args.backtest_config}'"
        assert args.json_output == "output/new", \
            f"json_output должен быть 'output/new' (приоритет), получен '{args.json_output}'"
        
    finally:
        # Восстанавливаем оригинальные аргументы
        sys.argv = original_argv

















