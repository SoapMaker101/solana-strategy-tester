# backtester/audit/invariants.py
# Инварианты и проверки для аудита

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import math

import pandas as pd


class AnomalyType(Enum):
    """Типы аномалий, обнаруженных при аудите."""
    
    # PnL и цены
    PNL_CAP_OR_MAGIC = "pnl_cap_or_magic"  # Магическое значение PnL (например, 920%)
    TP_REASON_BUT_NEGATIVE_PNL = "tp_reason_but_negative_pnl"  # reason=tp, но pnl < 0
    SL_REASON_BUT_POSITIVE_PNL = "sl_reason_but_positive_pnl"  # reason=sl, но pnl > 0
    ENTRY_PRICE_INVALID = "entry_price_invalid"  # entry_price <= 0 или NaN
    EXIT_PRICE_INVALID = "exit_price_invalid"  # exit_price <= 0 или NaN
    PRICE_SOURCE_MISMATCH = "price_source_mismatch"  # Несоответствие источников цен
    
    # Время
    TIME_ORDER_INVALID = "time_order_invalid"  # entry_time > exit_time
    HOLD_MINUTES_MISMATCH = "hold_minutes_mismatch"  # Несоответствие hold_minutes
    
    # События и политики
    MISSING_EVENTS_CHAIN = "missing_events_chain"  # Нет цепочки событий для позиции
    RESET_WITHOUT_EVENTS = "reset_without_events"  # Reset без соответствующих событий
    PRUNE_WITHOUT_EVENTS = "prune_without_events"  # Prune без событий
    
    # Причины закрытия
    UNKNOWN_REASON = "unknown_reason"  # Неизвестная причина закрытия
    TP_NO_PRICE_CROSS = "tp_no_price_cross"  # reason=tp, но цена не пересекала TP
    SL_NO_PRICE_CROSS = "sl_no_price_cross"  # reason=sl, но цена не пересекала SL
    
    # Прочее
    INVALID_POSITION_ID = "invalid_position_id"  # Отсутствует или некорректный position_id
    MISSING_REQUIRED_FIELDS = "missing_required_fields"  # Отсутствуют обязательные поля
    
    # P1: Positions ↔ Events consistency
    POSITION_CLOSED_BUT_NO_CLOSE_EVENT = "position_closed_but_no_close_event"  # Позиция закрыта, но нет события закрытия
    CLOSE_EVENT_BUT_POSITION_OPEN = "close_event_but_position_open"  # Есть событие закрытия, но позиция открыта
    MULTIPLE_OPEN_EVENTS = "multiple_open_events"  # Несколько событий открытия для одной позиции
    MULTIPLE_CLOSE_EVENTS = "multiple_close_events"  # Несколько событий закрытия (если должно быть 1)
    UNKNOWN_REASON_MAPPING = "unknown_reason_mapping"  # Неизвестный маппинг reason ↔ event_type
    
    # P1: Events ↔ Executions consistency
    TRADE_EVENT_WITHOUT_EXECUTION = "trade_event_without_execution"  # Событие торговли без execution
    EXECUTION_WITHOUT_TRADE_EVENT = "execution_without_trade_event"  # Execution без соответствующего события
    EXECUTION_TIME_BEFORE_EVENT = "execution_time_before_event"  # Execution раньше события
    EXECUTION_PRICE_OUT_OF_RANGE = "execution_price_out_of_range"  # Цена execution вне разумных пределов
    EXECUTION_SIZE_MISMATCH = "execution_size_mismatch"  # Размер execution не соответствует позиции
    
    # P2: Decision proof checks
    PROFIT_RESET_TRIGGERED_BUT_CONDITION_FALSE = "profit_reset_triggered_but_condition_false"  # Reset сработал, но условие не выполнено
    PROFIT_RESET_CONDITION_TRUE_BUT_NO_RESET = "profit_reset_condition_true_but_no_reset"  # Условие выполнено, но reset не сработал
    CAPACITY_ACTION_TRIGGERED_BUT_THRESHOLDS_NOT_MET = "capacity_action_triggered_but_thresholds_not_met"  # Prune/reset сработал, но пороги не превышены
    CAPACITY_THRESHOLDS_MET_BUT_NO_ACTION = "capacity_thresholds_met_but_no_action"  # Пороги превышены, но действие не сработало
    CLOSE_ALL_WITHOUT_POLICY_EVENT = "close_all_without_policy_event"  # Close-all без policy event
    CLOSE_ALL_DID_NOT_CLOSE_ALL_POSITIONS = "close_all_did_not_close_all_positions"  # Close-all не закрыл все позиции


