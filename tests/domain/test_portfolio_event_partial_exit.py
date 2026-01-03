"""
Unit тесты для PortfolioEvent.create_position_partial_exit.

Проверяет, что метод корректно обрабатывает параметр reason.
"""
import pytest
from datetime import datetime, timezone

from backtester.domain.portfolio_events import PortfolioEvent, PortfolioEventType


def test_create_position_partial_exit_with_reason():
    """Тест: создание события partial exit с явным reason не падает."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent.create_position_partial_exit(
        timestamp=timestamp,
        strategy="test_strategy",
        signal_id="sig_001",
        contract_address="0x123",
        position_id="pos_001",
        level_xn=2.0,
        fraction=0.5,
        raw_price=100.0,
        exec_price=99.0,
        pnl_pct_contrib=80.0,
        pnl_sol_contrib=0.5,
        reason="ladder_tp",
    )
    
    assert event.event_type == PortfolioEventType.POSITION_PARTIAL_EXIT
    assert event.reason == "ladder_tp"
    assert event.position_id == "pos_001"
    assert event.meta["level_xn"] == 2.0
    assert event.meta["fraction"] == 0.5


def test_create_position_partial_exit_without_reason_defaults():
    """Тест: создание события partial exit без reason использует дефолт "ladder_tp"."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent.create_position_partial_exit(
        timestamp=timestamp,
        strategy="test_strategy",
        signal_id="sig_001",
        contract_address="0x123",
        position_id="pos_001",
        level_xn=3.0,
        fraction=0.3,
        raw_price=150.0,
        exec_price=148.0,
        pnl_pct_contrib=90.0,
        pnl_sol_contrib=0.8,
        # reason не указан
    )
    
    assert event.event_type == PortfolioEventType.POSITION_PARTIAL_EXIT
    assert event.reason == "ladder_tp"  # Дефолтное значение
    assert event.position_id == "pos_001"


def test_create_position_partial_exit_with_custom_reason():
    """Тест: создание события partial exit с кастомным reason (например, time_stop)."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent.create_position_partial_exit(
        timestamp=timestamp,
        strategy="test_strategy",
        signal_id="sig_001",
        contract_address="0x123",
        position_id="pos_001",
        level_xn=1.5,
        fraction=0.7,
        raw_price=80.0,
        exec_price=79.0,
        pnl_pct_contrib=50.0,
        pnl_sol_contrib=0.3,
        reason="time_stop",  # Кастомный reason
    )
    
    assert event.event_type == PortfolioEventType.POSITION_PARTIAL_EXIT
    assert event.reason == "time_stop"  # Переданный reason
    assert event.position_id == "pos_001"


def test_create_position_partial_exit_reason_in_meta():
    """Тест: проверяем, что reason попадает в правильное поле (reason, а не meta)."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent.create_position_partial_exit(
        timestamp=timestamp,
        strategy="test_strategy",
        signal_id="sig_001",
        contract_address="0x123",
        position_id="pos_001",
        level_xn=2.5,
        fraction=0.4,
        raw_price=120.0,
        exec_price=119.0,
        pnl_pct_contrib=75.0,
        pnl_sol_contrib=0.6,
        reason="ladder_tp",
        meta={"custom_field": "value"},
    )
    
    # reason должен быть в поле reason, а не в meta
    assert event.reason == "ladder_tp"
    assert "reason" not in event.meta  # reason не должен быть в meta
    assert event.meta["custom_field"] == "value"  # meta сохраняется


def test_create_position_partial_exit_all_fields_populated():
    """Тест: все обязательные поля корректно заполняются."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    event = PortfolioEvent.create_position_partial_exit(
        timestamp=timestamp,
        strategy="test_strategy",
        signal_id="sig_001",
        contract_address="0x123",
        position_id="pos_001",
        level_xn=2.0,
        fraction=0.5,
        raw_price=100.0,
        exec_price=99.0,
        pnl_pct_contrib=80.0,
        pnl_sol_contrib=0.5,
        reason="ladder_tp",
    )
    
    # Проверяем все поля
    assert event.timestamp == timestamp
    assert event.strategy == "test_strategy"
    assert event.signal_id == "sig_001"
    assert event.contract_address == "0x123"
    assert event.position_id == "pos_001"
    assert event.event_type == PortfolioEventType.POSITION_PARTIAL_EXIT
    assert event.reason == "ladder_tp"
    
    # Проверяем meta
    assert event.meta["level_xn"] == 2.0
    assert event.meta["fraction"] == 0.5
    assert event.meta["raw_price"] == 100.0
    assert event.meta["exec_price"] == 99.0
    assert event.meta["pnl_pct_contrib"] == 80.0
    assert event.meta["pnl_sol_contrib"] == 0.5

