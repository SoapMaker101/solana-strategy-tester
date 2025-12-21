# tests/research/signal_quality/test_cap_thresholds.py
"""
Тесты для модуля cap_thresholds.
"""

import pytest
import pandas as pd

from backtester.research.signal_quality.cap_thresholds import (
    analyze_cap_thresholds,
    compute_runner_label,
)


class TestComputeRunnerLabel:
    """Тесты для compute_runner_label."""
    
    def test_runner_label_basic(self):
        """Тест базового вычисления is_runner."""
        df = pd.DataFrame({
            "max_xn": [2.0, 3.0, 4.0, 5.0]
        })
        
        result = compute_runner_label(df, runner_xn_threshold=3.0)
        
        assert result.tolist() == [False, True, True, True]
    
    def test_runner_label_custom_threshold(self):
        """Тест с кастомным порогом."""
        df = pd.DataFrame({
            "max_xn": [2.0, 3.0, 4.0, 5.0]
        })
        
        result = compute_runner_label(df, runner_xn_threshold=4.0)
        
        assert result.tolist() == [False, False, True, True]
    
    def test_runner_label_no_max_xn(self):
        """Тест когда нет колонки max_xn."""
        df = pd.DataFrame({
            "other_col": [1, 2, 3]
        })
        
        result = compute_runner_label(df)
        
        assert result.tolist() == [False, False, False]


class TestAnalyzeCapThresholds:
    """Тесты для analyze_cap_thresholds."""
    
    def test_analyze_cap_thresholds_basic(self):
        """Тест базового анализа порогов."""
        df = pd.DataFrame({
            "signal_id": ["s1", "s2", "s3", "s4", "s5"],
            "market_cap_proxy": [10000, 30000, 50000, 80000, 100000],
            "max_xn": [2.0, 3.0, 4.0, 2.5, 5.0],
            "status": ["ok", "ok", "ok", "ok", "ok"]
        })
        
        thresholds = [20000, 40000, 60000]
        result = analyze_cap_thresholds(df, thresholds, runner_xn_threshold=3.0)
        
        assert len(result) == 3
        assert "min_market_cap_proxy" in result.columns
        assert "kept_signals" in result.columns
        assert "kept_runners" in result.columns
        
        # Проверяем первый порог (20000)
        row_20k = result[result["min_market_cap_proxy"] == 20000].iloc[0]
        assert row_20k["kept_signals"] == 4  # s2, s3, s4, s5
        assert row_20k["kept_runners"] == 3  # s2 (3x), s3 (4x), s5 (5x)
    
    def test_analyze_cap_thresholds_with_invalid_status(self):
        """Тест с сигналами с разными статусами."""
        df = pd.DataFrame({
            "signal_id": ["s1", "s2", "s3", "s4"],
            "market_cap_proxy": [10000, 30000, 50000, 80000],
            "max_xn": [2.0, 3.0, 4.0, 2.5],
            "status": ["ok", "ok", "no_candles", "ok"]
        })
        
        thresholds = [20000]
        result = analyze_cap_thresholds(df, thresholds, runner_xn_threshold=3.0)
        
        # Только валидные сигналы (status="ok") учитываются
        row = result.iloc[0]
        assert row["kept_signals"] == 2  # s2 и s4 (s3 пропущен из-за статуса)
    
    def test_analyze_cap_thresholds_empty(self):
        """Тест с пустым DataFrame."""
        df = pd.DataFrame()
        thresholds = [20000]
        
        result = analyze_cap_thresholds(df, thresholds)
        
        assert result.empty
    
    def test_analyze_cap_thresholds_no_valid_signals(self):
        """Тест когда нет валидных сигналов."""
        df = pd.DataFrame({
            "signal_id": ["s1", "s2"],
            "market_cap_proxy": [10000, 30000],
            "max_xn": [2.0, 3.0],
            "status": ["no_candles", "error"]
        })
        
        thresholds = [20000]
        result = analyze_cap_thresholds(df, thresholds)
        
        assert result.empty









