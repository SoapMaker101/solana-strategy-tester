"""
Тесты для проверки что strategy_summary.csv строго portfolio-derived (Runner-only).

T2: strategy_summary portfolio-derived
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from backtester.domain.position import Position
from backtester.domain.portfolio import PortfolioResult, PortfolioStats
from backtester.infrastructure.reporter import Reporter
from main import generate_strategy_summary


def test_strategy_summary_portfolio_derived_runner(tmp_path):
    """
    T2: strategy_summary portfolio-derived
    
    Создать df из 5 строк portfolio_positions
    Проверить:
    - total_trades
    - pnl_total_sol / fees_total_sol
    - hit_rate_x2/x5
    - reset counts
    - hold percentiles
    """
    reporter = Reporter(output_dir=str(tmp_path))
    
    # Создаем 5 позиций для одной стратегии
    positions = []
    
    # Позиция 1: прибыльная, hit_x2=True, hit_x5=False, закрыта по profit reset
    pos1 = Position(
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
            "levels_hit": {"2.0": "2024-01-01T12:30:00Z"},
            "pnl_sol": 1.5,
            "fees_total_sol": 0.1,
            "exec_entry_price": 1.0,
            "exec_exit_price": 2.5,
            "raw_entry_price": 0.98,
            "raw_exit_price": 2.45,
            "closed_by_reset": True,
            "triggered_portfolio_reset": False,
            "reset_reason": "profit",
        }
    )
    positions.append(pos1)
    
    # Позиция 2: прибыльная, hit_x2=True, hit_x5=True, закрыта по capacity reset
    pos2 = Position(
        signal_id="test_2",
        contract_address="TOKEN2",
        entry_time=datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 2, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=6.0,
        status="closed",
        pnl_pct=5.0,
        meta={
            "levels_hit": {"2.0": "2024-01-02T12:15:00Z", "5.0": "2024-01-02T12:30:00Z"},
            "pnl_sol": 5.0,
            "fees_total_sol": 0.1,
            "exec_entry_price": 1.0,
            "exec_exit_price": 6.0,
            "raw_entry_price": 0.98,
            "raw_exit_price": 5.9,
            "closed_by_reset": True,
            "triggered_portfolio_reset": False,
            "reset_reason": "capacity",
        }
    )
    positions.append(pos2)
    
    # Позиция 3: убыточная, hit_x2=False, hit_x5=False
    pos3 = Position(
        signal_id="test_3",
        contract_address="TOKEN3",
        entry_time=datetime(2024, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 3, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=0.8,
        status="closed",
        pnl_pct=-0.2,
        meta={
            "pnl_sol": -0.2,
            "fees_total_sol": 0.1,
            "exec_entry_price": 1.0,
            "exec_exit_price": 0.8,
            "raw_entry_price": 0.98,
            "raw_exit_price": 0.78,
            "closed_by_reset": False,
            "triggered_portfolio_reset": False,
            "reset_reason": "none",
        }
    )
    positions.append(pos3)
    
    # Позиция 4: прибыльная, hit_x2=True, hit_x5=False, триггернула reset
    pos4 = Position(
        signal_id="test_4",
        contract_address="TOKEN4",
        entry_time=datetime(2024, 1, 4, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 4, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=2.2,
        status="closed",
        pnl_pct=1.2,
        meta={
            "levels_hit": {"2.0": "2024-01-04T12:20:00Z"},
            "pnl_sol": 1.2,
            "fees_total_sol": 0.1,
            "exec_entry_price": 1.0,
            "exec_exit_price": 2.2,
            "raw_entry_price": 0.98,
            "raw_exit_price": 2.15,
            "closed_by_reset": True,
            "triggered_portfolio_reset": True,
            "reset_reason": "profit",
        }
    )
    positions.append(pos4)
    
    # Позиция 5: прибыльная, hit_x2=False, hit_x5=False
    pos5 = Position(
        signal_id="test_5",
        contract_address="TOKEN5",
        entry_time=datetime(2024, 1, 5, 12, 0, 0, tzinfo=timezone.utc),
        entry_price=1.0,
        size=1.0,
        exit_time=datetime(2024, 1, 5, 13, 0, 0, tzinfo=timezone.utc),
        exit_price=1.5,
        status="closed",
        pnl_pct=0.5,
        meta={
            "pnl_sol": 0.5,
            "fees_total_sol": 0.1,
            "exec_entry_price": 1.0,
            "exec_exit_price": 1.5,
            "raw_entry_price": 0.98,
            "raw_exit_price": 1.48,
            "closed_by_reset": False,
            "triggered_portfolio_reset": False,
            "reset_reason": "none",
        }
    )
    positions.append(pos5)
    
    # Создаем portfolio_result
    portfolio_result = PortfolioResult(
        positions=positions,
        equity_curve=[],
        stats=PortfolioStats(
            final_balance_sol=18.0,
            total_return_pct=0.8,
            max_drawdown_pct=0.1,
            trades_executed=5,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
        )
    )
    
    # Сохраняем portfolio_positions.csv
    portfolio_results = {"Runner_Test": portfolio_result}
    reporter.save_portfolio_positions_table(portfolio_results)
    
    # Генерируем strategy_summary
    generate_strategy_summary(
        results_by_strategy={},
        portfolio_results=portfolio_results,
        output_dir=tmp_path,
        reporter=reporter
    )
    
    # Проверяем результат
    summary_path = tmp_path / "strategy_summary.csv"
    assert summary_path.exists(), "strategy_summary.csv должен быть создан"
    
    df = pd.read_csv(summary_path)
    assert len(df) == 1, "Должна быть одна стратегия"
    
    row = df.iloc[0]
    
    # Проверяем базовые счетчики
    assert row["total_trades"] == 5, f"total_trades должен быть 5, получен {row['total_trades']}"
    assert row["winning_trades"] == 4, f"winning_trades должен быть 4, получен {row['winning_trades']}"
    assert row["losing_trades"] == 1, f"losing_trades должен быть 1, получен {row['losing_trades']}"
    assert abs(row["winrate"] - 0.8) < 0.001, f"winrate должен быть 0.8, получен {row['winrate']}"
    
    # Проверяем PnL
    assert abs(row["strategy_total_pnl_sol"] - 8.0) < 0.001, f"strategy_total_pnl_sol должен быть 8.0, получен {row['strategy_total_pnl_sol']}"
    assert abs(row["fees_total_sol"] - 0.5) < 0.001, f"fees_total_sol должен быть 0.5, получен {row['fees_total_sol']}"
    assert abs(row["pnl_net_sol"] - 7.5) < 0.001, f"pnl_net_sol должен быть 7.5, получен {row['pnl_net_sol']}"
    
    # Проверяем hit rates
    assert abs(row["hit_rate_x2"] - 0.6) < 0.001, f"hit_rate_x2 должен быть 0.6 (3 из 5), получен {row['hit_rate_x2']}"
    assert abs(row["hit_rate_x5"] - 0.2) < 0.001, f"hit_rate_x5 должен быть 0.2 (1 из 5), получен {row['hit_rate_x5']}"
    
    # Проверяем reset counts
    assert row["profit_reset_closed_count"] == 2, f"profit_reset_closed_count должен быть 2, получен {row['profit_reset_closed_count']}"
    assert row["capacity_reset_closed_count"] == 1, f"capacity_reset_closed_count должен быть 1, получен {row['capacity_reset_closed_count']}"
    assert row["closed_by_reset_count"] == 3, f"closed_by_reset_count должен быть 3, получен {row['closed_by_reset_count']}"
    assert row["triggered_portfolio_reset_count"] == 1, f"triggered_portfolio_reset_count должен быть 1, получен {row['triggered_portfolio_reset_count']}"
    
    # Проверяем hold percentiles (все позиции закрыты через 60 минут)
    assert abs(row["avg_hold_minutes"] - 60.0) < 0.001, f"avg_hold_minutes должен быть 60.0, получен {row['avg_hold_minutes']}"
    assert abs(row["p50_hold_minutes"] - 60.0) < 0.001, f"p50_hold_minutes должен быть 60.0, получен {row['p50_hold_minutes']}"
    assert abs(row["p90_hold_minutes"] - 60.0) < 0.001, f"p90_hold_minutes должен быть 60.0, получен {row['p90_hold_minutes']}"
    
    # Проверяем наличие всех обязательных колонок
    required_cols = [
        "strategy", "total_trades", "winning_trades", "losing_trades", "winrate",
        "strategy_total_pnl_sol", "fees_total_sol", "pnl_net_sol",
        "avg_pnl_sol", "median_pnl_sol", "best_trade_pnl_sol", "worst_trade_pnl_sol",
        "hit_rate_x2", "hit_rate_x5",
        "profit_reset_closed_count", "capacity_reset_closed_count",
        "closed_by_reset_count", "triggered_portfolio_reset_count",
        "avg_hold_minutes", "p50_hold_minutes", "p90_hold_minutes",
    ]
    for col in required_cols:
        assert col in df.columns, f"Колонка {col} должна существовать в strategy_summary.csv"

