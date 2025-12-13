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


@dataclass
class PortfolioStats:
    final_balance_sol: float
    total_return_pct: float
    max_drawdown_pct: float
    trades_executed: int
    trades_skipped_by_risk: int


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

        for row in trades:
            out: StrategyOutput = row["result"]
            entry_time: datetime = out.entry_time  # type: ignore
            exit_time: datetime = out.exit_time    # type: ignore

            # 3. Закрываем позиции, у которых exit_time <= entry_time
            still_open: List[Position] = []
            for pos in open_positions:
                if pos.exit_time is not None and pos.exit_time <= entry_time:
                    # При закрытии: возвращаем размер позиции + прибыль/убыток
                    # balance = balance + size + size * pnl_pct = size * (1 + pnl_pct)
                    trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
                    balance += pos.size + trade_pnl_sol  # Возвращаем размер + PnL
                    pos.meta = pos.meta or {}
                    pos.meta["pnl_sol"] = trade_pnl_sol
                    pos.status = "closed"
                    closed_positions.append(pos)

                    peak_balance = max(peak_balance, balance)
                    if pos.exit_time:
                        equity_curve.append(
                            {"timestamp": pos.exit_time, "balance": balance}
                        )
                else:
                    still_open.append(pos)
            open_positions = still_open

            # 4. Проверка лимитов портфеля

            # лимит по количеству позиций
            if len(open_positions) >= self.config.max_open_positions:
                skipped_by_risk += 1
                continue

            # текущая экспозиция (учитываем, что баланс уже уменьшен на открытые позиции)
            total_open_notional = sum(p.size for p in open_positions)
            # Доступный баланс = текущий баланс (уже уменьшенный на открытые позиции)
            available_balance = balance
            current_exposure = total_open_notional / (available_balance + total_open_notional) if (available_balance + total_open_notional) > 0 else 0.0
            
            # Максимально допустимая экспозиция от общего капитала (баланс + открытые позиции)
            total_capital = available_balance + total_open_notional
            max_allowed_notional = self.config.max_exposure * total_capital - total_open_notional

            if max_allowed_notional <= 0:
                skipped_by_risk += 1
                continue

            # Размер позиции рассчитываем от доступного баланса
            desired_size = self._position_size(available_balance)
            size = min(desired_size, max_allowed_notional)
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
        for pos in open_positions:
            if pos.exit_time is None:
                continue
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
        )

        # Все позиции помечаем closed для консистентности
        for pos in closed_positions:
            pos.status = "closed"

        return PortfolioResult(
            equity_curve=equity_curve,
            positions=closed_positions,
            stats=stats,
        )




