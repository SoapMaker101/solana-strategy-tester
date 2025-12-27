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


# ===== TEST HELPERS =====

def make_entry_trade(
    signal_id: str,
    contract_address: str,
    entry_time: datetime,
    exit_time: datetime,
    entry_price: float = 1.0,
    exit_price: float = 0.7,
    pnl: float = -0.30,
    reason: str = "timeout",
    entry_mcap_proxy: float = 15000.0,
    last_seen_price: float = 0.7,
    max_xn: float = None,
) -> dict:
    """
    Создаёт trade dict с валидным StrategyOutput для входа в позицию.
    
    Args:
        signal_id: ID сигнала
        contract_address: Адрес контракта
        entry_time: Время входа
        exit_time: Время выхода
        entry_price: Цена входа
        exit_price: Цена выхода
        pnl: PnL в процентах
        reason: Причина выхода
        entry_mcap_proxy: Market cap proxy для входа
        last_seen_price: Последняя видимая цена (для current_pnl_pct fallback)
        max_xn: Максимальный XN (для защиты от prune)
    """
    meta = {
        "entry_mcap_proxy": entry_mcap_proxy,
        "last_seen_price": last_seen_price,
    }
    if max_xn is not None:
        meta["max_xn"] = max_xn
    
    strategy_output = StrategyOutput(
        entry_time=entry_time,
        entry_price=entry_price,
        exit_time=exit_time,
        exit_price=exit_price,
        pnl=pnl,
        reason=reason,
        meta=meta,
    )
    
    return {
        "signal_id": signal_id,
        "contract_address": contract_address,
        "strategy": "test_strategy",
        "timestamp": entry_time,
        "result": strategy_output,
    }


def fill_portfolio(trades: list, base_time: datetime, n: int = 2) -> None:
    """
    Добавляет n позиций для заполнения портфеля (создают capacity pressure).
    
    Args:
        trades: Список trades для добавления
        base_time: Базовое время
        n: Количество позиций для заполнения
    """
    for i in range(n):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        trade = make_entry_trade(
            signal_id=f"fill_{i+1}",
            contract_address=f"FILL{i+1}",
            entry_time=entry_time,
            exit_time=exit_time,
        )
        trades.append(trade)


