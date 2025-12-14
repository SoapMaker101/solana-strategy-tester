"""
Unit-тест для портфельного слоя: сценарий "одна сделка".

Проверяет:
- Применение комиссий и проскальзывания
- Изменение баланса после сделки
- Формирование equity curve
- Корректность расчета итоговой доходности с учетом комиссий
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_portfolio_single_trade_applies_fees_and_updates_balance():
    """
    Тест: одна сделка применяет комиссии и обновляет баланс корректно.
    
    Сценарий:
    - Стартовый баланс: 10.0 SOL
    - Одна сделка с сырым PnL: 5% (0.05)
    - Комиссии и проскальзывание включены
    - Режим: dynamic allocation, 10% на сделку
    
    Проверяемые формулы:
    1. Размер позиции = initial_balance * percent_per_trade = 10.0 * 0.1 = 1.0 SOL
    2. Комиссии (round-trip) = 2 * (swap_fee_pct + lp_fee_pct + slippage_pct) + network_fee_sol / size
    3. Net PnL = raw_pnl - fee_pct
    4. Баланс после открытия = initial_balance - size
    5. Баланс после закрытия = balance_after_open + size + size * net_pnl_pct
    6. Итоговая доходность != сырому PnL (если комиссии > 0)
    """
    # Настройка
    initial_balance = 10.0
    raw_pnl_pct = 0.05  # 5% прибыль
    
    # FeeModel с дефолтными значениями (как в проде)
    fee_model = FeeModel(
        swap_fee_pct=0.003,      # 0.3%
        lp_fee_pct=0.001,        # 0.1%
        slippage_pct=0.10,       # 10%
        network_fee_sol=0.0005   # фикс. комиссия
    )
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,  # 10% на сделку
        max_exposure=0.5,
        max_open_positions=10,
        fee_model=fee_model
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем одну сделку с четкими entry/exit
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.05,  # 5% прибыль
        pnl=raw_pnl_pct,
        reason="tp"
    )
    
    # Формируем all_results (как требуется для simulate)
    all_results = [{
        "signal_id": "test_signal_1",
        "contract_address": "TESTTOKEN123",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    # Запускаем симуляцию
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: сделка выполнена
    assert result.stats.trades_executed == 1, "Должна быть выполнена одна сделка"
    assert result.stats.trades_skipped_by_risk == 0, "Сделка не должна быть пропущена"
    assert len(result.positions) == 1, "Должна быть одна позиция"
    
    # 2. Расчет ожидаемых значений
    position_size = initial_balance * config.percent_per_trade  # 10.0 * 0.1 = 1.0 SOL
    
    # Комиссии по формуле: round-trip + фикс. комиссия сети
    pct_roundtrip = 2 * (fee_model.swap_fee_pct + fee_model.lp_fee_pct + fee_model.slippage_pct)
    # 2 * (0.003 + 0.001 + 0.10) = 2 * 0.104 = 0.208 = 20.8%
    network_pct = fee_model.network_fee_sol / position_size  # 0.0005 / 1.0 = 0.0005 = 0.05%
    expected_fee_pct = pct_roundtrip + network_pct  # 0.208 + 0.0005 = 0.2085 = 20.85%
    
    expected_net_pnl_pct = raw_pnl_pct - expected_fee_pct  # 0.05 - 0.2085 = -0.1585 (убыток!)
    
    # Баланс после открытия позиции
    expected_balance_after_open = initial_balance - position_size  # 10.0 - 1.0 = 9.0 SOL
    
    # Баланс после закрытия позиции
    # balance = balance_after_open + size + size * net_pnl_pct
    trade_pnl_sol = position_size * expected_net_pnl_pct  # 1.0 * (-0.1585) = -0.1585 SOL
    expected_final_balance = expected_balance_after_open + position_size + trade_pnl_sol
    # 9.0 + 1.0 + (-0.1585) = 9.8415 SOL
    
    # 3. Проверка: баланс изменился ожидаемо
    assert abs(result.stats.final_balance_sol - expected_final_balance) < 0.0001, \
        f"Ожидаемый финальный баланс: {expected_final_balance}, получен: {result.stats.final_balance_sol}"
    
    # 4. Проверка: итоговая доходность не равна сырому PnL (т.к. комиссии > 0)
    # Итоговая доходность = (final_balance - initial_balance) / initial_balance
    expected_total_return = (expected_final_balance - initial_balance) / initial_balance
    # (9.8415 - 10.0) / 10.0 = -0.01585 = -1.585%
    
    assert abs(result.stats.total_return_pct - expected_total_return) < 0.0001, \
        f"Ожидаемая доходность: {expected_total_return}, получена: {result.stats.total_return_pct}"
    
    assert result.stats.total_return_pct != raw_pnl_pct, \
        f"Итоговая доходность ({result.stats.total_return_pct}) должна отличаться от сырого PnL ({raw_pnl_pct}) из-за комиссий"
    
    # 5. Проверка: equity curve имеет корректные точки
    # Ожидаем минимум 2 точки: начальная точка и точка после закрытия сделки
    # (Может быть 3: начальная, после открытия, после закрытия)
    assert len(result.equity_curve) >= 2, \
        f"Equity curve должна иметь минимум 2 точки, получено: {len(result.equity_curve)}"
    
    # Проверяем, что есть точка с начальным балансом (первая точка на entry_time)
    # Equity curve сортируется по времени, поэтому первая точка - это начало
    first_point = result.equity_curve[0]
    assert abs(first_point["balance"] - initial_balance) < 0.0001, \
        f"Первая точка equity curve должна содержать начальный баланс {initial_balance}, получено: {first_point['balance']}"
    
    # Проверяем последнюю точку (exit) - должна быть финальный баланс
    last_point = result.equity_curve[-1]
    assert abs(last_point["balance"] - expected_final_balance) < 0.0001, \
        f"Последняя точка equity curve должна содержать финальный баланс {expected_final_balance}, получено: {last_point['balance']}"
    
    # Проверяем, что есть точка с балансом после открытия позиции
    # (баланс уменьшен на размер позиции)
    balance_after_open_point = None
    for point in result.equity_curve:
        if abs(point["balance"] - expected_balance_after_open) < 0.0001:
            balance_after_open_point = point
            break
    assert balance_after_open_point is not None, \
        f"Должна быть точка с балансом после открытия позиции {expected_balance_after_open}"
    
    # Проверяем, что все точки имеют timestamp
    for point in result.equity_curve:
        assert "timestamp" in point, "Каждая точка equity curve должна иметь timestamp"
        assert isinstance(point["timestamp"], datetime), "Timestamp должен быть datetime"
    
    # 6. Проверка позиции
    position = result.positions[0]
    assert position.pnl_pct is not None, "pnl_pct не должен быть None для закрытой позиции"
    assert position.size == position_size, \
        f"Размер позиции должен быть {position_size}, получен: {position.size}"
    assert abs(position.pnl_pct - expected_net_pnl_pct) < 0.0001, \
        f"Net PnL позиции должен быть {expected_net_pnl_pct}, получен: {position.pnl_pct}"
    assert position.status == "closed", "Позиция должна быть закрыта"
    
    # Проверяем мета-данные позиции (raw_pnl и fee_pct должны быть сохранены)
    assert "raw_pnl_pct" in position.meta, "Мета-данные должны содержать raw_pnl_pct"
    assert abs(position.meta["raw_pnl_pct"] - raw_pnl_pct) < 0.0001, \
        f"raw_pnl_pct в мета-данных должен быть {raw_pnl_pct}"
    assert "fee_pct" in position.meta, "Мета-данные должны содержать fee_pct"
    assert abs(position.meta["fee_pct"] - expected_fee_pct) < 0.0001, \
        f"fee_pct в мета-данных должен быть {expected_fee_pct}"


def test_portfolio_single_trade_profitable_after_fees():
    """
    Тест: проверяет сценарий, где сделка остается прибыльной после комиссий.
    
    Использует меньший размер позиции, чтобы фикс. комиссия сети была меньше в процентах.
    """
    initial_balance = 10.0
    raw_pnl_pct = 0.30  # 30% прибыль (больше комиссий)
    
    fee_model = FeeModel()
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        fee_model=fee_model
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.30,
        pnl=raw_pnl_pct,
        reason="tp"
    )
    
    all_results = [{
        "signal_id": "test_signal_2",
        "contract_address": "TESTTOKEN456",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Проверка: сделка выполнена
    assert result.stats.trades_executed == 1
    
    # Проверка: итоговая доходность > 0 (даже с комиссиями сделка прибыльна)
    assert result.stats.total_return_pct > 0, \
        f"При 30% сыром PnL сделка должна оставаться прибыльной после комиссий, получено: {result.stats.total_return_pct}"
    
    # Проверка: итоговая доходность != сырому PnL
    assert result.stats.total_return_pct != raw_pnl_pct, \
        "Итоговая доходность должна отличаться от сырого PnL из-за комиссий"
    
    # Проверка: финальный баланс больше начального
    assert result.stats.final_balance_sol > initial_balance, \
        f"Финальный баланс ({result.stats.final_balance_sol}) должен быть больше начального ({initial_balance})"



