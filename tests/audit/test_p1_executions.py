# tests/audit/test_p1_executions.py
# Тесты для P1 проверок events ↔ executions

import pytest
import pandas as pd
from datetime import datetime, timezone

from backtester.audit.invariants import InvariantChecker, AnomalyType
from backtester.audit.indices import AuditIndices


def test_trade_event_without_execution():
    """Тест: событие торговли без execution."""
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
    
    # Событие открытия есть (канонический тип), но БЕЗ execution данных в meta
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "POSITION_OPENED",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
        "event_id": "evt1",
        # НЕТ meta_json с execution_type - событие без execution данных
    }])
    
    # Нет execution для этого события (пустой executions_df)
    executions_df = pd.DataFrame([])  # Пустой
    
    anomalies = checker.check_all(positions_df, events_df, executions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.TRADE_EVENT_WITHOUT_EXECUTION for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_execution_without_trade_event():
    """Тест: execution без соответствующего события."""
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
    
    # Нет событий
    events_df = pd.DataFrame([])
    
    # Но есть execution
    executions_df = pd.DataFrame([{
        "signal_id": "sig1",
        "strategy": "Runner_Baseline",
        "event_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "entry",
        "qty_delta": 1.0,
        "raw_price": 100.0,
        "exec_price": 100.0,
        "fees_sol": 0.001,
        "pnl_sol_delta": 0.0,
    }])
    
    anomalies = checker.check_all(positions_df, events_df, executions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.EXECUTION_WITHOUT_TRADE_EVENT for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_execution_time_before_event():
    """Тест: execution раньше события."""
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
    
    # Событие в 12:00 (канонический тип)
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "POSITION_OPENED",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
        "event_id": "evt1",
        "meta_json": '{"execution_type": "entry", "raw_price": 100.0, "exec_price": 100.0, "qty_delta": 1.0, "fees_sol": 0.001, "pnl_sol_delta": 0.0}',
    }])
    
    # Execution в 11:59 (раньше события)
    executions_df = pd.DataFrame([{
        "signal_id": "sig1",
        "strategy": "Runner_Baseline",
        "event_time": datetime(2025, 1, 1, 11, 59, 0, tzinfo=timezone.utc),
        "event_type": "entry",
        "qty_delta": 1.0,
        "raw_price": 100.0,
        "exec_price": 100.0,
        "fees_sol": 0.001,
        "pnl_sol_delta": 0.0,
    }])
    
    anomalies = checker.check_all(positions_df, events_df, executions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.EXECUTION_TIME_BEFORE_EVENT for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)


def test_execution_price_out_of_range():
    """Тест: цена execution вне разумных пределов."""
    checker = InvariantChecker(include_p1=True)
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "status": "closed",
        "exec_entry_price": 100.0,  # Позиция имеет entry_price = 100.0
        "exec_exit_price": 110.0,
        "pnl_pct": 0.10,
        "reason": "tp",
    }])
    
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "POSITION_OPENED",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
        "event_id": "evt1",
        "meta_json": '{"execution_type": "entry", "raw_price": 200.0, "exec_price": 200.0, "qty_delta": 1.0, "fees_sol": 0.001, "pnl_sol_delta": 0.0}',
    }])
    
    # Execution с ценой, сильно отличающейся от позиции (200.0 вместо 100.0)
    executions_df = pd.DataFrame([{
        "signal_id": "sig1",
        "strategy": "Runner_Baseline",
        "event_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "entry",
        "qty_delta": 1.0,
        "raw_price": 200.0,  # Сильно отличается
        "exec_price": 200.0,  # Сильно отличается
        "fees_sol": 0.001,
        "pnl_sol_delta": 0.0,
    }])
    
    anomalies = checker.check_all(positions_df, events_df, executions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.EXECUTION_PRICE_OUT_OF_RANGE for a in anomalies)
    assert any(a.severity == "P1" for a in anomalies)

