# tests/infrastructure/test_reporter_realized_pnl.py
"""
Тесты для проверки записи realized_total_pnl_sol и realized_tail_pnl_sol в portfolio_positions.csv.

Проверяет корректность вычисления этих метрик из partial_exits и fallback логику.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from backtester.domain.position import Position
from backtester.domain.portfolio import PortfolioResult, PortfolioStats
from backtester.infrastructure.reporter import Reporter


def make_stats(**overrides):
    """Helper для создания PortfolioStats с безопасными дефолтами."""
    base = dict(
        final_balance_sol=10.0,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        trades_executed=1,
        trades_skipped_by_risk=0,
    )
    base.update(overrides)
    return PortfolioStats(**base)


def make_executed_position(*, max_xn: float, pnl_sol: float, partial_exits=None) -> Position:
    """
    Фабрика для создания executed позиции, которая проходит фильтр в Reporter.
    
    Требования для executed позиции (из reporter.py:834):
    - pos.status == "closed" (строка, не Enum)
    - pos.entry_time is not None
    - pos.exit_time is not None
    
    Цены читаются из meta с fallback на атрибуты:
    - exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
    - exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price)
    """
    pos = Position(
        signal_id="test1",
        contract_address="addr1",
        entry_time=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        exit_time=datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        exit_price=1.0,
        size=1.0,
        status="closed",  # ВАЖНО: строка "closed", не PositionStatus.CLOSED
    )
    
    # Заполняем meta с обязательными полями для executed позиции
    pos.meta = {
        "pnl_sol": pnl_sol,
        "fees_total_sol": 0.0,
        "max_xn_reached": max_xn,
        # Цены для executed позиции (reporter читает из meta)
        "exec_entry_price": 1.0,
        "exec_exit_price": 1.0,
        "raw_entry_price": 1.0,
        "raw_exit_price": 1.0,
    }
    
    if partial_exits is not None:
        pos.meta["partial_exits"] = partial_exits
    
    return pos


def test_reporter_writes_realized_pnl_from_partial_exits():
    """
    Тест: reporter пишет realized_total_pnl_sol и realized_tail_pnl_sol из partial_exits.
    
    Дано:
    - Позиция с partial_exits:
      - xn=2, pnl_sol=0.2
      - xn=4, pnl_sol=0.8
    
    Ожидаем:
    - realized_total_pnl_sol = 1.0 (0.2 + 0.8)
    - realized_tail_pnl_sol = 0.8 (только xn>=4.0)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        reporter = Reporter(output_dir=str(tmp_path))
        
        # Создаем позицию с partial_exits
        pos = make_executed_position(
            max_xn=4.0,
            pnl_sol=1.0,
            partial_exits=[
                {"xn": 2.0, "pnl_sol": 0.2},
                {"xn": 4.0, "pnl_sol": 0.8},
            ],
        )
        
        portfolio_result = PortfolioResult(
            equity_curve=[],
            positions=[pos],
            stats=make_stats(),
        )
        
        # Сохраняем portfolio positions
        reporter.save_portfolio_positions_table({"Runner_Test": portfolio_result})
        
        # Проверяем, что файл создан
        positions_path = tmp_path / "portfolio_positions.csv"
        assert positions_path.exists(), "portfolio_positions.csv должен быть создан"
        
        # Читаем CSV
        df = pd.read_csv(positions_path)
        assert len(df) == 1, "Должна быть одна позиция"
        
        # Проверяем колонки
        assert "realized_total_pnl_sol" in df.columns, "realized_total_pnl_sol должна быть в CSV"
        assert "realized_tail_pnl_sol" in df.columns, "realized_tail_pnl_sol должна быть в CSV"
        
        # Проверяем значения
        row = df.iloc[0]
        assert abs(row["realized_total_pnl_sol"] - 1.0) < 1e-6, \
            f"realized_total_pnl_sol должен быть 1.0, получен {row['realized_total_pnl_sol']}"
        assert abs(row["realized_tail_pnl_sol"] - 0.8) < 1e-6, \
            f"realized_tail_pnl_sol должен быть 0.8, получен {row['realized_tail_pnl_sol']}"


def test_reporter_fallback_realized_pnl_without_partial_exits():
    """
    Тест: reporter использует fallback для realized PnL, если partial_exits отсутствует.
    
    Дано:
    - Позиция без partial_exits
    - max_xn_reached = 4.5
    - pnl_sol = 1.0
    
    Ожидаем:
    - realized_total_pnl_sol = 1.0 (fallback: pnl_sol)
    - realized_tail_pnl_sol = 1.0 (fallback: pnl_sol, т.к. max_xn_reached >= 4.0)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        reporter = Reporter(output_dir=str(tmp_path))
        
        # Создаем позицию без partial_exits
        pos = make_executed_position(
            max_xn=4.5,
            pnl_sol=1.0,
            partial_exits=None,  # partial_exits отсутствует
        )
        
        portfolio_result = PortfolioResult(
            equity_curve=[],
            positions=[pos],
            stats=make_stats(),
        )
        
        # Сохраняем portfolio positions
        reporter.save_portfolio_positions_table({"Runner_Test": portfolio_result})
        
        # Читаем CSV
        positions_path = tmp_path / "portfolio_positions.csv"
        df = pd.read_csv(positions_path)
        
        # Проверяем значения
        row = df.iloc[0]
        assert abs(row["realized_total_pnl_sol"] - 1.0) < 1e-6, \
            f"realized_total_pnl_sol должен быть 1.0 (fallback), получен {row['realized_total_pnl_sol']}"
        assert abs(row["realized_tail_pnl_sol"] - 1.0) < 1e-6, \
            f"realized_tail_pnl_sol должен быть 1.0 (fallback, т.к. max_xn_reached=4.5 >= 4.0), получен {row['realized_tail_pnl_sol']}"


def test_reporter_fallback_realized_pnl_below_tail_threshold():
    """
    Тест: fallback для realized_tail_pnl_sol = 0, если max_xn_reached < 4.0.
    
    Дано:
    - Позиция без partial_exits
    - max_xn_reached = 2.0
    - pnl_sol = 1.0
    
    Ожидаем:
    - realized_total_pnl_sol = 1.0
    - realized_tail_pnl_sol = 0.0 (max_xn_reached < 4.0)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        reporter = Reporter(output_dir=str(tmp_path))
        
        pos = make_executed_position(
            max_xn=2.0,  # Ниже порога 4.0
            pnl_sol=1.0,
            partial_exits=None,
        )
        
        portfolio_result = PortfolioResult(
            equity_curve=[],
            positions=[pos],
            stats=make_stats(),
        )
        
        reporter.save_portfolio_positions_table({"Runner_Test": portfolio_result})
        
        positions_path = tmp_path / "portfolio_positions.csv"
        df = pd.read_csv(positions_path)
        
        row = df.iloc[0]
        assert abs(row["realized_total_pnl_sol"] - 1.0) < 1e-6
        assert abs(row["realized_tail_pnl_sol"] - 0.0) < 1e-6, \
            f"realized_tail_pnl_sol должен быть 0.0 (max_xn_reached=2.0 < 4.0), получен {row['realized_tail_pnl_sol']}"