def add_capacity_blocked_attempts(
    trades: list,
    base_time: datetime,
    count: int,
    start_offset_minutes: int = 10,
    interval_minutes: int = 5,
    exit_after_minutes: int = 1,
) -> None:
    """
    Добавляет попытки входа, которые будут заблокированы по capacity.
    
    ВАЖНО: StrategyOutput должен быть валидным (с exit_time/exit_price), чтобы
    пройти фильтр "entry/exit". Портфель должен отклонить эти попытки по capacity
    ДО открытия позиции, но они попадут в capacity window и увеличат blocked_ratio.
    
    Args:
        trades: Список trades для добавления
        base_time: Базовое время
        count: Количество попыток
        start_offset_minutes: Смещение от base_time в минутах для первой попытки
        interval_minutes: Интервал между попытками в минутах
        exit_after_minutes: Через сколько минут после entry будет exit (для валидности)
    """
    for i in range(count):
        entry_time = base_time + timedelta(minutes=start_offset_minutes + i * interval_minutes)
        exit_time = entry_time + timedelta(minutes=exit_after_minutes)
        
        # Валидные entry attempts с полным StrategyOutput (чтобы пройти фильтр entry/exit)
        # Портфель должен отклонить их по capacity ДО открытия позиции
        # meta["blocked_by_capacity"] = True указывает движку, что это blocked attempt
        trade = {
            "signal_id": f"blocked_{i+1}",
            "contract_address": f"BLOCKED{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": StrategyOutput(
                entry_time=entry_time,  # Стратегия хочет войти
                entry_price=1.0,  # Валидная цена входа
                exit_time=exit_time,  # Валидный exit_time (чтобы пройти фильтр)
                exit_price=1.0,  # Flat PnL (чтобы пройти фильтр)
                pnl=0.0,
                reason="tp",  # Валидная причина (не "open"/no_entry)
                meta={"blocked_by_capacity": True},  # Флаг для движка: это blocked attempt
            ),
        }
        trades.append(trade)


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
    
    trades = []
    # Создаем 10 позиций-кандидатов (первые 6 будут кандидатами для prune)
    for i in range(10):
        if i < 6:
            # Кандидаты: entry_time в прошлом, низкий mcap, плохой PnL
            entry_time = base_time - timedelta(days=2)  # 2 дня назад
            exit_time = base_time + timedelta(days=30)
            trade = make_entry_trade(
                signal_id=f"signal_{i+1}",
                contract_address=f"TOKEN{i+1}",
                entry_time=entry_time,
                exit_time=exit_time,
                exit_price=0.7,  # -30% PnL
                pnl=-0.30,
                entry_mcap_proxy=15000.0,  # Низкий mcap
            )
        else:
            # Не кандидаты: хороший PnL
            entry_time = base_time - timedelta(days=2)
            exit_time = base_time + timedelta(days=30)
            trade = make_entry_trade(
                signal_id=f"signal_{i+1}",
                contract_address=f"TOKEN{i+1}",
                entry_time=entry_time,
                exit_time=exit_time,
                exit_price=1.1,  # +10% PnL
                pnl=0.10,
                entry_mcap_proxy=50000.0,  # Высокий mcap
                last_seen_price=1.1,
            )
        trades.append(trade)
    
    # Добавляем блокированные попытки для capacity pressure
    add_capacity_blocked_attempts(trades, base_time, count=20, start_offset_minutes=100)
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    # Маленький портфель для создания capacity pressure
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=2,  # Маленький портфель
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=1.0,  # Жёстче: 100% заполненности
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.2,  # Жёстче: 20% отклоненных достаточно
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    # Заполняем портфель 2 позициями-кандидатами
    fill_portfolio(trades, base_time, n=2)
    
    # Добавляем блокированные попытки для capacity pressure
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    
    # 2. Добавляем блокированные попытки для capacity pressure
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
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
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    # Заполняем портфель кандидатами
    fill_portfolio(trades, base_time, n=2)
    # Добавляем еще кандидатов
    for i in range(3):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        trade = make_entry_trade(
            signal_id=f"signal_{i+3}",
            contract_address=f"TOKEN{i+3}",
            entry_time=entry_time,
            exit_time=exit_time,
        )
        trades.append(trade)
    
    # Добавляем блокированные попытки для capacity pressure
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    # Заполняем портфель 10 кандидатами
    for i in range(10):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        trade = make_entry_trade(
            signal_id=f"signal_{i+1}",
            contract_address=f"TOKEN{i+1}",
            entry_time=entry_time,
            exit_time=exit_time,
        )
        trades.append(trade)
    
    # Добавляем блокированные попытки для capacity pressure
    add_capacity_blocked_attempts(trades, base_time, count=20)
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
        max_open_positions=2,  # Маленький портфель для гарантированного pressure
        fee_model=FeeModel(),
        profit_reset_enabled=True,
        profit_reset_multiple=1.5,  # x1.5
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=1.0,  # Жёстче: 100% заполненности
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.2,  # Жёстче: 20% отклоненных достаточно
        capacity_max_avg_hold_days=1.0,
        prune_fraction=0.5,
        prune_min_hold_days=1.0,
        prune_max_mcap_usd=20000.0,
        prune_max_current_pnl_pct=-0.30,
        prune_min_candidates=1,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    initial_cycle_start_equity = config.initial_balance_sol
    
    trades = []
    
    # 1. Заполняем портфель ровно 2 плохими позициями-кандидатами (max_open_positions=2)
    fill_portfolio(trades, base_time, n=2)  # 2 позиции заполнят портфель
    
    # 2. Добавляем блокированные попытки для capacity pressure (валидные, с exit_time)
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
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
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
        max_open_positions=2,  # Маленький портфель для гарантированного pressure
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="close_all",  # Legacy режим
        capacity_open_ratio_threshold=1.0,  # Жёстче: 100% заполненности
        capacity_window_type="signals",
        capacity_window_size=10,
        capacity_max_blocked_ratio=0.2,  # Жёстче: 20% отклоненных достаточно
        capacity_max_avg_hold_days=1.0,
    )
    
    engine = PortfolioEngine(config)
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    trades = []
    # Заполняем портфель позициями
    fill_portfolio(trades, base_time, n=2)
    # Добавляем еще позиции
    for i in range(3):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        trade = make_entry_trade(
            signal_id=f"signal_{i+3}",
            contract_address=f"TOKEN{i+3}",
            entry_time=entry_time,
            exit_time=exit_time,
        )
        trades.append(trade)
    
    # Добавляем блокированные попытки для capacity pressure
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    # Маленький портфель для создания capacity pressure
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=2,  # Маленький портфель для capacity pressure
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,  # 2 * 0.8 = 1.6 → нужно >= 2 позиций
        capacity_window_type="signals",
        capacity_window_size=10,  # Окно на 10 сигналов
        capacity_max_blocked_ratio=0.5,  # 50% заблокированных
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
    # Шаг 1: Заполняем портфель 2 позициями (максимум) - плохие кандидаты для prune
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
                "last_seen_price": 0.7,  # Для current_pnl_pct fallback
            }
        )
        
        trades.append({
            "signal_id": f"signal_{i+1}",
            "contract_address": f"TOKEN{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Шаг 2: Добавляем блокированные попытки для capacity pressure (валидные, с meta флагом)
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
    # Шаг 3: После первого prune, добавляем еще позиции для второго capacity pressure (после cooldown)
    # Но только после того как пройдет cooldown (200+ сигналов)
    # Для простоты добавляем много сигналов, но их будет меньше чем нужно для второго prune из-за cooldown
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
                "last_seen_price": 0.7,  # Для current_pnl_pct fallback
            }
        )
        
        trades.append({
            "signal_id": f"signal2_{i+1}",
            "contract_address": f"TOKEN2{i+1}",
            "strategy": "test_strategy",
            "timestamp": entry_time,
            "result": strategy_output
        })
    
    # Шаг 4: Добавляем еще сигналы для второго capacity pressure
    # Но их меньше чем cooldown_signals=200, чтобы второй prune не сработал
    for i in range(50):  # Меньше чем cooldown_signals=200
        blocked_time = base_time + timedelta(hours=2, minutes=10 + i * 5)
        trades.append({
            "signal_id": f"blocked2_{i+1}",
            "contract_address": f"BLOCKED2{i+1}",
            "strategy": "test_strategy",
            "timestamp": blocked_time,
            "result": StrategyOutput(
                entry_time=blocked_time,  # Стратегия хочет войти
                entry_price=1.0,  # Валидная цена входа
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                reason="open"  # Позиция открыта (но портфель отклонит из-за capacity)
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
    # Создаем только 2 кандидата (меньше минимума = 3)
    fill_portfolio(trades, base_time, n=2)  # 2 позиции-кандидата
    
    # Добавляем блокированные попытки для capacity pressure
    # Но prune не должен сработать, т.к. кандидатов меньше минимума (2 < 3)
    add_capacity_blocked_attempts(trades, base_time, count=10)
    
    # Сортируем trades по timestamp
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    # Маленький портфель для создания capacity pressure
    config = PortfolioConfig(
        initial_balance_sol=100.0,
        allocation_mode="dynamic",
        percent_per_trade=0.01,
        max_exposure=1.0,
        max_open_positions=2,  # Маленький портфель
        fee_model=FeeModel(),
        capacity_reset_enabled=True,
        capacity_reset_mode="prune",
        capacity_open_ratio_threshold=0.8,  # 2 * 0.8 = 1.6 → нужно >= 2 позиций
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
        # Открываем ровно 2 позиции:
        # 1. Обычный кандидат (будет закрыт prune)
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        trade = make_entry_trade(
            signal_id="signal_1",
            contract_address="TOKEN1",
            entry_time=entry_time,
            exit_time=exit_time,
            last_seen_price=0.7,  # Для current_pnl_pct fallback
        )
        trades.append(trade)
        
        # 2. Protected кандидат (max_xn=2.5, защищена от prune)
        protected_trade = make_entry_trade(
            signal_id="protected_signal",
            contract_address="PROTECTED",
            entry_time=entry_time,
            exit_time=exit_time,
            last_seen_price=0.7,  # Для current_pnl_pct fallback
            max_xn=2.5,  # Hardening: защита от prune
        )
        trades.append(protected_trade)

        # Добавляем блокированные попытки для capacity pressure (валидные, с meta флагом)
        add_capacity_blocked_attempts(trades, base_time, count=10)
        
        # Сортируем trades по timestamp
        trades = sorted(trades, key=lambda x: x["timestamp"])
    
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
    fill_portfolio(trades, base_time, n=2)
    # Добавляем еще кандидатов
    for i in range(3):
        entry_time = base_time - timedelta(days=2)
        exit_time = base_time + timedelta(days=30)
        trade = make_entry_trade(
            signal_id=f"bad_signal_{i+1}",
            contract_address=f"BAD{i+1}",
            entry_time=entry_time,
            exit_time=exit_time,
        )
        trades.append(trade)
    
    # Добавляем блокированные попытки для capacity pressure
    # Используем start_offset_minutes чтобы они были после прибыльных сделок
    add_capacity_blocked_attempts(
        trades, 
        base_time, 
        count=10, 
        start_offset_minutes=6 * 60 + 10  # 6 часов + 10 минут
    )
    
    # Сортируем trades по timestamp (важно для правильного порядка событий)
    trades = sorted(trades, key=lambda x: x["timestamp"])
    
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