@dataclass
class Anomaly:
    """Аномалия, обнаруженная при аудите."""
    
    position_id: Optional[str]
    strategy: str
    signal_id: Optional[str]
    contract_address: str
    entry_time: Optional[datetime]
    exit_time: Optional[datetime]
    entry_price: Optional[float]
    exit_price: Optional[float]
    pnl_pct: Optional[float]
    reason: Optional[str]
    anomaly_type: AnomalyType
    details: Dict[str, Any]
    severity: str = "P0"  # P0, P1, P2
    event_id: Optional[str] = None  # ID события (если применимо)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для CSV экспорта."""
        import json
        return {
            "severity": self.severity,
            "code": self.anomaly_type.value,
            "position_id": self.position_id,
            "event_id": self.event_id,
            "strategy": self.strategy,
            "signal_id": self.signal_id,
            "contract_address": self.contract_address,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "reason": self.reason,
            "anomaly_type": self.anomaly_type.value,
            "details_json": json.dumps(self.details, default=str),
        }


class InvariantChecker:
    """Проверка инвариантов для позиций."""
    
    # Константы
    MAX_REASONABLE_PNL_PCT = 10.0  # 1000% - максимальный разумный PnL
    MAX_REASONABLE_XN = 100.0  # 100x - максимальный разумный множитель
    MIN_VALID_PRICE = 1e-10  # Минимальная валидная цена
    EPSILON = 1e-6  # Погрешность для сравнения float
    
    def __init__(self, include_p1: bool = True, include_p2: bool = True):
        """
        Инициализация проверщика.
        
        :param include_p1: Включать ли P1 проверки (positions ↔ events ↔ executions)
        :param include_p2: Включать ли P2 проверки (decision proofs)
        """
        self.anomalies: List[Anomaly] = []
        self.include_p1 = include_p1
        self.include_p2 = include_p2
    
    @staticmethod
    def _series(df: pd.DataFrame, col: str, default: Any) -> pd.Series:
        """
        Безопасное получение колонки из DataFrame.
        
        Если колонка существует, возвращает df[col].
        Если колонки нет, возвращает Series с default значениями.
        
        :param df: DataFrame
        :param col: Имя колонки
        :param default: Значение по умолчанию
        :return: pd.Series
        """
        if col in df.columns:
            return df[col]
        else:
            return pd.Series([default] * len(df), index=df.index)
    
    def check_all(
        self,
        positions_df: pd.DataFrame,
        events_df: Optional[pd.DataFrame] = None,
        executions_df: Optional[pd.DataFrame] = None,
    ) -> List[Anomaly]:
        """
        Запускает все проверки инвариантов.
        
        :param positions_df: DataFrame с позициями (portfolio_positions.csv)
        :param events_df: Опциональный DataFrame с событиями (portfolio_events.csv)
        :param executions_df: Опциональный DataFrame с исполнениями (portfolio_executions.csv)
        :return: Список обнаруженных аномалий
        """
        self.anomalies = []
        
        if len(positions_df) == 0:
            return []
        
        # Строим индексы (если есть события/исполнения)
        from .indices import AuditIndices
        indices = AuditIndices(events_df=events_df, executions_df=executions_df)
        
        # P0: Базовые проверки позиций
        for _, row in positions_df.iterrows():
            # Проверка обязательных полей
            if not self._check_required_fields(row):
                continue
            
            # Проверка цен
            self._check_prices(row)
            
            # Проверка PnL
            self._check_pnl(row)
            
            # Проверка причин закрытия
            self._check_reason_consistency(row)
            
            # Проверка времени
            self._check_time_ordering(row)
            
            # Проверка магических значений
            self._check_magic_values(row)
        
        # P0: Проверка событий (если есть)
        if events_df is not None and len(events_df) > 0:
            self._check_events_chain(positions_df, events_df)
            self._check_policy_consistency(positions_df, events_df)
        
        # P1: Cross-check positions ↔ events ↔ executions
        if self.include_p1:
            self._check_positions_events_consistency(positions_df, indices)
            if executions_df is not None and len(executions_df) > 0:
                self._check_events_executions_consistency(positions_df, indices)
        
        # P2: Decision proofs (если включено)
        if self.include_p2 and events_df is not None and len(events_df) > 0:
            self._check_decision_proofs(positions_df, events_df, indices)
        
        return self.anomalies
    
    def _check_required_fields(self, row: pd.Series) -> bool:
        """Проверка наличия обязательных полей."""
        required = ["strategy", "contract_address", "status"]
        missing = [f for f in required if f not in row.index or pd.isna(row.get(f))]
        
        if missing:
            self.anomalies.append(Anomaly(
                position_id=row.get("position_id"),
                strategy=row.get("strategy", "UNKNOWN"),
                signal_id=row.get("signal_id"),
                contract_address=row.get("contract_address", "UNKNOWN"),
                entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                entry_price=row.get("entry_price") if pd.notna(row.get("entry_price")) else None,
                exit_price=row.get("exit_price") if pd.notna(row.get("exit_price")) else None,
                pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                reason=row.get("reason"),
                anomaly_type=AnomalyType.MISSING_REQUIRED_FIELDS,
                severity="P0",
                details={"missing_fields": missing},
            ))
            return False
        return True
    
    def _check_prices(self, row: pd.Series) -> None:
        """Проверка валидности цен."""
        entry_price = row.get("exec_entry_price") or row.get("raw_entry_price") or row.get("entry_price")
        exit_price = row.get("exec_exit_price") or row.get("raw_exit_price") or row.get("exit_price")
        
        # Проверка entry_price
        if pd.isna(entry_price) or entry_price <= self.MIN_VALID_PRICE:
            self.anomalies.append(Anomaly(
                position_id=row.get("position_id"),
                strategy=row.get("strategy"),
                signal_id=row.get("signal_id"),
                contract_address=row.get("contract_address"),
                entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                reason=row.get("reason"),
                anomaly_type=AnomalyType.ENTRY_PRICE_INVALID,
                severity="P0",
                details={"entry_price": entry_price},
            ))
        
        # Проверка exit_price (только для закрытых позиций)
        if row.get("status") == "closed":
            if pd.isna(exit_price) or exit_price <= self.MIN_VALID_PRICE:
                self.anomalies.append(Anomaly(
                    position_id=row.get("position_id"),
                    strategy=row.get("strategy"),
                    signal_id=row.get("signal_id"),
                    contract_address=row.get("contract_address"),
                    entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                    reason=row.get("reason"),
                anomaly_type=AnomalyType.EXIT_PRICE_INVALID,
                severity="P0",
                details={"exit_price": exit_price},
            ))
    
    def _check_pnl(self, row: pd.Series) -> None:
        """Проверка формулы PnL и разумности значений."""
        if row.get("status") != "closed":
            return
        
        entry_price = row.get("exec_entry_price") or row.get("raw_entry_price") or row.get("entry_price")
        exit_price = row.get("exec_exit_price") or row.get("raw_exit_price") or row.get("exit_price")
        pnl_pct = row.get("pnl_pct") or row.get("pnl_sol")
        
        if pd.isna(entry_price) or pd.isna(exit_price) or entry_price <= 0:
            return  # Уже проверено в _check_prices
        
        # Проверка формулы PnL (для long позиций)
        expected_pnl_pct = (exit_price - entry_price) / entry_price
        
        # Проверка на магические значения
        if pd.notna(pnl_pct):
            if abs(pnl_pct) > self.MAX_REASONABLE_PNL_PCT:
                self.anomalies.append(Anomaly(
                    position_id=row.get("position_id"),
                    strategy=row.get("strategy"),
                    signal_id=row.get("signal_id"),
                    contract_address=row.get("contract_address"),
                    entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=pnl_pct,
                    reason=row.get("reason"),
                anomaly_type=AnomalyType.PNL_CAP_OR_MAGIC,
                severity="P0",
                details={
                    "pnl_pct": pnl_pct,
                    "expected_pnl_pct": expected_pnl_pct,
                    "max_reasonable": self.MAX_REASONABLE_PNL_PCT,
                },
            ))
    
    def _check_reason_consistency(self, row: pd.Series) -> None:
        """Проверка консистентности reason с фактическими данными."""
        if row.get("status") != "closed":
            return
        
        reason = row.get("reason") or row.get("exit_reason")
        pnl_pct = row.get("pnl_pct") or row.get("pnl_sol")
        
        if not reason or pd.isna(pnl_pct):
            return
        
        # Нормализуем reason для консистентной проверки
        normalized_reason = normalize_reason(str(reason))
        
        # Проверка: reason=tp, но pnl < 0 (строго отрицательный)
        if normalized_reason == "tp" and pnl_pct < -self.EPSILON:
            self.anomalies.append(Anomaly(
                position_id=row.get("position_id"),
                strategy=row.get("strategy"),
                signal_id=row.get("signal_id"),
                contract_address=row.get("contract_address"),
                entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=pnl_pct,
                reason=reason,
                anomaly_type=AnomalyType.TP_REASON_BUT_NEGATIVE_PNL,
                severity="P0",
                details={"pnl_pct": pnl_pct, "reason": reason, "normalized_reason": normalized_reason},
            ))
        
        # Проверка: reason=sl/stop_loss, но pnl >= 0 (неотрицательный)
        if normalized_reason == "sl" and pnl_pct >= 0:
            self.anomalies.append(Anomaly(
                position_id=row.get("position_id"),
                strategy=row.get("strategy"),
                signal_id=row.get("signal_id"),
                contract_address=row.get("contract_address"),
                entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=pnl_pct,
                reason=reason,
                anomaly_type=AnomalyType.SL_REASON_BUT_POSITIVE_PNL,
                severity="P0",
                details={"pnl_pct": pnl_pct, "reason": reason, "normalized_reason": normalized_reason},
            ))
    
    def _check_time_ordering(self, row: pd.Series) -> None:
        """Проверка порядка времени."""
        if row.get("status") != "closed":
            return
        
        entry_time = row.get("entry_time")
        exit_time = row.get("exit_time")
        
        if pd.isna(entry_time) or pd.isna(exit_time):
            return
        
        entry_dt = pd.to_datetime(entry_time)
        exit_dt = pd.to_datetime(exit_time)
        
        if entry_dt > exit_dt:
            self.anomalies.append(Anomaly(
                position_id=row.get("position_id"),
                strategy=row.get("strategy"),
                signal_id=row.get("signal_id"),
                contract_address=row.get("contract_address"),
                entry_time=entry_dt,
                exit_time=exit_dt,
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                reason=row.get("reason"),
                anomaly_type=AnomalyType.TIME_ORDER_INVALID,
                severity="P0",
                details={
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "diff_seconds": (exit_dt - entry_dt).total_seconds(),
                },
            ))
    
    def _check_magic_values(self, row: pd.Series) -> None:
        """Проверка на магические значения (920%, 0, NaN)."""
        pnl_pct = row.get("pnl_pct") or row.get("pnl_sol")
        
        if pd.notna(pnl_pct):
            # Проверка на известные магические значения
            magic_values = [920.0, 920.0 / 100, -920.0, -920.0 / 100]  # 920% и -920%
            if any(abs(pnl_pct - mv) < self.EPSILON for mv in magic_values):
                self.anomalies.append(Anomaly(
                    position_id=row.get("position_id"),
                    strategy=row.get("strategy"),
                    signal_id=row.get("signal_id"),
                    contract_address=row.get("contract_address"),
                    entry_time=pd.to_datetime(row.get("entry_time")) if pd.notna(row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(row.get("exit_time")) if pd.notna(row.get("exit_time")) else None,
                    entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                    exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                    pnl_pct=pnl_pct,
                    reason=row.get("reason"),
                    anomaly_type=AnomalyType.PNL_CAP_OR_MAGIC,
                    severity="P0",
                    details={"pnl_pct": pnl_pct, "magic_value": "920%"},
                ))
    
    def _check_events_chain(self, positions_df: pd.DataFrame, events_df: pd.DataFrame) -> None:
        """Проверка цепочки событий для каждой позиции."""
        # Для каждой закрытой позиции проверяем наличие событий по position_id
        for _, pos_row in positions_df.iterrows():
            if pos_row.get("status") != "closed":
                continue
            
            position_id = pos_row.get("position_id")
            signal_id = pos_row.get("signal_id")
            strategy = pos_row.get("strategy")
            contract = pos_row.get("contract_address")
            
            # Ищем события для этой позиции по position_id (требование: проверка по position_id)
            if position_id and pd.notna(position_id):
                pos_events = events_df[self._series(events_df, "position_id", None) == position_id]
                # Если events_df имеет zero rows для этого position_id -> MISSING_EVENTS_CHAIN
                if len(pos_events) == 0:
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=strategy,
                        signal_id=signal_id,
                        contract_address=contract,
                        entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                        exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                        entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                        exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                        reason=pos_row.get("reason"),
                        anomaly_type=AnomalyType.MISSING_EVENTS_CHAIN,
                        severity="P0",
                        details={"events_count": 0, "position_id": position_id},
                    ))
    
    def _check_policy_consistency(self, positions_df: pd.DataFrame, events_df: pd.DataFrame) -> None:
        """Проверка консистентности политик (reset, prune)."""
        # Проверяем позиции, закрытые по reset/prune
        # Используем безопасное получение колонок
        closed_by_reset_series = self._series(positions_df, "closed_by_reset", False)
        reset_reason_series = self._series(positions_df, "reset_reason", None)
        
        reset_positions = positions_df[
            (closed_by_reset_series == True) |
            (reset_reason_series.notna())
        ]
        
        for _, pos_row in reset_positions.iterrows():
            position_id = pos_row.get("position_id")
            signal_id = pos_row.get("signal_id")
            strategy = pos_row.get("strategy")
            contract = pos_row.get("contract_address")
            
            # Ищем события reset/prune
            event_type_series = self._series(events_df, "event_type", "")
            if position_id and pd.notna(position_id):
                reset_events = events_df[
                    (self._series(events_df, "position_id", None) == position_id) &
                    (event_type_series.str.contains("RESET|PRUNE", case=False, na=False))
                ]
            else:
                reset_events = events_df[
                    (self._series(events_df, "signal_id", None) == signal_id) &
                    (self._series(events_df, "strategy", None) == strategy) &
                    (self._series(events_df, "contract_address", None) == contract) &
                    (event_type_series.str.contains("RESET|PRUNE", case=False, na=False))
                ]
            
            if len(reset_events) == 0:
                self.anomalies.append(Anomaly(
                    position_id=position_id,
                    strategy=strategy,
                    signal_id=signal_id,
                    contract_address=contract,
                    entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=pos_row.get("reason"),
                    anomaly_type=AnomalyType.RESET_WITHOUT_EVENTS,
                    severity="P0",
                    details={"reset_reason": pos_row.get("reset_reason")},
                ))
    
    def _check_positions_events_consistency(
        self,
        positions_df: pd.DataFrame,
        indices: "AuditIndices",
    ) -> None:
        """P1: Проверка консистентности positions ↔ events."""
        for _, pos_row in positions_df.iterrows():
            position_id = pos_row.get("position_id")
            signal_id = pos_row.get("signal_id")
            strategy = pos_row.get("strategy")
            contract = pos_row.get("contract_address")
            status = pos_row.get("status", "open")
            
            events = indices.get_events_for_position(position_id, signal_id, strategy, contract)
            has_open = indices.has_open_event(position_id, signal_id, strategy, contract)
            has_close = indices.has_close_event(position_id, signal_id, strategy, contract)
            close_events = indices.get_close_events(position_id, signal_id, strategy, contract)
            
            # Проверка: позиция закрыта, но нет события закрытия
            if status == "closed" and not has_close:
                self.anomalies.append(Anomaly(
                    position_id=position_id,
                    strategy=strategy,
                    signal_id=signal_id,
                    contract_address=contract,
                    entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=pos_row.get("reason"),
                    anomaly_type=AnomalyType.POSITION_CLOSED_BUT_NO_CLOSE_EVENT,
                    severity="P1",
                    details={"status": status, "events_count": len(events)},
                ))
            
            # Проверка: есть событие закрытия, но позиция открыта
            if status == "open" and has_close:
                event_ids = [str(e.get("event_id", i)) for i, e in enumerate(close_events)]
                self.anomalies.append(Anomaly(
                    position_id=position_id,
                    strategy=strategy,
                    signal_id=signal_id,
                    contract_address=contract,
                    entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=pos_row.get("reason"),
                    anomaly_type=AnomalyType.CLOSE_EVENT_BUT_POSITION_OPEN,
                    severity="P1",
                    event_id=event_ids[0] if event_ids else None,
                    details={"status": status, "close_events": event_ids},
                ))
            
            # Проверка: несколько событий открытия
            open_events = [
                e for e in events
                if any(kw in str(e.get("event_type", "")).lower() for kw in ["attempt_accepted_open", "executed_open", "position_opened", "open"])
            ]
            if len(open_events) > 1:
                event_ids = [str(e.get("event_id", i)) for i, e in enumerate(open_events)]
                self.anomalies.append(Anomaly(
                    position_id=position_id,
                    strategy=strategy,
                    signal_id=signal_id,
                    contract_address=contract,
                    entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                    exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=pos_row.get("reason"),
                    anomaly_type=AnomalyType.MULTIPLE_OPEN_EVENTS,
                    severity="P1",
                    event_id=event_ids[0] if event_ids else None,
                    details={"open_events_count": len(open_events), "event_ids": event_ids},
                ))
            
            # Проверка: несколько событий закрытия (если должно быть 1)
            if len(close_events) > 1:
                # Для обычных закрытий (tp/sl/timeout) должно быть 1 событие
                reason = pos_row.get("reason") or ""
                if reason not in ["prune", "reset", "close_all"]:
                    event_ids = [str(e.get("event_id", i)) for i, e in enumerate(close_events)]
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=strategy,
                        signal_id=signal_id,
                        contract_address=contract,
                        entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                        exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                        entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                        exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                        reason=reason,
                        anomaly_type=AnomalyType.MULTIPLE_CLOSE_EVENTS,
                        severity="P1",
                        event_id=event_ids[0] if event_ids else None,
                        details={"close_events_count": len(close_events), "event_ids": event_ids, "reason": reason},
                    ))
            
            # Проверка маппинга reason ↔ event_type
            reason = pos_row.get("reason")
            if reason and status == "closed":
                # Нормализуем reason для консистентного маппинга
                normalized_reason = normalize_reason(str(reason))
                expected_event_types = self._get_expected_event_types_for_reason(normalized_reason)
                if expected_event_types:
                    actual_event_types = [str(e.get("event_type", "")).lower() for e in close_events]
                    if not any(exp in act for exp in expected_event_types for act in actual_event_types):
                        self.anomalies.append(Anomaly(
                            position_id=position_id,
                            strategy=strategy,
                            signal_id=signal_id,
                            contract_address=contract,
                            entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                            exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                            entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                            exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                            pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                            reason=reason,
                            anomaly_type=AnomalyType.UNKNOWN_REASON_MAPPING,
                            severity="P1",
                            details={
                                "reason": reason,
                                "normalized_reason": normalized_reason,
                                "expected_event_types": expected_event_types,
                                "actual_event_types": actual_event_types,
                            },
                        ))
    
    def _get_expected_event_types_for_reason(self, reason: str) -> List[str]:
        """
        Возвращает ожидаемые типы событий для причины закрытия.
        
        Использует нормализованную причину (normalize_reason должен быть применен заранее).
        """
        # reason уже должен быть нормализован
        mapping = {
            "tp": ["executed_close", "close", "exit", "position_closed"],
            "sl": ["executed_close", "close", "exit", "position_closed"],
            "timeout": ["executed_close", "close", "exit", "position_closed"],
            "prune": ["capacity_prune", "closed_by_capacity_prune", "prune", "position_closed"],
            "reset": ["profit_reset", "closed_by_profit_reset", "reset", "position_closed"],
            "close_all": ["close_all", "closed_by_capacity_close_all", "position_closed"],
        }
        return mapping.get(reason, [])
    
    def _check_events_executions_consistency(
        self,
        positions_df: pd.DataFrame,
        indices: "AuditIndices",
    ) -> None:
        """P1: Проверка консистентности events ↔ executions."""
        # Для каждой позиции проверяем соответствие событий и исполнений
        for _, pos_row in positions_df.iterrows():
            position_id = pos_row.get("position_id")
            signal_id = pos_row.get("signal_id")
            strategy = pos_row.get("strategy")
            contract = pos_row.get("contract_address")
            
            events = indices.get_events_for_position(position_id, signal_id, strategy, contract)
            executions = indices.get_executions_for_position(position_id, signal_id)
            
            # События, которые должны иметь execution
            trade_events = [
                e for e in events
                if any(kw in str(e.get("event_type", "")).lower() for kw in [
                    "attempt_accepted_open", "executed_open", "open",
                    "executed_close", "closed_by", "close", "exit",
                ])
            ]
            
            # Проверка: событие торговли без execution
            for event in trade_events:
                event_time = pd.to_datetime(event.get("timestamp")) if pd.notna(event.get("timestamp")) else None
                event_type = str(event.get("event_type", "")).lower()
                
                # Ищем соответствующее execution по времени (в пределах 1 минуты)
                matching_execution = None
                if event_time:
                    for exec_item in executions:
                        exec_time = pd.to_datetime(exec_item.get("event_time")) if pd.notna(exec_item.get("event_time")) else None
                        if exec_time and abs((exec_time - event_time).total_seconds()) < 60:
                            exec_event_type = str(exec_item.get("event_type", "")).lower()
                            # Проверяем соответствие типов
                            if ("open" in event_type and "entry" in exec_event_type) or \
                               ("close" in event_type or "exit" in event_type) and ("exit" in exec_event_type or "close" in exec_event_type):
                                matching_execution = exec_item
                                break
                
                if not matching_execution:
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=strategy,
                        signal_id=signal_id,
                        contract_address=contract,
                        entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                        exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                        entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                        exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                        reason=pos_row.get("reason"),
                        anomaly_type=AnomalyType.TRADE_EVENT_WITHOUT_EXECUTION,
                        severity="P1",
                        event_id=str(event.get("event_id", "")),
                        details={
                            "event_type": event_type,
                            "event_time": event_time.isoformat() if event_time else None,
                            "executions_count": len(executions),
                        },
                    ))
            
            # Проверка: execution без соответствующего события
            for exec_item in executions:
                exec_time = pd.to_datetime(exec_item.get("event_time")) if pd.notna(exec_item.get("event_time")) else None
                exec_event_type = str(exec_item.get("event_type", "")).lower()
                
                # Ищем соответствующее событие
                matching_event = None
                if exec_time:
                    for event in events:
                        event_time = pd.to_datetime(event.get("timestamp")) if pd.notna(event.get("timestamp")) else None
                        if event_time and abs((event_time - exec_time).total_seconds()) < 60:
                            event_type = str(event.get("event_type", "")).lower()
                            if ("entry" in exec_event_type and "open" in event_type) or \
                               ("exit" in exec_event_type and ("close" in event_type or "exit" in event_type)):
                                matching_event = event
                                break
                
                if not matching_event:
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=strategy,
                        signal_id=signal_id,
                        contract_address=contract,
                        entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                        exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                        entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                        exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                        reason=pos_row.get("reason"),
                        anomaly_type=AnomalyType.EXECUTION_WITHOUT_TRADE_EVENT,
                        severity="P1",
                        details={
                            "execution_type": exec_event_type,
                            "execution_time": exec_time.isoformat() if exec_time else None,
                            "events_count": len(events),
                        },
                    ))
            
            # Проверка времени: execution не может быть раньше события
            for event in trade_events:
                event_time = pd.to_datetime(event.get("timestamp")) if pd.notna(event.get("timestamp")) else None
                if not event_time:
                    continue
                
                for exec_item in executions:
                    exec_time = pd.to_datetime(exec_item.get("event_time")) if pd.notna(exec_item.get("event_time")) else None
                    if exec_time and exec_time < event_time:
                        # Проверяем, что это действительно связанные события
                        exec_event_type = str(exec_item.get("event_type", "")).lower()
                        event_type = str(event.get("event_type", "")).lower()
                        if (("entry" in exec_event_type and "open" in event_type) or
                            ("exit" in exec_event_type and ("close" in event_type or "exit" in event_type))):
                            self.anomalies.append(Anomaly(
                                position_id=position_id,
                                strategy=strategy,
                                signal_id=signal_id,
                                contract_address=contract,
                                entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                                exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                                entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                                exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                                pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                                reason=pos_row.get("reason"),
                                anomaly_type=AnomalyType.EXECUTION_TIME_BEFORE_EVENT,
                                severity="P1",
                                event_id=str(event.get("event_id", "")),
                                details={
                                    "event_time": event_time.isoformat(),
                                    "execution_time": exec_time.isoformat(),
                                    "diff_seconds": (event_time - exec_time).total_seconds(),
                                },
                            ))
            
            # Проверка цен: execution price должна быть в разумных пределах
            entry_price = pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price")
            exit_price = pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price")
            
            for exec_item in executions:
                exec_price = exec_item.get("exec_price")
                raw_price = exec_item.get("raw_price")
                exec_event_type = str(exec_item.get("event_type", "")).lower()
                
                if pd.isna(exec_price) or exec_price <= 0:
                    continue
                
                # Для entry: exec_price должна быть близка к entry_price
                if "entry" in exec_event_type and entry_price:
                    price_diff_pct = abs(exec_price - entry_price) / entry_price
                    if price_diff_pct > 0.5:  # Более 50% разница
                        self.anomalies.append(Anomaly(
                            position_id=position_id,
                            strategy=strategy,
                            signal_id=signal_id,
                            contract_address=contract,
                            entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                            exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                            reason=pos_row.get("reason"),
                            anomaly_type=AnomalyType.EXECUTION_PRICE_OUT_OF_RANGE,
                            severity="P1",
                            details={
                                "execution_type": exec_event_type,
                                "execution_price": exec_price,
                                "position_price": entry_price,
                                "price_diff_pct": price_diff_pct,
                            },
                        ))
                
                # Для exit: exec_price должна быть близка к exit_price
                if ("exit" in exec_event_type or "close" in exec_event_type) and exit_price:
                    price_diff_pct = abs(exec_price - exit_price) / exit_price
                    if price_diff_pct > 0.5:  # Более 50% разница
                        self.anomalies.append(Anomaly(
                            position_id=position_id,
                            strategy=strategy,
                            signal_id=signal_id,
                            contract_address=contract,
                            entry_time=pd.to_datetime(pos_row.get("entry_time")) if pd.notna(pos_row.get("entry_time")) else None,
                            exit_time=pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                            reason=pos_row.get("reason"),
                            anomaly_type=AnomalyType.EXECUTION_PRICE_OUT_OF_RANGE,
                            severity="P1",
                            details={
                                "execution_type": exec_event_type,
                                "execution_price": exec_price,
                                "position_price": exit_price,
                                "price_diff_pct": price_diff_pct,
                            },
                        ))
    
    def _check_decision_proofs(
        self,
        positions_df: pd.DataFrame,
        events_df: pd.DataFrame,
        indices: "AuditIndices",
    ) -> None:
        """P2: Проверка доказательств решений (reset/prune/close-all)."""
        # P2.1: Profit reset proof
        self._check_profit_reset_proof(events_df, positions_df)
        
        # P2.2: Capacity proof (будет реализовано позже)
        # self._check_capacity_proof(events_df, positions_df, indices)
        
        # P2.2: Close-all proof (будет реализовано позже)
        # self._check_close_all_proof(events_df, positions_df, indices)
    
    def _check_profit_reset_proof(
        self,
        events_df: pd.DataFrame,
        positions_df: pd.DataFrame,
    ) -> None:
        """P2.1: Проверка доказательства profit reset."""
        # Ищем события PROFIT_RESET_TRIGGERED
        event_type_series = self._series(events_df, "event_type", "")
        profit_reset_events = events_df[
            event_type_series.str.contains("PROFIT_RESET|profit_reset", case=False, na=False)
        ]
        
        for _, event_row in profit_reset_events.iterrows():
            # Извлекаем данные из meta (если есть)
            meta_str = event_row.get("meta_json") or event_row.get("meta") or "{}"
            try:
                if isinstance(meta_str, str):
                    import json
                    meta = json.loads(meta_str)
                else:
                    meta = meta_str if isinstance(meta_str, dict) else {}
            except Exception:
                meta = {}
            
            # Пытаемся извлечь cycle_start_equity, equity_peak_in_cycle, profit_reset_multiple
            cycle_start_equity = meta.get("cycle_start_equity")
            equity_peak_in_cycle = meta.get("equity_peak_in_cycle")
            profit_reset_multiple = meta.get("profit_reset_multiple")
            
            # Если данных нет в meta, пытаемся восстановить из equity_curve или positions
            # (упрощённая версия - для полной реализации нужно equity_curve)
            if cycle_start_equity is None or equity_peak_in_cycle is None:
                # Пропускаем проверку, если данных нет
                continue
            
            # Проверяем условие: equity_peak_in_cycle >= cycle_start_equity * profit_reset_multiple
            if profit_reset_multiple is None:
                profit_reset_multiple = 1.5  # Default значение (можно взять из конфига, но его нет в CSV)
            
            try:
                cycle_start_equity = float(cycle_start_equity)
                equity_peak_in_cycle = float(equity_peak_in_cycle)
                profit_reset_multiple = float(profit_reset_multiple)
                
                threshold = cycle_start_equity * profit_reset_multiple
                
                if equity_peak_in_cycle < threshold - self.EPSILON:
                    # Reset сработал, но условие не выполнено
                    self.anomalies.append(Anomaly(
                        position_id=None,
                        strategy="portfolio",
                        signal_id=event_row.get("signal_id"),
                        contract_address=event_row.get("contract_address"),
                        entry_time=None,
                        exit_time=pd.to_datetime(event_row.get("timestamp")) if pd.notna(event_row.get("timestamp")) else None,
                        entry_price=None,
                        exit_price=None,
                        pnl_pct=None,
                        reason="profit_reset",
                        anomaly_type=AnomalyType.PROFIT_RESET_TRIGGERED_BUT_CONDITION_FALSE,
                        severity="P2",
                        event_id=str(event_row.get("event_id", "")),
                        details={
                            "cycle_start_equity": cycle_start_equity,
                            "equity_peak_in_cycle": equity_peak_in_cycle,
                            "profit_reset_multiple": profit_reset_multiple,
                            "threshold": threshold,
                            "condition_met": equity_peak_in_cycle >= threshold,
                        },
                    ))
            except (ValueError, TypeError):
                # Не удалось преобразовать в числа - пропускаем
                pass


