"""
Unit-тест: комиссии могут превратить маленькую прибыль в убыток.

Проверяет важный сценарий защиты от ложноположительных результатов:
даже если стратегия показывает положительный raw PnL, после учета
комиссий и проскальзывания сделка может быть убыточной.
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_fees_can_turn_small_profit_into_loss():
    """
    Тест: комиссии и проскальзывание превращают маленькую прибыль в убыток.
    
    Сценарий:
    - Маленький положительный raw_pnl (например +0.2% = 0.002)
    - Комиссии и проскальзывание больше raw_pnl
    - Ожидаем: net_pnl < 0 (убыток после комиссий)
    - Ожидаем: баланс снизился после сделки
    
    Проверяемые формулы:
    1. raw_pnl = 0.002 (0.2% - маленькая прибыль)
    2. fee_pct = effective_fee_pct(size) (комиссии round-trip + фикс. комиссия)
    3. net_pnl_pct = raw_pnl - fee_pct
    4. Если fee_pct > raw_pnl, то net_pnl_pct < 0 (убыток)
    5. Баланс после сделки = initial_balance - size + size + size * net_pnl_pct
       = initial_balance + size * net_pnl_pct
    6. Если net_pnl_pct < 0, то баланс снизился
    
    Проверяем:
    - net_pnl < 0 (чистая прибыль отрицательная)
    - Баланс снизился после сделки
    - raw_pnl в мета-данных позиции положительный
    - fee_pct в мета-данных больше raw_pnl
    """
    initial_balance = 10.0
    
    # Используем дефолтные комиссии (как в проде)
    # swap_fee_pct=0.003, lp_fee_pct=0.001, slippage_pct=0.10, network_fee_sol=0.0005
    # Для размера позиции 1 SOL:
    # pct_roundtrip = 2 * (0.003 + 0.001 + 0.10) = 2 * 0.104 = 0.208 = 20.8%
    # network_pct = 0.0005 / 1.0 = 0.0005 = 0.05%
    # total_fee_pct ≈ 0.2085 = 20.85%
    # Это гораздо больше, чем наш маленький raw_pnl = 0.2% = 0.002
    fee_model = FeeModel()
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,  # 10% на сделку = 1.0 SOL
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=fee_model
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем сделку с маленьким положительным raw_pnl
    raw_pnl_pct = 0.002  # 0.2% - очень маленькая прибыль
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.002,  # 0.2% прибыль
        pnl=raw_pnl_pct,   # 0.002 = 0.2%
        reason="tp"
    )
    
    all_results = [{
        "signal_id": "small_profit_signal",
        "contract_address": "SMALLPROFIT",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    # Запускаем симуляцию
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: сделка выполнена
    assert result.stats.trades_executed == 1, \
        f"Должна быть выполнена одна сделка, получено: {result.stats.trades_executed}"
    
    assert len(result.positions) == 1, \
        f"Должна быть одна позиция, получено: {len(result.positions)}"
    
    position = result.positions[0]
    
    # 2. Расчет ожидаемых значений с учетом новой логики ExecutionModel
    position_size = initial_balance * config.percent_per_trade  # 10.0 * 0.1 = 1.0 SOL
    
    # Новая логика: slippage применяется к ценам, fees к нотионалу
    # Для legacy режима (без profiles) используется slippage_pct=0.10
    # effective_entry_price = raw_entry_price * (1 + slippage) = 1.0 * 1.1 = 1.1
    # effective_exit_price = raw_exit_price * (1 - slippage) = 1.002 * 0.9 = 0.9018
    # effective_pnl_pct = (0.9018 - 1.1) / 1.1 = -0.18018...
    # Fees (swap + LP) применяются к нотионалу при закрытии: (swap_fee_pct + lp_fee_pct) = 0.004
    # Network fee: 0.0005 SOL при входе + 0.0005 SOL при выходе = 0.001 SOL
    
    # Ожидаемый effective_pnl_pct (уже с учетом slippage в ценах)
    expected_effective_pnl_pct = -0.1801818181818182  # Примерное значение из реального расчета
    
    # Ожидаемый net_pnl_pct = effective_pnl_pct (fees вычитаются из нотионала, не из PnL)
    expected_net_pnl_pct = expected_effective_pnl_pct
    
    # 3. ГЛАВНАЯ ПРОВЕРКА: net_pnl < 0 (slippage и комиссии превратили прибыль в убыток)
    assert position.pnl_pct is not None, "pnl_pct не должен быть None для закрытой позиции"
    assert position.pnl_pct < 0, \
        f"Net PnL должен быть отрицательным (slippage + fees > raw_pnl), получен: {position.pnl_pct}"
    
    # Проверка точности расчета (допуск больше, т.к. расчет сложнее)
    assert abs(position.pnl_pct - expected_net_pnl_pct) < 0.01, \
        f"Net PnL должен быть около {expected_net_pnl_pct}, получен: {position.pnl_pct}"
    
    # 4. Проверка: slippage + fees действительно больше raw_pnl
    # В новой логике slippage применяется к ценам, поэтому effective_pnl уже отрицательный
    assert position.pnl_pct < raw_pnl_pct, \
        f"Net PnL ({position.pnl_pct}) должен быть меньше raw_pnl ({raw_pnl_pct}) из-за slippage и fees"
    
    # 5. Проверка мета-данных: raw_pnl положительный
    assert "raw_pnl_pct" in position.meta, \
        "Мета-данные должны содержать raw_pnl_pct"
    
    assert position.meta["raw_pnl_pct"] > 0, \
        f"Raw PnL должен быть положительным ({position.meta['raw_pnl_pct']})"
    
    assert abs(position.meta["raw_pnl_pct"] - raw_pnl_pct) < 0.0001, \
        f"Raw PnL в мета-данных должен быть {raw_pnl_pct}, получен: {position.meta['raw_pnl_pct']}"
    
    # 6. Проверка мета-данных: slippage и fees учтены
    assert "slippage_entry_pct" in position.meta, \
        "Мета-данные должны содержать slippage_entry_pct"
    assert "slippage_exit_pct" in position.meta, \
        "Мета-данные должны содержать slippage_exit_pct"
    
    # Проверяем, что slippage применен
    assert position.meta["slippage_entry_pct"] > 0, \
        f"Slippage при входе должен быть положительным: {position.meta['slippage_entry_pct']}"
    assert position.meta["slippage_exit_pct"] > 0, \
        f"Slippage при выходе должен быть положительным: {position.meta['slippage_exit_pct']}"
    
    # 7. Проверка: баланс снизился после сделки
    assert result.stats.final_balance_sol < initial_balance, \
        f"Баланс должен снизиться после убыточной сделки: {result.stats.final_balance_sol} < {initial_balance}"
    
    # Расчет ожидаемого баланса для проверки
    # Баланс после открытия: initial_balance - size - network_fee_entry = 10.0 - 1.0 - 0.0005 = 8.9995 SOL
    # При закрытии: возвращаем size + pnl_sol, применяем fees к нотионалу, вычитаем network_fee_exit
    # pnl_sol = size * net_pnl_pct = 1.0 * expected_net_pnl_pct
    # notional_returned = size + pnl_sol
    # notional_after_fees = notional_returned * (1 - swap_fee_pct - lp_fee_pct)
    # final_balance = balance_after_open + notional_after_fees - network_fee_exit
    # Упрощенная проверка: баланс должен снизиться
    # (точный расчет сложнее из-за fees к нотионалу)
    assert result.stats.final_balance_sol < initial_balance, \
        f"Финальный баланс должен быть меньше начального: {result.stats.final_balance_sol} < {initial_balance}"
    
    # 8. Проверка итоговой доходности портфеля
    # total_return_pct = (final_balance - initial_balance) / initial_balance
    expected_total_return = (result.stats.final_balance_sol - initial_balance) / initial_balance
    
    assert result.stats.total_return_pct < 0, \
        f"Итоговая доходность портфеля должна быть отрицательной, получена: {result.stats.total_return_pct}"
    
    # Проверяем, что доходность соответствует реальному изменению баланса
    assert abs(result.stats.total_return_pct - expected_total_return) < 0.0001, \
        f"Ожидаемая доходность: {expected_total_return}, получена: {result.stats.total_return_pct}"
    
    # 9. Проверка: итоговая доходность не равна raw_pnl
    assert result.stats.total_return_pct != raw_pnl_pct, \
        f"Итоговая доходность ({result.stats.total_return_pct}) должна отличаться от raw_pnl ({raw_pnl_pct}) " \
        f"из-за комиссий"


def test_fees_can_turn_small_profit_into_loss_with_different_sizes():
    """
    Тест: проверяет сценарий с разными размерами позиций.
    
    Комиссии включают фиксированную компоненту (network_fee_sol),
    поэтому для маленьких позиций комиссии в процентах выше.
    """
    initial_balance = 10.0
    raw_pnl_pct = 0.01  # 1% прибыль
    
    fee_model = FeeModel(
        swap_fee_pct=0.003,
        lp_fee_pct=0.001,
        slippage_pct=0.10,
        network_fee_sol=0.0005  # Фиксированная комиссия
    )
    
    # Маленький размер позиции - фиксированная комиссия будет иметь большее влияние
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.05,  # 5% на сделку = 0.5 SOL (маленькая позиция)
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=fee_model
    )
    
    engine = PortfolioEngine(config)
    
    entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_time = entry_time + timedelta(hours=2)
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=1.01,  # 1% прибыль
        pnl=raw_pnl_pct,
        reason="tp"
    )
    
    all_results = [{
        "signal_id": "small_size_signal",
        "contract_address": "SMALLSIZE",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output
    }]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    position = result.positions[0]
    position_size = initial_balance * config.percent_per_trade  # 0.5 SOL
    
    # Для маленькой позиции slippage и fees превращают прибыль в убыток
    # В новой логике slippage применяется к ценам, fees к нотионалу
    
    # Проверка: net_pnl отрицательный (slippage + fees больше прибыли)
    assert position.pnl_pct is not None, "pnl_pct не должен быть None для закрытой позиции"
    assert position.pnl_pct < 0, \
        f"Для маленькой позиции slippage и fees должны превратить прибыль в убыток, " \
        f"получен net_pnl: {position.pnl_pct}"
    
    # Проверяем, что net_pnl меньше raw_pnl
    assert position.pnl_pct < raw_pnl_pct, \
        f"Net PnL ({position.pnl_pct}) должен быть меньше raw_pnl ({raw_pnl_pct})"
    
    # Проверка: баланс снизился
    assert result.stats.final_balance_sol < initial_balance, \
        f"Баланс должен снизиться: {result.stats.final_balance_sol} < {initial_balance}"


















