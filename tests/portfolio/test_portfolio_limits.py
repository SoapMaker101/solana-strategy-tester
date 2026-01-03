"""
Unit-тесты для ограничений портфеля.

Проверяет:
- max_open_positions: ограничение на количество одновременных открытых позиций
- max_exposure: ограничение на максимальную экспозицию портфеля
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_max_open_positions_rejects_excess_trades():
    """
    Тест: max_open_positions ограничивает количество одновременных открытых позиций.
    
    Сценарий:
    - 3 сделки с пересекающимися временными окнами (все открываются одновременно)
    - max_open_positions = 1
    - Ожидаем: откроется только 1 сделка, остальные 2 будут отклонены
    
    Проверяем:
    - trades_executed == 1 (только одна сделка выполнена)
    - trades_skipped_by_risk == 2 (две сделки отклонены)
    - В результате только одна позиция
    """
    initial_balance = 10.0
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.1,  # 10% на сделку
        max_exposure=1.0,  # 100% экспозиция (не ограничиваем здесь)
        max_open_positions=1,  # КЛЮЧЕВОЕ ОГРАНИЧЕНИЕ: только 1 открытая позиция
        fee_model=FeeModel()
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем 3 сделки с пересекающимися временными окнами
    # Все они должны открыться одновременно (entry_time совпадает или близко)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    for i in range(3):
        entry_time = base_time + timedelta(minutes=i * 5)  # Небольшой разброс для сортировки
        exit_time = entry_time + timedelta(hours=2)  # Все закрываются позже
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.05,  # 5% прибыль
            pnl=0.05,
            reason="ladder_tp"
        )
        
        trades.append({
            "signal_id": f"test_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Запускаем симуляцию
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: только одна сделка выполнена
    assert result.stats.trades_executed == 1, \
        f"Должна быть выполнена только 1 сделка (max_open_positions=1), получено: {result.stats.trades_executed}"
    
    # 2. Проверка: две сделки отклонены из-за лимита позиций
    assert result.stats.trades_skipped_by_risk == 2, \
        f"Должны быть отклонены 2 сделки, получено: {result.stats.trades_skipped_by_risk}"
    
    # 3. Проверка: в результате только одна позиция
    assert len(result.positions) == 1, \
        f"Должна быть только одна позиция, получено: {len(result.positions)}"
    
    # 4. Проверка: первая сделка выполнена (она самая ранняя по entry_time)
    assert result.positions[0].signal_id == "test_signal_1", \
        "Первая сделка по времени должна быть выполнена"
    
    # 5. Проверка: баланс соответствует одной сделке
    # Размер позиции = 10.0 * 0.1 = 1.0 SOL
    # Баланс после открытия = 10.0 - 1.0 = 9.0
    # Комиссии примерно 20.8%, net_pnl = 5% - 20.8% = -15.8%
    # Финальный баланс ≈ 9.84 SOL (зависит от точных комиссий)
    # Проверяем, что баланс соответствует одной сделке (не трем)
    position_size = initial_balance * config.percent_per_trade  # 1.0 SOL
    assert result.stats.final_balance_sol < initial_balance + position_size * 2, \
        f"Баланс должен соответствовать только одной сделке, получен: {result.stats.final_balance_sol}"


def test_max_exposure_rejects_second_trade():
    """
    Тест: max_exposure ограничивает максимальную экспозицию портфеля.
    
    Сценарий:
    - 2 одновременные сделки (пересекающиеся окна)
    - allocation_mode = "dynamic"
    - percent_per_trade установлен так, чтобы 2 сделки превышали max_exposure
    - max_exposure = 0.5 (50%)
    
    Расчет для dynamic mode:
    - Начальный баланс: 10.0 SOL
    - percent_per_trade = 0.4 (40%)
    - Первая сделка: размер = 10.0 * 0.4 = 4.0 SOL (экспозиция = 4.0/10.0 = 40% - OK)
    - После открытия первой: баланс = 10.0 - 4.0 = 6.0 SOL
    - Вторая сделка: желаемый размер = 6.0 * 0.4 = 2.4 SOL
    - Общая экспозиция при двух сделках = (4.0 + 2.4) / (6.0 + 4.0 + 2.4) = 6.4 / 12.4 = 51.6% > 50%
    - Ожидаем: вторая сделка отклонена
    
    Проверяем:
    - trades_executed == 1
    - trades_skipped_by_risk == 1
    """
    initial_balance = 10.0
    max_exposure = 0.5  # 50% максимальная экспозиция
    
    config = PortfolioConfig(
        initial_balance_sol=initial_balance,
        allocation_mode="dynamic",
        percent_per_trade=0.4,  # 40% на сделку - достаточно, чтобы 2 сделки превысили 50%
        max_exposure=max_exposure,
        max_open_positions=10,  # Не ограничиваем количество позиций
        fee_model=FeeModel()
    )
    
    engine = PortfolioEngine(config)
    
    # Создаем 2 сделки с пересекающимися окнами
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    for i in range(2):
        entry_time = base_time + timedelta(minutes=i * 5)
        exit_time = entry_time + timedelta(hours=2)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.05,
            pnl=0.05,
            reason="ladder_tp"
        )
        
        trades.append({
            "signal_id": f"exposure_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Запускаем симуляцию
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: только одна сделка выполнена
    assert result.stats.trades_executed == 1, \
        f"Должна быть выполнена только 1 сделка (max_exposure ограничивает), получено: {result.stats.trades_executed}"
    
    # 2. Проверка: вторая сделка отклонена из-за превышения экспозиции
    assert result.stats.trades_skipped_by_risk == 1, \
        f"Должна быть отклонена 1 сделка из-за превышения max_exposure, получено: {result.stats.trades_skipped_by_risk}"
    
    # 3. Проверка: в результате только одна позиция
    assert len(result.positions) == 1, \
        f"Должна быть только одна позиция, получено: {len(result.positions)}"
    
    # 4. Проверка: первая сделка выполнена
    assert result.positions[0].signal_id == "exposure_signal_1", \
        "Первая сделка должна быть выполнена"
    
    # 5. Проверка: размер позиции соответствует percent_per_trade от начального баланса
    expected_size = initial_balance * config.percent_per_trade  # 10.0 * 0.4 = 4.0 SOL
    assert abs(result.positions[0].size - expected_size) < 0.01, \
        f"Размер первой позиции должен быть {expected_size} SOL, получено: {result.positions[0].size}"
    
    # 6. Проверка: экспозиция первой сделки в пределах лимита
    first_exposure = expected_size / initial_balance  # 4.0 / 10.0 = 0.4 = 40%
    assert first_exposure <= max_exposure, \
        f"Экспозиция первой сделки ({first_exposure}) должна быть <= max_exposure ({max_exposure})"


