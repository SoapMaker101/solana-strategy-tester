# tests/research/test_stage_a_realized_pnl_fallback.py
"""
Тесты для проверки fallback логики в Stage A при отсутствии realized колонок.

Проверяет, что tail_pnl_share корректно вычисляется из pnl_sol и max_xn_reached,
если realized_total_pnl_sol и realized_tail_pnl_sol отсутствуют в portfolio_positions.csv.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile

from backtester.research.strategy_stability import calculate_runner_metrics


def test_stage_a_fallback_tail_pnl_share_without_realized_columns():
    """
    Тест: Stage A fallback корректно считает tail_pnl_share при отсутствии realized колонок.
    
    Дано:
    - portfolio_positions.csv БЕЗ realized_total_pnl_sol и realized_tail_pnl_sol
    - 3 позиции:
      - Позиция 1: pnl_sol=2.0, max_xn_reached=4.0 (tail)
      - Позиция 2: pnl_sol=1.0, max_xn_reached=2.0 (non-tail)
      - Позиция 3: pnl_sol=3.0, max_xn_reached=5.0 (tail)
    
    Ожидаем:
    - tail_pnl_share = (2.0 + 3.0) / (2.0 + 1.0 + 3.0) = 5.0 / 6.0 ≈ 0.833
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        # Создаем portfolio_positions.csv БЕЗ realized колонок
        positions_df = pd.DataFrame([
            {
                "strategy": "Runner_Test",
                "signal_id": "test1",
                "contract_address": "addr1",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "pnl_sol": 2.0,
                "max_xn_reached": 4.0,  # Tail (>= 4.0)
            },
            {
                "strategy": "Runner_Test",
                "signal_id": "test2",
                "contract_address": "addr2",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "pnl_sol": 1.0,
                "max_xn_reached": 2.0,  # Non-tail (< 4.0)
            },
            {
                "strategy": "Runner_Test",
                "signal_id": "test3",
                "contract_address": "addr3",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "pnl_sol": 3.0,
                "max_xn_reached": 5.0,  # Tail (>= 4.0)
            },
        ])
        positions_df.to_csv(positions_path, index=False)
        
        # Вычисляем метрики
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        # Проверяем tail_pnl_share
        expected_tail_share = (2.0 + 3.0) / (2.0 + 1.0 + 3.0)  # 5.0 / 6.0 ≈ 0.833
        assert abs(metrics["tail_pnl_share"] - expected_tail_share) < 1e-6, \
            f"tail_pnl_share должен быть {expected_tail_share}, получен {metrics['tail_pnl_share']}"
        
        # Проверяем non_tail_pnl_share
        expected_non_tail_share = 1.0 / 6.0  # 1.0 / 6.0 ≈ 0.167
        assert abs(metrics["non_tail_pnl_share"] - expected_non_tail_share) < 1e-6, \
            f"non_tail_pnl_share должен быть {expected_non_tail_share}, получен {metrics['non_tail_pnl_share']}"


def test_stage_a_fallback_tail_pnl_share_with_realized_columns():
    """
    Тест: Stage A использует realized колонки, если они есть (приоритет над fallback).
    
    Дано:
    - portfolio_positions.csv С realized_total_pnl_sol и realized_tail_pnl_sol
    - Позиция 1: realized_total=2.0, realized_tail=1.0
    - Позиция 2: realized_total=1.0, realized_tail=0.0
    
    Ожидаем:
    - tail_pnl_share = (1.0 + 0.0) / (2.0 + 1.0) = 1.0 / 3.0 ≈ 0.333
    - Fallback НЕ используется
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        # Создаем portfolio_positions.csv С realized колонками
        positions_df = pd.DataFrame([
            {
                "strategy": "Runner_Test",
                "signal_id": "test1",
                "contract_address": "addr1",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "pnl_sol": 2.0,  # Игнорируется, т.к. есть realized
                "max_xn_reached": 2.0,  # Игнорируется, т.к. есть realized
                "realized_total_pnl_sol": 2.0,
                "realized_tail_pnl_sol": 1.0,
            },
            {
                "strategy": "Runner_Test",
                "signal_id": "test2",
                "contract_address": "addr2",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "pnl_sol": 1.0,
                "max_xn_reached": 4.0,  # Игнорируется
                "realized_total_pnl_sol": 1.0,
                "realized_tail_pnl_sol": 0.0,
            },
        ])
        positions_df.to_csv(positions_path, index=False)
        
        # Вычисляем метрики
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        # Проверяем, что используется realized (не fallback)
        expected_tail_share = (1.0 + 0.0) / (2.0 + 1.0)  # 1.0 / 3.0 ≈ 0.333
        assert abs(metrics["tail_pnl_share"] - expected_tail_share) < 1e-6, \
            f"tail_pnl_share должен быть {expected_tail_share} (из realized), получен {metrics['tail_pnl_share']}"


def test_stage_a_fallback_tail_pnl_share_no_tail_positions():
    """
    Тест: fallback корректно обрабатывает случай, когда нет tail позиций.
    
    Дано:
    - Все позиции с max_xn_reached < 4.0
    
    Ожидаем:
    - tail_pnl_share = 0.0
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
                "pnl_sol": 1.0,
                "max_xn_reached": 2.0,  # < 4.0
            },
            {
                "strategy": "Runner_Test",
                "signal_id": "test2",
                "contract_address": "addr2",
                "entry_time": "2024-01-01T00:00:00",
                "exit_time": "2024-01-01T01:00:00",
                "status": "closed",
                "pnl_sol": 2.0,
                "max_xn_reached": 3.0,  # < 4.0
            },
        ])
        positions_df.to_csv(positions_path, index=False)
        
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        assert abs(metrics["tail_pnl_share"] - 0.0) < 1e-6, \
            f"tail_pnl_share должен быть 0.0 (нет tail позиций), получен {metrics['tail_pnl_share']}"






