"""
Unit-тесты для runner reset функциональности.

Проверяет портфельную политику: при достижении позицией XN (multiplying return >= XN)
закрываются все открытые позиции и входы игнорируются до следующего сигнала.
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_runner_reset_closes_all_positions_on_xn():
    """
    Тест: runner reset закрывает все открытые позиции при достижении XN.
    
    Сценарий:
    - runner_reset_enabled = True
    - runner_reset_multiple = 2.0 (x2)
    - 3 открытые позиции одновременно
    - Одна позиция достигает x2 (exit_price / entry_price >= 2.0)
    - Ожидаем: все 3 позиции закрываются на момент закрытия триггерной
    
    Проверяем:
    - Все позиции закрыты
    - Триггерная позиция имеет метку "triggered_reset"
    - Остальные позиции имеют метку "closed_by_reset"
    - trades_executed == 3
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=True,
        runner_reset_multiple=2.0  # x2
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Три сделки, открывающиеся одновременно
    trades = []
    for i in range(3):
        entry_time = base_time + timedelta(minutes=i * 5)
        exit_time = entry_time + timedelta(hours=2)
        
        # Первая сделка достигает x2 (триггер reset)
        # Остальные - обычные сделки
        if i == 0:
            exit_price = 2.0  # x2 от entry_price=1.0
            pnl = 1.0  # 100% прибыль
        else:
            exit_price = 1.05  # 5% прибыль
            pnl = 0.05
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=exit_price,
            pnl=pnl,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"reset_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Все 3 позиции закрыты
    assert result.stats.trades_executed == 3, \
        f"Должны быть выполнены все 3 сделки, получено: {result.stats.trades_executed}"
    
    assert len(result.positions) == 3, \
        f"Должны быть 3 позиции, получено: {len(result.positions)}"
    
    # 2. Находим триггерную позицию (первая)
    trigger_position = next((p for p in result.positions if p.signal_id == "reset_signal_1"), None)
    assert trigger_position is not None, "Триггерная позиция должна быть найдена"
    
    # 3. Проверка: триггерная позиция достигла XN
    assert trigger_position.exit_price is not None, "exit_price не должен быть None для закрытой позиции"
    assert trigger_position.entry_price is not None, "entry_price не должен быть None"
    multiplying_return = trigger_position.exit_price / trigger_position.entry_price
    assert multiplying_return >= config.runner_reset_multiple, \
        f"Триггерная позиция должна достичь XN ({config.runner_reset_multiple}), " \
        f"получено: {multiplying_return}"
    
    # 4. Проверка: триггерная позиция имеет метку "triggered_reset"
    assert trigger_position.meta.get("triggered_reset") == True, \
        "Триггерная позиция должна иметь метку 'triggered_reset'"
    
    # 5. Проверка: остальные позиции закрыты по reset
    other_positions = [p for p in result.positions if p.signal_id != "reset_signal_1"]
    for pos in other_positions:
        assert pos.meta.get("closed_by_reset") == True, \
            f"Позиция {pos.signal_id} должна быть закрыта по reset"
        assert pos.status == "closed", \
            f"Позиция {pos.signal_id} должна быть закрыта"
    
    # 6. Проверка: все позиции закрыты на момент reset (или раньше)
    reset_time = trigger_position.exit_time
    assert reset_time is not None, "reset_time не должен быть None"
    for pos in result.positions:
        assert pos.exit_time is not None, \
            f"Позиция {pos.signal_id} должна иметь exit_time"
        # Все позиции должны быть закрыты не позже reset времени
        assert pos.exit_time <= reset_time, \
            f"Позиция {pos.signal_id} закрыта в {pos.exit_time}, " \
            f"но reset был в {reset_time}"


