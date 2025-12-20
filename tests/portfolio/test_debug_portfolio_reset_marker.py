"""
Временный тест-диагност для portfolio-level reset.

Копирует сценарий из test_portfolio_reset_triggered_when_threshold_reached,
но после engine.simulate печатает/логирует диагностическую информацию:
- reset_count
- все позиции: signal_id, status, meta.keys(), closed_by_reset, triggered_portfolio_reset
- id(position) для обеих позиций
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_debug_portfolio_reset_marker():
    """
    Диагностический тест для portfolio-level reset.
    
    Сценарий:
    - Начальный баланс: 10.0
    - Порог: 20.0 (2x)
    - Создаем сделки, которые приведут к equity >= 20.0
    - После simulate выводим диагностическую информацию
    """
    initial_balance = 10.0
    
        config = PortfolioConfig(
            initial_balance_sol=initial_balance,
            allocation_mode="dynamic",
            percent_per_trade=0.2,  # 20% для быстрого роста equity
            max_exposure=1.0,
            max_open_positions=10,
            fee_model=FeeModel(
                swap_fee_pct=0.003,
                lp_fee_pct=0.001,
                slippage_pct=0.0,  # Без slippage для простоты
                network_fee_sol=0.0005
            ),
            runner_reset_enabled=False,  # Отключаем runner reset, чтобы тест проверял только portfolio-level reset
            runner_reset_multiple=2.0  # x2
        )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Первая сделка: очень прибыльная (3x)
    # Размер: 10.0 * 0.2 = 2.0 SOL
    # После закрытия: баланс увеличится примерно до 10.0 + 2.0 * 2.0 = 14.0 SOL (с учетом fees меньше)
    # Нужна вторая сделка, чтобы достичь порога 20.0
    
    entry_time_1 = base_time
    exit_time_1 = base_time + timedelta(hours=1)
    
    strategy_output_1 = StrategyOutput(
        entry_time=entry_time_1,
        entry_price=100.0,
        exit_time=exit_time_1,
        exit_price=300.0,  # 3x
        pnl=2.0,  # 200%
        reason="tp",
        meta={}
    )
    
    # Вторая сделка: открывается после первой, еще открыта когда equity достигает порога
    entry_time_2 = exit_time_1 + timedelta(minutes=5)
    exit_time_2 = entry_time_2 + timedelta(hours=1)
    
    strategy_output_2 = StrategyOutput(
        entry_time=entry_time_2,
        entry_price=100.0,
        exit_time=exit_time_2,
        exit_price=200.0,  # 2x
        pnl=1.0,
        reason="tp",
        meta={}
    )
    
    all_results = [
        {
            "signal_id": "trade_1",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": entry_time_1,
            "result": strategy_output_1
        },
        {
            "signal_id": "trade_2",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": entry_time_2,
            "result": strategy_output_2
        }
    ]
    
    result = engine.simulate(all_results, strategy_name="test_strategy")
    
    # Диагностическая информация
    print("\n" + "="*80)
    print("DIAGNOSTIC INFO: Portfolio Reset Marker")
    print("="*80)
    
        print(f"\nRunner reset count: {result.stats.runner_reset_count}")
        print(f"Portfolio reset count: {result.stats.portfolio_reset_count}")
        print(f"Reset count (legacy): {result.stats.reset_count}")
        print(f"Cycle start equity: {result.stats.cycle_start_equity}")
        print(f"Equity peak in cycle: {result.stats.equity_peak_in_cycle}")
        print(f"Last portfolio reset time: {result.stats.last_portfolio_reset_time}")
    
    print(f"\nTotal positions: {len(result.positions)}")
    
    # Сохраняем id позиций для сравнения
    position_ids = {}
    
    for i, pos in enumerate(result.positions):
        pos_id = id(pos)
        position_ids[pos.signal_id] = pos_id
        
        print(f"\n  Position {i+1}:")
        print(f"    signal_id: {pos.signal_id}")
        print(f"    status: {pos.status}")
        print(f"    id(position): {pos_id}")
        print(f"    closed_by_reset: {pos.meta.get('closed_by_reset', False)}")
        print(f"    triggered_portfolio_reset: {pos.meta.get('triggered_portfolio_reset', False)}")
        print(f"    triggered_reset: {pos.meta.get('triggered_reset', False)}")
        print(f"    meta.keys(): {list(pos.meta.keys())}")
    
    # Проверяем, какие позиции закрыты по reset
    reset_positions = [p for p in result.positions if p.meta.get("closed_by_reset", False)]
    print(f"\nReset positions count: {len(reset_positions)}")
    print(f"Reset positions signal_ids: {[p.signal_id for p in reset_positions]}")
    
    # Проверяем, какая позиция является marker (triggered_portfolio_reset)
    marker_positions = [p for p in result.positions if p.meta.get("triggered_portfolio_reset", False)]
    print(f"\nMarker positions (triggered_portfolio_reset=True) count: {len(marker_positions)}")
    print(f"Marker positions signal_ids: {[p.signal_id for p in marker_positions]}")
    
    if marker_positions:
        for marker_pos in marker_positions:
            print(f"\n  Marker position details:")
            print(f"    signal_id: {marker_pos.signal_id}")
            print(f"    id(position): {id(marker_pos)}")
            print(f"    in result.positions: {marker_pos in result.positions}")
            print(f"    closed_by_reset: {marker_pos.meta.get('closed_by_reset', False)}")
            print(f"    triggered_portfolio_reset: {marker_pos.meta.get('triggered_portfolio_reset', False)}")
    
    print("\n" + "="*80)
    
        # Базовые проверки
        assert result.stats.portfolio_reset_count >= 0
        assert result.stats.runner_reset_count >= 0
        assert result.stats.cycle_start_equity > 0
        
        # Если был portfolio-level reset, проверяем детали
        # Инвариант: portfolio_reset_count > 0 => есть позиции с closed_by_reset и triggered_portfolio_reset
        if result.stats.portfolio_reset_count > 0:
            assert result.stats.last_portfolio_reset_time is not None
            assert len(reset_positions) > 0, "Должны быть позиции, закрытые по portfolio reset"
            assert len(marker_positions) > 0, "Должна быть хотя бы одна marker позиция с triggered_portfolio_reset=True"




