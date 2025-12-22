# backtester/domain/portfolio.py

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional, Union

from .position import Position
from .models import StrategyOutput
from .execution_model import ExecutionProfileConfig, ExecutionModel
from .portfolio_reset import (
    PortfolioState,
    PortfolioResetContext,
    ResetReason,
    apply_portfolio_reset,
)

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

    # Profit reset конфигурация (reset по росту equity портфеля)
    profit_reset_enabled: bool = False
    profit_reset_multiple: float = 2.0  # Множитель для profit reset (например, 2.0 = x2)
    
    # DEPRECATED: Используйте profit_reset_enabled и profit_reset_multiple вместо этих полей
    # Оставлено для обратной совместимости со старыми YAML конфигами
    runner_reset_enabled: bool = False
    runner_reset_multiple: float = 2.0  # XN multiplier (например, 2.0 = x2)
    
    # Capacity reset конфигурация (v1.6)
    capacity_reset_enabled: bool = True
    capacity_open_ratio_threshold: float = 1.0  # Порог заполненности портфеля (1.0 = 100%)
    capacity_window_type: Literal["time", "signals"] = "time"  # Тип окна: по времени или по количеству сигналов
    capacity_window_size: Union[int, str] = 7  # Размер окна: дни (int) или строка "7d" для time, количество сигналов для signals
    capacity_max_blocked_ratio: float = 0.4  # Максимальная доля отклоненных сигналов за окно (0.4 = 40%)
    capacity_max_avg_hold_days: float = 10.0  # Максимальное среднее время удержания открытых позиций (дни)
    
    def resolved_profit_reset_enabled(self) -> bool:
        """
        Возвращает значение profit_reset_enabled с fallback на runner_reset_enabled для обратной совместимости.
        
        Приоритет:
        1. profit_reset_enabled (если задан явно)
        2. runner_reset_enabled (deprecated alias)
        """
        # Проверяем, задано ли новое поле явно (не None и не default)
        if hasattr(self, "profit_reset_enabled") and self.profit_reset_enabled is not None:
            return bool(self.profit_reset_enabled)
        # Fallback на старое поле для обратной совместимости
        return bool(getattr(self, "runner_reset_enabled", False))
    
    def resolved_profit_reset_multiple(self) -> float:
        """
        Возвращает значение profit_reset_multiple с fallback на runner_reset_multiple для обратной совместимости.
        
        Приоритет:
        1. profit_reset_multiple (если задан явно)
        2. runner_reset_multiple (deprecated alias)
        """
        # Проверяем, задано ли новое поле явно (не None и не default)
        if hasattr(self, "profit_reset_multiple") and self.profit_reset_multiple is not None:
            return float(self.profit_reset_multiple)
        # Fallback на старое поле для обратной совместимости
        return float(getattr(self, "runner_reset_multiple", 2.0))


