# backtester/domain/portfolio.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from .position import Position
from .models import StrategyOutput


@dataclass
class FeeModel:
    """
    Модель комиссий и проскальзывания.
    Все значения в долях (0.1 = 10%).
    """
    swap_fee_pct: float = 0.003       # 0.3%
    lp_fee_pct: float = 0.001         # 0.1%
    slippage_pct: float = 0.10        # 10% slippage
    network_fee_sol: float = 0.0005   # фикс. комиссия сети в SOL

    def effective_fee_pct(self, notional_sol: float) -> float:
        """
        Считает суммарные издержки как долю от notional_sol.
        Round-trip: вход + выход.
        """
        # Переменные компоненты (в процентах)
        pct_roundtrip = 2 * (self.swap_fee_pct + self.lp_fee_pct + self.slippage_pct)
        # Фиксированная сеть в процентах
        network_pct = self.network_fee_sol / notional_sol if notional_sol > 0 else 0.0
        return pct_roundtrip + network_pct


@dataclass
class PortfolioConfig:
    """
    Конфигурация портфеля.
    """
    initial_balance_sol: float = 10.0
    allocation_mode: Literal["fixed", "dynamic"] = "dynamic"
    percent_per_trade: float = 0.1
    max_exposure: float = 0.5
    max_open_positions: int = 10

    fee_model: FeeModel = field(default_factory=FeeModel)

    backtest_start: Optional[datetime] = None
    backtest_end: Optional[datetime] = None

    # Флаги для Policy-уровня
    runner_reset_enabled: bool = False
    runner_reset_multiple: float = 2.0  # XN multiplier (например, 2.0 = x2)


@dataclass
class PortfolioStats:
    final_balance_sol: float
    total_return_pct: float
    max_drawdown_pct: float
    trades_executed: int
    trades_skipped_by_risk: int
    trades_skipped_by_reset: int = 0  # Сделки, пропущенные из-за runner reset


@dataclass
class PortfolioResult:
    equity_curve: List[Dict[str, Any]]
    positions: List[Position]
    stats: PortfolioStats


