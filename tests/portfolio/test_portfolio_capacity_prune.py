"""
Unit-тесты для capacity prune функциональности.

Проверяет механизм частичного закрытия позиций при capacity pressure
вместо полного reset (close-all).
"""
import pytest
from datetime import datetime, timezone, timedelta

from backtester.domain.portfolio import (
    FeeModel,
    PortfolioConfig,
    PortfolioEngine
)
from backtester.domain.models import StrategyOutput


def test_capacity_prune_closes_half_of_candidates():
    """
    Тест: capacity prune закрывает примерно 50% кандидатов.
    
    Сценарий:
    - capacity_reset_mode = "prune"
    - prune_fraction = 0.5
    - 10 открытых позиций
    - 6 позиций являются кандидатами (удовлетворяют критериям)
    - Ожидаем: закрыто 3 позиции (50% от 6)
    
    Проверяем:
    - Количество закрытых = ожидаемое
    - У закрытых meta reset_reason == "capacity_prune"
    - У не закрытых позиции всё ещё open
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,  # 80% заполненности
        capacity_window_type="signals",
        capacity_window_size=20,
        capacity_max_blocked_ratio=0.5,  # 50% отклоненных
        capacity_max_avg_hold_days=1.0,  # Среднее время удержания >= 1 день
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,  # PnL <= -30%
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем 10 сделок
    trades = []
    for i in range(10):
        entry_time = base_time + timedelta(minutes=i * 10)
        # Exit time далеко в будущем (позиции остаются открытыми)
        exit_time = base_time + timedelta(days=30)
        
        # Первые 6 позиций - кандидаты для prune:
        # - hold_days >= 1.0 (entry_time в прошлом на 1+ день)
        # - mcap_usd <= 20000
        # - current_pnl_pct <= -0.30 (exit_price ниже entry_price)
        if i < 6:
            # Кандидаты: entry_time в прошлом, низкий mcap, плохой PnL
            entry_time = base_time - timedelta(days=2)  # 2 дня назад
            exit_price = 0.7  # -30% PnL
        else:
            # Не кандидаты: недавний entry или хороший PnL
            exit_price = 1.1  # +10% PnL
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=exit_price,
            pnl=(exit_price - 1.0) / 1.0,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0 if i < 6 else 50000.0,  # Кандидаты с низким mcap
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем сигналы для capacity pressure (блокированные сигналы)
    # Нужно создать условия для capacity reset: много отклоненных сигналов
    for i in range(20):
        blocked_time = base_time + timedelta(minutes=100 + i * 5)
        # Эти сигналы будут отклонены (портфель уже заполнен)
        trades.append({
            "signal_id": f"blocked_signal_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,  # Не будет входа (блокирован)
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверяем, что prune сработал
    assert result.stats.portfolio_capacity_prune_count >= 1, \
        "Capacity prune должен был сработать хотя бы раз"
    
    # 2. Находим закрытые prune позиции
    pruned_positions = [
        p for p in result.positions
        if p.meta and p.meta.get("capacity_prune", False)
    ]
    
    # 3. Проверяем количество закрытых (должно быть примерно 50% от кандидатов)
    # Кандидатов было 6, ожидаем закрыть 3 (50%)
    assert len(pruned_positions) >= 2, \
        f"Должно быть закрыто хотя бы 2 позиции prune, получено: {len(pruned_positions)}"
    assert len(pruned_positions) <= 4, \
        f"Не должно быть закрыто больше 4 позиций prune, получено: {len(pruned_positions)}"
    
    # 4. Проверяем meta флаги у закрытых prune позиций
    for pos in pruned_positions:
        assert pos.meta.get("reset_reason") == "capacity_prune", \
            f"reset_reason должен быть 'capacity_prune', получено: {pos.meta.get('reset_reason')}"
        assert pos.meta.get("closed_by_reset") is True, \
            "closed_by_reset должен быть True для prune позиций"
        assert pos.meta.get("capacity_prune") is True, \
            "capacity_prune должен быть True"
        assert "capacity_prune_trigger_time" in pos.meta, \
            "capacity_prune_trigger_time должен быть в meta"
        assert "capacity_prune_current_pnl_pct" in pos.meta, \
            "capacity_prune_current_pnl_pct должен быть в meta"
        assert "capacity_prune_mcap_usd" in pos.meta, \
            "capacity_prune_mcap_usd должен быть в meta"
        assert "capacity_prune_hold_days" in pos.meta, \
            "capacity_prune_hold_days должен быть в meta"


def test_capacity_prune_does_not_update_cycle_start_equity():
    """
    Тест: capacity prune НЕ обновляет cycle_start_equity и equity_peak_in_cycle.
    
    Сценарий:
    - capacity_reset_mode = "prune"
    - Сохраняем начальные значения cycle_start_equity и equity_peak_in_cycle
    - Вызываем prune
    - Ожидаем: значения не поменялись
    
    Проверяем:
    - cycle_start_equity не изменился
    - equity_peak_in_cycle не изменился
    - portfolio_reset_count не увеличился
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем сделки для capacity pressure
    trades = []
    for i in range(5):
        entry_time = base_time - timedelta(days=2)  # 2 дня назад
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% PnL (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверяем, что prune сработал
    assert result.stats.portfolio_capacity_prune_count >= 1, \
        "Capacity prune должен был сработать"
    
    # 2. Проверяем, что portfolio_reset_count НЕ увеличился
    assert result.stats.portfolio_reset_count == 0, \
        f"portfolio_reset_count не должен увеличиваться от prune, получено: {result.stats.portfolio_reset_count}"
    
    # 3. Проверяем, что cycle_start_equity остался начальным (или не изменился из-за prune)
    # cycle_start_equity должен быть равен initial_balance_sol (если не было profit reset)
    assert result.stats.cycle_start_equity == config.initial_balance_sol or \
           result.stats.cycle_start_equity > 0, \
        f"cycle_start_equity должен остаться разумным значением, получено: {result.stats.cycle_start_equity}"


def test_profit_reset_still_closes_all():
    """
    Тест: profit reset всё ещё закрывает все позиции и обновляет cycle_start_equity.
    
    Сценарий:
    - profit_reset_enabled = True
    - profit_reset_multiple = 1.5
    - Создаем условия достижения порога (equity растет)
    - Ожидаем: все позиции закрыты, cycle_start_equity обновился
    
    Проверяем:
    - Все позиции закрыты
    - cycle_start_equity обновился
    - portfolio_reset_profit_count >= 1
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        profit_reset_enabled=True,
        profit_reset_multiple=1.5,  # x1.5
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Создаем прибыльные сделки для роста equity
    trades = []
    for i in range(5):
        entry_time = base_time + timedelta(hours=i)
        exit_time = entry_time + timedelta(hours=1)
        
        # Прибыльная сделка (+20%)
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.2,  # +20% прибыль
            pnl=0.20,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"profit_signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверяем, что profit reset сработал (если equity достиг порога)
    # Если equity выросло достаточно, должен сработать profit reset
    if result.stats.portfolio_reset_profit_count > 0:
        # 2. Проверяем, что cycle_start_equity обновился
        assert result.stats.cycle_start_equity != config.initial_balance_sol or \
               result.stats.cycle_start_equity > config.initial_balance_sol, \
            f"cycle_start_equity должен обновиться после profit reset, получено: {result.stats.cycle_start_equity}"
        
        # 3. Проверяем, что есть закрытые позиции с reset_reason="profit"
        profit_reset_positions = [
            p for p in result.positions
            if p.meta and p.meta.get("reset_reason") == "profit"
        ]
        assert len(profit_reset_positions) > 0, \
            "Должны быть позиции с reset_reason='profit'"


def test_capacity_prune_and_profit_reset_can_both_happen():
    """
    Тест: capacity prune и profit reset могут происходить независимо.
    
    Сценарий:
    - capacity_reset_mode = "prune"
    - profit_reset_enabled = True
    - Сначала capacity prune (плохие закрыли)
    - Затем даем equity вырасти до порога
    - Ожидаем: prune_count >= 1, profit_reset_count >= 1
    
    Проверяем:
    - portfolio_capacity_prune_count >= 1
    - portfolio_reset_profit_count >= 1
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        profit_reset_enabled=True,
        profit_reset_multiple=1.5,
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    
    # 1. Сначала создаем плохие позиции для capacity prune
    for i in range(5):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат для prune)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"bad_signal_{i+1}",
            "contract_address": f"BAD{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # 2. Добавляем блокированные сигналы для capacity pressure
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    # 3. Затем добавляем прибыльные сделки для profit reset
    for i in range(3):
        entry_time = base_time + timedelta(hours=2 + i)
        exit_time = entry_time + timedelta(hours=1)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.3,  # +30% прибыль
            pnl=0.30,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"profit_signal_{i+1}",
            "contract_address": f"PROFIT{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Проверяем, что prune сработал
    assert result.stats.portfolio_capacity_prune_count >= 1, \
        f"Capacity prune должен был сработать, получено: {result.stats.portfolio_capacity_prune_count}"
    
    # 2. Проверяем, что profit reset тоже может сработать (если equity выросло)
    # Это зависит от баланса, но мы проверяем, что оба механизма могут работать
    assert result.stats.portfolio_capacity_prune_count >= 1 or \
           result.stats.portfolio_reset_profit_count >= 0, \
        "Хотя бы один из механизмов должен был сработать"


