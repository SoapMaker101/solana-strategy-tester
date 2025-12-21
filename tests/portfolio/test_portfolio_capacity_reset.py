"""
Unit-тесты для capacity reset функциональности.

Проверяет портфельную политику: при заполнении портфеля (много открытых позиций,
мало закрытий, много отклоненных сигналов) срабатывает capacity reset.
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_capacity_reset_triggers():
    """
    Тест: capacity reset срабатывает при заполнении портфеля.
    
    Сценарий (v1.6):
    - capacity_reset.enabled = True
    - max_open_positions = 2 (маленький портфель)
    - capacity_open_ratio_threshold = 1.0 (100%)
    - capacity_reset.window_type = "signals"
    - capacity_reset.window_size = 5
    - capacity_reset.max_blocked_ratio = 0.4 (40%)
    - capacity_reset.max_avg_hold_days = 0.5 (12 часов)
    
    Создаем поток сигналов:
    - Открываем 2 позиции (портфель заполнен)
    - Отклоняем сигналы по capacity (blocked_ratio >= 0.4)
    - Позиции удерживаются долго (avg_hold_days >= 0.5)
    - Ожидаем: capacity reset срабатывает
    
    Проверяем:
    - portfolio_reset_capacity_count >= 1
    - Есть позиция с closed_by_reset=True и reset_reason="capacity"
    - Баланс изменился согласно market close (pnl не всегда 0)
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=2,  # Маленький портфель
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_open_ratio_threshold=1.0,
        capacity_window_type="signals",
        capacity_window_size=5,
        capacity_max_blocked_ratio=0.4,  # 40% отклоненных сигналов
        capacity_max_avg_hold_days=0.5,  # 12 часов (0.5 дня)
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем поток сигналов
    trades = []
    
    # Первые 2 сигнала - открываем позиции (портфель заполняется)
    # Делаем их долгими, чтобы avg_hold_days стал большим
    for i in range(2):
        entry_time = base_time + timedelta(hours=i)
        exit_time = entry_time + timedelta(days=1)  # Долгие позиции (1 день, чтобы avg_hold_days >= 0.5)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.05,  # 5% прибыль
            pnl=0.05,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Следующие сигналы - отклоняются по capacity (портфель заполнен)
    # Нужно чтобы blocked_ratio >= 0.4 (40%)
    # Если window_size=5, то нужно минимум 2 отклоненных из 5 сигналов (2/5 = 0.4)
    # Создаем 3 отклоненных сигнала из 5, чтобы ratio = 3/5 = 0.6 >= 0.4
    for i in range(3):
        entry_time = base_time + timedelta(hours=2+i)
        exit_time = entry_time + timedelta(hours=2)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.05,
            pnl=0.05,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"signal_blocked_{i+1}",
            "contract_address": f"TOKEN_BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Capacity reset сработал
    assert result.stats.portfolio_reset_capacity_count >= 1, \
        f"Capacity reset должен был сработать, но portfolio_reset_capacity_count={result.stats.portfolio_reset_capacity_count}"
    
    # 2. Есть позиция с closed_by_reset=True и reset_reason="capacity"
    capacity_reset_positions = [
        p for p in result.positions
        if p.meta.get("closed_by_reset") == True and p.meta.get("reset_reason") == "capacity"
    ]
    assert len(capacity_reset_positions) > 0, \
        "Должна быть хотя бы одна позиция, закрытая по capacity reset"
    
    # 3. Баланс изменился (market close, не pnl=0)
    # Проверяем, что хотя бы одна позиция имеет ненулевой pnl_sol
    reset_positions_with_pnl = [
        p for p in capacity_reset_positions
        if p.meta.get("pnl_sol", 0.0) != 0.0
    ]
    # Market close может дать pnl=0 если цена не изменилась, но обычно есть изменение
    # Проверяем что exec_exit_price установлен (market close произошел)
    reset_positions_with_exec_price = [
        p for p in capacity_reset_positions
        if p.meta.get("exec_exit_price") is not None
    ]
    assert len(reset_positions_with_exec_price) > 0, \
        "Позиции, закрытые по capacity reset, должны иметь exec_exit_price (market close)"


