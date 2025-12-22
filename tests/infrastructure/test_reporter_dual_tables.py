"""
Тесты для dual reporting: positions-level и executions-level таблицы.
"""
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta
from tempfile import TemporaryDirectory

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine,
    PortfolioResult,
    PortfolioStats,
)
from backtester.domain.models import StrategyOutput
from backtester.domain.position import Position
from backtester.infrastructure.reporter import Reporter


def test_positions_table_no_duplicates():
    """
    Тест: positions report не содержит дублей по (strategy, signal_id, contract).
    
    Сценарий:
    - Создаем позиции с одинаковым signal_id (например, partial exits)
    - Генерируем positions-level таблицу
    - Проверяем: нет дублей
    
    Проверяем:
    - Каждая комбинация (strategy, signal_id, contract_address) встречается только 1 раз
    """
    reporter = Reporter()
    
    # Создаем синтетические позиции
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    positions = []
    
    # Позиция 1: обычная
    pos1 = Position(
        signal_id="signal_1",
        contract_address="TOKEN1",
        entry_time=base_time,
        entry_price=1.0,
        size=1.0,
        exit_time=base_time + timedelta(hours=2),
        exit_price=1.05,
        pnl_pct=0.05,
        status="closed",
        meta={
            "strategy": "test_strategy",
            "pnl_sol": 0.05,
            "fees_total_sol": 0.001,
            "exec_entry_price": 1.0,
            "exec_exit_price": 1.05,
            "raw_entry_price": 1.0,
            "raw_exit_price": 1.05,
        }
    )
    positions.append(pos1)
    
    # Позиция 2: с partial exits (Runner)
    pos2 = Position(
        signal_id="signal_2",
        contract_address="TOKEN2",
        entry_time=base_time + timedelta(hours=1),
        entry_price=1.0,
        size=0.0,  # Полностью закрыта через partial exits
        exit_time=base_time + timedelta(hours=5),
        exit_price=1.1,
        pnl_pct=0.1,
        status="closed",
        meta={
            "strategy": "test_strategy",
            "pnl_sol": 0.1,
            "fees_total_sol": 0.002,
            "exec_entry_price": 1.0,
            "exec_exit_price": 1.1,
            "raw_entry_price": 1.0,
            "raw_exit_price": 1.1,
            "partial_exits": [
                {"exit_size": 0.5, "pnl_sol": 0.05},
                {"exit_size": 0.5, "pnl_sol": 0.05},
            ]
        }
    )
    positions.append(pos2)
    
    # Создаем PortfolioResult
    stats = PortfolioStats(
        final_balance_sol=10.1,
        total_return_pct=0.01,
        max_drawdown_pct=0.0,
        trades_executed=2,
        trades_skipped_by_risk=0,
    )
    
    result = PortfolioResult(
        equity_curve=[],
        positions=positions,
        stats=stats,
    )
    
    portfolio_results = {"test_strategy": result}
    
    # Генерируем таблицу
    with TemporaryDirectory() as tmpdir:
        reporter.output_dir = Path(tmpdir)
        reporter.save_portfolio_positions_table(portfolio_results)
        
        # Читаем сгенерированный файл
        positions_path = reporter.output_dir / "portfolio_positions.csv"
        assert positions_path.exists(), "Файл portfolio_positions.csv должен быть создан"
        
        df = pd.read_csv(positions_path)
        
        # Проверяем отсутствие дублей
        duplicates = df.duplicated(subset=["strategy", "signal_id", "contract_address"], keep=False)
        assert not duplicates.any(), \
            f"Найдены дубликаты в positions table: {df[duplicates]}"
        
        # Проверяем что каждая позиция представлена только один раз
        assert len(df) == len(positions), \
            f"Количество строк ({len(df)}) должно совпадать с количеством позиций ({len(positions)})"


def test_executions_table_has_partial_exits():
    """
    Тест: executions report содержит несколько строк для одного signal_id, если были partial exits.
    
    Сценарий:
    - Создаем позицию с partial exits (Runner стратегия)
    - Генерируем executions-level таблицу
    - Проверяем: несколько строк для одного signal_id
    
    Проверяем:
    - Есть entry event
    - Есть partial_exit events
    - Есть final_exit event (если есть)
    """
    reporter = Reporter()
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    positions = []
    
    # Позиция с partial exits
    pos = Position(
        signal_id="signal_runner",
        contract_address="TOKEN_RUNNER",
        entry_time=base_time,
        entry_price=1.0,
        size=0.0,  # Полностью закрыта
        exit_time=base_time + timedelta(hours=5),
        exit_price=1.1,
        pnl_pct=0.1,
        status="closed",
        meta={
            "strategy": "test_strategy",
            "pnl_sol": 0.1,
            "fees_total_sol": 0.003,
            "exec_entry_price": 1.0,
            "exec_exit_price": 1.1,
            "raw_entry_price": 1.0,
            "raw_exit_price": 1.1,
            "partial_exits": [
                {
                    "hit_time": (base_time + timedelta(hours=2)).isoformat(),
                    "exit_size": 0.5,
                    "exit_price": 1.05,
                    "pnl_sol": 0.025,
                    "fees_sol": 0.001,
                    "network_fee_sol": 0.0005,
                },
                {
                    "hit_time": (base_time + timedelta(hours=4)).isoformat(),
                    "exit_size": 0.5,
                    "exit_price": 1.1,
                    "pnl_sol": 0.05,
                    "fees_sol": 0.001,
                    "network_fee_sol": 0.0005,
                },
            ]
        }
    )
    positions.append(pos)
    
    stats = PortfolioStats(
        final_balance_sol=10.1,
        total_return_pct=0.01,
        max_drawdown_pct=0.0,
        trades_executed=1,
        trades_skipped_by_risk=0,
    )
    
    result = PortfolioResult(
        equity_curve=[],
        positions=positions,
        stats=stats,
    )
    
    portfolio_results = {"test_strategy": result}
    
    # Генерируем таблицу
    with TemporaryDirectory() as tmpdir:
        reporter.output_dir = Path(tmpdir)
        reporter.save_portfolio_executions_table(portfolio_results)
        
        # Читаем сгенерированный файл
        executions_path = reporter.output_dir / "portfolio_executions.csv"
        assert executions_path.exists(), "Файл portfolio_executions.csv должен быть создан"
        
        df = pd.read_csv(executions_path)
        
        # Фильтруем по signal_id
        signal_executions = df[df["signal_id"] == "signal_runner"]
        
        # Должно быть минимум 3 события: entry + 2 partial_exit
        assert len(signal_executions) >= 3, \
            f"Должно быть минимум 3 события (entry + 2 partial_exit), получено: {len(signal_executions)}"
        
        # Проверяем наличие entry
        entry_events = signal_executions[signal_executions["event_type"] == "entry"]
        assert len(entry_events) == 1, "Должен быть ровно 1 entry event"
        
        # Проверяем наличие partial_exit
        partial_exit_events = signal_executions[signal_executions["event_type"] == "partial_exit"]
        assert len(partial_exit_events) >= 2, \
            f"Должно быть минимум 2 partial_exit events, получено: {len(partial_exit_events)}"


