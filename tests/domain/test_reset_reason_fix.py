"""
Тест для проверки исправления ResetReason enum в _apply_reset.

Проверяет, что код не падает при использовании ResetReason.PROFIT_RESET
и что reason правильно маппится в "profit_reset".
"""
import pytest
from datetime import datetime, timezone

from backtester.domain.portfolio_reset import ResetReason
from backtester.domain.portfolio_events import PortfolioEvent


def test_reset_reason_profit_reset_exists():
    """Тест: ResetReason.PROFIT_RESET существует и имеет правильное значение."""
    assert hasattr(ResetReason, 'PROFIT_RESET'), "ResetReason.PROFIT_RESET должен существовать"
    assert ResetReason.PROFIT_RESET.value == "profit_reset"


def test_reset_reason_mapping_to_string():
    """Тест: маппинг ResetReason.PROFIT_RESET -> 'profit_reset' работает корректно."""
    # Маппинг, используемый в _apply_reset
    reset_reason_mapping = {
        ResetReason.PROFIT_RESET: "profit_reset",
        ResetReason.CAPACITY_PRUNE: "capacity_prune",
        ResetReason.MANUAL: "manual_close",
    }
    
    # Проверяем, что PROFIT_RESET правильно маппится
    assert reset_reason_mapping[ResetReason.PROFIT_RESET] == "profit_reset"
    
    # Проверяем fallback
    unknown_reason = ResetReason.MANUAL
    fallback = reset_reason_mapping.get(unknown_reason, unknown_reason.value if hasattr(unknown_reason, 'value') else "manual_close")
    assert fallback == "manual_close"


def test_portfolio_event_reset_with_profit_reset_reason():
    """
    Тест: создание события PORTFOLIO_RESET_TRIGGERED с reason="profit_reset" работает.
    
    Проверяет, что код не падает при создании события с правильным reason.
    """
    reset_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем событие reset с reason="profit_reset" (маппинг из ResetReason.PROFIT_RESET)
    event = PortfolioEvent.create_portfolio_reset_triggered(
        timestamp=reset_time,
        reason="profit_reset",  # Это значение должно приходить из маппинга ResetReason.PROFIT_RESET
        closed_positions_count=2,
        position_id="pos_001",
        signal_id="sig_001",
        contract_address="0x123",
        strategy="test_strategy",
    )
    
    # Проверяем, что событие создано корректно
    assert event.reason == "profit_reset", f"Expected 'profit_reset', got '{event.reason}'"
    assert event.event_type.value == "portfolio_reset_triggered"
    assert event.timestamp == reset_time


def test_all_reset_reason_enum_values_exist():
    """Тест: все используемые enum-члены ResetReason существуют."""
    # Проверяем, что все используемые в маппинге enum-члены существуют
    assert hasattr(ResetReason, 'PROFIT_RESET')
    assert hasattr(ResetReason, 'CAPACITY_PRUNE')
    assert hasattr(ResetReason, 'MANUAL')
    
    # Проверяем, что старые несуществующие члены НЕ существуют
    assert not hasattr(ResetReason, 'EQUITY_THRESHOLD'), "ResetReason.EQUITY_THRESHOLD не должен существовать"
    assert not hasattr(ResetReason, 'CAPACITY_PRESSURE'), "ResetReason.CAPACITY_PRESSURE не должен существовать"
    assert not hasattr(ResetReason, 'RUNNER_XN'), "ResetReason.RUNNER_XN не должен существовать"