# Convenience functions
def normalize_reason(reason: str) -> str:
    """
    Нормализует reason для консистентной обработки.
    
    Правила нормализации:
    - "stop_loss" -> "sl"
    - "tp", "ladder_tp" -> "tp" (сохраняем как есть)
    - Остальные остаются без изменений
    
    :param reason: Исходная причина закрытия
    :return: Нормализованная причина
    """
    if not reason:
        return reason
    
    reason_lower = str(reason).lower()
    
    # Нормализуем stop_loss в sl
    if "stop_loss" in reason_lower or reason_lower == "sl":
        return "sl"
    
    # tp и его варианты (ladder_tp, tp_2x и т.д.) остаются как есть
    if "tp" in reason_lower:
        return "tp"
    
    # Возвращаем исходное значение
    return reason


def check_pnl_formula(entry_price: float, exit_price: float, pnl_pct: float, epsilon: float = 1e-6) -> bool:
    """Проверка формулы PnL для long позиции."""
    if entry_price <= 0:
        return False
    expected = (exit_price - entry_price) / entry_price
    return abs(pnl_pct - expected) < epsilon


def check_reason_consistency(reason: str, pnl_pct: float, epsilon: float = 1e-6) -> bool:
    """
    Проверка консистентности reason с PnL.
    
    Правила:
    - tp (и его варианты): требует pnl_pct >= -epsilon (неотрицательный с допуском)
    - sl/stop_loss: требует pnl_pct < 0 (строго отрицательный)
    
    :param reason: Причина закрытия позиции
    :param pnl_pct: PnL в процентах (десятичная форма, например 0.1 = 10%)
    :param epsilon: Погрешность для сравнения
    :return: True если reason согласуется с PnL, False иначе
    """
    normalized = normalize_reason(reason)
    
    if normalized == "tp":
        # tp требует неотрицательный PnL (с допуском epsilon)
        return pnl_pct >= -epsilon
    
    if normalized == "sl":
        # sl/stop_loss требует строго отрицательный PnL
        return pnl_pct < 0
    
    # Для остальных причин считаем валидным (нет ограничений)
    return True


def check_magic_values(pnl_pct: float, magic_values: List[float] = None, epsilon: float = 1e-6) -> bool:
    """Проверка на магические значения."""
    if magic_values is None:
        magic_values = [920.0, 920.0 / 100, -920.0, -920.0 / 100]
    return not any(abs(pnl_pct - mv) < epsilon for mv in magic_values)


def check_time_ordering(entry_time: datetime, exit_time: datetime) -> bool:
    """Проверка порядка времени."""
    return entry_time <= exit_time


def check_policy_consistency(closed_by_reset: bool, reset_events_count: int) -> bool:
    """Проверка консистентности политик."""
    if closed_by_reset:
        return reset_events_count > 0
    return True