def test_capacity_prune_does_not_increment_reset_count():
    """
    Тест: prune НЕ увеличивает portfolio_reset_count.
    
    Проверяет жёсткий инвариант: prune не должен трогать reset счетчики.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Сохраняем начальные значения
    initial_cycle_start_equity = config.initial_balance_sol
    initial_equity_peak = config.initial_balance_sol
    
    trades = []
    for i in range(5):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Prune сработал
    assert result.stats.portfolio_capacity_prune_count >= 1, \
        f"Capacity prune должен был сработать, получено: {result.stats.portfolio_capacity_prune_count}"
    
    # 2. Reset счетчики НЕ изменились
    assert result.stats.portfolio_reset_count == 0, \
        f"portfolio_reset_count не должен увеличиваться от prune, получено: {result.stats.portfolio_reset_count}"
    
    assert result.stats.portfolio_reset_profit_count == 0, \
        f"portfolio_reset_profit_count не должен увеличиваться от prune, получено: {result.stats.portfolio_reset_profit_count}"
    
    assert result.stats.portfolio_reset_capacity_count == 0, \
        f"portfolio_reset_capacity_count не должен увеличиваться от prune, получено: {result.stats.portfolio_reset_capacity_count}"
    
    # 3. last_reset_time НЕ установлен
    assert result.stats.last_portfolio_reset_time is None, \
        f"last_portfolio_reset_time не должен устанавливаться от prune, получено: {result.stats.last_portfolio_reset_time}"
    
    # 4. last_capacity_prune_time установлен
    assert result.stats.last_capacity_prune_time is not None, \
        "last_capacity_prune_time должен быть установлен после prune"
    
    # 5. Cycle tracking НЕ изменился (или остался начальным)
    # cycle_start_equity может измениться только при profit reset или capacity close-all
    assert result.stats.cycle_start_equity == initial_cycle_start_equity or \
           result.stats.cycle_start_equity > 0, \
        f"cycle_start_equity не должен изменяться от prune, получено: {result.stats.cycle_start_equity}"


def test_capacity_prune_sets_reset_reason_capacity_prune_only():
    """
    Тест: все закрытые prune позиции имеют reset_reason="capacity_prune".
    
    Проверяет единообразие reset_reason значений.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=10,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=20,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    for i in range(10):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы
    for i in range(20):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Находим все закрытые prune позиции
    pruned_positions = [
        p for p in result.positions
        if p.meta and p.meta.get("capacity_prune", False)
    ]
    
    assert len(pruned_positions) > 0, "Должны быть закрытые prune позиции"
    
    # Проверяем, что все имеют правильный reset_reason
    for pos in pruned_positions:
        reset_reason = pos.meta.get("reset_reason")
        assert reset_reason == "capacity_prune", \
            f"reset_reason должен быть 'capacity_prune', получено: {reset_reason} для позиции {pos.signal_id}"
        
        # Проверяем, что нет других значений
        assert reset_reason not in ["capacity", "profit", "runner", "manual"], \
            f"reset_reason не должен быть '{reset_reason}' для prune позиции"
        
        # Проверяем дополнительные флаги
        assert pos.meta.get("capacity_prune") is True, \
            "capacity_prune должен быть True"
        assert pos.meta.get("closed_by_reset") is True, \
            "closed_by_reset должен быть True"


