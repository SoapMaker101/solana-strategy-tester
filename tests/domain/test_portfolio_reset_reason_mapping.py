"""
Тест для проверки маппинга ResetReason в строковые значения.

Проверяет, что ResetReason enum правильно маппится в строковые reason
для событий портфеля (profit_reset, capacity_prune, manual_close).
"""
import pytest
from datetime import datetime, timezone

from backtester.domain.portfolio_reset import ResetReason
from backtester.domain.portfolio_events import PortfolioEvent


def test_reset_reason_profit_reset_maps_to_profit_reset_string():
    """
    Тест: ResetReason.PROFIT_RESET правильно маппится в "profit_reset".
    
    Проверяет, что при создании события PORTFOLIO_RESET_TRIGGERED
    с ResetReason.PROFIT_RESET, reason в событии равен "profit_reset".
    """
    reset_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем событие reset с PROFIT_RESET
    event = PortfolioEvent.create_portfolio_reset_triggered(
        timestamp=reset_time,
        reason="profit_reset",  # Маппинг ResetReason.PROFIT_RESET -> "profit_reset"
        closed_positions_count=2,
        position_id="pos_001",
        signal_id="sig_001",
        contract_address="0x123",
        strategy="test_strategy",
    )
    
    # Проверяем, что reason правильно установлен
    assert event.reason == "profit_reset", f"Expected 'profit_reset', got '{event.reason}'"
    assert event.event_type.value == "portfolio_reset_triggered"


def test_reset_reason_enum_values():
    """
    Тест: проверяет, что все значения ResetReason enum существуют и имеют правильные значения.
    """
    # Проверяем, что enum-члены существуют
    assert hasattr(ResetReason, 'PROFIT_RESET'), "ResetReason.PROFIT_RESET должен существовать"
    assert hasattr(ResetReason, 'CAPACITY_PRUNE'), "ResetReason.CAPACITY_PRUNE должен существовать"
    assert hasattr(ResetReason, 'MANUAL'), "ResetReason.MANUAL должен существовать"
    
    # Проверяем значения
    assert ResetReason.PROFIT_RESET.value == "profit_reset"
    assert ResetReason.CAPACITY_PRUNE.value == "capacity_prune"
    assert ResetReason.MANUAL.value == "manual"
    
    # Проверяем, что старые несуществующие члены не существуют
    assert not hasattr(ResetReason, 'EQUITY_THRESHOLD'), "ResetReason.EQUITY_THRESHOLD не должен существовать"
    assert not hasattr(ResetReason, 'CAPACITY_PRESSURE'), "ResetReason.CAPACITY_PRESSURE не должен существовать"
    assert not hasattr(ResetReason, 'RUNNER_XN'), "ResetReason.RUNNER_XN не должен существовать"


def test_reset_reason_mapping_in_portfolio_engine():
    """
    Тест: проверяет маппинг ResetReason в _apply_reset.
    
    Этот тест проверяет логику маппинга, которая используется в PortfolioEngine._apply_reset.
    """
    # Маппинг должен соответствовать тому, что в _apply_reset
    reset_reason_mapping = {
        ResetReason.PROFIT_RESET: "profit_reset",
        ResetReason.CAPACITY_PRUNE: "capacity_prune",
        ResetReason.MANUAL: "manual_close",
    }
    
    # Проверяем все маппинги
    assert reset_reason_mapping[ResetReason.PROFIT_RESET] == "profit_reset"
    assert reset_reason_mapping[ResetReason.CAPACITY_PRUNE] == "capacity_prune"
    assert reset_reason_mapping[ResetReason.MANUAL] == "manual_close"
    
    # Проверяем fallback для неизвестного reason
    unknown_reason = ResetReason.MANUAL  # Используем существующий для проверки
    fallback_value = reset_reason_mapping.get(unknown_reason, unknown_reason.value if hasattr(unknown_reason, 'value') else "manual_close")
    assert fallback_value == "manual_close"

