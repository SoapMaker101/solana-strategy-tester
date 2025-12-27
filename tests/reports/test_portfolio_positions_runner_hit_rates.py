"""
Тесты для проверки расчета max_xn_reached, hit_x2, hit_x5 из levels_hit в portfolio_positions.csv.

T1: levels_hit определяет max_xn_reached
T2: fallback raw prices
T3: fallback exec prices
T4: no data
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from backtester.domain.position import Position
from backtester.domain.portfolio import PortfolioResult, PortfolioStats
from backtester.infrastructure.reporter import Reporter


def test_levels_hit_determines_max_xn_reached(tmp_path):
    """
    T1: levels_hit определяет max_xn_reached
    
    Position.meta.levels_hit = {"2.0": "...", "7.0": "..."}
    Ожидаем:
    - max_xn_reached == 7.0
    - hit_x2 True
    - hit_x5 True
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию с levels_hit в meta
    pos = Position(
        signal_id="test_1",
        contract_address="TOKEN1",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=7.0,
        status="closed",
        pnl_pct=6.0,
        meta={
            "levels_hit": {
                "2.0": "2024-01-01T12:30:00Z",
                "7.0": "2024-01-01T12:45:00Z",
            },
            "exec_entry_price": 1.0,
            "exec_exit_price": 6.5,  # Меньше чем 7.0 из levels_hit
            "raw_entry_price": 0.98,
            "raw_exit_price": 6.4,  # Меньше чем 7.0 из levels_hit
            "pnl_sol": 6.0,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=16.0,
            total_return_pct=0.6,
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
    assert row["max_xn_reached"] == 7.0, f"max_xn_reached должен быть 7.0 (из levels_hit), получен {row['max_xn_reached']}"
    assert row["hit_x2"] == True, f"hit_x2 должен быть True, получен {row['hit_x2']}"
    assert row["hit_x5"] == True, f"hit_x5 должен быть True, получен {row['hit_x5']}"


def test_fallback_raw_prices(tmp_path):
    """
    T2: fallback raw prices
    
    levels_hit отсутствует
    raw_entry_price=1.0 raw_exit_price=6.0
    Ожидаем: max_xn_reached=6.0, hit_x5 True
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию без levels_hit, но с raw ценами
    pos = Position(
        signal_id="test_2",
        contract_address="TOKEN2",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=6.0,
        status="closed",
        pnl_pct=5.0,
        meta={
            # levels_hit отсутствует
            "raw_entry_price": 1.0,
            "raw_exit_price": 6.0,
            "pnl_sol": 5.0,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=15.0,
            total_return_pct=0.5,
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
    assert abs(row["max_xn_reached"] - 6.0) < 0.001, f"max_xn_reached должен быть ~6.0 (из raw цен), получен {row['max_xn_reached']}"
    assert row["hit_x2"] == True, f"hit_x2 должен быть True, получен {row['hit_x2']}"
    assert row["hit_x5"] == True, f"hit_x5 должен быть True, получен {row['hit_x5']}"


def test_fallback_exec_prices(tmp_path):
    """
    T3: fallback exec prices
    
    levels_hit отсутствует, raw отсутствуют
    exec_entry_price=1.0 exec_exit_price=1.9
    Ожидаем: max_xn_reached=1.9, hit_x2 False
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию без levels_hit и raw цен, но с exec ценами
    pos = Position(
        signal_id="test_3",
        contract_address="TOKEN3",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=1.9,
        status="closed",
        pnl_pct=0.9,
        meta={
            # levels_hit отсутствует, raw цены отсутствуют
            "exec_entry_price": 1.0,
            "exec_exit_price": 1.9,
            "pnl_sol": 0.9,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=10.9,
            total_return_pct=0.09,
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
    assert abs(row["max_xn_reached"] - 1.9) < 0.001, f"max_xn_reached должен быть ~1.9 (из exec цен), получен {row['max_xn_reached']}"
    assert row["hit_x2"] == False, f"hit_x2 должен быть False (1.9 < 2.0), получен {row['hit_x2']}"
    assert row["hit_x5"] == False, f"hit_x5 должен быть False (1.9 < 5.0), получен {row['hit_x5']}"


def test_no_data(tmp_path):
    """
    T4: no data
    
    levels_hit отсутствует, цены None
    Ожидаем: max_xn_reached None, hit_x2 False, hit_x5 False
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию без levels_hit и без цен
    pos = Position(
        signal_id="test_4",
        contract_address="TOKEN4",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=0.0,  # Нет цены
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=0.0,  # Нет цены
        status="closed",
        pnl_pct=0.0,
        meta={
            # levels_hit отсутствует, цены отсутствуют
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
    # max_xn_reached должен быть NaN если данных нет
    assert pd.isna(row["max_xn_reached"]) or row["max_xn_reached"] == 0, f"max_xn_reached должен быть NaN или 0, получен {row['max_xn_reached']}"
    assert row["hit_x2"] == False, f"hit_x2 должен быть False, получен {row['hit_x2']}"
    assert row["hit_x5"] == False, f"hit_x5 должен быть False, получен {row['hit_x5']}"


def test_max_xn_reached_columns_exist(tmp_path):
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


def test_levels_hit_invalid_keys(tmp_path, caplog):
    """
    Тест: проверка обработки невалидных ключей в levels_hit.
    
    levels_hit содержит невалидные ключи (не float)
    Ожидаем: warning в логах, fallback на цены
    """
    import logging
    logging.basicConfig(level=logging.WARNING)
    
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем позицию с невалидными ключами в levels_hit
    pos = Position(
        signal_id="test_5",
        contract_address="TOKEN5",
        entry_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=3.0,
        status="closed",
        pnl_pct=2.0,
        meta={
            "levels_hit": {
                "invalid_key": "2024-01-01T12:30:00Z",  # Невалидный ключ
                "not_a_number": "2024-01-01T12:45:00Z",  # Невалидный ключ
            },
            "raw_entry_price": 1.0,
            "raw_exit_price": 3.0,  # Fallback на цены
            "pnl_sol": 2.0,
            "fees_total_sol": 0.1,
        }
    )
    
    portfolio_result = PortfolioResult(
        positions=[pos],
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=12.0,
            total_return_pct=0.2,
            max_drawdown_pct=0.0,
            trades_executed=1,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
        )
    )
    
    portfolio_results = {"test_strategy": portfolio_result}
    reporter.save_portfolio_positions_table(portfolio_results)
    
    # Проверяем что был warning
    assert any("Invalid levels_hit keys" in record.message for record in caplog.records), "Должен быть warning о невалидных ключах"
    
    # Проверяем результат - должен использоваться fallback на цены
    positions_path = tmp_path / "portfolio_positions.csv"
    assert positions_path.exists(), "portfolio_positions.csv должен быть создан"
    
    df = pd.read_csv(positions_path)
    assert len(df) == 1, "Должна быть одна позиция"
    
    row = df.iloc[0]
    assert abs(row["max_xn_reached"] - 3.0) < 0.001, f"max_xn_reached должен быть ~3.0 (fallback на raw цены), получен {row['max_xn_reached']}"