class PortfolioEngine:
    """
    Портфельный движок:
    - принимает StrategyOutput'ы
    - применяет размер позиции, лимиты, комиссии
    - считает баланс и equity кривую
    """

    def __init__(self, config: PortfolioConfig) -> None:
        self.config = config

    def _position_size(self, current_balance: float) -> float:
        """
        Вычисляет размер позиции на основе текущего баланса и режима аллокации.
        """
        if self.config.allocation_mode == "fixed":
            base = self.config.initial_balance_sol
        else:
            base = current_balance
        return max(0.0, base * self.config.percent_per_trade)

    def simulate(
        self,
        all_results: List[Dict[str, Any]],
        strategy_name: str,
    ) -> PortfolioResult:
        """
        Основной метод симуляции по одной стратегии.

        all_results: список dict'ов: {
            "signal_id": ...,
            "contract_address": ...,
            "strategy": str,
            "timestamp": datetime (время сигнала),
            "result": StrategyOutput
        }
        """
        # 1. Отфильтровать по стратегии и backtest window
        trades: List[Dict[str, Any]] = []
        total_results = len(all_results)
        filtered_by_strategy = 0
        filtered_by_entry = 0
        filtered_by_window = 0
        
        for r in all_results:
            if r.get("strategy") != strategy_name:
                filtered_by_strategy += 1
                continue
            out = r.get("result")
            if not isinstance(out, StrategyOutput):
                continue
            if out.entry_time is None or out.exit_time is None:
                filtered_by_entry += 1
                continue

            # Фильтрация по окну по entry_time
            if self.config.backtest_start and out.entry_time < self.config.backtest_start:
                filtered_by_window += 1
                continue
            if self.config.backtest_end and out.entry_time > self.config.backtest_end:
                filtered_by_window += 1
                continue
            
            # Дополнительная проверка: если exit_time выходит за backtest_end, 
            # обрезаем exit_time до backtest_end (но это требует доступа к ценам, пока пропускаем)

            # NOTE: здесь можно дополнительно обрезать exit_time > backtest_end,
            # но это потребует доступа к ценам. Пока выходим, как есть.
            trades.append(r)
        
        print(f"  📊 Portfolio filtering for {strategy_name}:")
        print(f"     Total results: {total_results}")
        print(f"     Filtered by strategy: {filtered_by_strategy}")
        print(f"     Filtered by entry/exit: {filtered_by_entry}")
        print(f"     Filtered by window: {filtered_by_window}")
        print(f"     Valid trades: {len(trades)}")

        if not trades:
            # Нет сделок для симуляции
            initial = self.config.initial_balance_sol
            empty_stats = PortfolioStats(
                final_balance_sol=initial,
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                trades_executed=0,
                trades_skipped_by_risk=0,
            )
            # Используем текущее время для equity curve, если нет сделок
            from datetime import datetime, timezone
            return PortfolioResult(
                equity_curve=[{"timestamp": datetime.now(timezone.utc), "balance": initial}],
                positions=[],
                stats=empty_stats,
            )

        # 2. Сортировка по entry_time
        trades.sort(key=lambda r: (r["result"].entry_time or datetime.min))  # type: ignore

        balance = self.config.initial_balance_sol
        peak_balance = balance

        open_positions: List[Position] = []
        closed_positions: List[Position] = []
        equity_curve: List[Dict[str, Any]] = []

        # стартовая точка equity-кривой
        first_time = trades[0]["result"].entry_time  # type: ignore
        if first_time:
            equity_curve.append({"timestamp": first_time, "balance": balance})

        skipped_by_risk = 0
        skipped_by_reset = 0
        reset_until: Optional[datetime] = None  # Время, до которого игнорируем входы после reset

        for row in trades:
            out: StrategyOutput = row["result"]
            entry_time: datetime = out.entry_time  # type: ignore
            exit_time: datetime = out.exit_time    # type: ignore

            # 3. Закрываем позиции, у которых exit_time <= entry_time
            still_open: List[Position] = []
            reset_triggered = False
            
            for pos in open_positions:
                if pos.exit_time is not None and pos.exit_time <= entry_time:
                    # При закрытии: возвращаем размер позиции + прибыль/убыток
                    # balance = balance + size + size * pnl_pct = size * (1 + pnl_pct)
                    trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
                    balance += pos.size + trade_pnl_sol  # Возвращаем размер + PnL
                    pos.meta = pos.meta or {}
                    pos.meta["pnl_sol"] = trade_pnl_sol
                    
                    # Проверка runner reset: достигла ли позиция XN?
                    # Выполняем ДО установки status и добавления в closed_positions
                    if (self.config.runner_reset_enabled and 
                        pos.entry_price > 0 and pos.exit_price is not None):
                        multiplying_return = pos.exit_price / pos.entry_price
                        if multiplying_return >= self.config.runner_reset_multiple:
                            reset_triggered = True
                            reset_until = pos.exit_time
                            pos.meta["triggered_reset"] = True
                    
                    pos.status = "closed"
                    closed_positions.append(pos)

                    peak_balance = max(peak_balance, balance)
                    if pos.exit_time:
                        equity_curve.append(
                            {"timestamp": pos.exit_time, "balance": balance}
                        )
                else:
                    still_open.append(pos)
            
            # Если сработал reset, закрываем все остальные открытые позиции
            if reset_triggered:
                reset_time = reset_until
                if reset_time:
                    # Закрываем все открытые позиции на момент reset
                    for pos in still_open:
                        if pos.exit_time is None:
                            continue
                        # Закрываем позицию на момент reset (или на ее exit_time, если он раньше)
                        close_time = min(reset_time, pos.exit_time) if pos.exit_time else reset_time
                        
                        # Обновляем exit_time позиции на момент принудительного закрытия
                        pos.exit_time = close_time
                        
                        # Пересчитываем PnL для досрочного закрытия
                        # Используем текущий exit_price и exit_time позиции
                        trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
                        balance += pos.size + trade_pnl_sol
                        pos.meta = pos.meta or {}
                        pos.meta["pnl_sol"] = trade_pnl_sol
                        pos.meta["closed_by_reset"] = True
                        pos.status = "closed"
                        closed_positions.append(pos)
                        
                        peak_balance = max(peak_balance, balance)
                        equity_curve.append(
                            {"timestamp": close_time, "balance": balance}
                        )
                    still_open = []  # Все позиции закрыты
            
            open_positions = still_open

            # Проверка: игнорируем входы до следующего сигнала после reset
            if reset_until is not None and entry_time <= reset_until:
                skipped_by_reset += 1
                continue

            # 4. Проверка лимитов портфеля

            # лимит по количеству позиций
            if len(open_positions) >= self.config.max_open_positions:
                skipped_by_risk += 1
                continue

            # текущая экспозиция (учитываем, что баланс уже уменьшен на открытые позиции)
            total_open_notional = sum(p.size for p in open_positions)
            # Доступный баланс = текущий баланс (уже уменьшенный на открытые позиции)
            available_balance = balance
            total_capital = available_balance + total_open_notional
            
            # Рассчитываем максимально допустимый размер новой позиции с учетом max_exposure
            # Формула: (total_open_notional + new_size) / (total_capital + new_size) <= max_exposure
            # Решаем: new_size <= (max_exposure * total_capital - total_open_notional) / (1 - max_exposure)
            if self.config.max_exposure >= 1.0:
                # Нет ограничения на экспозицию
                max_allowed_notional = float('inf')
            else:
                numerator = self.config.max_exposure * total_capital - total_open_notional
                if numerator <= 0:
                    # Уже превышен лимит экспозиции
                    max_allowed_notional = 0.0
                else:
                    max_allowed_notional = numerator / (1.0 - self.config.max_exposure)

            # Размер позиции рассчитываем от доступного баланса
            desired_size = self._position_size(available_balance)
            
            # Проверяем, что желаемый размер не превышает лимит экспозиции
            if desired_size > max_allowed_notional:
                # Если желаемый размер превышает лимит, отклоняем сделку полностью
                skipped_by_risk += 1
                continue
            
            size = desired_size
            if size <= 0:
                skipped_by_risk += 1
                continue

            # 5. Комиссии
            raw_pnl_pct = out.pnl
            fee_pct = self.config.fee_model.effective_fee_pct(size)
            net_pnl_pct = raw_pnl_pct - fee_pct

            # 6. Вычитаем размер позиции из баланса при открытии
            balance -= size

            # 7. Создаем Position
            pos = Position(
                signal_id=row["signal_id"],
                contract_address=row["contract_address"],
                entry_time=entry_time,
                entry_price=out.entry_price or 0.0,
                size=size,
                exit_time=exit_time,
                exit_price=out.exit_price,
                pnl_pct=net_pnl_pct,
                status="open",
                meta={
                    "strategy": strategy_name,
                    "raw_pnl_pct": raw_pnl_pct,
                    "fee_pct": fee_pct,
                },
            )
            open_positions.append(pos)
            
            # Обновляем equity curve при открытии позиции
            equity_curve.append({"timestamp": entry_time, "balance": balance})

        # 8. Закрываем все оставшиеся открытые позиции
        # Сортируем позиции по exit_time для корректной обработки reset
        positions_to_close = sorted([p for p in open_positions if p.exit_time is not None], 
                                   key=lambda p: p.exit_time if p.exit_time else datetime.max)
        
        reset_triggered_final = False
        reset_time_final: Optional[datetime] = None
        
        for pos in positions_to_close:
            # Проверка runner reset: достигла ли позиция XN?
            if (self.config.runner_reset_enabled and 
                not reset_triggered_final and
                pos.entry_price > 0 and pos.exit_price is not None):
                multiplying_return = pos.exit_price / pos.entry_price
                if multiplying_return >= self.config.runner_reset_multiple:
                    reset_triggered_final = True
                    reset_time_final = pos.exit_time
                    pos.meta = pos.meta or {}
                    pos.meta["triggered_reset"] = True
                    # Все последующие позиции закрываем принудительно
                    remaining_positions = [p for p in positions_to_close if p != pos and positions_to_close.index(p) > positions_to_close.index(pos)]
                    for remaining_pos in remaining_positions:
                        remaining_pos.meta = remaining_pos.meta or {}
                        remaining_pos.meta["closed_by_reset"] = True
                        if remaining_pos.exit_time and reset_time_final:
                            remaining_pos.exit_time = min(remaining_pos.exit_time, reset_time_final)
            
            # Если позиция закрыта по reset и уже помечена, skip
            if pos.meta.get("closed_by_reset"):
                # Позиция уже помечена как closed_by_reset, продолжаем
                pass
            
            # При закрытии: возвращаем размер позиции + прибыль/убыток
            trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
            balance += pos.size + trade_pnl_sol  # Возвращаем размер + PnL
            pos.meta = pos.meta or {}
            pos.meta["pnl_sol"] = trade_pnl_sol
            
            pos.status = "closed"
            closed_positions.append(pos)

            peak_balance = max(peak_balance, balance)
            if pos.exit_time:
                equity_curve.append({"timestamp": pos.exit_time, "balance": balance})

        # 9. Сортируем equity curve по времени для корректного расчета drawdown
        equity_curve.sort(key=lambda x: x["timestamp"] if x.get("timestamp") else datetime.min)
        
        # 10. Статистика
        final_balance = balance
        total_return_pct = (final_balance - self.config.initial_balance_sol) / self.config.initial_balance_sol

        max_drawdown_pct = 0.0
        if equity_curve:
            peak = equity_curve[0]["balance"]
            max_dd = 0.0
            for point in equity_curve:
                bal = point["balance"]
                if bal > peak:
                    peak = bal
                dd = (bal - peak) / peak if peak > 0 else 0.0
                if dd < max_dd:
                    max_dd = dd
            max_drawdown_pct = max_dd

        stats = PortfolioStats(
            final_balance_sol=final_balance,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            trades_executed=len(closed_positions),
            trades_skipped_by_risk=skipped_by_risk,
            trades_skipped_by_reset=skipped_by_reset,
        )

        # Все позиции помечаем closed для консистентности
        for pos in closed_positions:
            pos.status = "closed"

        return PortfolioResult(
            equity_curve=equity_curve,
            positions=closed_positions,
            stats=stats,
        )




