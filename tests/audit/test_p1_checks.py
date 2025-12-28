# tests/audit/test_p1_checks.py
# Тесты для P1 проверок (positions ↔ events ↔ executions)

import pytest
import pandas as pd
from datetime import datetime, timezone

from backtester.audit.invariants import InvariantChecker, AnomalyType
from backtester.audit.indices import AuditIndices


def test_position_closed_but_no_close_event():
    """Тест: позиция закрыта, но нет события закрытия."""
    checker = InvariantChecker(include_p1=True)
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "status": "closed",
        "exec_entry_price": 100.0,
        "exec_exit_price": 110.0,
        "pnl_pct": 0.10,
        "reason": "tp",
    }])
    
    # События только с открытием, без закрытия
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "attempt_accepted_open",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
    }])
    
    anomalies = checker.check_all(positions_df, events_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.POSITION_CLOSED_BUT_NO_CLOSE_EVENT for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_close_event_but_position_open():
    """Тест: есть событие закрытия, но позиция открыта."""
    checker = InvariantChecker(include_p1=True)
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": None,
        "status": "open",
        "exec_entry_price": 100.0,
        "exec_exit_price": None,
        "pnl_pct": None,
        "reason": None,
    }])
    
    # Событие закрытия для открытой позиции
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "event_type": "executed_close",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
    }])
    
    anomalies = checker.check_all(positions_df, events_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.CLOSE_EVENT_BUT_POSITION_OPEN for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_multiple_open_events():
    """Тест: несколько событий открытия для одной позиции."""
    checker = InvariantChecker(include_p1=True)
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "status": "closed",
        "exec_entry_price": 100.0,
        "exec_exit_price": 110.0,
        "pnl_pct": 0.10,
        "reason": "tp",
    }])
    
    # Два события открытия
    events_df = pd.DataFrame([
        {
            "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "event_type": "attempt_accepted_open",
            "strategy": "Runner_Baseline",
            "signal_id": "sig1",
            "contract_address": "0x123",
            "position_id": "pos1",
        },
        {
            "timestamp": datetime(2025, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
            "event_type": "attempt_accepted_open",
            "strategy": "Runner_Baseline",
            "signal_id": "sig1",
            "contract_address": "0x123",
            "position_id": "pos1",
        },
    ])
    
    anomalies = checker.check_all(positions_df, events_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.MULTIPLE_OPEN_EVENTS for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_unknown_reason_mapping():
    """Тест: неизвестный маппинг reason ↔ event_type."""
    checker = InvariantChecker(include_p1=True)
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "status": "closed",
        "exec_entry_price": 100.0,
        "exec_exit_price": 110.0,
        "pnl_pct": 0.10,
        "reason": "tp",  # reason=tp
    }])
    
    # Событие закрытия не соответствует reason (например, prune вместо tp)
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "event_type": "closed_by_capacity_prune",  # Не соответствует reason=tp
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
    }])
    
    anomalies = checker.check_all(positions_df, events_df)
    
    # Должна быть аномалия UNKNOWN_REASON_MAPPING
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.UNKNOWN_REASON_MAPPING for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_audit_indices_get_events_for_position():
    """Тест: AuditIndices правильно индексирует события."""
    events_df = pd.DataFrame([
        {
            "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "event_type": "attempt_accepted_open",
            "strategy": "Runner_Baseline",
            "signal_id": "sig1",
            "contract_address": "0x123",
            "position_id": "pos1",
        },
        {
            "timestamp": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
            "event_type": "executed_close",
            "strategy": "Runner_Baseline",
            "signal_id": "sig1",
            "contract_address": "0x123",
            "position_id": "pos1",
        },
    ])
    
    indices = AuditIndices(events_df=events_df)
    
    # Поиск по position_id
    events = indices.get_events_for_position(position_id="pos1")
    assert len(events) == 2
    
    # Поиск по signal_id
    events = indices.get_events_for_position(signal_id="sig1")
    assert len(events) == 2
    
    # Поиск по (strategy, signal_id, contract)
    events = indices.get_events_for_position(
        signal_id="sig1",
        strategy="Runner_Baseline",
        contract_address="0x123",
    )
    assert len(events) == 2
    
    # Проверка наличия событий
    assert indices.has_open_event(position_id="pos1")
    assert indices.has_close_event(position_id="pos1")
    
    # Проверка событий закрытия
    close_events = indices.get_close_events(position_id="pos1")
    assert len(close_events) == 1
    assert close_events[0]["event_type"] == "executed_close"

