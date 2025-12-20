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
    
    # 2. Расчет ожидаемых значений
    position_size = initial_balance * config.percent_per_trade  # 10.0 * 0.1 = 1.0 SOL
    expected_fee_pct = fee_model.effective_fee_pct(position_size)
    expected_net_pnl_pct = raw_pnl_pct - expected_fee_pct
    
    # 3. ГЛАВНАЯ ПРОВЕРКА: net_pnl < 0 (комиссии превратили прибыль в убыток)
    assert position.pnl_pct is not None, "pnl_pct не должен быть None для закрытой позиции"
    assert position.pnl_pct < 0, \
        f"Net PnL должен быть отрицательным (комиссии > raw_pnl), получен: {position.pnl_pct}"
    
    # Проверка точности расчета
    assert abs(position.pnl_pct - expected_net_pnl_pct) < 0.0001, \
        f"Net PnL должен быть {expected_net_pnl_pct}, получен: {position.pnl_pct}"
    
    # 4. Проверка: комиссии действительно больше raw_pnl
    assert expected_fee_pct > raw_pnl_pct, \
        f"Комиссии ({expected_fee_pct}) должны быть больше raw_pnl ({raw_pnl_pct}), " \
        f"иначе тест не проверяет сценарий превращения прибыли в убыток"
    
    # 5. Проверка мета-данных: raw_pnl положительный
    assert "raw_pnl_pct" in position.meta, \
        "Мета-данные должны содержать raw_pnl_pct"
    
    assert position.meta["raw_pnl_pct"] > 0, \
        f"Raw PnL должен быть положительным ({position.meta['raw_pnl_pct']})"
    
    assert abs(position.meta["raw_pnl_pct"] - raw_pnl_pct) < 0.0001, \
        f"Raw PnL в мета-данных должен быть {raw_pnl_pct}, получен: {position.meta['raw_pnl_pct']}"
    
    # 6. Проверка мета-данных: fee_pct больше raw_pnl
    assert "fee_pct" in position.meta, \
        "Мета-данные должны содержать fee_pct"
    
    assert position.meta["fee_pct"] > position.meta["raw_pnl_pct"], \
        f"Комиссии ({position.meta['fee_pct']}) должны быть больше raw_pnl ({position.meta['raw_pnl_pct']})"
    
    # 7. Проверка: баланс снизился после сделки
    assert result.stats.final_balance_sol < initial_balance, \
        f"Баланс должен снизиться после убыточной сделки: {result.stats.final_balance_sol} < {initial_balance}"
    
    # Расчет ожидаемого баланса для проверки
    # Баланс после открытия: initial_balance - size = 10.0 - 1.0 = 9.0 SOL
    # Баланс после закрытия: 9.0 + 1.0 + 1.0 * net_pnl_pct = 10.0 + net_pnl_pct
    # Если net_pnl_pct < 0, то баланс < 10.0
    expected_final_balance = initial_balance + position_size * expected_net_pnl_pct
    
    assert abs(result.stats.final_balance_sol - expected_final_balance) < 0.0001, \
        f"Ожидаемый финальный баланс: {expected_final_balance}, получен: {result.stats.final_balance_sol}"
    
    # 8. Проверка итоговой доходности портфеля
    # total_return_pct = (final_balance - initial_balance) / initial_balance
    expected_total_return = expected_net_pnl_pct * (position_size / initial_balance)
    # = net_pnl_pct * percent_per_trade
    
    assert result.stats.total_return_pct < 0, \
        f"Итоговая доходность портфеля должна быть отрицательной, получена: {result.stats.total_return_pct}"
    
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
    
    # Для маленькой позиции фиксированная комиссия в процентах выше
    fee_pct = fee_model.effective_fee_pct(position_size)
    # pct_roundtrip = 2 * (0.003 + 0.001 + 0.10) = 20.8%
    # network_pct = 0.0005 / 0.5 = 0.001 = 0.1%
    # total_fee_pct ≈ 20.9% > 1% raw_pnl
    
    # Проверка: net_pnl отрицательный (комиссии больше прибыли)
    assert position.pnl_pct is not None, "pnl_pct не должен быть None для закрытой позиции"
    assert position.pnl_pct < 0, \
        f"Для маленькой позиции комиссии должны превратить прибыль в убыток, " \
        f"получен net_pnl: {position.pnl_pct}"
    
    assert fee_pct > raw_pnl_pct, \
        f"Комиссии ({fee_pct}) должны быть больше raw_pnl ({raw_pnl_pct})"
    
    # Проверка: баланс снизился
    assert result.stats.final_balance_sol < initial_balance, \
        f"Баланс должен снизиться: {result.stats.final_balance_sol} < {initial_balance}"














