# tests/research/test_stage_a_hit_rate_x4.py
"""
Тесты для проверки расчета hit_rate_x4 в Stage A.

Проверяет, что hit_rate_x4 правильно считается по max_xn_reached >= 4.0.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile

from backtester.research.strategy_stability import calculate_runner_metrics


def test_hit_rate_x4_calculated_from_max_xn_reached():
    """
    Тест: hit_rate_x4 считается по max_xn_reached.
    
    Дано:
    - 10 позиций
    - 3 из них max_xn_reached >= 4.0
    
    Ожидаем:
    - hit_rate_x4 = 0.3
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        # Создаем 10 позиций: 3 с max_xn_reached >= 4.0, 7 с max_xn_reached < 4.0
        positions_data = []
        for i in range(10):
            max_xn = 5.0 if i < 3 else 2.0  # Первые 3 позиции достигают x5, остальные x2
            positions_data.append({
                "strategy": "Runner_Test",
                "signal_id": f"test{i}",
                "contract_address": f"addr{i}",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "max_xn_reached": max_xn,
                "realized_total_pnl_sol": 1.0,
                "realized_tail_pnl_sol": 0.5 if max_xn >= 4.0 else 0.0,
            })
        
        positions_df = pd.DataFrame(positions_data)
        positions_df.to_csv(positions_path, index=False)
        
        # Вычисляем метрики
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        # Проверяем hit_rate_x4
        expected_hit_rate_x4 = 3.0 / 10.0  # 3 из 10 позиций достигли x4+
        assert abs(metrics["hit_rate_x4"] - expected_hit_rate_x4) < 1e-6, \
            f"hit_rate_x4 должен быть {expected_hit_rate_x4}, получен {metrics['hit_rate_x4']}"
        
        # Проверяем, что hit_rate_x5 тоже считается правильно (все 3 позиции с x5)
        assert abs(metrics["hit_rate_x5"] - 3.0 / 10.0) < 1e-6


def test_hit_rate_x4_with_exact_threshold():
    """
    Тест: hit_rate_x4 с точным порогом 4.0.
    
    Дано:
    - Позиция 1: max_xn_reached = 4.0 (должна считаться)
    - Позиция 2: max_xn_reached = 3.9 (не должна считаться)
    - Позиция 3: max_xn_reached = 4.1 (должна считаться)
    
    Ожидаем:
    - hit_rate_x4 = 2/3 = 0.666...
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        positions_df = pd.DataFrame([
            {
                "strategy": "Runner_Test",
                "signal_id": "test1",
                "contract_address": "addr1",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "max_xn_reached": 4.0,  # Точный порог
                "realized_total_pnl_sol": 1.0,
                "realized_tail_pnl_sol": 0.5,
            },
            {
                "strategy": "Runner_Test",
                "signal_id": "test2",
                "contract_address": "addr2",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "max_xn_reached": 3.9,  # Ниже порога
                "realized_total_pnl_sol": 1.0,
                "realized_tail_pnl_sol": 0.0,
            },
            {
                "strategy": "Runner_Test",
                "signal_id": "test3",
                "contract_address": "addr3",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "max_xn_reached": 4.1,  # Выше порога
                "realized_total_pnl_sol": 1.0,
                "realized_tail_pnl_sol": 0.5,
            },
        ])
        positions_df.to_csv(positions_path, index=False)
        
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        expected_hit_rate_x4 = 2.0 / 3.0
        assert abs(metrics["hit_rate_x4"] - expected_hit_rate_x4) < 1e-6, \
            f"hit_rate_x4 должен быть {expected_hit_rate_x4}, получен {metrics['hit_rate_x4']}"

