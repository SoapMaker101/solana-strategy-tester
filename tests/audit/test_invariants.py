# tests/audit/test_invariants.py
# Тесты для инвариантов аудита

import pytest
import pandas as pd
from datetime import datetime, timezone

from backtester.audit.invariants import (
    InvariantChecker,
    AnomalyType,
    check_pnl_formula,
    check_reason_consistency,
    check_magic_values,
    check_time_ordering,
    normalize_reason,
)


def test_pnl_formula_long_basic():
    """Тест формулы PnL для long позиции."""
    # Корректный случай
    assert check_pnl_formula(entry_price=100.0, exit_price=110.0, pnl_pct=0.10)
    assert check_pnl_formula(entry_price=100.0, exit_price=90.0, pnl_pct=-0.10)
    
    # Некорректный случай
    assert not check_pnl_formula(entry_price=100.0, exit_price=110.0, pnl_pct=0.20)
    
    # Нулевая цена входа
    assert not check_pnl_formula(entry_price=0.0, exit_price=110.0, pnl_pct=0.10)


def test_tp_reason_requires_non_negative_pnl():
    """Тест: reason=tp требует неотрицательный PnL (с допуском epsilon)."""
    # Правильные случаи: положительный PnL
    assert check_reason_consistency(reason="tp", pnl_pct=0.10)
    assert check_reason_consistency(reason="tp_2x", pnl_pct=1.0)
    assert check_reason_consistency(reason="ladder_tp", pnl_pct=3.8)  # 380%
    
    # Правильные случаи: ноль и очень маленький отрицательный с допуском
    assert check_reason_consistency(reason="tp", pnl_pct=0.0)
    assert check_reason_consistency(reason="tp", pnl_pct=-1e-7)  # В пределах epsilon
    
    # Неправильные случаи: значительный отрицательный PnL
    assert not check_reason_consistency(reason="tp", pnl_pct=-0.10)
    assert not check_reason_consistency(reason="tp_5x", pnl_pct=-0.05)


def test_sl_reason_requires_negative_pnl():
    """Тест: reason=sl/stop_loss требует строго отрицательный PnL."""
    # Правильные случаи: отрицательный PnL
    assert check_reason_consistency(reason="sl", pnl_pct=-0.10)
    assert check_reason_consistency(reason="stop_loss", pnl_pct=-0.05)
    
    # Неправильные случаи: положительный PnL
    assert not check_reason_consistency(reason="sl", pnl_pct=0.10)
    assert not check_reason_consistency(reason="stop_loss", pnl_pct=0.05)
    
    # Неправильные случаи: ноль не допустим для sl
    assert not check_reason_consistency(reason="sl", pnl_pct=0.0)
    assert not check_reason_consistency(reason="stop_loss", pnl_pct=0.0)


def test_no_magic_pnl_fallback():
    """Тест: запрет магических значений PnL (920%)."""
    assert check_magic_values(pnl_pct=0.10)
    assert check_magic_values(pnl_pct=-0.10)
    assert not check_magic_values(pnl_pct=920.0)
    assert not check_magic_values(pnl_pct=9.2)  # 920% / 100
    assert not check_magic_values(pnl_pct=-920.0)


def test_tz_aware_ordering():
    """Тест: порядок времени."""
    entry = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    
    assert check_time_ordering(entry, exit_time)
    assert not check_time_ordering(exit_time, entry)
    assert check_time_ordering(entry, entry)  # Равные времена допустимы


def test_invariant_checker_detects_invalid_entry_price():
    """Тест: InvariantChecker обнаруживает невалидную цену входа."""
    checker = InvariantChecker()
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "status": "closed",
        "exec_entry_price": 0.0,  # Невалидная цена
        "exec_exit_price": 110.0,
        "pnl_pct": 0.10,
        "reason": "tp",
    }])
    
    anomalies = checker.check_all(positions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.ENTRY_PRICE_INVALID for a in anomalies)


