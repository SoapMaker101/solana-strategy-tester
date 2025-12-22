"""
Тесты для проверки расчета max_xn_reached, hit_x2, hit_x5 в portfolio_positions.csv.

T1: max_xn_reached/hit_x2/hit_x5 в portfolio_positions.csv
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from backtester.domain.position import Position
from backtester.domain.portfolio import PortfolioResult, PortfolioStats
from backtester.infrastructure.reporter import Reporter


def test_max_xn_from_exec_prices(tmp_path):
    """
    Тест: max_xn_reached рассчитывается из exec цен если они есть.
    
    Position: exec_entry_price=1.0, exec_exit_price=2.5
    Ожидаем: max_xn_reached=2.5, hit_x2=True, hit_x5=False
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию с exec ценами
    pos = Position(
        signal_id="test_1",
        contract_address="TOKEN1",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=2.5,
        status="closed",
        pnl_pct=1.5,
        meta={
            "exec_entry_price": 1.0,
            "exec_exit_price": 2.5,
            "raw_entry_price": 0.98,
            "raw_exit_price": 2.45,
            "pnl_sol": 1.5,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=11.5,
            total_return_pct=0.15,
            max_drawdown_pct=0.0,
            trades_executed=1,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
        )
    )
    
    portfolio_results = {"test_strategy": portfolio_result}
    reporter.save_portfolio_positions_table(portfolio_results)
    
    # Проверяем результат
    positions_path = tmp_path / "portfolio_positions.csv"
    assert positions_path.exists(), "portfolio_positions.csv должен быть создан"
    
    df = pd.read_csv(positions_path)
    assert len(df) == 1, "Должна быть одна позиция"
    
    row = df.iloc[0]
    assert row["max_xn_reached"] == pytest.approx(2.5, abs=1e-9), f"max_xn_reached должен быть ~2.5, получен {row['max_xn_reached']}"
    assert row["hit_x2"] == True, f"hit_x2 должен быть True, получен {row['hit_x2']}"
    assert row["hit_x5"] == False, f"hit_x5 должен быть False, получен {row['hit_x5']}"


def test_max_xn_from_raw_prices(tmp_path):
    """
    Тест: max_xn_reached рассчитывается из raw цен если exec цен нет.
    
    raw_entry_price=1.0, raw_exit_price=5.1
    Ожидаем: max_xn_reached=5.1, hit_x2=True, hit_x5=True
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию без exec цен, но с raw ценами
    pos = Position(
        signal_id="test_2",
        contract_address="TOKEN2",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=5.1,
        status="closed",
        pnl_pct=4.1,
        meta={
            "raw_entry_price": 1.0,
            "raw_exit_price": 5.1,
            "pnl_sol": 4.1,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=14.1,
            total_return_pct=0.41,
            max_drawdown_pct=0.0,
            trades_executed=1,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
        )
    )
    
    portfolio_results = {"test_strategy": portfolio_result}
    reporter.save_portfolio_positions_table(portfolio_results)
    
    # Проверяем результат
    positions_path = tmp_path / "portfolio_positions.csv"
    assert positions_path.exists(), "portfolio_positions.csv должен быть создан"
    
    df = pd.read_csv(positions_path)
    assert len(df) == 1, "Должна быть одна позиция"
    
    row = df.iloc[0]
    assert abs(row["max_xn_reached"] - 5.1) < 0.001, f"max_xn_reached должен быть ~5.1, получен {row['max_xn_reached']}"
    assert row["hit_x2"] == True, f"hit_x2 должен быть True, получен {row['hit_x2']}"
    assert row["hit_x5"] == True, f"hit_x5 должен быть True, получен {row['hit_x5']}"


def test_max_xn_no_prices(tmp_path):
    """
    Тест: max_xn_reached=None/NaN если цен нет.
    
    все entry/exit = None
    Ожидаем: max_xn_reached=None/NaN, hit_x2=False, hit_x5=False
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию без цен
    pos = Position(
        signal_id="test_3",
        contract_address="TOKEN3",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=0.0,  # Нет цены
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=0.0,  # Нет цены
        status="closed",
        pnl_pct=0.0,
        meta={
            "pnl_sol": 0.0,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=10.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            trades_executed=1,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
        )
    )
    
    portfolio_results = {"test_strategy": portfolio_result}
    reporter.save_portfolio_positions_table(portfolio_results)
    
    # Проверяем результат
    positions_path = tmp_path / "portfolio_positions.csv"
    assert positions_path.exists(), "portfolio_positions.csv должен быть создан"
    
    df = pd.read_csv(positions_path)
    assert len(df) == 1, "Должна быть одна позиция"
    
    row = df.iloc[0]
    # max_xn_reached должен быть NaN если цены отсутствуют или равны 0
    assert pd.isna(row["max_xn_reached"]) or row["max_xn_reached"] == 0, f"max_xn_reached должен быть NaN или 0, получен {row['max_xn_reached']}"
    assert row["hit_x2"] == False, f"hit_x2 должен быть False, получен {row['hit_x2']}"
    assert row["hit_x5"] == False, f"hit_x5 должен быть False, получен {row['hit_x5']}"


def test_max_xn_columns_exist(tmp_path):
    """
    Тест: проверка что колонки max_xn_reached, hit_x2, hit_x5 существуют в CSV.
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем пустой результат
    portfolio_results = {}
    reporter.save_portfolio_positions_table(portfolio_results)
    
    # Проверяем что файл создан с правильными колонками
    positions_path = tmp_path / "portfolio_positions.csv"
    assert positions_path.exists(), "portfolio_positions.csv должен быть создан"
    
    df = pd.read_csv(positions_path)
    
    # Проверяем наличие обязательных колонок
    required_cols = ["max_xn_reached", "hit_x2", "hit_x5"]
    for col in required_cols:
        assert col in df.columns, f"Колонка {col} должна существовать в portfolio_positions.csv"