@dataclass
class PortfolioStats:
    final_balance_sol: float
    total_return_pct: float
    max_drawdown_pct: float
    trades_executed: int
    trades_skipped_by_risk: int
    trades_skipped_by_reset: int = 0  # Сделки, пропущенные из-за runner reset
    
    # Runner reset tracking (по XN)
    runner_reset_count: int = 0  # Количество срабатываний runner reset (по XN)
    last_runner_reset_time: Optional[datetime] = None  # Время последнего runner reset
    
    # Portfolio-level reset tracking (по equity threshold и capacity)
    portfolio_reset_count: int = 0  # Количество срабатываний portfolio-level reset (profit + capacity)
    last_portfolio_reset_time: Optional[datetime] = None  # Время последнего portfolio-level reset
    
    # Разделение счетчиков portfolio reset (опционально, для детализации)
    portfolio_reset_profit_count: int = 0  # Количество profit reset (по equity threshold)
    portfolio_reset_capacity_count: int = 0  # Количество capacity reset
    
    def __post_init__(self):
        """Инициализация счетчиков reset."""
        # Если счетчики не были явно установлены, инициализируем их
        if not hasattr(self, 'portfolio_reset_profit_count'):
            self.portfolio_reset_profit_count = 0
        if not hasattr(self, 'portfolio_reset_capacity_count'):
            self.portfolio_reset_capacity_count = 0
    
    # Обратная совместимость: reset_count означает portfolio-level reset
    @property
    def reset_count(self) -> int:
        """Обратная совместимость: reset_count = portfolio_reset_count"""
        return self.portfolio_reset_count
    
    @property
    def last_reset_time(self) -> Optional[datetime]:
        """Обратная совместимость: last_reset_time = last_portfolio_reset_time"""
        return self.last_portfolio_reset_time
    
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
    
    ПРОБЛЕМА CAPACITY CHOKE (v1.6):
    Портфель может перестать открывать новые сделки (capacity choke):
    - open_positions долго == max_open_positions
    - новые сигналы отклоняются (max_open_positions/max_exposure)
    - turnover маленький → прибыльный profit reset может не наступить, портфель "висит"
    
    РЕШЕНИЕ:
    - Profit reset (по equity threshold) - сохраняется, показал прибыльность
    - Capacity reset (новый механизм) - срабатывает при capacity pressure независимо от profit reset
    """

    def __init__(self, config: PortfolioConfig) -> None:
        self.config = config
        self.execution_model = ExecutionModel.from_config(config)

    def _dbg(self, event: str, **kv) -> None:
        """
        Диагностический helper для portfolio-level reset.
        Логирует только при включенном флаге PORTFOLIO_DEBUG_RESET=1.
        
        Args:
            event: Название события
            **kv: Ключ-значение пары для логирования
        """
        debug_enabled = os.getenv("PORTFOLIO_DEBUG_RESET") == "1"
        if not debug_enabled:
            return
        
        # Формируем строку с параметрами
        parts = [f"[RESETDBG] {event}"]
        for key, value in kv.items():
            if isinstance(value, Position):
                # Для позиций выводим ключевую информацию
                parts.append(f"{key}.signal_id={value.signal_id}")
                parts.append(f"{key}.status={value.status}")
                parts.append(f"{key}.id={id(value)}")
                parts.append(f"{key}.closed_by_reset={value.meta.get('closed_by_reset', False)}")
                parts.append(f"{key}.triggered_portfolio_reset={value.meta.get('triggered_portfolio_reset', False)}")
            elif isinstance(value, datetime):
                parts.append(f"{key}={value.isoformat()}")
            elif isinstance(value, list):
                # Для списков позиций выводим количество и signal_id
                if value and isinstance(value[0], Position):
                    parts.append(f"{key}.count={len(value)}")
                    parts.append(f"{key}.signal_ids=[{', '.join(p.signal_id for p in value)}]")
                elif not value:
                    parts.append(f"{key}=[]")
                else:
                    parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}={value}")
        
        message = " ".join(parts)
        logger.debug(message)
        print(message)

    def _dbg_meta(self, pos: Position, label: str) -> None:
        """
        Диагностический helper для отслеживания изменений meta позиции.
        Логирует только при включенном флаге PORTFOLIO_DEBUG_RESET=1.
        
        Args:
            pos: Позиция для диагностики
            label: Метка события/места в коде
        """
        debug_enabled = os.getenv("PORTFOLIO_DEBUG_RESET") == "1"
        if not debug_enabled:
            return
        
        meta_id = id(pos.meta) if pos.meta is not None else None
        meta_keys = list(pos.meta.keys()) if pos.meta is not None else []
        closed_by_reset = pos.meta.get("closed_by_reset", False) if pos.meta is not None else False
        triggered_portfolio_reset = pos.meta.get("triggered_portfolio_reset", False) if pos.meta is not None else False
        
        message = (
            f"[METADBG] {label} | "
            f"signal_id={pos.signal_id} | "
            f"status={pos.status} | "
            f"id(pos)={id(pos)} | "
            f"id(meta)={meta_id} | "
            f"meta_keys={sorted(meta_keys)} | "
            f"closed_by_reset={closed_by_reset} | "
            f"triggered_portfolio_reset={triggered_portfolio_reset}"
        )
        logger.debug(message)
        print(message)

    def _ensure_meta(self, pos: Position) -> Dict[str, Any]:
        """
        Гарантирует, что pos.meta существует и возвращает его.
        НЕ создает новый dict, если meta уже существует.
        
        Args:
            pos: Позиция для проверки/инициализации meta
            
        Returns:
            Существующий или новый dict для pos.meta
        """
        if pos.meta is None:
            pos.meta = {}
        return pos.meta

    def _position_size(self, current_balance: float) -> float:
        """
        Вычисляет размер позиции на основе текущего баланса и режима аллокации.
        """
        if self.config.allocation_mode == "fixed":
            base = self.config.initial_balance_sol
        else:
            base = current_balance
        return max(0.0, base * self.config.percent_per_trade)
    
    def _check_capacity_reset(
        self,
        state: PortfolioState,
        current_time: datetime,
        capacity_tracking: Dict[str, Any],
    ) -> Optional[PortfolioResetContext]:
        """
        Проверяет, должен ли сработать capacity reset.
        
        Триггер capacity reset:
        1. open_positions / max_open_positions >= capacity_open_ratio_threshold
        2. blocked_by_capacity_in_window >= capacity_blocked_signals_threshold
        3. closed_in_window <= capacity_min_turnover_threshold
        
        Args:
            state: Состояние портфеля
            current_time: Текущее время
            capacity_tracking: Dict с метриками capacity (blocked_by_capacity_in_window, closed_in_window, window_start, window_end)
            
        Returns:
            PortfolioResetContext если reset должен сработать, иначе None
        """
        if not self.config.capacity_reset_enabled:
            return None
        
        # Вычисляем open_ratio
        max_open = self.config.max_open_positions
        if max_open <= 0:
            return None
        
        open_ratio = len(state.open_positions) / max_open
        if open_ratio < self.config.capacity_open_ratio_threshold:
            return None  # Портфель не заполнен
        
        # Проверяем метрики окна
        blocked_window = capacity_tracking.get("blocked_by_capacity_in_window", 0)
        signals_in_window = capacity_tracking.get("signals_in_window", 0)
        avg_hold_days = capacity_tracking.get("avg_hold_time_open_positions", 0.0)
        
        # Проверяем max_blocked_ratio (доля отклоненных сигналов)
        if signals_in_window > 0:
            blocked_ratio = blocked_window / signals_in_window
            if blocked_ratio < self.config.capacity_max_blocked_ratio:
                return None  # Недостаточно отклоненных сигналов (низкая доля)
        else:
            return None  # Нет сигналов в окне
        
        # Проверяем max_avg_hold_days (среднее время удержания открытых позиций)
        if avg_hold_days < self.config.capacity_max_avg_hold_days:
            return None  # Среднее время удержания низкое (есть turnover), reset не нужен
        
        # Все условия выполнены - capacity reset должен сработать
        # Выбираем marker position (первая открытая позиция)
        if not state.open_positions:
            return None  # Нет открытых позиций (не должно происходить)
        
        marker_position = state.open_positions[0]
        # Исключаем marker из positions_to_force_close (архитектурный инвариант)
        # Marker будет закрыт отдельно в apply_portfolio_reset
        positions_to_force_close = [
            p for p in state.open_positions
            if p.signal_id != marker_position.signal_id
        ]
        
        context = PortfolioResetContext(
            reason=ResetReason.CAPACITY_PRESSURE,
            reset_time=current_time,
            marker_position=marker_position,
            positions_to_force_close=positions_to_force_close,
            open_ratio=open_ratio,
            blocked_window=blocked_window,
            turnover_window=capacity_tracking.get("closed_in_window", 0),
            window_start=capacity_tracking.get("window_start"),
            window_end=capacity_tracking.get("window_end"),
        )
        
        return context
    
    def _update_capacity_tracking(
        self,
        capacity_tracking: Dict[str, Any],
        current_time: datetime,
        state: PortfolioState,
        signal_blocked_by_capacity: bool,
        position_closed: bool,
    ) -> None:
        """
        Обновляет метрики capacity tracking.
        
        Args:
            capacity_tracking: Dict для хранения метрик (изменяется in-place)
            current_time: Текущее время
            signal_blocked_by_capacity: Был ли сигнал отклонен по capacity
            position_closed: Была ли закрыта позиция
        """
        # Инициализация если нужно
        if "window_start" not in capacity_tracking:
            capacity_tracking["window_start"] = current_time
            capacity_tracking["blocked_by_capacity_in_window"] = 0
            capacity_tracking["closed_in_window"] = 0
            capacity_tracking["signals_in_window"] = 0
        
        window_start = capacity_tracking["window_start"]
        
        # Определяем границы окна
        if self.config.capacity_window_type == "time":
            # Окно по времени
            window_size = self.config.capacity_window_size
            if isinstance(window_size, str) and window_size.endswith("d"):
                days = int(window_size[:-1])
            else:
                days = int(window_size)
            window_duration = timedelta(days=days)
            window_end = window_start + window_duration
        else:
            # Окно по количеству сигналов
            window_end = None  # Будет обновляться по количеству сигналов
        
        # Обновляем счетчики
        if signal_blocked_by_capacity:
            capacity_tracking["blocked_by_capacity_in_window"] = capacity_tracking.get("blocked_by_capacity_in_window", 0) + 1
        
        if position_closed:
            capacity_tracking["closed_in_window"] = capacity_tracking.get("closed_in_window", 0) + 1
        
        capacity_tracking["signals_in_window"] = capacity_tracking.get("signals_in_window", 0) + 1
        
        # Обновляем окно если нужно
        if self.config.capacity_window_type == "time":
            # Если текущее время вышло за окно, сдвигаем окно
            if window_end is not None and current_time > window_end:
                # Сбрасываем окно
                capacity_tracking["window_start"] = current_time
                capacity_tracking["blocked_by_capacity_in_window"] = 0
                capacity_tracking["closed_in_window"] = 0
                capacity_tracking["signals_in_window"] = 0
        else:
            # Окно по сигналам: если достигли лимита, сдвигаем окно
            window_size = int(self.config.capacity_window_size)
            if capacity_tracking["signals_in_window"] >= window_size:
                # Сбрасываем окно
                capacity_tracking["window_start"] = current_time
                capacity_tracking["blocked_by_capacity_in_window"] = 0
                capacity_tracking["closed_in_window"] = 0
                capacity_tracking["signals_in_window"] = 0
        
        # Обновляем avg_hold_time_open_positions
        if state.open_positions:
            total_hold_seconds = sum(
                (current_time - pos.entry_time).total_seconds()
                for pos in state.open_positions
                if pos.entry_time
            )
            avg_hold_seconds = total_hold_seconds / len(state.open_positions)
            avg_hold_days = avg_hold_seconds / (24 * 3600)
            capacity_tracking["avg_hold_time_open_positions"] = avg_hold_days
        else:
            capacity_tracking["avg_hold_time_open_positions"] = 0.0
        
        capacity_tracking["window_end"] = window_end if self.config.capacity_window_type == "time" else current_time
    
    def _apply_reset(
        self,
        state: PortfolioState,
        marker_position: Position,
        reset_time: datetime,
        positions_to_force_close: List[Position],
        reason: ResetReason,
    ) -> None:
        """
        Helper-метод для применения reset к PortfolioState.
        
        Это единственная точка в PortfolioEngine, где вызывается apply_portfolio_reset().
        
        Args:
            state: Состояние портфеля (изменяется in-place)
            marker_position: Позиция-маркер для reset
            reset_time: Время reset
            positions_to_force_close: Позиции для принудительного закрытия
            reason: Причина reset
        """
        context = PortfolioResetContext(
            reason=reason,
            reset_time=reset_time,
            marker_position=marker_position,
            positions_to_force_close=positions_to_force_close,
        )
        apply_portfolio_reset(context, state, self.execution_model)

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
            out_result = r.get("result")
            if not isinstance(out_result, StrategyOutput):
                continue
            if out_result.entry_time is None or out_result.exit_time is None:
                filtered_by_entry += 1
                continue

            # Фильтрация по окну по entry_time
            if self.config.backtest_start and out_result.entry_time < self.config.backtest_start:
                filtered_by_window += 1
                continue
            if self.config.backtest_end and out_result.entry_time > self.config.backtest_end:
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

        # Инициализация состояния портфеля
        initial_balance = self.config.initial_balance_sol
        state = PortfolioState(
            balance=initial_balance,
            peak_balance=initial_balance,
            open_positions=[],
            closed_positions=[],
            equity_curve=[],
            cycle_start_equity=initial_balance,  # Начало цикла = начальный баланс
            equity_peak_in_cycle=initial_balance,  # Пик equity в текущем цикле
        )

        # стартовая точка equity-кривой
        first_time = trades[0]["result"].entry_time  # type: ignore
        if first_time:
            state.equity_curve.append({"timestamp": first_time, "balance": state.balance})

        skipped_by_risk = 0
        skipped_by_reset = 0
        
        # Инициализация capacity tracking
        capacity_tracking: Dict[str, Any] = {}

        for row in trades:
            out: StrategyOutput = row["result"]
            entry_time: datetime = out.entry_time  # type: ignore
            exit_time: datetime = out.exit_time    # type: ignore
            
            # Обновляем equity_peak_in_cycle перед обработкой (для portfolio-level reset tracking)
            if self.config.resolved_profit_reset_enabled():
                state.update_equity_peak()

            # 3. Закрываем позиции, у которых exit_time <= entry_time
            # Для Runner стратегий обрабатываем частичные выходы
            still_open: List[Position] = []
            reset_time_current: Optional[datetime] = None
            trigger_position: Optional[Position] = None
            
            # Первый проход: находим позиции, которые нужно закрыть, и проверяем reset
            positions_to_close_now: List[Position] = []
            for pos in state.open_positions:
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
                            balance=state.balance,
                            equity_curve=state.equity_curve,
                            closed_positions=state.closed_positions,
                        )
                        state.balance = partial_exits_processed["balance"]
                        state.peak_balance = max(state.peak_balance, state.balance)
                    
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
                                # Флаг triggered_reset будет установлен в _apply_reset()
                else:
                    still_open.append(pos)
            
            # Второй проход: закрываем позиции, которые должны закрыться
            # Если есть runner reset по XN, применяем его через новый механизм
            if trigger_position is not None and reset_time_current is not None:
                # Формируем список позиций для принудительного закрытия (кроме триггерной)
                positions_to_force_close = [
                    p for p in still_open 
                    if p.signal_id != trigger_position.signal_id
                ]
                
                # Применяем runner reset через единый механизм
                self._apply_reset(
                    state=state,
                    marker_position=trigger_position,
                    reset_time=reset_time_current,
                    positions_to_force_close=positions_to_force_close,
                    reason=ResetReason.RUNNER_XN,
                )
                
                # Обновляем still_open после reset
                still_open = [p for p in still_open if p.status != "closed"]
                
                self._dbg(
                    "runner_reset_count_incremented",
                    old_reset_count=state.runner_reset_count - 1,
                    new_reset_count=state.runner_reset_count,
                    reset_time=reset_time_current,
                    trigger_pos=trigger_position,
                )
            
            # Проверка: игнорируем входы до следующего сигнала после reset
            # Должна быть ПОСЛЕ обработки закрытий позиций, когда reset_until уже может быть установлен
            # Reset должен влиять на сделки, которые начинаются в момент reset или раньше (entry_time <= reset_until)
            if self.config.runner_reset_enabled and state.reset_until is not None and entry_time <= state.reset_until:
                skipped_by_reset += 1
                continue
            
            # Закрываем позиции, которые должны закрыться нормально (включая триггерную)
            # Сохраняем последнюю закрытую позицию для возможного использования в portfolio-level reset
            last_closed_position: Optional[Position] = None
            for pos in positions_to_close_now:
                # При закрытии: возвращаем размер позиции + прибыль/убыток
                # Вычитаем fees (swap + LP) из возвращаемого нотионала
                network_fee_exit = self.execution_model.network_fee()
                trade_pnl_sol = pos.size * (pos.pnl_pct or 0.0)
                
                # Применяем fees к возвращаемому нотионалу
                notional_returned = pos.size + trade_pnl_sol
                notional_after_fees = self.execution_model.apply_fees(notional_returned)
                fees_total = notional_returned - notional_after_fees
                
                state.balance += notional_after_fees  # Возвращаем размер + PnL минус fees
                state.balance -= network_fee_exit  # Network fee при выходе
                m = self._ensure_meta(pos)
                m.update({
                    "pnl_sol": trade_pnl_sol,
                    "fees_total_sol": fees_total,
                })
                # Обновляем общий network_fee_sol (вход + выход)
                m["network_fee_sol"] = m.get("network_fee_sol", 0.0) + network_fee_exit
                
                pos.status = "closed"
                state.closed_positions.append(pos)
                last_closed_position = pos  # Сохраняем для возможного использования в portfolio-level reset

                state.peak_balance = max(state.peak_balance, state.balance)
                if pos.exit_time:
                    state.equity_curve.append(
                        {"timestamp": pos.exit_time, "balance": state.balance}
                    )
                
                # Обновляем equity_peak_in_cycle после закрытия позиции (для portfolio-level reset)
                if self.config.resolved_profit_reset_enabled():
                    state.update_equity_peak()
                    
                    # Проверка portfolio-level reset по equity (profit reset)
                    reset_threshold = state.cycle_start_equity * self.config.resolved_profit_reset_multiple()
                    if state.equity_peak_in_cycle >= reset_threshold:
                        # Формируем список позиций для принудительного закрытия (кроме уже закрытой)
                        positions_to_force_close = [
                            p for p in state.open_positions 
                            if p.signal_id != pos.signal_id and p.status == "open" and not p.meta.get("closed_by_reset")
                        ]
                        
                        # Используем новый метод для обработки portfolio-level reset
                        # pos уже закрыта и в closed_positions - используем её как marker
                        reset_time_portfolio = pos.exit_time if pos.exit_time else datetime.now(timezone.utc)
                        self._apply_reset(
                            state=state,
                            marker_position=pos,  # pos уже закрыта, используем как marker
                            reset_time=reset_time_portfolio,
                            positions_to_force_close=positions_to_force_close,
                            reason=ResetReason.EQUITY_THRESHOLD,
                        )
                        self._dbg_meta(pos, "AFTER_process_portfolio_level_reset_line_846_main_loop")
            
            state.open_positions = still_open
            
            # Обновляем capacity tracking: учитываем закрытые позиции
            positions_closed_count = len(positions_to_close_now)
            if positions_closed_count > 0:
                self._update_capacity_tracking(
                    capacity_tracking=capacity_tracking,
                    current_time=entry_time,
                    state=state,
                    signal_blocked_by_capacity=False,
                    position_closed=True,
                )
            
            # Обновляем equity_peak_in_cycle после обработки позиций
            state.update_equity_peak()
            
            # Проверка capacity reset (после обработки закрытий, перед открытием новой позиции)
            if self.config.capacity_reset_enabled:
                capacity_reset_context = self._check_capacity_reset(
                    state=state,
                    current_time=entry_time,
                    capacity_tracking=capacity_tracking,
                )
                if capacity_reset_context is not None:
                    # Применяем capacity reset
                    self._apply_reset(
                        state=state,
                        marker_position=capacity_reset_context.marker_position,
                        reset_time=capacity_reset_context.reset_time,
                        positions_to_force_close=capacity_reset_context.positions_to_force_close,
                        reason=ResetReason.CAPACITY_PRESSURE,
                    )
                    # Обновляем still_open после reset
                    still_open = [p for p in still_open if p.status != "closed"]
                    state.open_positions = still_open
                    
                    logger.info(
                        f"[CAPACITY_RESET] Triggered at {entry_time.isoformat()}: "
                        f"open_ratio={capacity_reset_context.open_ratio:.2f}, "
                        f"blocked_window={capacity_reset_context.blocked_window}, "
                        f"turnover_window={capacity_reset_context.turnover_window}"
                    )
            
            # Проверка portfolio-level reset по equity (profit reset)
            # Если equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple, закрываем все позиции
            if self.config.resolved_profit_reset_enabled():
                reset_threshold = state.cycle_start_equity * self.config.resolved_profit_reset_multiple()
                if state.equity_peak_in_cycle >= reset_threshold:
                    # Формируем список позиций для принудительного закрытия
                    positions_to_force_close = [p for p in state.open_positions if p.status == "open"]
                    
                    reset_time_portfolio = entry_time  # Используем текущее время события
                    
                    # Выбираем marker position для reset:
                    # - Если есть last_closed_position - используем её как marker (уже закрыта)
                    # - Иначе используем первую позицию из positions_to_force_close как marker,
                    #   но НЕ force-close её (она будет marker, но закроется нормально позже)
                    if last_closed_position is not None:
                        # Используем последнюю закрытую позицию как marker
                        marker_position = last_closed_position
                        other_positions_to_force_close = positions_to_force_close
                    elif positions_to_force_close:
                        # Нет закрытых позиций, но есть открытые - используем первую открытую как marker
                        marker_position = positions_to_force_close[0]
                        # Исключаем marker из списка forced-close (она будет закрыта нормально позже)
                        other_positions_to_force_close = [p for p in positions_to_force_close if p.signal_id != marker_position.signal_id]
                    else:
                        # Нет ни закрытых, ни открытых позиций - skip reset (не должно происходить, но на всякий случай)
                        marker_position = None
                    
                    # Выполняем reset только если есть позиция для marker
                    if marker_position is not None:
                        self._apply_reset(
                            state=state,
                            marker_position=marker_position,
                            reset_time=reset_time_portfolio,
                            positions_to_force_close=other_positions_to_force_close,
                            reason=ResetReason.EQUITY_THRESHOLD,
                        )
                        if marker_position is not None:
                            self._dbg_meta(marker_position, "AFTER_process_portfolio_level_reset_line_911_main_loop_last_closed")


            # 4. Проверка лимитов портфеля

            # лимит по количеству позиций
            blocked_by_capacity = False
            if len(state.open_positions) >= self.config.max_open_positions:
                skipped_by_risk += 1
                blocked_by_capacity = True
                # Обновляем capacity tracking: сигнал отклонен по capacity
                self._update_capacity_tracking(
                    capacity_tracking=capacity_tracking,
                    current_time=entry_time,
                    state=state,
                    signal_blocked_by_capacity=True,
                    position_closed=False,
                )
                continue

            # текущая экспозиция (учитываем, что баланс уже уменьшен на открытые позиции)
            total_open_notional = sum(p.size for p in state.open_positions)
            # Доступный баланс = текущий баланс (уже уменьшенный на открытые позиции)
            available_balance = state.balance
            
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
                blocked_by_capacity = True
                # Обновляем capacity tracking: сигнал отклонен по capacity (exposure)
                self._update_capacity_tracking(
                    capacity_tracking=capacity_tracking,
                    current_time=entry_time,
                    state=state,
                    signal_blocked_by_capacity=True,
                    position_closed=False,
                )
                continue
            
            size = desired_size
            if size <= 0:
                skipped_by_risk += 1
                blocked_by_capacity = True
                # Обновляем capacity tracking: сигнал отклонен (size <= 0)
                self._update_capacity_tracking(
                    capacity_tracking=capacity_tracking,
                    current_time=entry_time,
                    state=state,
                    signal_blocked_by_capacity=True,
                    position_closed=False,
                )
                continue
            
            # Обновляем capacity tracking: сигнал принят (не был отклонен)
            if not blocked_by_capacity:
                self._update_capacity_tracking(
                    capacity_tracking=capacity_tracking,
                    current_time=entry_time,
                    state=state,
                    signal_blocked_by_capacity=False,
                    position_closed=False,
                )

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
            state.balance -= size  # Платим полный размер позиции
            state.balance -= network_fee  # Network fee при входе
            
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
            state.open_positions.append(pos)
            
            # Обновляем equity curve при открытии позиции
            state.equity_curve.append({"timestamp": entry_time, "balance": state.balance})

        # 8. Закрываем все оставшиеся открытые позиции
        # Сортируем позиции по exit_time для корректной обработки reset
        positions_to_close = sorted([p for p in state.open_positions if p.exit_time is not None], 
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
                        balance=state.balance,
                        equity_curve=state.equity_curve,
                        closed_positions=state.closed_positions,
                    )
                    state.balance = partial_result["balance"]
                    state.peak_balance = max(state.peak_balance, state.balance)
                    
                    # Если позиция уже закрыта частичными выходами, пропускаем
                    if pos.size <= 1e-9:
                        continue
            
            # Если позиция уже закрыта по reset и помечена, пропускаем
            if pos.meta and pos.meta.get("closed_by_reset"):
                continue
            
            # Обновляем equity_peak_in_cycle перед закрытием позиции (для portfolio-level reset)
            if self.config.resolved_profit_reset_enabled():
                state.update_equity_peak()
                
                # Проверка portfolio-level reset по equity (profit reset)
                reset_threshold = state.cycle_start_equity * self.config.resolved_profit_reset_multiple()
                if state.equity_peak_in_cycle >= reset_threshold:
                    # Формируем список позиций для принудительного закрытия (кроме той, которую уже закрываем)
                    positions_to_force_close = [
                        p for p in state.open_positions 
                        if p.signal_id != pos.signal_id and p.status == "open" and not p.meta.get("closed_by_reset")
                    ]
                    
                    # Используем новый метод для обработки portfolio-level reset
                    # pos еще открыта, но будет закрыта нормально сразу после этого - используем её как marker
                    reset_time_portfolio = pos.exit_time if pos.exit_time else datetime.now(timezone.utc)
                    self._apply_reset(
                        state=state,
                        marker_position=pos,  # pos будет закрыта нормально, используем как marker
                        reset_time=reset_time_portfolio,
                        positions_to_force_close=positions_to_force_close,
                        reason=ResetReason.EQUITY_THRESHOLD,
                    )
                    self._dbg_meta(pos, "AFTER_process_portfolio_level_reset_line_1118_final_close")
            
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
                        # Флаг triggered_reset будет установлен в _apply_reset()
                        
                        # Закрываем все остальные открытые позиции через новый механизм
                        other_positions = [p for p in positions_to_close if p.signal_id != pos.signal_id and not p.meta.get("closed_by_reset")]
                        
                        # Применяем runner reset через единый механизм
                        self._apply_reset(
                            state=state,
                            marker_position=pos,
                            reset_time=reset_time_final,
                            positions_to_force_close=other_positions,
                            reason=ResetReason.RUNNER_XN,
                        )
                        
                        self._dbg(
                            "runner_reset_final_count_incremented",
                            old_reset_count=state.runner_reset_count - 1,
                            new_reset_count=state.runner_reset_count,
                            reset_time=reset_time_final,
                            trigger_pos=pos,
                        )
            
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
            
            state.balance += notional_after_exit_fees  # Возвращаем размер + PnL минус fees (round-trip)
            state.balance -= network_fee_exit  # Network fee при выходе
            
            # КРИТИЧЕСКОЕ МЕСТО: используем _ensure_meta чтобы НЕ потерять reset-флаги
            # НЕ создаем новый dict, только обновляем существующий
            # Важно: сохраняем reset-флаги, если они были установлены
            m = self._ensure_meta(pos)
            # Сохраняем reset-флаги перед обновлением
            closed_by_reset = m.get("closed_by_reset", False)
            triggered_portfolio_reset = m.get("triggered_portfolio_reset", False)
            m.update({
                "pnl_sol": trade_pnl_sol,
                "fees_total_sol": fees_total,
            })
            # Восстанавливаем reset-флаги, если они были установлены
            if closed_by_reset:
                m["closed_by_reset"] = True
            if triggered_portfolio_reset:
                m["triggered_portfolio_reset"] = True
            # Обновляем общий network_fee_sol (вход + выход)
            m["network_fee_sol"] = m.get("network_fee_sol", 0.0) + network_fee_exit
            
            pos.status = "closed"
            state.closed_positions.append(pos)

            state.peak_balance = max(state.peak_balance, state.balance)
            if pos.exit_time:
                state.equity_curve.append({"timestamp": pos.exit_time, "balance": state.balance})

        # 9. Сортируем equity curve по времени для корректного расчета drawdown
        state.equity_curve.sort(key=lambda x: x["timestamp"] if x.get("timestamp") else datetime.min)
        
        # 10. Статистика
        final_balance = state.balance
        total_return_pct = (final_balance - self.config.initial_balance_sol) / self.config.initial_balance_sol

        max_drawdown_pct = 0.0
        if state.equity_curve:
            peak = state.equity_curve[0]["balance"]
            max_dd = 0.0
            for point in state.equity_curve:
                bal = point["balance"]
                if bal > peak:
                    peak = bal
                dd = (bal - peak) / peak if peak > 0 else 0.0
                if dd < max_dd:
                    max_dd = dd
            max_drawdown_pct = max_dd

        # Обновляем equity_peak_in_cycle для финального значения
        state.update_equity_peak()
        
        stats = PortfolioStats(
            final_balance_sol=final_balance,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            trades_executed=len(state.closed_positions),
            trades_skipped_by_risk=skipped_by_risk,
            trades_skipped_by_reset=skipped_by_reset,
            runner_reset_count=state.runner_reset_count,
            last_runner_reset_time=state.last_runner_reset_time,
            portfolio_reset_count=state.portfolio_reset_count,
            last_portfolio_reset_time=state.last_portfolio_reset_time,
            portfolio_reset_profit_count=getattr(state, 'portfolio_reset_profit_count', 0),
            portfolio_reset_capacity_count=getattr(state, 'portfolio_reset_capacity_count', 0),
            cycle_start_equity=state.cycle_start_equity,
            equity_peak_in_cycle=state.equity_peak_in_cycle,
        )

        # Все позиции помечаем closed для консистентности
        for pos in state.closed_positions:
            pos.status = "closed"

        # Логируем момент возврата результата
        reset_positions = [p for p in state.closed_positions if p.meta.get("closed_by_reset", False)]
        self._dbg(
            "result_return",
            positions_count=len(state.closed_positions),
            reset_positions_count=len(reset_positions),
            reset_positions_signal_ids=[p.signal_id for p in reset_positions],
            runner_reset_count=state.runner_reset_count,
            portfolio_reset_count=state.portfolio_reset_count,
            cycle_start_equity=state.cycle_start_equity,
            equity_peak_in_cycle=state.equity_peak_in_cycle,
        )
        
        # Финальная проверка всех позиций перед возвратом
        for pos in state.closed_positions:
            self._dbg_meta(pos, f"FINAL_CHECK_before_return_signal_id={pos.signal_id}")

        return PortfolioResult(
            equity_curve=state.equity_curve,
            positions=state.closed_positions,
            stats=stats,
        )




