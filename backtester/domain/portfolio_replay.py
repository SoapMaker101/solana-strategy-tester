# backtester/domain/portfolio_replay.py
"""
PortfolioReplay - альтернативный путь исполнения портфеля на основе StrategyTradeBlueprint.

Отличается от legacy PortfolioEngine:
- Принимает blueprints вместо StrategyOutput
- Строит positions/events/executions самостоятельно
- Использует max_hold_minutes для закрытия позиций (вместо time_stop стратегии)
- Полностью независим от RunnerStrategy
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .portfolio import (
    PortfolioConfig,
    PortfolioResult,
    PortfolioStats,
    Position,
    PortfolioEvent,
)
from .portfolio_events import PortfolioEventType
# ExecutionModel lives in execution_model.py; portfolio.py holds ledger types.
from .execution_model import ExecutionModel
from .portfolio_reset import (
    PortfolioState,
    PortfolioResetContext,
    ResetReason,
    apply_portfolio_reset,
)
from .strategy_trade_blueprint import (
    StrategyTradeBlueprint,
    PartialExitBlueprint,
    FinalExitBlueprint,
)


# Type alias для market data (пока простой dict с ценами по timestamp)
# В будущем можно сделать более строгую структуру
MarketData = Dict[datetime, float]  # timestamp -> price


@dataclass
class PortfolioReplay:
    """
    Replay движок портфеля.
    
    Строит portfolio ledger (positions / events / executions) исключительно
    на основе StrategyTradeBlueprint.
    """

    @staticmethod
    def replay(
        blueprints: List[StrategyTradeBlueprint],
        portfolio_config: PortfolioConfig,
        market_data: Optional[MarketData] = None,
    ) -> PortfolioResult:
        """
        Replay blueprints в portfolio ledger.
        
        Алгоритм (строго по PIPE):
        1) Отсортировать blueprints по entry_time
        2) Для каждого blueprint:
           - проверить capacity / allocation
           - если не проходит → SKIP (без POSITION_OPENED)
        3) Если проходит:
           - создать POSITION_OPENED
           - создать EXECUTION (entry)
        4) Для каждого partial_exit:
           - создать EXECUTION
           - создать POSITION_PARTIAL_EXIT
        5) Если final_exit существует:
           - создать EXECUTION
           - создать POSITION_CLOSED
        6) Если final_exit НЕ существует:
           - позиция остается открытой
           - потенциально будет закрыта:
             - по max_hold_minutes
             - при portfolio reset
             - при forced close
        
        Args:
            blueprints: Список StrategyTradeBlueprint (будет отсортирован по entry_time)
            portfolio_config: Конфигурация портфеля
            market_data: Словарь timestamp -> price для получения цен выхода (опционально)
        
        Returns:
            PortfolioResult в том же формате, что и legacy PortfolioEngine
        """
        if market_data is None:
            market_data = {}
        
        # 1) Отсортировать blueprints по entry_time (ВАЖНО: делаем это сразу, чтобы использовать дальше)
        sorted_blueprints = sorted(blueprints, key=lambda bp: bp.entry_time)
        
        # Инициализация состояния портфеля
        state = PortfolioState(
            balance=portfolio_config.initial_balance_sol,
            peak_balance=portfolio_config.initial_balance_sol,
            open_positions=[],
            closed_positions=[],
            equity_curve=[],
        )
        # Инициализируем cycle_start_equity для profit reset
        state.cycle_start_equity = portfolio_config.initial_balance_sol
        state.equity_peak_in_cycle = portfolio_config.initial_balance_sol
        
        # Создаем marker_position для profit reset (если включен)
        marker_position: Optional[Position] = None
        if portfolio_config.resolved_profit_reset_enabled():
            # Определяем base_time для marker_position (время первого blueprint или текущее время)
            base_time = None
            if sorted_blueprints:
                base_time = sorted_blueprints[0].entry_time
            if base_time is None:
                from datetime import datetime, timezone
                base_time = datetime.now(timezone.utc)
            
            # Создаем marker_position
            from .position import Position
            marker_position = Position(
                signal_id="__profit_reset_marker__",
                contract_address="__profit_reset_marker__",
                entry_time=base_time,
                entry_price=1.0,
                size=0.0,  # Не влияет на баланс
                status="open",
                meta={
                    "marker": True,  # Исключаем из лимитов
                    "strategy": "portfolio",
                },
            )
            # Добавляем marker_position в open_positions (но он не учитывается в лимитах через meta["marker"])
            state.open_positions.append(marker_position)
        
        # Создаем ExecutionModel для расчета цен
        execution_model = ExecutionModel.from_config(portfolio_config)
        
        # Статистика
        stats = PortfolioStats(
            final_balance_sol=portfolio_config.initial_balance_sol,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            trades_executed=0,
            trades_skipped_by_risk=0,
            trades_skipped_by_reset=0,
            portfolio_reset_count=0,
            portfolio_reset_profit_count=0,
        )
        
        # Список событий портфеля
        portfolio_events: List[PortfolioEvent] = []
        
        # 2) Для каждого blueprint
        for blueprint in sorted_blueprints:
            # Проверка: no_entry blueprints пропускаем
            if blueprint.reason == "no_entry" or blueprint.entry_price_raw <= 0:
                stats.trades_skipped_by_risk += 1
                continue
            
            # Применяем все pending exits для открытых позиций до текущего времени
            # Это необходимо для правильной проверки capacity (time-aware)
            # И для обновления баланса перед проверкой profit reset
            PortfolioReplay._apply_pending_exits_until_time(
                state,
                blueprint.entry_time,
                market_data,
                execution_model,
                portfolio_events,
                portfolio_config,
            )
            
            # Проверяем max_hold_minutes для всех открытых позиций
            # (должно быть после применения exits, но перед profit reset)
            PortfolioReplay._check_max_hold_minutes_for_all(
                state,
                blueprint,
                portfolio_config,
                market_data,
                execution_model,
                portfolio_events,
            )
            
            # Проверяем profit reset ПОСЛЕ применения exits (чтобы баланс был обновлен)
            if portfolio_config.resolved_profit_reset_enabled():
                reset_triggered = PortfolioReplay._check_and_apply_profit_reset(
                    state,
                    portfolio_config,
                    blueprint.entry_time,
                    execution_model,
                    portfolio_events,
                    market_data,
                    marker_position=marker_position,
                )
                if reset_triggered:
                    # После reset все позиции закрыты, продолжаем обработку
                    pass
            
            # Проверяем capacity / allocation (теперь open_positions отражает реальное состояние на timeline)
            can_open = PortfolioReplay._can_open_position(
                state, portfolio_config, blueprint.entry_time
            )
            
            # Если не проходит → SKIP (без POSITION_OPENED)
            if not can_open:
                stats.trades_skipped_by_risk += 1
                continue
            
            # 3) Если проходит: создать POSITION_OPENED и EXECUTION (entry)
            position = PortfolioReplay._open_position(
                blueprint,
                portfolio_config,
                state,
                execution_model,
                portfolio_events,
            )
            
            if position is None:
                stats.trades_skipped_by_risk += 1
                continue
            
            state.open_positions.append(position)
            stats.trades_executed += 1
            
            # Exits будут применены event-driven образом в _apply_pending_exits_until_time
            # при обработке следующих blueprints или в конце replay
        
        # Применяем все оставшиеся pending exits для всех открытых позиций
        # (на случай, если есть позиции без последующих blueprints)
        final_time = sorted_blueprints[-1].entry_time if sorted_blueprints else datetime.min.replace(tzinfo=timezone.utc)
        PortfolioReplay._apply_pending_exits_until_time(
            state,
            final_time + timedelta(days=365),  # Будущее время для применения всех exits
            market_data,
            execution_model,
            portfolio_events,
            portfolio_config,
        )
        
        # Финализируем статистику
        stats.final_balance_sol = state.balance
        
        # Сортируем события по timestamp и ordering_rank для обеспечения монотонности
        # Согласно REPLAY_EVENT_ORDERING.md: сортировка по (timestamp, tie-breaker)
        portfolio_events = PortfolioReplay._sort_events_by_timestamp_and_type(portfolio_events)
        
        stats.portfolio_events = portfolio_events
        # Обновляем reset статистику из state
        stats.portfolio_reset_count = state.portfolio_reset_count
        stats.portfolio_reset_profit_count = state.portfolio_reset_profit_count
        stats.portfolio_reset_capacity_count = state.portfolio_reset_capacity_count
        stats.last_portfolio_reset_time = state.last_portfolio_reset_time
        
        # Формируем equity_curve (упрощенная версия)
        equity_curve = PortfolioReplay._build_equity_curve(state, portfolio_events)
        
        return PortfolioResult(  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            equity_curve=equity_curve,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            positions=state.closed_positions + state.open_positions,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
            stats=stats,  # type: ignore[reportCallIssue]  # basedpyright limitation; runtime covered by tests
        )
    
    @staticmethod
    def _sort_events_by_timestamp_and_type(events: List[PortfolioEvent]) -> List[PortfolioEvent]:
        """
        Сортирует события по timestamp и ordering_rank (tie-breaker).
        
        Порядок tie-breaker (согласно REPLAY_EVENT_ORDERING.md):
        - POSITION_OPENED -> 10
        - POSITION_PARTIAL_EXIT -> 20
        - POSITION_CLOSED -> 30
        - PORTFOLIO_RESET_TRIGGERED -> 40
        
        Args:
            events: Список событий для сортировки
            
        Returns:
            Отсортированный список событий (стабильная сортировка)
        """
        def get_ordering_rank(event: PortfolioEvent) -> int:
            """Возвращает ordering_rank для события (tie-breaker при одинаковом timestamp)."""
            event_type_ranks = {
                PortfolioEventType.POSITION_OPENED: 10,
                PortfolioEventType.POSITION_PARTIAL_EXIT: 20,
                PortfolioEventType.POSITION_CLOSED: 30,
                PortfolioEventType.PORTFOLIO_RESET_TRIGGERED: 40,
            }
            return event_type_ranks.get(event.event_type, 50)  # Неизвестные типы в конец
        
        # Сортируем по (timestamp, ordering_rank)
        # Используем стабильную сортировку для сохранения порядка событий с одинаковым timestamp и типом
        sorted_events = sorted(
            events,
            key=lambda e: (e.timestamp, get_ordering_rank(e))
        )
        
        return sorted_events
    
    @staticmethod
    def _apply_pending_exits_until_time(
        state: PortfolioState,
        current_time: datetime,
        market_data: MarketData,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
        config: PortfolioConfig,
    ) -> None:
        """
        Применяет все pending exits для открытых позиций до указанного времени.
        
        Это необходимо для правильной проверки capacity (time-aware):
        перед открытием новой позиции нужно закрыть все позиции, у которых
        exit timestamp <= текущий entry_time.
        
        Args:
            state: Состояние портфеля
            current_time: Время до которого применять exits
            market_data: Данные о ценах
            execution_model: Модель исполнения
            portfolio_events: Список событий портфеля
            config: Конфигурация портфеля
        """
        # Обрабатываем открытые позиции (создаем копию списка, т.к. он может изменяться)
        positions_to_process = list(state.open_positions)
        
        for position in positions_to_process:
            if position.status != "open":
                continue
            
            # Получаем pending exits из meta
            if not position.meta:
                continue
            
            pending_partial_exits = position.meta.get("pending_partial_exits", [])
            pending_final_exit = position.meta.get("pending_final_exit")
            original_size = position.meta.get("original_size", position.size)
            
            # Применяем partial exits, которые должны произойти до current_time
            remaining_size = position.size
            applied_partial_exits = []
            
            for partial_exit_data in pending_partial_exits:
                exit_timestamp = datetime.fromisoformat(partial_exit_data["timestamp"])
                
                if exit_timestamp > current_time:
                    continue  # Этот exit еще не наступил
                
                # Применяем partial exit
                xn = partial_exit_data["xn"]
                fraction = partial_exit_data["fraction"]
                
                # Получаем цену выхода
                exit_price_raw = PortfolioReplay._get_exit_price(
                    exit_timestamp,
                    position.entry_price,
                    xn,
                    market_data,
                )
                
                # Вычисляем размер закрываемой части
                exit_size = remaining_size * fraction
                
                # EXECUTION: применяем slippage
                exit_price_effective = execution_model.apply_exit(exit_price_raw, "ladder_tp")
                
                # Вычисляем PnL для этой части
                pnl_pct = (exit_price_effective / position.entry_price - 1.0) * 100.0
                pnl_sol = exit_size * (exit_price_effective / position.entry_price - 1.0)
                
                # Вычисляем комиссии для exit
                notional_returned = exit_size + pnl_sol
                fees_sol = PortfolioReplay._calc_fees_sol_exit(execution_model, notional_returned)
                
                # Обновляем баланс
                notional_after_fees = execution_model.apply_fees(notional_returned)
                state.balance += notional_after_fees
                state.balance -= execution_model.network_fee()
                
                # Уменьшаем размер позиции
                remaining_size -= exit_size
                
                # Создаем POSITION_PARTIAL_EXIT event
                event = PortfolioEvent.create_position_partial_exit(
                    timestamp=exit_timestamp,
                    strategy=position.meta.get("strategy", "unknown"),
                    signal_id=position.signal_id,
                    contract_address=position.contract_address,
                    position_id=position.position_id,
                    level_xn=xn,
                    fraction=fraction,
                    raw_price=exit_price_raw,
                    exec_price=exit_price_effective,
                    pnl_pct_contrib=pnl_pct,
                    pnl_sol_contrib=pnl_sol,
                    meta={
                        "execution_type": "partial_exit",
                        "raw_price": exit_price_raw,
                        "exec_price": exit_price_effective,
                        "qty_delta": -exit_size,
                        "fees_sol": fees_sol,
                        "pnl_sol_delta": pnl_sol,
                    },
                )
                portfolio_events.append(event)
                
                applied_partial_exits.append(partial_exit_data)
            
            # Обновляем размер позиции и список pending partial exits
            position.size = remaining_size
            position.meta["pending_partial_exits"] = [
                pe for pe in pending_partial_exits if pe not in applied_partial_exits
            ]
            
            # Применяем final exit, если он должен произойти до current_time
            if pending_final_exit:
                final_exit_timestamp = datetime.fromisoformat(pending_final_exit["timestamp"])
                
                if final_exit_timestamp <= current_time:
                    # Применяем final exit
                    reason = pending_final_exit.get("reason", "all_levels_hit")
                    
                    # Получаем цену выхода (используем последний известный xn или entry_price)
                    # Для final exit используем realized_multiple из meta или вычисляем
                    max_xn = position.meta.get("max_xn_reached", 1.0)
                    exit_price_raw = PortfolioReplay._get_exit_price(
                        final_exit_timestamp,
                        position.entry_price,
                        max_xn,
                        market_data,
                    )
                    
                    # EXECUTION: применяем slippage
                    exit_price_effective = execution_model.apply_exit(exit_price_raw, reason)
                    
                    # Вычисляем PnL
                    pnl_pct = (exit_price_effective / position.entry_price - 1.0) * 100.0
                    pnl_sol = remaining_size * (exit_price_effective / position.entry_price - 1.0)
                    
                    # Вычисляем комиссии
                    notional_returned = remaining_size + pnl_sol
                    fees_sol = PortfolioReplay._calc_fees_sol_exit(execution_model, notional_returned)
                    
                    # Обновляем баланс
                    notional_after_fees = execution_model.apply_fees(notional_returned)
                    state.balance += notional_after_fees
                    state.balance -= execution_model.network_fee()
                    
                    # Обновляем позицию
                    position.exit_time = final_exit_timestamp
                    position.exit_price = exit_price_raw
                    position.pnl_pct = pnl_pct
                    position.status = "closed"
                    if position.meta:
                        position.meta["exec_exit_price"] = exit_price_effective
                        position.meta["pnl_sol"] = pnl_sol
                        position.meta["fees_total_sol"] = fees_sol
                        position.meta.pop("pending_final_exit", None)  # Удаляем pending final exit
                    
                    # Создаем POSITION_CLOSED event
                    event = PortfolioEvent.create_position_closed(
                        timestamp=final_exit_timestamp,
                        strategy=position.meta.get("strategy", "unknown") if position.meta else "unknown",
                        signal_id=position.signal_id,
                        contract_address=position.contract_address,
                        position_id=position.position_id,
                        reason=reason,
                        raw_price=exit_price_raw,
                        exec_price=exit_price_effective,
                        pnl_pct=pnl_pct,
                        pnl_sol=pnl_sol,
                        meta={
                            "execution_type": "final_exit",
                            "raw_price": exit_price_raw,
                            "exec_price": exit_price_effective,
                            "qty_delta": -remaining_size,
                            "fees_sol": fees_sol,
                            "pnl_sol_delta": pnl_sol,
                        },
                    )
                    portfolio_events.append(event)
                    
                    # Переносим позицию из open в closed
                    if position in state.open_positions:
                        state.open_positions.remove(position)
                        state.closed_positions.append(position)
    
    @staticmethod
    def _can_open_position(
        state: PortfolioState,
        config: PortfolioConfig,
        current_time: datetime,
    ) -> bool:
        """
        Проверяет, можно ли открыть новую позицию (capacity / allocation).
        
        Returns:
            True если можно открыть, False иначе
        """
        # Проверка max_open_positions
        if config.max_open_positions > 0:
            if len(state.open_positions) >= config.max_open_positions:
                return False
        
        # Проверка max_exposure (TODO: реализовать полную логику)
        # Пока упрощенная проверка баланса
        if config.allocation_mode == "fixed":
            required_size = config.initial_balance_sol * config.percent_per_trade
        else:  # dynamic
            required_size = state.balance * config.percent_per_trade
        
        if required_size > state.balance:
            return False
        
        return True
    
    @staticmethod
    def _calc_fees_sol_entry(execution_model: ExecutionModel) -> float:
        """
        Вычисляет комиссии для entry execution.
        
        Для entry: только network fee (swap+LP fees применяются при exit).
        
        Returns:
            Комиссии в SOL (network fee для entry)
        """
        return execution_model.network_fee()
    
    @staticmethod
    def _calc_fees_sol_exit(execution_model: ExecutionModel, notional_sol: float) -> float:
        """
        Вычисляет комиссии для exit execution.
        
        Для exit: swap + LP + network fees.
        
        Args:
            execution_model: ExecutionModel для доступа к fee_model
            notional_sol: Нотионал в SOL (size + pnl_sol)
            
        Returns:
            Комиссии в SOL (swap + LP + network)
        """
        # Swap + LP fees как процент от нотионала
        swap_lp_fees = notional_sol * (execution_model.fee_model.swap_fee_pct + execution_model.fee_model.lp_fee_pct)
        # Network fee (фиксированная)
        network_fee = execution_model.network_fee()
        return swap_lp_fees + network_fee
    
    @staticmethod
    def _open_position(
        blueprint: StrategyTradeBlueprint,
        config: PortfolioConfig,
        state: PortfolioState,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
    ) -> Optional[Position]:
        """
        Открывает позицию на основе blueprint.
        
        Создает:
        - Position объект
        - POSITION_OPENED event
        - EXECUTION (entry) - фиксируется в event meta
        
        Returns:
            Position или None если не удалось открыть
        """
        # Вычисляем размер позиции
        if config.allocation_mode == "fixed":
            size_sol = config.initial_balance_sol * config.percent_per_trade
        else:  # dynamic
            size_sol = state.balance * config.percent_per_trade
        
        # Проверяем, достаточно ли баланса
        if size_sol > state.balance:
            return None
        
        # Применяем slippage к цене входа (EXECUTION: entry)
        entry_price_raw = blueprint.entry_price_raw
        entry_price_effective = execution_model.apply_entry(entry_price_raw)
        
        # Вычисляем комиссии для entry (только network fee)
        fees_sol = PortfolioReplay._calc_fees_sol_entry(execution_model)
        
        # Вычитаем размер позиции и network fee из баланса
        state.balance -= size_sol
        state.balance -= fees_sol
        
        # Создаем позицию
        # Сохраняем информацию о pending exits в meta для event-driven обработки
        pending_partial_exits = [
            {
                "timestamp": pe.timestamp.isoformat(),
                "xn": pe.xn,
                "fraction": pe.fraction,
            }
            for pe in blueprint.partial_exits
        ]
        pending_final_exit = None
        if blueprint.final_exit is not None:
            pending_final_exit = {
                "timestamp": blueprint.final_exit.timestamp.isoformat(),
                "reason": blueprint.final_exit.reason,
            }
        
        position = Position(
            signal_id=blueprint.signal_id,
            contract_address=blueprint.contract_address,
            entry_time=blueprint.entry_time,
            entry_price=entry_price_effective,
            size=size_sol,
            status="open",
            meta={
                "strategy": blueprint.strategy_id,
                "entry_price_raw": entry_price_raw,
                "entry_mcap_proxy": blueprint.entry_mcap_proxy,
                "max_xn_reached": blueprint.max_xn_reached,
                "exec_entry_price": entry_price_effective,  # Для reset логики
                "pending_partial_exits": pending_partial_exits,  # Для event-driven обработки
                "pending_final_exit": pending_final_exit,  # Для event-driven обработки
                "original_size": size_sol,  # Для расчета fraction
            },
        )
        
        # Создаем POSITION_OPENED event с execution данными в meta
        event = PortfolioEvent.create_position_opened(
            timestamp=blueprint.entry_time,
            strategy=blueprint.strategy_id,
            signal_id=blueprint.signal_id,
            contract_address=blueprint.contract_address,
            position_id=position.position_id,
            meta={
                "execution_type": "entry",
                "raw_price": entry_price_raw,
                "exec_price": entry_price_effective,
                "qty_delta": size_sol,
                "fees_sol": fees_sol,
                "pnl_sol_delta": 0.0,
            },
        )
        portfolio_events.append(event)
        
        return position
    
    @staticmethod
    def _process_partial_exits(
        position: Position,
        blueprint: StrategyTradeBlueprint,
        market_data: MarketData,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
        state: PortfolioState,
    ) -> None:
        """
        Обрабатывает partial exits из blueprint.
        
        Для каждого partial_exit:
        - создает EXECUTION (partial exit)
        - создает POSITION_PARTIAL_EXIT event
        """
        remaining_size = position.size
        
        for partial_exit in blueprint.partial_exits:
            # Получаем цену выхода из market_data или вычисляем из xn
            exit_price_raw = PortfolioReplay._get_exit_price(
                partial_exit.timestamp,
                position.entry_price,
                partial_exit.xn,
                market_data,
            )
            
            # Вычисляем размер закрываемой части
            exit_size = remaining_size * partial_exit.fraction
            
            # EXECUTION: применяем slippage
            exit_price_effective = execution_model.apply_exit(exit_price_raw, "ladder_tp")
            
            # Вычисляем PnL для этой части
            pnl_pct = (exit_price_effective / position.entry_price - 1.0) * 100.0
            pnl_sol = exit_size * (exit_price_effective / position.entry_price - 1.0)
            
            # Вычисляем комиссии для exit (swap + LP + network)
            notional_returned = exit_size + pnl_sol
            fees_sol = PortfolioReplay._calc_fees_sol_exit(execution_model, notional_returned)
            
            # Обновляем баланс (возвращаем нотионал после комиссий)
            notional_after_fees = execution_model.apply_fees(notional_returned)
            state.balance += notional_after_fees
            state.balance -= execution_model.network_fee()  # Network fee вычитается отдельно
            
            # Уменьшаем размер позиции
            remaining_size -= exit_size
            
            # Создаем POSITION_PARTIAL_EXIT event с execution данными в meta
            event = PortfolioEvent.create_position_partial_exit(
                timestamp=partial_exit.timestamp,
                strategy=blueprint.strategy_id,
                signal_id=blueprint.signal_id,
                contract_address=blueprint.contract_address,
                position_id=position.position_id,
                level_xn=partial_exit.xn,
                fraction=partial_exit.fraction,
                raw_price=exit_price_raw,
                exec_price=exit_price_effective,
                pnl_pct_contrib=pnl_pct,
                pnl_sol_contrib=pnl_sol,
                meta={
                    "execution_type": "partial_exit",
                    "raw_price": exit_price_raw,
                    "exec_price": exit_price_effective,
                    "qty_delta": -exit_size,
                    "fees_sol": fees_sol,
                    "pnl_sol_delta": pnl_sol,
                },
            )
            portfolio_events.append(event)
        
        # Обновляем размер позиции после partial exits
        position.size = remaining_size
    
    @staticmethod
    def _process_final_exit(
        position: Position,
        blueprint: StrategyTradeBlueprint,
        market_data: MarketData,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
        state: PortfolioState,
    ) -> None:
        """
        Обрабатывает final exit из blueprint.
        
        Создает:
        - EXECUTION (final exit)
        - POSITION_CLOSED event
        
        ВАЖНО: Если позиция уже закрыта reset'ом (closed_by_reset=True),
        не эмитим событие здесь - оно уже эмитчено в reset логике.
        """
        if blueprint.final_exit is None:
            return
        
        # ВАЖНО: Если позиция уже закрыта reset'ом, не обрабатываем её здесь
        if position.meta and position.meta.get("closed_by_reset", False):
            # Позиция закрыта reset'ом, событие уже эмитчено в reset логике
            return
        
        # Получаем цену выхода
        # Для final_exit используем последний partial_exit.xn или entry_price
        if blueprint.partial_exits:
            last_xn = blueprint.partial_exits[-1].xn
        else:
            # Если нет partial_exits, используем entry_price (закрытие в убыток)
            last_xn = 1.0
        
        exit_price_raw = PortfolioReplay._get_exit_price(
            blueprint.final_exit.timestamp,
            position.entry_price,
            last_xn,
            market_data,
        )
        
        # EXECUTION: применяем slippage
        exit_price_effective = execution_model.apply_exit(
            exit_price_raw, blueprint.final_exit.reason
        )
        
        # Вычисляем PnL
        pnl_pct = (exit_price_effective / position.entry_price - 1.0) * 100.0
        pnl_sol = position.size * (exit_price_effective / position.entry_price - 1.0)
        
        # Вычисляем комиссии для exit (swap + LP + network)
        notional_returned = position.size + pnl_sol
        fees_sol = PortfolioReplay._calc_fees_sol_exit(execution_model, notional_returned)
        
        # ВАЖНО: Если позиция уже закрыта reset'ом, не обрабатываем её здесь
        if position.meta and position.meta.get("closed_by_reset", False):
            # Позиция закрыта reset'ом, событие уже эмитчено в reset логике
            return
        
        # Обновляем баланс (возвращаем нотионал после комиссий)
        notional_after_fees = execution_model.apply_fees(notional_returned)
        state.balance += notional_after_fees
        state.balance -= execution_model.network_fee()  # Network fee вычитается отдельно
        
        # Закрываем позицию
        position.status = "closed"
        position.exit_time = blueprint.final_exit.timestamp
        position.exit_price = exit_price_effective
        position.pnl_pct = pnl_pct
        
        # Создаем POSITION_CLOSED event с execution данными в meta
        # ВАЖНО: override_reason не используется здесь, так как это нормальное закрытие по blueprint
        # override_reason используется только в reset логике для принудительного закрытия
        event = PortfolioEvent.create_position_closed(
            timestamp=blueprint.final_exit.timestamp,
            strategy=blueprint.strategy_id,
            signal_id=blueprint.signal_id,
            contract_address=blueprint.contract_address,
            position_id=position.position_id,
            reason=blueprint.final_exit.reason,  # Используем reason из blueprint (не override_reason)
            raw_price=exit_price_raw,
            exec_price=exit_price_effective,
            pnl_pct=pnl_pct,
            pnl_sol=pnl_sol,
            meta={
                "execution_type": "final_exit",
                "raw_price": exit_price_raw,
                "exec_price": exit_price_effective,
                "qty_delta": -position.size,
                "fees_sol": fees_sol,
                "pnl_sol_delta": pnl_sol,
            },
        )
        portfolio_events.append(event)
        
        # Переносим позицию из open в closed
        if position in state.open_positions:
            state.open_positions.remove(position)
            state.closed_positions.append(position)
    
    @staticmethod
    def _check_max_hold_minutes_for_all(
        state: PortfolioState,
        current_blueprint: StrategyTradeBlueprint,
        config: PortfolioConfig,
        market_data: MarketData,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
    ) -> None:
        """
        Проверяет max_hold_minutes для всех открытых позиций и закрывает при необходимости.
        
        Использует время текущего blueprint (entry_time или последнее событие) как reference point.
        """
        if config.max_hold_minutes is None:
            return
        
        # Определяем текущее время (reference point для проверки)
        # Используем entry_time текущего blueprint для проверки max_hold_minutes
        # (проверяем, прошло ли max_hold_minutes с момента открытия позиции до момента, когда приходит новый blueprint)
        current_time = current_blueprint.entry_time
        
        # Проверяем все открытые позиции
        positions_to_close = []
        for position in list(state.open_positions):
            if position.status != "open":
                continue
            
            # Вычисляем время закрытия по max_hold_minutes
            max_hold_time = position.entry_time + timedelta(minutes=config.max_hold_minutes)
            
            # Если прошло max_hold_minutes - закрываем позицию
            if current_time >= max_hold_time:
                positions_to_close.append((position, max_hold_time))
        
        # Закрываем позиции
        for position, close_time in positions_to_close:
            PortfolioReplay._close_position_by_max_hold(
                position,
                close_time,
                market_data,
                execution_model,
                portfolio_events,
                state,
            )
    
    @staticmethod
    def _close_position_by_max_hold(
        position: Position,
        close_time: datetime,
        market_data: MarketData,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
        state: PortfolioState,
    ) -> None:
        """
        Закрывает позицию по max_hold_minutes.
        
        Создает:
        - forced EXECUTION
        - POSITION_CLOSED event с reason="max_hold_minutes"
        """
        # Получаем цену закрытия
        # Используем последний известный xn или entry_price (закрытие по текущей цене)
        # Для max_hold_minutes используем entry_price * 1.0 (закрытие без прибыли/убытка)
        # или берем цену из market_data если доступна
        if close_time in market_data:
            exit_price_raw = market_data[close_time]
        else:
            # Если нет market_data, используем entry_price (закрытие по цене входа)
            exit_price_raw = position.entry_price
        
        # EXECUTION: применяем slippage (forced close)
        exit_price_effective = execution_model.apply_exit(exit_price_raw, "manual_close")
        
        # Вычисляем PnL
        pnl_pct = (exit_price_effective / position.entry_price - 1.0) * 100.0
        pnl_sol = position.size * (exit_price_effective / position.entry_price - 1.0)
        
        # Вычисляем комиссии для exit (swap + LP + network)
        notional_returned = position.size + pnl_sol
        fees_sol = PortfolioReplay._calc_fees_sol_exit(execution_model, notional_returned)
        
        # Обновляем баланс (возвращаем нотионал после комиссий)
        notional_after_fees = execution_model.apply_fees(notional_returned)
        state.balance += notional_after_fees
        state.balance -= execution_model.network_fee()  # Network fee вычитается отдельно
        
        # Закрываем позицию
        position.status = "closed"
        position.exit_time = close_time
        position.exit_price = exit_price_raw  # Используем raw_price для позиции
        position.pnl_pct = pnl_pct
        if position.meta:
            position.meta["exec_exit_price"] = exit_price_effective  # Effective price в meta
            position.meta["pnl_sol"] = pnl_sol
            position.meta["fees_total_sol"] = fees_sol
        
        # Получаем strategy_id из meta
        strategy_id = position.meta.get("strategy", "unknown") if position.meta else "unknown"
        
        # Создаем POSITION_CLOSED event с execution данными в meta
        event = PortfolioEvent.create_position_closed(
            timestamp=close_time,
            strategy=strategy_id,
            signal_id=position.signal_id,
            contract_address=position.contract_address,
            position_id=position.position_id,
            reason="max_hold_minutes",
            raw_price=exit_price_raw,
            exec_price=exit_price_effective,
            pnl_pct=pnl_pct,
            pnl_sol=pnl_sol,
            meta={
                "execution_type": "forced_close",
                "raw_price": exit_price_raw,
                "exec_price": exit_price_effective,
                "qty_delta": -position.size,
                "fees_sol": fees_sol,
                "pnl_sol_delta": pnl_sol,
                "forced_reason": "max_hold_minutes",
            },
        )
        portfolio_events.append(event)
        
        # Переносим позицию из open в closed
        if position in state.open_positions:
            state.open_positions.remove(position)
            state.closed_positions.append(position)
    
    @staticmethod
    def _check_and_apply_profit_reset(
        state: PortfolioState,
        config: PortfolioConfig,
        current_time: datetime,
        execution_model: ExecutionModel,
        portfolio_events: List[PortfolioEvent],
        market_data: MarketData,
        marker_position: Optional[Position] = None,
    ) -> bool:
        """
        Проверяет и применяет profit reset.
        
        При срабатывании reset:
        1) emit PORTFOLIO_RESET_TRIGGERED
        2) закрыть ВСЕ открытые позиции (EXECUTION + POSITION_CLOSED)
        3) сохранить корректную цепочку событий
        
        Returns:
            True если reset был применен
        """
        if not config.resolved_profit_reset_enabled():
            return False
        
        # Вычисляем equity (баланс + текущая стоимость открытых позиций)
        # Для упрощения: equity = balance + сумма size открытых позиций
        # (реальная стоимость позиций может отличаться, но для reset threshold это достаточно)
        equity = state.balance + sum(p.size for p in state.open_positions)
        
        # Обновляем equity_peak_in_cycle
        if equity > state.equity_peak_in_cycle:
            state.equity_peak_in_cycle = equity
        
        # Проверяем условие profit reset: equity >= cycle_start_equity * profit_reset_multiple
        threshold = state.cycle_start_equity * config.resolved_profit_reset_multiple()
        if equity < threshold:
            return False
        
        # ВАЖНО: Определяем reset_time как единый источник истины
        # Это timestamp, который будет использоваться для всех событий reset
        reset_time = current_time
        
        # Собираем реальные открытые позиции (исключаем marker)
        real_open_positions = [
            p for p in state.open_positions 
            if p.status == "open" and not (p.meta and p.meta.get("marker", False))
        ]
        
        # Используем marker_position, переданный как параметр, или находим его в state
        reset_marker_position = marker_position
        if reset_marker_position is None:
            # Ищем marker_position в state.open_positions
            for p in state.open_positions:
                if p.meta and p.meta.get("marker", False):
                    reset_marker_position = p
                    break
        
        # Если marker_position не найден, создаем временный
        if reset_marker_position is None:
            from .position import Position
            reset_marker_position = Position(
                signal_id="__profit_reset_marker__",
                contract_address="__profit_reset_marker__",
                entry_time=reset_time,
                entry_price=1.0,
                size=0.0,
                status="open",
                meta={"marker": True, "strategy": "portfolio"},
            )
            state.open_positions.append(reset_marker_position)
        
        # ВАЖНО: Если нет реальных открытых позиций, закрываем marker_position
        if len(real_open_positions) == 0:
            # Закрываем только marker_position
            positions_to_force_close = []
            all_positions_to_close = [reset_marker_position]
        else:
            # Закрываем все реальные позиции + marker_position
            positions_to_force_close = real_open_positions
            all_positions_to_close = [reset_marker_position] + positions_to_force_close
        
        # Создаем контекст для reset
        reset_context = PortfolioResetContext(
            reset_time=reset_time,
            reason=ResetReason.PROFIT_RESET,
            marker_position=reset_marker_position,
            positions_to_force_close=positions_to_force_close,
        )
        
        # Применяем reset (закрывает позиции из positions_to_force_close и обновляет state)
        # marker_position закрывается отдельно (она не в positions_to_force_close)
        apply_portfolio_reset(reset_context, state, execution_model)
        
        # Закрываем marker_position отдельно, если она реальная позиция
        marker_was_closed_here = False
        if state.open_positions and reset_marker_position in state.open_positions:
            # Принудительно закрываем marker_position
            from .portfolio_reset import get_mark_price_for_position
            raw_exit_price = get_mark_price_for_position(reset_marker_position, reset_time)
            effective_exit_price = execution_model.apply_exit(raw_exit_price, "manual_close")
            exec_entry_price = reset_marker_position.meta.get("exec_entry_price", reset_marker_position.entry_price)
            exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price if exec_entry_price > 0 else 0.0
            exit_pnl_sol = reset_marker_position.size * exit_pnl_pct
            notional_returned = reset_marker_position.size + exit_pnl_sol
            notional_after_fees = execution_model.apply_fees(notional_returned)
            fees_total = notional_returned - notional_after_fees
            network_fee_exit = execution_model.network_fee()
            state.balance += notional_after_fees
            state.balance -= network_fee_exit
            reset_marker_position.size = 0.0
            reset_marker_position.status = "closed"
            reset_marker_position.exit_time = reset_time
            reset_marker_position.exit_price = effective_exit_price
            reset_marker_position.pnl_pct = exit_pnl_pct
            m = reset_marker_position.meta
            m["pnl_sol"] = exit_pnl_sol
            m["fees_total_sol"] = fees_total
            m["network_fee_sol"] = m.get("network_fee_sol", 0.0) + network_fee_exit
            m["closed_by_reset"] = True
            m["triggered_portfolio_reset"] = True
            state.open_positions.remove(reset_marker_position)
            if reset_marker_position not in state.closed_positions:
                state.closed_positions.append(reset_marker_position)
            marker_was_closed_here = True
        
        # ВАЖНО: Создаем POSITION_CLOSED events для всех закрытых позиций ПЕРЕД PORTFOLIO_RESET_TRIGGERED
        # (apply_portfolio_reset закрывает позиции, но не создает PortfolioEvent)
        # Используем все позиции, которые должны быть закрыты (включая marker, если он реальная позиция)
        real_closed_positions = all_positions_to_close
        # ВАЖНО: Если marker был закрыт здесь, добавляем его в список для эмиссии события
        if marker_was_closed_here and reset_marker_position not in real_closed_positions:
            real_closed_positions.append(reset_marker_position)
        
        # 1) Эмитим POSITION_CLOSED для каждой закрытой позиции (N событий) - ПЕРВЫМИ
        # ЖЁСТКИЙ КОНТРАКТ: reason="profit_reset", timestamp=reset_time (не reset_time + delta), position_id обязателен
        for position in real_closed_positions:
            # apply_portfolio_reset уже установил exit_price, pnl_pct, pnl_sol в position и meta
            # Получаем данные из позиции (apply_portfolio_reset уже установил)
            exit_price_raw = position.exit_price if position.exit_price is not None else position.entry_price
            exec_exit_price = position.meta.get("exec_exit_price", exit_price_raw) if position.meta else exit_price_raw
            
            # PnL уже вычислен и установлен в position через apply_portfolio_reset
            pnl_pct = position.pnl_pct if position.pnl_pct is not None else 0.0
            pnl_sol = position.meta.get("pnl_sol", 0.0) if position.meta else 0.0
            
            # Получаем fees из meta (apply_portfolio_reset установил fees_total_sol = swap+LP fees)
            fees_total_sol = position.meta.get("fees_total_sol", 0.0) if position.meta else 0.0
            # network_fee для exit (фиксированное значение)
            network_fee_exit = execution_model.network_fee()
            # fees_sol = swap+LP fees + network fee для exit
            fees_sol = fees_total_sol + network_fee_exit
            
            # Получаем strategy_id из meta
            strategy_id = position.meta.get("strategy", "unknown") if position.meta else "unknown"
            
            # Создаем POSITION_CLOSED event с execution данными в meta
            # ЖЁСТКИЙ КОНТРАКТ: timestamp строго reset_time (не reset_time + delta), reason строго "profit_reset"
            event = PortfolioEvent.create_position_closed(
                timestamp=reset_time,  # ВАЖНО: строго reset_time, не reset_time + delta
                strategy=strategy_id,
                signal_id=position.signal_id,
                contract_address=position.contract_address,
                position_id=position.position_id,  # Обязателен
                reason="profit_reset",  # Строго "profit_reset" (не нормализуется)
                raw_price=exit_price_raw,
                exec_price=exec_exit_price,
                pnl_pct=pnl_pct,
                pnl_sol=pnl_sol,
                meta={
                    "execution_type": "forced_close",
                    "raw_price": exit_price_raw,
                    "exec_price": exec_exit_price,
                    "qty_delta": -position.size,
                    "fees_sol": fees_sol,
                    "pnl_sol_delta": pnl_sol,
                    "forced_reason": "profit_reset",
                    "closed_by_reset": True,
                },
            )
            portfolio_events.append(event)
        
        # 2) Эмитим PORTFOLIO_RESET_TRIGGERED event ПОСЛЕ всех POSITION_CLOSED
        # ЖЁСТКИЙ КОНТРАКТ: timestamp=reset_time, reason="profit_reset"
        reset_event = PortfolioEvent.create_portfolio_reset_triggered(
            timestamp=reset_time,  # ВАЖНО: строго reset_time, не reset_time + delta
            reason="profit_reset",  # Строго "profit_reset"
            closed_positions_count=len(real_closed_positions),
            position_id=reset_marker_position.position_id,  # Marker position для audit traceability
            signal_id=reset_marker_position.signal_id,
            contract_address=reset_marker_position.contract_address,
            strategy=reset_marker_position.meta.get("strategy", "unknown") if reset_marker_position.meta else "unknown",
        )
        portfolio_events.append(reset_event)
        
        return True
    
    @staticmethod
    def _get_exit_price(
        timestamp: datetime,
        entry_price: float,
        xn: float,
        market_data: MarketData,
    ) -> float:
        """
        Получает цену выхода из market_data или вычисляет из xn.
        
        Приоритет:
        1. market_data[timestamp] (если есть)
        2. entry_price * xn (вычисляем из множителя)
        """
        if timestamp in market_data:
            return market_data[timestamp]
        return entry_price * xn
    
    @staticmethod
    def _build_equity_curve(
        state: PortfolioState,
        portfolio_events: List[PortfolioEvent],
    ) -> List[Dict[str, Any]]:
        """
        Строит equity curve на основе событий.
        
        Упрощенная версия - возвращает пустой список.
        Полная реализация будет в следующих этапах.
        """
        return []