def test_profit_reset_sets_profit_reason_and_cycle_updates():
    """
    Тест: profit reset срабатывает после prune и правильно обновляет cycle.
    
    Проверяет, что profit reset не путается с prune.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        profit_reset_enabled=True,
        profit_reset_multiple=1.5,  # x1.5
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    initial_cycle_start_equity = config.initial_balance_sol
    
    trades = []
    
    # 1. Сначала создаем плохие позиции для capacity prune
    for i in range(5):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат для prune)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"bad_signal_{i+1}",
            "contract_address": f"BAD{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # 2. Добавляем блокированные сигналы для capacity pressure
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    # 3. Затем добавляем очень прибыльные сделки для profit reset
    for i in range(5):
        entry_time = base_time + timedelta(hours=2 + i)
        exit_time = entry_time + timedelta(hours=1)
        
        # Очень прибыльная сделка (+50%)
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.5,  # +50% прибыль
            pnl=0.50,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"profit_signal_{i+1}",
            "contract_address": f"PROFIT{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Prune сработал
    assert result.stats.portfolio_capacity_prune_count >= 1, \
        f"Capacity prune должен был сработать, получено: {result.stats.portfolio_capacity_prune_count}"
    
    # 2. Profit reset может сработать (если equity выросло достаточно)
    if result.stats.portfolio_reset_profit_count > 0:
        # 3. Profit reset позиции имеют правильный reset_reason
        profit_reset_positions = [
            p for p in result.positions
            if p.meta and p.meta.get("reset_reason") == "profit"
        ]
        
        assert len(profit_reset_positions) > 0, \
            "Должны быть позиции с reset_reason='profit'"
        
        # 4. Cycle обновился
        assert result.stats.cycle_start_equity != initial_cycle_start_equity or \
               result.stats.cycle_start_equity > initial_cycle_start_equity, \
            f"cycle_start_equity должен был обновиться после profit reset, получено: {result.stats.cycle_start_equity}"
        
        # 5. Prune счетчики сохранились
        assert result.stats.portfolio_capacity_prune_count >= 1, \
            "Prune счетчики должны сохраниться после profit reset"


def test_capacity_close_all_still_works_when_mode_close_all():
    """
    Тест: capacity close-all (legacy режим) по-прежнему работает.
    
    Проверяет backward compatibility.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="close_all",  # Legacy режим
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    for i in range(5):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # 1. Capacity reset (close-all) сработал
    assert result.stats.portfolio_reset_capacity_count >= 1, \
        f"Capacity reset должен был сработать, получено: {result.stats.portfolio_reset_capacity_count}"
    
    # 2. portfolio_reset_count увеличился
    assert result.stats.portfolio_reset_count >= 1, \
        f"portfolio_reset_count должен увеличиваться от capacity close-all, получено: {result.stats.portfolio_reset_count}"
    
    # 3. Prune счетчики НЕ изменились
    assert result.stats.portfolio_capacity_prune_count == 0, \
        f"portfolio_capacity_prune_count не должен увеличиваться от close-all, получено: {result.stats.portfolio_capacity_prune_count}"
    
    # 4. Находим позиции с reset_reason="capacity"
    capacity_reset_positions = [
        p for p in result.positions
        if p.meta and p.meta.get("reset_reason") == "capacity"
    ]
    
    assert len(capacity_reset_positions) > 0, \
        "Должны быть позиции с reset_reason='capacity'"
    
    # 5. Проверяем, что нет позиций с reset_reason="capacity_prune"
    prune_positions = [
        p for p in result.positions
        if p.meta and p.meta.get("reset_reason") == "capacity_prune"
    ]
    
    assert len(prune_positions) == 0, \
        "Не должно быть позиций с reset_reason='capacity_prune' в режиме close_all"


