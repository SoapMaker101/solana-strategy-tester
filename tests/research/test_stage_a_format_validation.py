"""
Тесты для валидации формата входных данных в Stage A.
"""
import pytest
import pandas as pd
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from backtester.research.run_stage_a import main


def test_stage_a_rejects_executions_level_csv():
    """
    Тест: Stage A отклоняет executions-level CSV с понятной ошибкой.
    
    Сценарий:
    - Создаем executions-level CSV (с колонкой event_type)
    - Запускаем Stage A с этим файлом
    - Ожидаем: ошибка с понятным сообщением
    
    Проверяем:
    - Выводится ошибка о неправильном формате
    - Упоминается что это executions-level CSV
    - Упоминается что нужен positions-level CSV
    """
    with TemporaryDirectory() as tmpdir:
        # Создаем executions-level CSV
        executions_path = Path(tmpdir) / "portfolio_executions.csv"
        df_executions = pd.DataFrame({
            "signal_id": ["signal_1"],
            "strategy": ["test_strategy"],
            "event_time": ["2024-01-01T12:00:00"],
            "event_type": ["entry"],  # Это executions-level формат
            "qty_delta": [1.0],
            "raw_price": [1.0],
            "exec_price": [1.0],
            "fees_sol": [0.001],
            "pnl_sol_delta": [0.0],
            "reset_reason": [None],
        })
        df_executions.to_csv(executions_path, index=False)
        
        # Запускаем Stage A с этим файлом
        with patch("sys.argv", ["run_stage_a.py", "--trades", str(executions_path)]):
            with patch("builtins.print") as mock_print:
                try:
                    main()
                except SystemExit:
                    pass  # Ожидаем выход при ошибке
        
        # Проверяем что была выведена ошибка
        print_calls = [str(call) for call in mock_print.call_args_list]
        # Ищем сообщение с "executions-level" и "event_type"
        error_found = any(
            "executions-level" in str(call).lower() and "event_type" in str(call).lower()
            for call in print_calls
        )
        assert error_found, \
            f"Должна быть выведена ошибка о executions-level формате с упоминанием 'event_type'. Вызовы print: {print_calls}"


def test_stage_a_accepts_positions_level_csv():
    """
    Тест: Stage A принимает positions-level CSV.
    
    Сценарий:
    - Создаем positions-level CSV (без колонки event_type, с обязательными колонками)
    - Запускаем Stage A с этим файлом
    - Ожидаем: валидация проходит успешно
    
    Проверяем:
    - Нет ошибок валидации формата
    - Stage A продолжает работу
    """
    with TemporaryDirectory() as tmpdir:
        # Создаем positions-level CSV
        positions_path = Path(tmpdir) / "portfolio_positions.csv"
        df_positions = pd.DataFrame({
            "strategy": ["test_strategy"],
            "signal_id": ["signal_1"],
            "contract_address": ["TOKEN1"],
            "entry_time": ["2024-01-01T12:00:00"],
            "exit_time": ["2024-01-01T14:00:00"],
            "status": ["closed"],
            "size": [1.0],
            "pnl_sol": [0.05],
            "fees_total_sol": [0.001],
            "exec_entry_price": [1.0],
            "exec_exit_price": [1.05],
            "raw_entry_price": [1.0],
            "raw_exit_price": [1.05],
            "closed_by_reset": [False],
            "triggered_portfolio_reset": [False],
            "reset_reason": ["none"],
            "hold_minutes": [120],
        })
        df_positions.to_csv(positions_path, index=False)
        
        # Запускаем Stage A с этим файлом
        with patch("sys.argv", ["run_stage_a.py", "--trades", str(positions_path), "--reports-dir", str(tmpdir)]):
            with patch("backtester.research.strategy_stability.generate_stability_table_from_portfolio_trades") as mock_gen:
                mock_gen.return_value = pd.DataFrame()  # Пустой результат для упрощения
                
                try:
                    main()
                except Exception as e:
                    # Может быть ошибка из-за отсутствия данных, но не из-за формата
                    assert "Invalid" not in str(e) and "format" not in str(e).lower(), \
                        f"Не должно быть ошибки формата: {e}"

