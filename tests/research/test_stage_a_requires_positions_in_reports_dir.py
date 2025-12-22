"""
Тесты для проверки что Stage A читает portfolio_positions.csv только из reports_dir.

T3: Stage A reads portfolio_positions from output/reports
"""
import pytest
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone

from backtester.research.run_stage_a import main as stage_a_main
import sys


def test_stage_a_fails_without_positions(tmp_path, monkeypatch, capsys):
    """
    Тест: если нет portfolio_positions.csv - падает с понятной ошибкой.
    """
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    
    # Мокаем sys.argv для argparse
    test_args = [
        "run_stage_a.py",
        "--reports-dir", str(reports_dir),
    ]
    
    with monkeypatch.context() as m:
        m.setattr(sys, "argv", test_args)
        
        # Должна быть ошибка с sys.exit(1)
        with pytest.raises(SystemExit) as exc_info:
            stage_a_main()
        
        assert exc_info.value.code == 1, "Должен быть exit code 1"
        
        # Проверяем что выведено сообщение об ошибке
        captured = capsys.readouterr()
        assert "ERROR: Portfolio positions file not found" in captured.out
        assert "Stage A requires portfolio_positions.csv" in captured.out
        
        # Проверяем что файл не создан
        stability_path = reports_dir / "strategy_stability.csv"
        assert not stability_path.exists(), "strategy_stability.csv не должен быть создан если нет portfolio_positions.csv"


def test_stage_a_succeeds_with_positions(tmp_path, monkeypatch):
    """
    Тест: если есть portfolio_positions.csv в reports_dir - создаёт strategy_stability.csv.
    """
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    
    # Создаем portfolio_positions.csv
    positions_data = {
        "strategy": ["Runner_Test"] * 3,
        "signal_id": ["test_1", "test_2", "test_3"],
        "contract_address": ["TOKEN1", "TOKEN2", "TOKEN3"],
        "entry_time": [
            "2024-01-01T12:00:00Z",
            "2024-01-02T12:00:00Z",
            "2024-01-03T12:00:00Z",
        ],
        "exit_time": [
            "2024-01-01T13:00:00Z",
            "2024-01-02T13:00:00Z",
            "2024-01-03T13:00:00Z",
        ],
        "status": ["closed", "closed", "closed"],
        "size": [1.0, 1.0, 1.0],
        "pnl_sol": [1.5, -0.2, 0.5],
        "fees_total_sol": [0.1, 0.1, 0.1],
        "exec_entry_price": [1.0, 1.0, 1.0],
        "exec_exit_price": [2.5, 0.8, 1.5],
        "raw_entry_price": [0.98, 0.98, 0.98],
        "raw_exit_price": [2.45, 0.78, 1.48],
        "closed_by_reset": [False, False, False],
        "triggered_portfolio_reset": [False, False, False],
        "reset_reason": ["none", "none", "none"],
        "hold_minutes": [60, 60, 60],
        "max_xn_reached": [2.5, 0.8, 1.5],
        "hit_x2": [True, False, False],
        "hit_x5": [False, False, False],
    }
    
    positions_df = pd.DataFrame(positions_data)
    positions_path = reports_dir / "portfolio_positions.csv"
    positions_df.to_csv(positions_path, index=False)
    
    # Мокаем sys.argv
    test_args = [
        "run_stage_a.py",
        "--reports-dir", str(reports_dir),
        "--splits", "2", "3",
    ]
    
    with monkeypatch.context() as m:
        m.setattr(sys, "argv", test_args)
        
        # Должен успешно выполниться
        stage_a_main()
        
        # Проверяем что файл создан
        stability_path = reports_dir / "strategy_stability.csv"
        assert stability_path.exists(), "strategy_stability.csv должен быть создан"
        
        # Проверяем содержимое
        stability_df = pd.read_csv(stability_path)
        assert len(stability_df) > 0, "strategy_stability.csv должен содержать данные"
        assert "strategy" in stability_df.columns, "Должна быть колонка strategy"
        assert "survival_rate" in stability_df.columns, "Должна быть колонка survival_rate"