def test_runner_reset_ignores_entries_until_next_signal():
    """
    Тест: runner reset игнорирует входы до следующего сигнала после reset.
    
    Сценарий:
    - Первая сделка достигает XN и закрывается в T1
    - Вторая сделка начинается в T2, где T1 <= T2 <= reset_until
    - Ожидаем: вторая сделка пропущена (trades_skipped_by_reset > 0)
    - Третья сделка начинается после reset_until
    - Ожидаем: третья сделка выполняется
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=True,
        runner_reset_multiple=2.0
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Первая сделка: достигает XN в T1
    trigger_entry = base_time
    trigger_exit = trigger_entry + timedelta(hours=1)  # T1
    
    # Вторая сделка: начинается сразу после reset (должна быть пропущена)
    skipped_entry = trigger_exit  # T1 (в момент reset)
    skipped_exit = skipped_entry + timedelta(hours=1)
    
    # Третья сделка: начинается после reset (должна выполниться)
    allowed_entry = trigger_exit + timedelta(minutes=1)  # T1 + 1 min (после reset)
    allowed_exit = allowed_entry + timedelta(hours=1)
    
    trades = [
        {
            "signal_id": "trigger_reset",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": trigger_entry,
            "result": StrategyOutput(
                entry_time=trigger_entry,
                entry_price=1.0,
                exit_time=trigger_exit,
                exit_price=2.0,  # x2
                pnl=1.0,
                reason="tp"
            )
        },
        {
            "signal_id": "skipped_by_reset",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": skipped_entry,
            "result": StrategyOutput(
                entry_time=skipped_entry,
                entry_price=1.0,
                exit_time=skipped_exit,
                exit_price=1.05,
                pnl=0.05,
                reason="tp"
            )
        },
        {
            "signal_id": "allowed_after_reset",
            "contract_address": "TOKEN3",
            "strategy": "test_strategy",
            "timestamp": allowed_entry,
            "result": StrategyOutput(
                entry_time=allowed_entry,
                entry_price=1.0,
                exit_time=allowed_exit,
                exit_price=1.05,
                pnl=0.05,
                reason="tp"
            )
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: сделка, начинающаяся в момент reset, пропущена
    assert result.stats.trades_skipped_by_reset >= 1, \
        f"Должна быть пропущена хотя бы одна сделка из-за reset, " \
        f"получено: {result.stats.trades_skipped_by_reset}"
    
    # 2. Проверка: выполнены первая и третья сделки
    assert result.stats.trades_executed >= 2, \
        f"Должны быть выполнены минимум 2 сделки (trigger и allowed), " \
        f"получено: {result.stats.trades_executed}"
    
    # 3. Проверка: пропущенная сделка отсутствует в результатах
    skipped_position = next((p for p in result.positions if p.signal_id == "skipped_by_reset"), None)
    assert skipped_position is None, \
        "Сделка 'skipped_by_reset' не должна быть в результатах"
    
    # 4. Проверка: разрешенная сделка присутствует
    allowed_position = next((p for p in result.positions if p.signal_id == "allowed_after_reset"), None)
    assert allowed_position is not None, \
        "Сделка 'allowed_after_reset' должна быть выполнена"


def test_runner_reset_disabled_does_not_trigger():
    """
    Тест: когда runner_reset_enabled = False, reset не срабатывает.
    
    Проверяем, что при отключенном reset все позиции работают нормально.
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=False,  # Отключен
        runner_reset_multiple=2.0
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    for i in range(3):
        entry_time = base_time + timedelta(minutes=i * 5)
        exit_time = entry_time + timedelta(hours=2)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=2.0 if i == 0 else 1.05,  # Первая достигает x2
            pnl=1.0 if i == 0 else 0.05,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"no_reset_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверка: все сделки выполнены
    assert result.stats.trades_executed == 3, \
        f"Все 3 сделки должны быть выполнены при отключенном reset, " \
        f"получено: {result.stats.trades_executed}"
    
    # Проверка: нет пропущенных сделок из-за reset
    assert result.stats.trades_skipped_by_reset == 0, \
        f"Не должно быть пропущенных сделок из-за reset, " \
        f"получено: {result.stats.trades_skipped_by_reset}"
    
    # Проверка: нет меток reset
    for pos in result.positions:
        assert pos.meta.get("triggered_reset") != True, \
            f"Позиция {pos.signal_id} не должна иметь метку 'triggered_reset'"
        assert pos.meta.get("closed_by_reset") != True, \
            f"Позиция {pos.signal_id} не должна иметь метку 'closed_by_reset'"


