# tests/research/signal_quality/test_filter_signals.py
"""
Тесты для модуля filter_signals.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile

from backtester.research.signal_quality.filter_signals import (
    filter_signals,
    generate_filter_summary,
)


@pytest.fixture
def sample_signals_csv(tmp_path):
    """Создаёт временный CSV файл с сигналами."""
    signals_data = {
        "id": ["s1", "s2", "s3", "s4", "s5"],
        "contract_address": ["c1", "c2", "c3", "c4", "c5"],
        "timestamp": [
            "2025-01-01T12:00:00Z",
            "2025-01-01T13:00:00Z",
            "2025-01-01T14:00:00Z",
            "2025-01-01T15:00:00Z",
            "2025-01-01T16:00:00Z",
        ],
        "source": ["test"] * 5,
        "narrative": [""] * 5,
    }
    df = pd.DataFrame(signals_data)
    csv_path = tmp_path / "signals.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def sample_features_df():
    """Создаёт DataFrame с признаками."""
    return pd.DataFrame({
        "signal_id": ["s1", "s2", "s3", "s4", "s5"],
        "market_cap_proxy": [10000, 30000, 50000, 80000, 100000],
        "status": ["ok", "ok", "ok", "ok", "ok"]
    })


class TestFilterSignals:
    """Тесты для filter_signals."""
    
    def test_filter_signals_basic(self, sample_signals_csv, sample_features_df):
        """Тест базовой фильтрации."""
        result = filter_signals(
            signals_path=sample_signals_csv,
            features_df=sample_features_df,
            min_market_cap_proxy=40000,
            require_status_ok=True
        )
        
        # Должны остаться s3, s4, s5 (market_cap_proxy >= 40000)
        assert len(result) == 3
        assert set(result["id"].tolist()) == {"s3", "s4", "s5"}
    
    def test_filter_signals_no_status_ok_requirement(self, sample_signals_csv, sample_features_df):
        """Тест фильтрации без требования status=ok."""
        # Добавляем сигнал с невалидным статусом
        features_with_error = sample_features_df.copy()
        features_with_error.loc[4, "status"] = "error"
        features_with_error.loc[4, "market_cap_proxy"] = 150000  # Высокий cap
        
        result = filter_signals(
            signals_path=sample_signals_csv,
            features_df=features_with_error,
            min_market_cap_proxy=40000,
            require_status_ok=False
        )
        
        # s5 должен быть включён даже со статусом "error" (s3, s4, s5 остаются)
        assert len(result) == 3
        assert "s5" in result["id"].tolist()
        assert set(result["id"].tolist()) == {"s3", "s4", "s5"}
    
    def test_filter_signals_with_status_ok_requirement(self, sample_signals_csv, sample_features_df):
        """Тест фильтрации с требованием status=ok."""
        # Добавляем сигнал с невалидным статусом
        features_with_error = sample_features_df.copy()
        features_with_error.loc[4, "status"] = "error"
        features_with_error.loc[4, "market_cap_proxy"] = 150000  # Высокий cap
        
        result = filter_signals(
            signals_path=sample_signals_csv,
            features_df=features_with_error,
            min_market_cap_proxy=40000,
            require_status_ok=True
        )
        
        # s5 должен быть исключён из-за статуса "error" (s3, s4 остаются)
        assert len(result) == 2
        assert "s5" not in result["id"].tolist()
        assert set(result["id"].tolist()) == {"s3", "s4"}
    
    def test_filter_signals_all_removed(self, sample_signals_csv, sample_features_df):
        """Тест когда все сигналы отфильтрованы."""
        result = filter_signals(
            signals_path=sample_signals_csv,
            features_df=sample_features_df,
            min_market_cap_proxy=200000,  # Очень высокий порог
            require_status_ok=True
        )
        
        assert len(result) == 0
    
    def test_filter_signals_none_removed(self, sample_signals_csv, sample_features_df):
        """Тест когда ни один сигнал не отфильтрован."""
        result = filter_signals(
            signals_path=sample_signals_csv,
            features_df=sample_features_df,
            min_market_cap_proxy=0,  # Очень низкий порог
            require_status_ok=True
        )
        
        assert len(result) == 5


class TestGenerateFilterSummary:
    """Тесты для generate_filter_summary."""
    
    def test_generate_filter_summary_basic(self, sample_features_df):
        """Тест генерации summary."""
        original_count = 10
        filtered_count = 5
        min_market_cap_proxy = 40000
        
        summary = generate_filter_summary(
            original_count=original_count,
            filtered_count=filtered_count,
            features_df=sample_features_df,
            min_market_cap_proxy=min_market_cap_proxy
        )
        
        assert summary["original_signals"] == 10
        assert summary["filtered_signals"] == 5
        assert summary["removed_signals"] == 5
        assert summary["removed_pct"] == 50.0
        assert summary["min_market_cap_proxy"] == 40000
        assert "valid_signals_before_filter" in summary
        assert "valid_signals_after_filter" in summary
    
    def test_generate_filter_summary_no_removal(self, sample_features_df):
        """Тест когда ничего не удалено."""
        original_count = 5
        filtered_count = 5
        
        summary = generate_filter_summary(
            original_count=original_count,
            filtered_count=filtered_count,
            features_df=sample_features_df,
            min_market_cap_proxy=0
        )
        
        assert summary["removed_signals"] == 0
        assert summary["removed_pct"] == 0.0