def test_invariant_checker_detects_tp_but_negative_pnl():
    """Тест: InvariantChecker обнаруживает reason=tp при отрицательном PnL."""
    checker = InvariantChecker()
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        "status": "closed",
        "exec_entry_price": 100.0,
        "exec_exit_price": 90.0,
        "pnl_pct": -0.10,  # Отрицательный PnL
        "reason": "tp",  # Но reason=tp
    }])
    
    anomalies = checker.check_all(positions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.TP_REASON_BUT_NEGATIVE_PNL for a in anomalies)


def test_invariant_checker_detects_magic_pnl():
    """Тест: InvariantChecker обнаруживает магическое значение PnL (920%)."""
    checker = InvariantChecker()
    
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
        "pnl_pct": 920.0,  # Магическое значение
        "reason": "tp",
    }])
    
    anomalies = checker.check_all(positions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.PNL_CAP_OR_MAGIC for a in anomalies)


def test_invariant_checker_detects_time_order_invalid():
    """Тест: InvariantChecker обнаруживает неверный порядок времени."""
    checker = InvariantChecker()
    
    positions_df = pd.DataFrame([{
        "position_id": "pos1",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "entry_time": datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),  # Позже exit
        "exit_time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),  # Раньше entry
        "status": "closed",
        "exec_entry_price": 100.0,
        "exec_exit_price": 110.0,
        "pnl_pct": 0.10,
        "reason": "tp",
    }])
    
    anomalies = checker.check_all(positions_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.TIME_ORDER_INVALID for a in anomalies)


def test_invariant_checker_detects_missing_events():
    """Тест: InvariantChecker обнаруживает отсутствие событий для позиции."""
    checker = InvariantChecker()
    
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
    
    # Пустой DataFrame событий
    events_df = pd.DataFrame(columns=["timestamp", "event_type", "strategy", "signal_id", "contract_address", "position_id"])
    
    anomalies = checker.check_all(positions_df, events_df)
    
    assert len(anomalies) > 0
    assert any(a.anomaly_type == AnomalyType.MISSING_EVENTS_CHAIN for a in anomalies)


def test_invariant_checker_handles_missing_columns():
    """Тест: InvariantChecker не падает при отсутствующих колонках."""
    checker = InvariantChecker()
    
    # DataFrame без колонок closed_by_reset и reset_reason
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
        # Нет closed_by_reset и reset_reason
    }])
    
    # DataFrame событий без некоторых колонок
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "ATTEMPT_ACCEPTED_OPEN",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        # Нет position_id
    }])
    
    # Должно выполниться без ошибок
    anomalies = checker.check_all(positions_df, events_df)
    
    # Проверяем, что нет ошибок (может быть 0 или более аномалий, но не должна быть ошибка)
    assert isinstance(anomalies, list)


def test_invariant_checker_handles_missing_policy_columns():
    """Тест: InvariantChecker не падает при отсутствующих колонках reset_reason/closed_by_reset."""
    checker = InvariantChecker()
    
    # DataFrame без колонок closed_by_reset и reset_reason (должно работать безопасно)
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
    
    events_df = pd.DataFrame([{
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "ATTEMPT_ACCEPTED_OPEN",
        "strategy": "Runner_Baseline",
        "signal_id": "sig1",
        "contract_address": "0x123",
        "position_id": "pos1",
    }])
    
    # Должно выполниться без ошибок (_check_policy_consistency не должен упасть)
    anomalies = checker.check_all(positions_df, events_df)
    
    # Проверяем, что нет ошибок
    assert isinstance(anomalies, list)


def test_normalize_reason():
    """Тест: нормализация reason работает корректно."""
    assert normalize_reason("sl") == "sl"
    assert normalize_reason("stop_loss") == "sl"
    assert normalize_reason("STOP_LOSS") == "sl"
    assert normalize_reason("tp") == "tp"
    assert normalize_reason("ladder_tp") == "tp"
    assert normalize_reason("tp_2x") == "tp"
    assert normalize_reason("timeout") == "timeout"  # Неизвестные остаются без изменений
    assert normalize_reason("") == ""  # Пустая строка
    assert normalize_reason(None) == None  # None остается None
