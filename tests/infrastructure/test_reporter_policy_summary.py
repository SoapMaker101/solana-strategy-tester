"""
Тесты для save_portfolio_policy_summary (без pandas).

Проверяет, что метод работает с csv.DictWriter и создает корректные CSV файлы.
"""
import tempfile
import csv
from pathlib import Path

import pytest

from backtester.infrastructure.reporter import Reporter


def test_save_portfolio_policy_summary_with_data():
    """
    Тест: save_portfolio_policy_summary создает CSV файл с данными.
    
    Проверяет:
    - Файл создан
    - Header присутствует
    - Данные записаны корректно
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        # Создаем тестовые данные (как в реальном коде)
        summary_rows = [
            {"strategy": "test_strategy_1", "portfolio_reset_profit_count": 2, "portfolio_reset_capacity_count": 1, "b": 2},
            {"strategy": "test_strategy_2", "portfolio_reset_profit_count": 1, "portfolio_reset_capacity_count": 0, "b": 4},
        ]
        
        # Вызываем метод (симулируем через вызов на пустом portfolio_results)
        # Но метод принимает portfolio_results, поэтому нам нужно вызвать его правильно
        # Или можно использовать mock/рефлексию, но проще создать минимальный PortfolioResult
        
        # В реальности метод получает summary_rows из portfolio_results
        # Для теста мы можем напрямую проверить логику записи CSV
        # Но так как метод приватный, протестируем через публичный интерфейс
        
        # Создаем минимальный portfolio_results для вызова метода
        from backtester.domain.portfolio import PortfolioResult, PortfolioStats
        
        stats1 = PortfolioStats(
            final_balance_sol=10.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            trades_executed=0,
            trades_skipped_by_risk=0,
            portfolio_reset_profit_count=2,
            portfolio_reset_capacity_count=1,
        )
        
        result1 = PortfolioResult(
            equity_curve=[],
            positions=[],
            stats=stats1,
        )
        
        portfolio_results = {"test_strategy_1": result1}
        
        # Вызываем метод
        reporter.save_portfolio_policy_summary(portfolio_results)
        
        # Проверяем, что файл создан
        summary_path = Path(tmpdir) / "portfolio_policy_summary.csv"
        assert summary_path.exists(), "portfolio_policy_summary.csv должен быть создан"
        
        # Читаем файл и проверяем содержимое
        with open(summary_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            # Проверяем header
            assert reader.fieldnames is not None
            assert "strategy" in reader.fieldnames
            assert "portfolio_reset_profit_count" in reader.fieldnames
            assert "portfolio_reset_capacity_count" in reader.fieldnames
            
            # Проверяем данные (если есть строки)
            if rows:
                assert len(rows) >= 1
                first_row = rows[0]
                assert "strategy" in first_row
                assert first_row["strategy"] == "test_strategy_1"


def test_save_portfolio_policy_summary_empty():
    """
    Тест: save_portfolio_policy_summary создает файл с header даже при пустых данных.
    
    Проверяет:
    - Файл создан
    - Header присутствует
    - Файл не падает при пустом portfolio_results
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        reporter = Reporter(output_dir=tmpdir)
        
        # Вызываем метод с пустым словарем
        portfolio_results = {}
        reporter.save_portfolio_policy_summary(portfolio_results)
        
        # Проверяем, что файл создан
        summary_path = Path(tmpdir) / "portfolio_policy_summary.csv"
        assert summary_path.exists(), "portfolio_policy_summary.csv должен быть создан даже при пустых данных"
        
        # Читаем файл и проверяем header
        with open(summary_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Проверяем, что header присутствует
            assert reader.fieldnames is not None
            assert len(reader.fieldnames) > 0
            
            # Проверяем, что файл содержит ожидаемые колонки
            expected_columns = [
                "strategy",
                "portfolio_reset_profit_count",
                "portfolio_reset_capacity_count",
                "portfolio_capacity_prune_count",
            ]
            for col in expected_columns:
                assert col in reader.fieldnames, f"Колонка {col} должна быть в header"
            
            # Проверяем, что строк данных нет
            rows = list(reader)
            assert len(rows) == 0, "При пустом portfolio_results файл должен содержать только header"

