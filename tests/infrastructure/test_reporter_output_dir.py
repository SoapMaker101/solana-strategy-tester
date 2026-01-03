"""
Интеграционный тест для проверки, что файлы сохраняются в правильную директорию.

Проверяет, что:
- strategy_trades.csv сохраняется в reports_dir
- portfolio артефакты сохраняются в reports_dir
- Все артефакты сохраняются в одну директорию без ошибок
"""
import tempfile
from pathlib import Path

import pytest

from backtester.infrastructure.reporter import Reporter
from backtester.domain.strategy_trade_blueprint import StrategyTradeBlueprint
from backtester.domain.portfolio import PortfolioResult, PortfolioStats, Position
from datetime import datetime, timezone


@pytest.fixture
def sample_blueprint():
    """Создает минимальный blueprint для тестирования."""
    return StrategyTradeBlueprint(
        signal_id="sig_001",
        strategy_id="test_strategy",
        contract_address="0x123",
        entry_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        entry_price_raw=100.0,
        entry_mcap_proxy=None,
        partial_exits=[],
        final_exit=None,
        realized_multiple=0.0,
        max_xn_reached=0.0,
        reason="no_entry",
    )


@pytest.fixture
def sample_portfolio_result():
    """Создает минимальный PortfolioResult для тестирования."""
    stats = PortfolioStats(
        final_balance_sol=10.0,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        trades_executed=0,
        trades_skipped_by_risk=0,
    )
    
    # Минимальная позиция
    position = Position(
        position_id="pos_001",
        signal_id="sig_001",
        contract_address="0x123",
        entry_time=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        exit_price=110.0,
        size=1.0,
        pnl_pct=0.1,
        status="closed",
        meta={},
    )
    
    return PortfolioResult(
        equity_curve=[],
        positions=[position],
        stats=stats,
    )


def test_reporter_saves_strategy_trades_in_output_dir(sample_blueprint):
    """Тест: strategy_trades.csv сохраняется в output_dir репортера."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reports_dir = Path(tmpdir) / "test_reports"
        reporter = Reporter(output_dir=str(reports_dir))
        
        # Сохраняем strategy_trades.csv
        reporter.save_strategy_trades([sample_blueprint])
        
        # Проверяем, что файл создан в правильной директории
        strategy_trades_path = reports_dir / "strategy_trades.csv"
        assert strategy_trades_path.exists(), f"strategy_trades.csv должен быть в {reports_dir}"
        assert strategy_trades_path.is_file()


def test_reporter_saves_portfolio_artifacts_in_output_dir(sample_portfolio_result):
    """Тест: portfolio артефакты сохраняются в output_dir репортера."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reports_dir = Path(tmpdir) / "test_reports"
        reporter = Reporter(output_dir=str(reports_dir))
        
        # Сохраняем portfolio артефакты
        portfolio_results = {"test_strategy": sample_portfolio_result}
        reporter.save_portfolio_positions_table(portfolio_results)
        reporter.save_portfolio_events_table(portfolio_results)
        
        # Проверяем, что файлы созданы в правильной директории
        positions_path = reports_dir / "portfolio_positions.csv"
        events_path = reports_dir / "portfolio_events.csv"
        
        assert positions_path.exists(), f"portfolio_positions.csv должен быть в {reports_dir}"
        assert events_path.exists(), f"portfolio_events.csv должен быть в {reports_dir}"


def test_reporter_all_artifacts_in_same_dir(sample_blueprint, sample_portfolio_result):
    """Тест: все артефакты (strategy_trades + portfolio) сохраняются в одну директорию."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reports_dir = Path(tmpdir) / "test_reports"
        reporter = Reporter(output_dir=str(reports_dir))
        
        # Сохраняем strategy_trades.csv
        reporter.save_strategy_trades([sample_blueprint])
        
        # Сохраняем portfolio артефакты
        portfolio_results = {"test_strategy": sample_portfolio_result}
        reporter.save_portfolio_positions_table(portfolio_results)
        reporter.save_portfolio_events_table(portfolio_results)
        reporter.save_portfolio_executions_table(portfolio_results)
        
        # Проверяем, что все файлы в одной директории
        strategy_trades_path = reports_dir / "strategy_trades.csv"
        positions_path = reports_dir / "portfolio_positions.csv"
        events_path = reports_dir / "portfolio_events.csv"
        executions_path = reports_dir / "portfolio_executions.csv"
        
        assert strategy_trades_path.exists(), "strategy_trades.csv должен быть в reports_dir"
        assert positions_path.exists(), "portfolio_positions.csv должен быть в reports_dir"
        assert events_path.exists(), "portfolio_events.csv должен быть в reports_dir"
        assert executions_path.exists(), "portfolio_executions.csv должен быть в reports_dir"
        
        # Проверяем, что все файлы в одной директории (не в поддиректориях)
        assert strategy_trades_path.parent == reports_dir
        assert positions_path.parent == reports_dir
        assert events_path.parent == reports_dir
        assert executions_path.parent == reports_dir

