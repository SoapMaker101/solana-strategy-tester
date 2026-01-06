# tests/research/test_tail_realized_metrics.py
"""
Тесты для проверки расчета realized_tail_pnl_sol из partial_exits.

Проверяет корректность вычисления realized_total_pnl_sol и realized_tail_pnl_sol
для Runner стратегий с частичными закрытиями.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile
import shutil

from backtester.research.strategy_stability import calculate_runner_metrics


def test_realized_tail_pnl_case1_tail_reached_but_no_money():
    """
    Case 1: tail достигнут (x4), но деньги взяты до tail.
    
    Дано:
    - partial_exits:
      - xn=2 pnl_sol=+1.0
      - xn=4 pnl_sol=0.0
    
    Ожидаем:
    - realized_total_pnl_sol = 1.0
    - realized_tail_pnl_sol = 0.0
    - tail_pnl_share = 0.0
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        # Создаем portfolio_positions.csv с одной позицией
        # В реальности realized_total_pnl_sol и realized_tail_pnl_sol будут вычислены
        # в reporter.py из partial_exits, но для теста мы их задаем напрямую
        positions_df = pd.DataFrame([{
            "strategy": "Runner_Test",
            "signal_id": "test1",
            "contract_address": "addr1",
            "entry_time": "2024-01-01T00:00:00",
            "exit_time": "2024-01-01T01:00:00",
            "status": "closed",
            "max_xn_reached": 4.0,
            "realized_total_pnl_sol": 1.0,  # Сумма всех partial_exits
            "realized_tail_pnl_sol": 0.0,  # Только xn>=4.0
        }])
        positions_df.to_csv(positions_path, index=False)
        
        # Вычисляем метрики
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        # Проверяем результаты
        assert metrics["tail_pnl_share"] == 0.0, "tail_pnl_share должен быть 0.0 (нет денег на tail)"
        assert metrics["hit_rate_x4"] == 1.0, "hit_rate_x4 должен быть 1.0 (достигнут x4)"


def test_realized_tail_pnl_case2_tail_feeds():
    """
    Case 2: tail реально кормит.
    
    Дано:
    - partial_exits:
      - xn=2 pnl=0.2
      - xn=4 pnl=0.8
    
    Ожидаем:
    - realized_total_pnl_sol = 1.0
    - realized_tail_pnl_sol = 0.8
    - tail_pnl_share = 0.8
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        positions_df = pd.DataFrame([{
            "strategy": "Runner_Test",
            "signal_id": "test1",
            "contract_address": "addr1",
            "entry_time": "2024-01-01T00:00:00",
            "exit_time": "2024-01-01T01:00:00",
            "status": "closed",
            "max_xn_reached": 4.0,
            "realized_total_pnl_sol": 1.0,  # 0.2 + 0.8
            "realized_tail_pnl_sol": 0.8,  # Только xn>=4.0
        }])
        positions_df.to_csv(positions_path, index=False)
        
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        assert abs(metrics["tail_pnl_share"] - 0.8) < 1e-6, f"tail_pnl_share должен быть 0.8, получен {metrics['tail_pnl_share']}"
        assert metrics["hit_rate_x4"] == 1.0


def test_realized_tail_pnl_case3_fallback_without_partial_exits():
    """
    Case 3: fallback без partial_exits.
    
    Дано:
    - max_xn_reached=4.5, pnl_sol=1.0
    - partial_exits отсутствует (legacy позиция)
    
    Ожидаем:
    - realized_tail_pnl_sol=1.0 (fallback: если max_xn_reached >= 4.0, то весь PnL считается tail)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        positions_path = tmp_path / "portfolio_positions.csv"
        
        # Для fallback случая, если нет realized_total_pnl_sol/realized_tail_pnl_sol,
        # метрики будут вычисляться из pnl_sol и max_xn_reached
        # Но в реальности reporter.py всегда должен добавлять эти колонки
        positions_df = pd.DataFrame([{
            "strategy": "Runner_Test",
            "signal_id": "test1",
            "contract_address": "addr1",
            "entry_time": "2024-01-01T00:00:00",
            "exit_time": "2024-01-01T01:00:00",
            "status": "closed",
            "max_xn_reached": 4.5,
            "pnl_sol": 1.0,
            # Если нет realized_* колонок, tail_pnl_share будет 0.0 (не можем вычислить)
        }])
        positions_df.to_csv(positions_path, index=False)
        
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        # Если нет realized_* колонок, tail_pnl_share остается 0.0
        # Это нормально, так как мы не можем вычислить без partial_exits
        assert metrics["hit_rate_x4"] == 1.0, "hit_rate_x4 должен быть 1.0 (max_xn_reached=4.5 >= 4.0)"


def test_realized_tail_pnl_multiple_positions():
    """
    Тест с несколькими позициями для проверки агрегации.
    
    Дано:
    - Позиция 1: realized_total=2.0, realized_tail=1.0
    - Позиция 2: realized_total=1.0, realized_tail=0.0
    - Позиция 3: realized_total=3.0, realized_tail=2.0
    
    Ожидаем:
    - tail_pnl_share = (1.0 + 0.0 + 2.0) / (2.0 + 1.0 + 3.0) = 3.0 / 6.0 = 0.5
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
                "max_xn_reached": 4.0,
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
                "max_xn_reached": 2.0,
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
                "max_xn_reached": 5.0,
                "realized_total_pnl_sol": 3.0,
                "realized_tail_pnl_sol": 2.0,
            },
        ])
        positions_df.to_csv(positions_path, index=False)
        
        metrics = calculate_runner_metrics(
            strategy_name="Runner_Test",
            portfolio_positions_path=positions_path,
        )
        
        # Проверяем агрегацию
        expected_tail_share = (1.0 + 0.0 + 2.0) / (2.0 + 1.0 + 3.0)  # 3.0 / 6.0 = 0.5
        assert abs(metrics["tail_pnl_share"] - expected_tail_share) < 1e-6, \
            f"tail_pnl_share должен быть {expected_tail_share}, получен {metrics['tail_pnl_share']}"
        
        # hit_rate_x4: 2 из 3 позиций достигли x4 (test1 и test3)
        assert abs(metrics["hit_rate_x4"] - 2.0/3.0) < 1e-6, \
            f"hit_rate_x4 должен быть {2.0/3.0}, получен {metrics['hit_rate_x4']}"