def test_runner_reset_with_three_trades_first_triggers_reset():
    """
    Тест: проверяет сценарий с 3 сделками - первые две overlap, третья позже.
    
    Сценарий (как в требованиях):
    - 3 сделки, первые две overlap по времени, третья позже
    - Первая достигает XN и триггерит reset
    - Ожидание:
      a) вторая закрывается принудительно из-за reset
      b) третья обрабатывается нормально (после reset)
    
    Проверяем:
    - Первая сделка триггерит reset
    - Вторая сделка закрыта принудительно (closed_by_reset)
    - Третья сделка обрабатывается нормально (не пропущена)
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=True,
        runner_reset_multiple=2.0  # x2
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Первая сделка: достигает XN и триггерит reset
    trade1_entry = base_time
    trade1_exit = base_time + timedelta(hours=1)  # Закрывается в T1
    
    # Вторая сделка: overlap с первой (начинается до закрытия первой)
    trade2_entry = base_time + timedelta(minutes=30)  # Начинается через 30 мин от первой
    trade2_exit = base_time + timedelta(hours=2)  # Закрывается позже первой
    
    # Третья сделка: позже, после reset (должна обработаться нормально)
    trade3_entry = trade1_exit + timedelta(minutes=10)  # Начинается после закрытия первой (после reset)
    trade3_exit = trade3_entry + timedelta(hours=1)
    
    trades = [
        {
            "signal_id": "trigger_reset_trade",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": trade1_entry,
            "result": StrategyOutput(
                entry_time=trade1_entry,
                entry_price=1.0,
                exit_time=trade1_exit,
                exit_price=2.0,  # x2 - достигает XN
                pnl=1.0,
                reason="tp"
            )
        },
        {
            "signal_id": "overlap_forced_close",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": trade2_entry,
            "result": StrategyOutput(
                entry_time=trade2_entry,
                entry_price=1.0,
                exit_time=trade2_exit,
                exit_price=1.05,  # 5% прибыль
                pnl=0.05,
                reason="tp"
            )
        },
        {
            "signal_id": "after_reset_normal",
            "contract_address": "TOKEN3",
            "strategy": "test_strategy",
            "timestamp": trade3_entry,
            "result": StrategyOutput(
                entry_time=trade3_entry,
                entry_price=1.0,
                exit_time=trade3_exit,
                exit_price=1.05,  # 5% прибыль
                pnl=0.05,
                reason="tp"
            )
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверка: все 3 сделки выполнены (третья не пропущена)
    assert result.stats.trades_executed == 3, \
        f"Должны быть выполнены все 3 сделки, получено: {result.stats.trades_executed}"
    
    assert len(result.positions) == 3, \
        f"Должны быть 3 позиции, получено: {len(result.positions)}"
    
    # 2. Проверка (a): вторая сделка закрыта принудительно из-за reset
    position2 = next((p for p in result.positions if p.signal_id == "overlap_forced_close"), None)
    assert position2 is not None, "Вторая позиция должна быть найдена"
    
    assert position2.meta.get("closed_by_reset") == True, \
        "Вторая позиция должна быть закрыта принудительно из-за reset"
    
    assert position2.status == "closed", \
        "Вторая позиция должна быть закрыта"
    
    # Проверка: вторая позиция закрыта на момент reset (не на свой exit_time)
    position1 = next((p for p in result.positions if p.signal_id == "trigger_reset_trade"), None)
    assert position1 is not None, "Первая позиция должна быть найдена"
    reset_time = position1.exit_time
    assert reset_time is not None, "reset_time не должен быть None"
    
    # Вторая позиция должна быть закрыта не позже reset времени
    assert position2.exit_time is not None, "exit_time второй позиции не должен быть None"
    assert position2.exit_time <= reset_time, \
        f"Вторая позиция должна быть закрыта на момент reset ({reset_time}), " \
        f"но закрыта в {position2.exit_time}"
    
    # 3. Проверка (b): третья сделка обрабатывается нормально (после reset)
    position3 = next((p for p in result.positions if p.signal_id == "after_reset_normal"), None)
    assert position3 is not None, "Третья позиция должна быть найдена"
    
    assert position3.meta.get("closed_by_reset") != True, \
        "Третья позиция НЕ должна быть закрыта по reset (она после reset)"
    
    assert position3.status == "closed", \
        "Третья позиция должна быть закрыта нормально"
    
    # Проверка: третья позиция не пропущена
    assert result.stats.trades_skipped_by_reset == 0, \
        f"Третья сделка не должна быть пропущена из-за reset, " \
        f"получено trades_skipped_by_reset: {result.stats.trades_skipped_by_reset}"
    
    # 4. Проверка: первая сделка триггерит reset
    assert position1.meta.get("triggered_reset") == True, \
        "Первая позиция должна триггерить reset"
    
    assert position1.exit_price is not None, "exit_price не должен быть None для закрытой позиции"
    assert position1.entry_price is not None, "entry_price не должен быть None"
    multiplying_return = position1.exit_price / position1.entry_price
    assert multiplying_return >= config.runner_reset_multiple, \
        f"Первая позиция должна достичь XN ({config.runner_reset_multiple}), " \
        f"получено: {multiplying_return}"


def test_runner_reset_with_multiple_xn_levels():
    """
    Тест: проверяет работу с разными уровнями XN (например, x3 вместо x2).
    """
    config = PortfolioConfig(
        initial_balance_sol=10.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        runner_reset_enabled=True,
        runner_reset_multiple=3.0  # x3
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Первая сделка: x2 (не достигает x3, reset не сработает)
    # Вторая сделка: x3 (достигает x3, reset сработает)
    trades = [
        {
            "signal_id": "below_xn",
            "contract_address": "TOKEN1",
            "strategy": "test_strategy",
            "timestamp": base_time,
            "result": StrategyOutput(
                entry_time=base_time,
                entry_price=1.0,
                exit_time=base_time + timedelta(hours=1),
                exit_price=2.0,  # x2, но не x3
                pnl=1.0,
                reason="tp"
            )
        },
        {
            "signal_id": "at_xn",
            "contract_address": "TOKEN2",
            "strategy": "test_strategy",
            "timestamp": base_time + timedelta(minutes=5),
            "result": StrategyOutput(
                entry_time=base_time + timedelta(minutes=5),
                entry_price=1.0,
                exit_time=base_time + timedelta(hours=1, minutes=5),
                exit_price=3.0,  # x3 - достигает XN
                pnl=2.0,
                reason="tp"
            )
        }
    ]
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # Проверка: вторая сделка триггерит reset
    xn_position = next((p for p in result.positions if p.signal_id == "at_xn"), None)
    assert xn_position is not None, "Позиция 'at_xn' должна быть найдена"
    
    assert xn_position.exit_price is not None, "exit_price не должен быть None для закрытой позиции"
    assert xn_position.entry_price is not None, "entry_price не должен быть None"
    multiplying_return = xn_position.exit_price / xn_position.entry_price
    assert multiplying_return >= config.runner_reset_multiple, \
        f"Позиция должна достичь XN {config.runner_reset_multiple}, получено: {multiplying_return}"
    
    assert xn_position.meta.get("triggered_reset") == True, \
        "Позиция, достигшая XN, должна иметь метку 'triggered_reset'"