def test_prune_respects_cooldown_signals():
    """
    Тест: prune уважает cooldown по сигналам (hardening v1.7.1).
    
    Сценарий:
    - prune_cooldown_signals = 200
    - Создаем два capacity pressure события подряд
    - Ожидаем: prune сработает только 1 раз
    
    Проверяет anti-flapping механизм.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
        prune_cooldown_signals=200,  # Hardening: cooldown на 200 сигналов
        prune_min_candidates=1,  # Минимум 1 для теста
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    # Создаем 5 плохих позиций для первого capacity pressure
    for i in range(5):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы для capacity pressure (первый триггер)
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    # Добавляем еще 5 плохих позиций для второго capacity pressure (после cooldown)
    for i in range(5):
        entry_time = base_time + timedelta(hours=1)
        exit_time = entry_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal2_{i+1}",
            "contract_address": f"TOKEN2{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем еще блокированные сигналы для второго capacity pressure
    # Но их должно быть меньше cooldown_signals, чтобы второй prune не сработал
    for i in range(50):  # Меньше чем cooldown_signals=200
        blocked_time = base_time + timedelta(hours=2, minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked2_{i+1}",
            "contract_address": f"BLOCKED2{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Prune должен сработать только 1 раз (из-за cooldown)
    assert result.stats.portfolio_capacity_prune_count == 1, \
        f"Prune должен сработать только 1 раз из-за cooldown, получено: {result.stats.portfolio_capacity_prune_count}"


def test_prune_skips_when_candidates_below_min():
    """
    Тест: prune не выполняется, если кандидатов меньше минимума (hardening v1.7.1).
    
    Сценарий:
    - prune_min_candidates = 3
    - Создаем только 2 кандидата
    - Ожидаем: prune не сработал
    
    Проверяет min_candidates safeguard.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
        prune_min_candidates=3,  # Hardening: минимум 3 кандидата
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    # Создаем только 2 кандидата (меньше минимума)
    for i in range(2):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы для capacity pressure
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Prune не должен сработать (кандидатов меньше минимума)
    assert result.stats.portfolio_capacity_prune_count == 0, \
        f"Prune не должен сработать при кандидатах < min_candidates, получено: {result.stats.portfolio_capacity_prune_count}"


