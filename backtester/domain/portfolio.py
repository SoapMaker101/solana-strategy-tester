# backtester/domain/portfolio.py

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from .position import Position
from .models import StrategyOutput
from .execution_model import ExecutionProfileConfig, ExecutionModel

logger = logging.getLogger(__name__)


@dataclass
class FeeModel:
    """
    Модель комиссий и проскальзывания.
    Все значения в долях (0.1 = 10%).
    
    Поддерживает два режима:
    1. Legacy: slippage_pct применяется одинаково для всех событий
    2. Profiles: reason-based slippage через execution profiles
    """
    swap_fee_pct: float = 0.003       # 0.3%
    lp_fee_pct: float = 0.001         # 0.1%
    slippage_pct: Optional[float] = 0.10  # 10% slippage (legacy, используется если profiles=None)
    network_fee_sol: float = 0.0005   # фикс. комиссия сети в SOL
    profiles: Optional[Dict[str, ExecutionProfileConfig]] = None  # Execution profiles

    def effective_fee_pct(self, notional_sol: float) -> float:
        """
        DEPRECATED: Используется только для обратной совместимости.
        Новая логика применяет slippage к ценам через ExecutionModel.
        
        Считает суммарные издержки как долю от notional_sol.
        Round-trip: вход + выход.
        """
        # Используем slippage_pct для legacy режима
        slippage = self.slippage_pct if self.slippage_pct is not None else 0.10
        # Переменные компоненты (в процентах)
        pct_roundtrip = 2 * (self.swap_fee_pct + self.lp_fee_pct + slippage)
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
    execution_profile: str = "realistic"  # realistic | stress | custom

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
    reset_count: int = 0  # Количество срабатываний portfolio-level reset
    last_reset_time: Optional[datetime] = None  # Время последнего reset
    cycle_start_equity: float = 0.0  # Equity в начале текущего цикла
    equity_peak_in_cycle: float = 0.0  # Пик equity в текущем цикле


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
        self.execution_model = ExecutionModel.from_config(config)

    def _position_size(self, current_balance: float) -> float:
        """
        Вычисляет размер позиции на основе текущего баланса и режима аллокации.
        """
        if self.config.allocation_mode == "fixed":
            base = self.config.initial_balance_sol
        else:
            base = current_balance
        return max(0.0, base * self.config.percent_per_trade)

    def _process_runner_partial_exits(
        self,
        pos: Position,
        current_time: datetime,
        balance: float,
        equity_curve: List[Dict[str, Any]],
        closed_positions: List[Position],
    ) -> Dict[str, Any]:
        """
        Обрабатывает частичные выходы для Runner стратегии.
        
        Args:
            pos: Позиция Runner
            current_time: Текущее время (время входа новой сделки)
            balance: Текущий баланс
            equity_curve: Кривая equity для обновления
            closed_positions: Список закрытых позиций
            
        Returns:
            Dict с обновленным balance
        """
        
        # Извлекаем данные о частичных выходах из meta
        levels_hit_raw = pos.meta.get("levels_hit", {})
        fractions_exited_raw = pos.meta.get("fractions_exited", {})
        
        if not levels_hit_raw or not fractions_exited_raw:
            # Нет частичных выходов, возвращаем как есть
            return {"balance": balance}
        
        # Парсим levels_hit (ключи - строки, значения - ISO строки времени)
        levels_hit: Dict[float, datetime] = {}
        for k_str, v_str in levels_hit_raw.items():
            try:
                xn = float(k_str)
                hit_time = datetime.fromisoformat(v_str) if isinstance(v_str, str) else v_str
                levels_hit[xn] = hit_time
            except (ValueError, TypeError):
                continue
        
        # Парсим fractions_exited (ключи - строки, значения - float)
        fractions_exited: Dict[float, float] = {}
        for k_str, v in fractions_exited_raw.items():
            try:
                xn = float(k_str)
                fraction = float(v)
                fractions_exited[xn] = fraction
            except (ValueError, TypeError):
                continue
        
        # Получаем оригинальный размер позиции (если не сохранен, используем текущий)
        original_size = pos.meta.get("original_size", pos.size)
        if "original_size" not in pos.meta:
            pos.meta["original_size"] = original_size
        
        # Сортируем уровни по времени достижения
        sorted_levels = sorted(levels_hit.items(), key=lambda x: x[1])
        
        # Обрабатываем каждый уровень, который был достигнут до current_time
        for xn, hit_time in sorted_levels:
            # Проверяем, был ли этот уровень уже обработан
            processed_key = f"partial_exit_processed_{xn}"
            if pos.meta.get(processed_key, False):
                continue  # Уже обработан
            
            # Проверяем, что уровень был достигнут до current_time
            if hit_time > current_time:
                continue  # Еще не достигнут
            
            # Получаем долю для закрытия
            fraction = fractions_exited.get(xn, 0.0)
            if fraction <= 0:
                continue
            
            # Вычисляем размер частичного выхода (от оригинального размера)
            exit_size = original_size * fraction
            
            # Проверяем, что есть что закрывать
            if exit_size > pos.size:
                exit_size = pos.size  # Закрываем только то, что осталось
            
            if exit_size <= 1e-9:
                continue  # Ничего не закрываем
            
            # Вычисляем цену выхода (entry_price * xn)
            exit_price_raw = pos.entry_price * xn
            
            # Применяем slippage к цене выхода (для TP используем reason="tp")
            effective_exit_price = self.execution_model.apply_exit(exit_price_raw, "tp")
            
            # Вычисляем PnL для этой части - используем exec_entry_price из meta для правильного расчета баланса
            exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
            exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price
            exit_pnl_sol = exit_size * exit_pnl_pct
            
            # Применяем fees к возвращаемому нотионалу
            notional_returned = exit_size + exit_pnl_sol
            notional_after_fees = self.execution_model.apply_fees(notional_returned)
            fees_partial = notional_returned - notional_after_fees
            
            # Network fee для частичного выхода
            network_fee_exit = self.execution_model.network_fee()
            
            # Возвращаем капитал в баланс
            balance += notional_after_fees
            balance -= network_fee_exit
            
            # Уменьшаем размер позиции
            pos.size -= exit_size
            
            # Сохраняем информацию о частичном выходе в meta
            if "partial_exits" not in pos.meta:
                pos.meta["partial_exits"] = []
            pos.meta["partial_exits"].append({
                "xn": xn,
                "hit_time": hit_time.isoformat(),
                "exit_size": exit_size,
                "exit_price": effective_exit_price,
                "pnl_pct": exit_pnl_pct,
                "pnl_sol": exit_pnl_sol,
                "fees_sol": fees_partial,
                "network_fee_sol": network_fee_exit,
            })
            
            # Обновляем общие fees
            if "fees_total_sol" in pos.meta:
                pos.meta["fees_total_sol"] += fees_partial + network_fee_exit
            else:
                pos.meta["fees_total_sol"] = fees_partial + network_fee_exit
            
            if "network_fee_sol" in pos.meta:
                pos.meta["network_fee_sol"] += network_fee_exit
            else:
                pos.meta["network_fee_sol"] = network_fee_exit
            
            # Помечаем уровень как обработанный
            pos.meta[processed_key] = True
            
            # Обновляем equity curve
            equity_curve.append({"timestamp": hit_time, "balance": balance})
        
        # Если после обработки частичных выходов остался остаток, закрываем его по time_stop
        # Остаток закрывается только если current_time >= exit_time (time_stop наступил)
        if pos.size > 1e-9 and pos.exit_time is not None and current_time >= pos.exit_time:
            # Проверяем, не был ли остаток уже закрыт
            remainder_closed_key = "remainder_closed"
            if pos.meta.get(remainder_closed_key, False):
                # Остаток уже закрыт
                pass
            elif pos.exit_price is not None:
                # Применяем slippage для timeout - используем raw exit_price для расчета slippage
                effective_exit_price = self.execution_model.apply_exit(pos.exit_price, "timeout")
                
                # Вычисляем PnL для остатка - используем exec_entry_price из meta для правильного расчета баланса
                exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price)
                exit_pnl_pct = (effective_exit_price - exec_entry_price) / exec_entry_price
                exit_pnl_sol = pos.size * exit_pnl_pct
                
                # Применяем fees
                notional_returned = pos.size + exit_pnl_sol
                notional_after_fees = self.execution_model.apply_fees(notional_returned)
                fees_remainder = notional_returned - notional_after_fees
                network_fee_exit = self.execution_model.network_fee()
                
                # Возвращаем капитал
                balance += notional_after_fees
                balance -= network_fee_exit
                
                # Сохраняем информацию о закрытии остатка
                if "partial_exits" not in pos.meta:
                    pos.meta["partial_exits"] = []
                pos.meta["partial_exits"].append({
                    "xn": pos.exit_price / pos.entry_price if pos.entry_price > 0 else 1.0,
                    "hit_time": pos.exit_time.isoformat() if pos.exit_time else "",
                    "exit_size": pos.size,
                    "exit_price": effective_exit_price,
                    "pnl_pct": exit_pnl_pct,
                    "pnl_sol": exit_pnl_sol,
                    "fees_sol": fees_remainder,
                    "network_fee_sol": network_fee_exit,
                    "is_remainder": True,
                })
                
                # Обновляем fees
                pos.meta["fees_total_sol"] = pos.meta.get("fees_total_sol", 0.0) + fees_remainder + network_fee_exit
                if "network_fee_sol" in pos.meta:
                    pos.meta["network_fee_sol"] += network_fee_exit
                else:
                    pos.meta["network_fee_sol"] = network_fee_exit
                
                # Помечаем остаток как закрытый
                pos.meta[remainder_closed_key] = True
                pos.size = 0.0
        
        # Если позиция полностью закрыта
        if pos.size <= 1e-9:
            pos.status = "closed"
            closed_positions.append(pos)
            
            # Обновляем общий PnL позиции
            total_pnl_sol = sum(exit.get("pnl_sol", 0.0) for exit in pos.meta.get("partial_exits", []))
            pos.meta["pnl_sol"] = total_pnl_sol
        
        return {"balance": balance}

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
            out: Any | None = r.get("result")
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
        
        print(f"  [portfolio] Portfolio filtering for {strategy_name}:")
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
        
        # Portfolio-level reset tracking
        reset_count = 0
        last_reset_time: Optional[datetime] = None
        cycle_start_equity = balance  # Начало цикла = начальный баланс
        equity_peak_in_cycle = balance  # Пик equity в текущем цикле

        for row in trades:
            out: StrategyOutput = row["result"]
            entry_time: datetime = out.entry_time  # type: ignore
            exit_time: datetime = out.exit_time    # type: ignore
            
            # Обновляем equity_peak_in_cycle перед обработкой (для portfolio-level reset tracking)
            if self.config.runner_reset_enabled:
                current_equity = balance + sum(p.size for p in open_positions)
                equity_peak_in_cycle = max(equity_peak_in_cycle, current_equity)

            # 3. Закрываем позиции, у которых exit_time <= entry_time
            # Для Runner стратегий обрабатываем частичные выходы
            still_open: List[Position] = []
            reset_time_current: Optional[datetime] = None
            trigger_position: Optional[Position] = None
            
            # Первый проход: находим позиции, которые нужно закрыть, и проверяем reset
            positions_to_close_now: List[Position] = []
            for pos in open_positions:
                # Проверяем, является ли позиция Runner с частичными выходами
                is_runner = pos.meta.get("runner_ladder", False)
                
                if is_runner and pos.exit_time is not None:
                    # Обрабатываем частичные выходы Runner только если exit_time наступил или уже был достигнут
                    # (для частичных выходов по уровням проверяем current_time >= hit_time в методе)
                    if entry_time >= pos.exit_time or any(
                        # Проверяем, есть ли уровни, которые нужно обработать до current_time
                        hit_time <= entry_time 
                        for hit_time in (
                            datetime.fromisoformat(v) if isinstance(v, str) else v
                            for v in pos.meta.get("levels_hit", {}).values()
                        )
                    ):
                        partial_exits_processed = self._process_runner_partial_exits(
                            pos=pos,
                            current_time=entry_time,
                            balance=balance,
                            equity_curve=equity_curve,
                            closed_positions=closed_positions,
                        )
                        balance = partial_exits_processed["balance"]
                        peak_balance = max(peak_balance, balance)
                    
                    # Если позиция полностью закрыта (size <= 0), удаляем из open
                    if pos.size <= 1e-9:  # Учитываем погрешности float
                        positions_to_close_now.append(pos)
                        continue  # Позиция полностью закрыта, не добавляем в still_open
                    else:
                        # Позиция еще открыта (есть остаток), добавляем в still_open
                        still_open.append(pos)
                        continue
                
                # Обычная обработка для RR/RRD (полное закрытие)
                if pos.exit_time is not None and pos.exit_time <= entry_time:
                    positions_to_close_now.append(pos)
                    # Проверка runner reset: если позиция достигает XN, закрываем все позиции
                    # Проверяем по raw ценам, а не по effective (slippage не должен влиять на XN)
                    if self.config.runner_reset_enabled and trigger_position is None:
                        raw_entry_price = pos.meta.get("raw_entry_price")
                        raw_exit_price = pos.meta.get("raw_exit_price")
                        if raw_entry_price and raw_exit_price and raw_entry_price > 0:
                            multiplying_return = raw_exit_price / raw_entry_price
                            if multiplying_return >= self.config.runner_reset_multiple:
                                trigger_position = pos
                                reset_time_current = pos.exit_time
                                # Помечаем триггерную позицию
                                pos.meta = pos.meta or {}
                                pos.meta["triggered_reset"] = True
                else:
                    still_open.append(pos)
            
            # Второй проход: закрываем позиции, которые должны закрыться
            # Если есть reset, сначала закрываем все остальные открытые позиции
            if trigger_position is not None and reset_time_current is not None:
                # Закрываем все остальные открытые позиции (кроме триггерной)
                for other_pos in still_open:
                    if other_pos.signal_id != trigger_position.signal_id:
                        # Принудительное закрытие по exec_entry_price для правильного расчета баланса
                        effective_exit_price = other_pos.meta.get("exec_entry_price", other_pos.entry_price)
                        exit_pnl_pct = 0.0  # PnL = 0 для принудительного закрытия
                        exit_pnl_sol = 0.0
                        
                        # Применяем fees к возвращаемому нотионалу (только размер позиции)
                        notional_returned = other_pos.size
                        notional_after_fees = self.execution_model.apply_fees(notional_returned)
                        fees_total = notional_returned - notional_after_fees
                        network_fee_exit = self.execution_model.network_fee()
                        
                        # Возвращаем капитал
                        balance += notional_after_fees
                        balance -= network_fee_exit
                        
                        # Обновляем позицию (exit_price остается raw для проверки reset, exec цена в meta)
                        other_pos.exit_time = reset_time_current
                        other_pos.exit_price = other_pos.exit_price  # Сохраняем raw exit_price
                        other_pos.meta["exec_exit_price"] = effective_exit_price  # Исполненная цена в meta
                        other_pos.pnl_pct = exit_pnl_pct
                        other_pos.status = "closed"
                        other_pos.meta = other_pos.meta or {}
                        other_pos.meta["pnl_sol"] = exit_pnl_sol
                        other_pos.meta["fees_total_sol"] = fees_total
                        other_pos.meta["network_fee_sol"] = other_pos.meta.get("network_fee_sol", 0.0) + network_fee_exit
                        other_pos.meta["closed_by_reset"] = True
                        
                        closed_positions.append(other_pos)
                        peak_balance = max(peak_balance, balance)
                        if reset_time_current:
                            equity_curve.append({"timestamp": reset_time_current, "balance": balance})
                
                # Удаляем закрытые позиции из still_open (триггерная позиция останется в positions_to_close_now)
                still_open = [p for p in still_open if p.status != "closed"]
                
                # Устанавливаем reset_until для игнорирования входов ПОСЛЕ reset
                reset_until = reset_time_current
                reset_count += 1
                last_reset_time = reset_time_current
            
            # Проверка: игнорируем входы до следующего сигнала после reset
            # Должна быть ПОСЛЕ обработки закрытий позиций, когда reset_until уже может быть установлен
            # Reset должен влиять на сделки, которые начинаются в момент reset или раньше (entry_time <= reset_until)
            if self.config.runner_reset_enabled and reset_until is not None and entry_time <= reset_until:
                skipped_by_reset += 1
                continue
            
            # Закрываем позиции, которые должны закрыться нормально (включая триггерную)
            for pos in positions_to_close_now:
                # При закрытии: возвращаем размер позиции + прибыль/убыток
                # Вычитаем fees (swap + LP) из возвращаемого нотионала
                network_fee_exit = self.execution_model.network_fee()
                trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
                
                # Применяем fees к возвращаемому нотионалу
                notional_returned = pos.size + trade_pnl_sol
                notional_after_fees = self.execution_model.apply_fees(notional_returned)
                fees_total = notional_returned - notional_after_fees
                
                balance += notional_after_fees  # Возвращаем размер + PnL минус fees
                balance -= network_fee_exit  # Network fee при выходе
                pos.meta = pos.meta or {}
                pos.meta["pnl_sol"] = trade_pnl_sol
                pos.meta["fees_total_sol"] = fees_total
                # Обновляем общий network_fee_sol (вход + выход)
                if "network_fee_sol" in pos.meta:
                    pos.meta["network_fee_sol"] += network_fee_exit
                else:
                    pos.meta["network_fee_sol"] = network_fee_exit
                
                pos.status = "closed"
                closed_positions.append(pos)

                peak_balance = max(peak_balance, balance)
                if pos.exit_time:
                    equity_curve.append(
                        {"timestamp": pos.exit_time, "balance": balance}
                    )
            
            open_positions = still_open
            
            # Обновляем equity_peak_in_cycle после обработки позиций
            current_equity = balance + sum(p.size for p in open_positions)
            equity_peak_in_cycle = max(equity_peak_in_cycle, current_equity)


            # 4. Проверка лимитов портфеля

            # лимит по количеству позиций
            if len(open_positions) >= self.config.max_open_positions:
                skipped_by_risk += 1
                continue

            # текущая экспозиция (учитываем, что баланс уже уменьшен на открытые позиции)
            total_open_notional = sum(p.size for p in open_positions)
            # Доступный баланс = текущий баланс (уже уменьшенный на открытые позиции)
            available_balance = balance
            
            # В fixed mode total_capital должен быть равен initial_balance_sol,
            # так как размер позиции рассчитывается от начального баланса.
            # В dynamic mode total_capital = available_balance + total_open_notional.
            if self.config.allocation_mode == "fixed":
                total_capital = self.config.initial_balance_sol
            else:
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
            
            # DEBUG-лог перед risk-check
            logger.debug(
                f"[PortfolioEngine] Risk check before trade: "
                f"balance={available_balance:.6f}, "
                f"position_size={desired_size:.6f}, "
                f"open_notional={total_open_notional:.6f}, "
                f"total_capital={total_capital:.6f}, "
                f"max_allowed_exposure={max_allowed_notional:.6f}, "
                f"allocation_mode={self.config.allocation_mode}, "
                f"percent_per_trade={self.config.percent_per_trade}, "
                f"max_exposure={self.config.max_exposure}"
            )
            
            # Проверяем, что желаемый размер не превышает лимит экспозиции
            if desired_size > max_allowed_notional:
                # Если желаемый размер превышает лимит, отклоняем сделку полностью
                logger.debug(
                    f"[PortfolioEngine] Trade rejected by exposure limit: "
                    f"desired_size={desired_size:.6f} > max_allowed_notional={max_allowed_notional:.6f}"
                )
                skipped_by_risk += 1
                continue
            
            size = desired_size
            if size <= 0:
                skipped_by_risk += 1
                continue

            # 5. Применяем ExecutionModel: slippage к ценам и fees к нотионалу
            raw_entry_price = out.entry_price or 0.0
            raw_exit_price = out.exit_price or 0.0
            
            if raw_entry_price <= 0 or raw_exit_price <= 0:
                skipped_by_risk += 1
                continue
            
            # Применяем slippage к ценам
            effective_entry_price = self.execution_model.apply_entry(raw_entry_price, "entry")
            effective_exit_price = self.execution_model.apply_exit(raw_exit_price, out.reason)
            
            # Пересчитываем PnL на основе эффективных цен (slippage уже учтен)
            raw_pnl_pct = out.pnl
            effective_pnl_pct = (effective_exit_price - effective_entry_price) / effective_entry_price
            
            # Network fee вычитается отдельно из баланса
            network_fee = self.execution_model.network_fee()
            
            # Итоговый PnL с учетом slippage (fees будут вычтены из нотионала при закрытии)
            net_pnl_pct = effective_pnl_pct
            
            # 6. Вычитаем размер позиции и network fee из баланса при открытии
            balance -= size  # Платим полный размер позиции
            balance -= network_fee  # Network fee при входе
            
            # 7. Создаем Position с эффективными ценами
            # Проверяем, является ли стратегия Runner
            is_runner = out.meta.get("runner_ladder", False)
            
            pos_meta = {
                "strategy": strategy_name,
                "raw_pnl_pct": raw_pnl_pct,
                "raw_entry_price": raw_entry_price,
                "raw_exit_price": raw_exit_price,
                "effective_pnl_pct": effective_pnl_pct,
                "slippage_entry_pct": (effective_entry_price - raw_entry_price) / raw_entry_price if raw_entry_price > 0 else 0.0,
                "slippage_exit_pct": (raw_exit_price - effective_exit_price) / raw_exit_price if raw_exit_price > 0 else 0.0,
                "network_fee_sol": network_fee,  # Только вход, выход добавится при закрытии
                "execution_profile": self.config.execution_profile,
                # Исполненные цены (с slippage) для расчета PnL и баланса
                "exec_entry_price": effective_entry_price,
                "exec_exit_price": effective_exit_price,
            }
            
            # Примечание: reset-флаги устанавливаются только в Position.meta при закрытии позиции,
            # а не в StrategyOutput.meta (reset-политика - это исключительно портфельная функциональность)
            
            # Для Runner сохраняем данные о частичных выходах и original_size
            if is_runner:
                pos_meta["runner_ladder"] = True
                pos_meta["original_size"] = size  # Сохраняем оригинальный размер для расчета частичных выходов
                pos_meta["levels_hit"] = out.meta.get("levels_hit", {})
                pos_meta["fractions_exited"] = out.meta.get("fractions_exited", {})
                pos_meta["time_stop_triggered"] = out.meta.get("time_stop_triggered", False)
                pos_meta["realized_multiple"] = out.meta.get("realized_multiple", 1.0)
            
            # Position.entry_price и Position.exit_price содержат RAW цены (для reset проверки)
            # Исполненные цены (с slippage) хранятся в meta["exec_entry_price"] и meta["exec_exit_price"]
            pos = Position(
                signal_id=row["signal_id"],
                contract_address=row["contract_address"],
                entry_time=entry_time,
                entry_price=raw_entry_price,  # RAW цена (для reset проверки)
                size=size,
                exit_time=exit_time,
                exit_price=raw_exit_price,  # RAW цена (для reset проверки)
                pnl_pct=net_pnl_pct,  # PnL рассчитывается по исполненным ценам (effective_pnl_pct)
                status="open",
                meta=pos_meta,
            )
            open_positions.append(pos)
            
            # Обновляем equity curve при открытии позиции
            equity_curve.append({"timestamp": entry_time, "balance": balance})

        # 8. Закрываем все оставшиеся открытые позиции
        # Сортируем позиции по exit_time для корректной обработки reset
        positions_to_close = sorted([p for p in open_positions if p.exit_time is not None], 
                                   key=lambda p: p.exit_time if p.exit_time else datetime.max)
        
        # Обрабатываем позиции по времени закрытия, проверяя reset
        for pos in positions_to_close:
            # Обрабатываем частичные выходы Runner перед финальным закрытием
            is_runner = pos.meta.get("runner_ladder", False)
            if is_runner:
                # Обрабатываем все оставшиеся частичные выходы
                # Используем exit_time как current_time для обработки всех уровней
                if pos.exit_time:
                    partial_result = self._process_runner_partial_exits(
                        pos=pos,
                        current_time=pos.exit_time,
                        balance=balance,
                        equity_curve=equity_curve,
                        closed_positions=closed_positions,
                    )
                    balance = partial_result["balance"]
                    peak_balance = max(peak_balance, balance)
                    
                    # Если позиция уже закрыта частичными выходами, пропускаем
                    if pos.size <= 1e-9:
                        continue
            
            # Если позиция уже закрыта по reset и помечена, пропускаем
            if pos.meta.get("closed_by_reset"):
                continue
            
            # Проверка runner reset: если позиция достигает XN, закрываем все остальные открытые позиции
            # Проверяем по raw ценам, а не по effective (slippage не должен влиять на XN)
            should_trigger_reset = False
            if self.config.runner_reset_enabled and pos.exit_time is not None:
                raw_entry_price = pos.meta.get("raw_entry_price")
                raw_exit_price = pos.meta.get("raw_exit_price")
                if raw_entry_price and raw_exit_price and raw_entry_price > 0:
                    multiplying_return = raw_exit_price / raw_entry_price
                    if multiplying_return >= self.config.runner_reset_multiple:
                        should_trigger_reset = True
                        reset_time_final = pos.exit_time
                        # Помечаем триггерную позицию
                        pos.meta = pos.meta or {}
                        pos.meta["triggered_reset"] = True
                        
                        # Закрываем все остальные открытые позиции
                        other_positions = [p for p in positions_to_close if p.signal_id != pos.signal_id and not p.meta.get("closed_by_reset")]
                        for other_pos in other_positions:
                            # Принудительное закрытие по exec_entry_price для правильного расчета баланса
                            effective_exit_price = other_pos.meta.get("exec_entry_price", other_pos.entry_price)
                            exit_pnl_pct = 0.0  # PnL = 0 для принудительного закрытия
                            exit_pnl_sol = 0.0
                            
                            # Применяем fees к возвращаемому нотионалу (только размер позиции)
                            notional_returned = other_pos.size
                            notional_after_fees = self.execution_model.apply_fees(notional_returned)
                            fees_total = notional_returned - notional_after_fees
                            network_fee_exit = self.execution_model.network_fee()
                            
                            # Возвращаем капитал
                            balance += notional_after_fees
                            balance -= network_fee_exit
                            
                            # Обновляем позицию (exit_price остается raw для проверки reset, exec цена в meta)
                            other_pos.exit_time = reset_time_final
                            other_pos.exit_price = other_pos.exit_price  # Сохраняем raw exit_price
                            other_pos.meta["exec_exit_price"] = effective_exit_price  # Исполненная цена в meta
                            other_pos.pnl_pct = exit_pnl_pct
                            other_pos.status = "closed"
                            other_pos.meta = other_pos.meta or {}
                            other_pos.meta["pnl_sol"] = exit_pnl_sol
                            other_pos.meta["fees_total_sol"] = fees_total
                            other_pos.meta["network_fee_sol"] = other_pos.meta.get("network_fee_sol", 0.0) + network_fee_exit
                            other_pos.meta["closed_by_reset"] = True
                            
                            closed_positions.append(other_pos)
                            peak_balance = max(peak_balance, balance)
                            if reset_time_final:
                                equity_curve.append({"timestamp": reset_time_final, "balance": balance})
                        
                        reset_count += 1
                        if last_reset_time is None or (reset_time_final and reset_time_final > last_reset_time):
                            last_reset_time = reset_time_final
            
            # При закрытии: возвращаем размер позиции + прибыль/убыток
            # Вычитаем fees (swap + LP) из возвращаемого нотионала
            # Fees применяются дважды: при входе и при выходе (round-trip)
            network_fee_exit = self.execution_model.network_fee()
            trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
            
            # Применяем fees к возвращаемому нотионалу (round-trip: вход + выход)
            notional_returned = pos.size + trade_pnl_sol
            # Fees применяются дважды (вход и выход)
            notional_after_entry_fees = self.execution_model.apply_fees(notional_returned)
            notional_after_exit_fees = self.execution_model.apply_fees(notional_after_entry_fees)
            fees_total = notional_returned - notional_after_exit_fees
            
            balance += notional_after_exit_fees  # Возвращаем размер + PnL минус fees (round-trip)
            balance -= network_fee_exit  # Network fee при выходе
            
            pos.meta = pos.meta or {}
            pos.meta["pnl_sol"] = trade_pnl_sol
            pos.meta["fees_total_sol"] = fees_total
            # Обновляем общий network_fee_sol (вход + выход)
            if "network_fee_sol" in pos.meta:
                pos.meta["network_fee_sol"] += network_fee_exit
            else:
                pos.meta["network_fee_sol"] = network_fee_exit
            
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

        # Обновляем equity_peak_in_cycle для финального значения
        final_equity = balance + sum(p.size for p in open_positions)
        equity_peak_in_cycle = max(equity_peak_in_cycle, final_equity)
        
        stats = PortfolioStats(
            final_balance_sol=final_balance,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            trades_executed=len(closed_positions),
            trades_skipped_by_risk=skipped_by_risk,
            trades_skipped_by_reset=skipped_by_reset,
            reset_count=reset_count,
            last_reset_time=last_reset_time,
            cycle_start_equity=cycle_start_equity,
            equity_peak_in_cycle=equity_peak_in_cycle,
        )

        # Все позиции помечаем closed для консистентности
        for pos in closed_positions:
            pos.status = "closed"

        return PortfolioResult(
            equity_curve=equity_curve,
            positions=closed_positions,
            stats=stats,
        )