def test_capacity_reset_not_triggers_with_turnover():
    """
    Тест: capacity reset не срабатывает если есть turnover (низкое avg_hold_days).
    
    Сценарий (v1.6):
    - capacity_reset.enabled = True
    - max_open_positions = 2
    - capacity_reset.max_avg_hold_days = 0.5 (12 часов)
    
    Создаем поток сигналов:
    - Открываем 2 позиции (портфель заполнен)
    - Закрываем 1 позицию быстро (avg_hold_days < 0.5)
    - Отклоняем несколько сигналов
    - Ожидаем: capacity reset НЕ срабатывает (avg_hold_days низкий = есть turnover)
    
    Проверяем:
    - portfolio_reset_capacity_count == 0 (или проверяем что нет capacity reset позиций)
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=2,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_open_ratio_threshold=1.0,
        capacity_window_type="signals",
        capacity_window_size=5,
        capacity_max_blocked_ratio=0.4,
        capacity_max_avg_hold_days=0.5,  # 12 часов
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    
    # Первая позиция - открывается и быстро закрывается (turnover)
    entry_time_1 = base_time
    exit_time_1 = base_time + timedelta(hours=6)  # Закрывается через 6 часов (< 12 часов = avg_hold_days < 0.5)
    
    trades.append({
        "signal_id": "signal_1",
        "contract_address": "TOKEN1",
        "strategy": "test_strategy",
        "timestamp": entry_time_1,
        "result": StrategyOutput(
            entry_time=entry_time_1,
            entry_price=1.0,
            exit_time=exit_time_1,
            exit_price=1.05,
            pnl=0.05,
            reason="tp"
        )
    })
    
    # Вторая позиция - открывается (портфель заполнен), но тоже быстро закроется
    entry_time_2 = base_time + timedelta(hours=1)
    exit_time_2 = base_time + timedelta(hours=7)  # Закрывается через 6 часов после входа
    
    trades.append({
        "signal_id": "signal_2",
        "contract_address": "TOKEN2",
        "strategy": "test_strategy",
        "timestamp": entry_time_2,
        "result": StrategyOutput(
            entry_time=entry_time_2,
            entry_price=1.0,
            exit_time=exit_time_2,
            exit_price=1.05,
            pnl=0.05,
            reason="tp"
        )
    })
    
    # Несколько сигналов отклоняются по capacity
    for i in range(3):
        entry_time = base_time + timedelta(hours=1+i)
        exit_time = entry_time + timedelta(hours=2)
        
        trades.append({
            "signal_id": f"signal_blocked_{i+1}",
            "contract_address": f"TOKEN_BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": StrategyOutput(
                entry_time=entry_time,
                entry_price=1.0,
                exit_time=exit_time,
                exit_price=1.05,
                pnl=0.05,
                reason="tp"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Capacity reset НЕ должен сработать (avg_hold_days низкий = есть turnover)
    # Проверяем что нет capacity reset позиций
    capacity_reset_positions = [
        p for p in result.positions
        if p.meta.get("reset_reason") == "capacity"
    ]
    assert len(capacity_reset_positions) == 0, \
        f"Capacity reset не должен был сработать (есть turnover), но найдено {len(capacity_reset_positions)} позиций с reset_reason='capacity'"


def test_capacity_reset_disabled():
    """
    Тест: capacity reset не срабатывает если выключен.
    
    Сценарий (v1.6):
    - capacity_reset.enabled = False
    - Портфель заполнен, много отклоненных сигналов, высокое avg_hold_days
    - Ожидаем: capacity reset НЕ срабатывает
    
    Проверяем:
    - portfolio_reset_capacity_count == 0
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=2,
        fee_model=FeeModel(),
        capacity_reset_enabled=False,  # Выключен
        capacity_open_ratio_threshold=1.0,
        capacity_window_type="signals",
        capacity_window_size=5,
        capacity_max_blocked_ratio=0.4,
        capacity_max_avg_hold_days=0.5,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    
    # Открываем 2 позиции (портфель заполнен)
    # Делаем их долгими, чтобы avg_hold_days стал большим (но reset не сработает, т.к. выключен)
    for i in range(2):
        entry_time = base_time + timedelta(hours=i)
        exit_time = entry_time + timedelta(days=1)  # Долгие позиции
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": StrategyOutput(
                entry_time=entry_time,
                entry_price=1.0,
                exit_time=exit_time,
                exit_price=1.05,
                pnl=0.05,
                reason="tp"
            )
        })
    
    # Отклоняем несколько сигналов
    for i in range(3):
        entry_time = base_time + timedelta(hours=2+i)
        exit_time = entry_time + timedelta(hours=2)
        
        trades.append({
            "signal_id": f"signal_blocked_{i+1}",
            "contract_address": f"TOKEN_BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": StrategyOutput(
                entry_time=entry_time,
                entry_price=1.0,
                exit_time=exit_time,
                exit_price=1.05,
                pnl=0.05,
                reason="tp"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Capacity reset НЕ должен сработать (выключен)
    assert result.stats.portfolio_reset_capacity_count == 0, \
        f"Capacity reset не должен был сработать (выключен), но portfolio_reset_capacity_count={result.stats.portfolio_reset_capacity_count}"