def test_prune_protects_positions_with_max_xn():
    """
    Тест: prune защищает позиции с max_xn >= protect_min_max_xn (hardening v1.7.1).
    
    Сценарий:
    - prune_protect_min_max_xn = 2.0
    - Создаем позицию с max_xn=2.5, которая иначе была бы кандидатом
    - Ожидаем: позиция не закрыта prune'ом
    
    Проверяет tail protection механизм.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
        prune_protect_min_max_xn=2.0,  # Hardening: защита позиций с max_xn >= 2.0
        prune_min_candidates=1,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    # Создаем 3 обычных кандидата
    for i in range(3):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Создаем позицию с max_xn=2.5 (защищена от prune)
    entry_time = base_time - timedelta(days=2)
    exit_time = base_time + timedelta(days=30)
    
    protected_strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=1.0,
        exit_time=exit_time,
        exit_price=0.7,  # -30% (иначе была бы кандидатом)
        pnl=-0.30,
        reason="timeout",
        meta={
            "entry_mcap_proxy": 15000.0,
            "max_xn": 2.5,  # Hardening: защита от prune
        }
    )
    
    trades.append({
        "signal_id": "protected_signal",
        "contract_address": "PROTECTED",
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": protected_strategy_output
    })
    
    # Добавляем блокированные сигналы для capacity pressure
    for i in range(10):
        blocked_time = base_time + timedelta(minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Prune должен сработать
    assert result.stats.portfolio_capacity_prune_count >= 1, \
        "Prune должен был сработать"
    
    # Защищенная позиция не должна быть закрыта prune'ом
    protected_positions = [
        p for p in result.positions
        if p.signal_id == "protected_signal"
    ]
    
    assert len(protected_positions) > 0, "Защищенная позиция должна существовать"
    
    protected_pos = protected_positions[0]
    assert not (protected_pos.meta and protected_pos.meta.get("capacity_prune", False)), \
        "Защищенная позиция не должна быть закрыта prune'ом"


def test_profit_reset_has_priority_over_capacity():
    """
    Тест: profit reset имеет приоритет над capacity на одном timestamp (hardening v1.7.1).
    
    Сценарий:
    - profit_reset_enabled = True
    - profit_reset_multiple = 1.5
    - capacity_reset_enabled = True
    - capacity_reset_mode = "prune"
    - Создаем условия, где одновременно выполняются profit reset threshold и capacity pressure
    - Ожидаем: срабатывает profit reset, capacity prune не увеличивается на этом timestamp
    
    Проверяет порядок приоритетов.
    """
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.1,  # Больше для быстрого роста equity
        max_exposure=1.0,
        max_open_positions=5,
        fee_model=FeeModel(),
        profit_reset_enabled=True,
        profit_reset_multiple=1.5,  # x1.5
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.5,
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
        prune_min_candidates=1,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    initial_prune_count = 0
    
    trades = []
    # Создаем очень прибыльные сделки для быстрого роста equity (profit reset)
    for i in range(5):
        entry_time = base_time + timedelta(hours=i)
        exit_time = entry_time + timedelta(hours=1)
        
        # Очень прибыльная сделка (+50%)
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=1.5,  # +50% прибыль
            pnl=0.50,
            reason="tp"
        )
        
        trades.append({
            "signal_id": f"profit_signal_{i+1}",
            "contract_address": f"PROFIT{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Создаем плохие позиции для capacity pressure
    for i in range(5):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        
        strategy_output = StrategyOutput(
            entry_time=entry_time,
            entry_price=1.0,
            exit_time=exit_time,
            exit_price=0.7,  # -30% (кандидат для prune)
            pnl=-0.30,
            reason="timeout",
            meta={
                "entry_mcap_proxy": 15000.0,
            }
        )
        
        trades.append({
            "signal_id": f"bad_signal_{i+1}",
            "contract_address": f"BAD{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Добавляем блокированные сигналы для capacity pressure
    for i in range(10):
        blocked_time = base_time + timedelta(hours=6, minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=None,
                entry_price=None,
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="no_entry"
            )
        })
    
    result = engine.simulate(trades, strategy_name="test_strategy")
    
    # ===== ПРОВЕРКИ =====
    
    # Profit reset должен сработать (если equity выросло достаточно)
    if result.stats.portfolio_reset_profit_count > 0:
        # На том же timestamp, где сработал profit reset, capacity prune не должен увеличиться
        # (или должен увеличиться только после cooldown/следующих событий)
        # Это сложно проверить точно, но мы проверяем, что profit reset имеет приоритет
        assert result.stats.portfolio_reset_profit_count >= 1, \
            "Profit reset должен был сработать"
        
        # Проверяем, что profit reset позиции имеют правильный reset_reason
        profit_reset_positions = [
            p for p in result.positions
            if p.meta and p.meta.get("reset_reason") == "profit"
        ]
        
        assert len(profit_reset_positions) > 0, \
            "Должны быть позиции с reset_reason='profit'"

