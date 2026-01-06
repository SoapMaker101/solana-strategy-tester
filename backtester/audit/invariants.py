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
    def _series(df: Optional[pd.DataFrame], col: str, default: Any = None) -> pd.Series:
        """
        Безопасное получение колонки из DataFrame.
        
        Если df is None или колонка не существует, возвращает пустой Series или Series с default значениями.
        Гарантирует, что возвращается Series, а не None или DataFrame.
        
        :param df: DataFrame (может быть None)
        :param col: Имя колонки
        :param default: Значение по умолчанию
        :return: pd.Series (никогда не None)
        """
        if df is None or df.empty:
            return pd.Series([], dtype="object")
        
        if col in df.columns:
            result = df[col]
            # Гарантируем, что возвращается Series, а не DataFrame
            if isinstance(result, pd.Series):
                return result
            else:
                # Если это DataFrame (не должно быть, но на всякий случай)
                return pd.Series([default] * len(df), index=df.index, dtype="object")
        else:
            return pd.Series([default] * len(df), index=df.index, dtype="object")
    
    @staticmethod
    def _dt_series(df: Optional[pd.DataFrame], col: str) -> pd.Series:
        """
        Безопасное получение datetime колонки из DataFrame.
        
        Внутри использует _series и pd.to_datetime с errors="coerce".
        НИКАКИХ вызовов pd.to_datetime на None.
        
        :param df: DataFrame (может быть None)
        :param col: Имя колонки
        :return: pd.Series с datetime типом (UTC)
        """
        s = InvariantChecker._series(df, col, None)
        if len(s) == 0:
            return pd.Series([], dtype="datetime64[ns, UTC]")
        # Применяем to_datetime только к Series, никогда к None
        return pd.to_datetime(s, utc=True, errors="coerce")
    
    @staticmethod
    def _str_series(df: Optional[pd.DataFrame], col: str) -> pd.Series:
        """
        Безопасное получение строковой колонки из DataFrame.
        
        Используется для strategy/signal_id/contract_address/position_id.
        Гарантирует, что возвращается Series[str] без None значений.
        
        :param df: DataFrame (может быть None)
        :param col: Имя колонки
        :return: pd.Series[str] (заполнено пустыми строками вместо None)
        """
        s = InvariantChecker._series(df, col, "")
        if len(s) == 0:
            return pd.Series([], dtype="string")
        # Конвертируем в string и заполняем None пустыми строками
        return s.astype("string").fillna("")
    
    @staticmethod
    def _safe_str(value: Any, default: str = "") -> str:
        """
        Безопасное преобразование значения в строку.
        
        :param value: Значение (может быть None, Unknown, и т.д.)
        :param default: Значение по умолчанию, если value is None или NaN
        :return: str (никогда не None, всегда строка)
        """
        if value is None or pd.isna(value):
            return default
        result = str(value)
        return result if result else default
    
    @staticmethod
    def _safe_dt(value: Any) -> Optional[datetime]:
        """
        Безопасное преобразование значения в datetime.
        
        НИКАКИХ вызовов pd.to_datetime на None.
        
        :param value: Значение (может быть None, Unknown, и т.д.)
        :return: datetime или None
        """
        if value is None or pd.isna(value):
            return None
        # Применяем to_datetime только к не-None значениям
        result = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(result):
            return None
        return result.to_pydatetime() if hasattr(result, 'to_pydatetime') else result
    
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
        
        # Определяем effective executions_df: используем переданный или строим из events
        effective_executions_df = executions_df
        if effective_executions_df is None or len(effective_executions_df) == 0:
            # Пустой или None - строим из events
            if events_df is not None and len(events_df) > 0:
                effective_executions_df = self.build_executions_from_events(events_df)
        else:
            # executions_df не пустой - проверяем наличие нужных колонок
            required_cols = ["event_time", "event_type"]
            has_required_cols = all(col in effective_executions_df.columns for col in required_cols)
            if not has_required_cols:
                # Нет нужных колонок - строим из events
                if events_df is not None and len(events_df) > 0:
                    effective_executions_df = self.build_executions_from_events(events_df)
        
        indices = AuditIndices(events_df=events_df, executions_df=effective_executions_df)
        
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
        
        # P0: Проверка событий
        # Если events_df не None (даже пустой), проверяем цепочку событий
        # _check_events_chain корректно обрабатывает пустой DataFrame
        if events_df is not None:
            self._check_events_chain(positions_df, events_df)
        
        # Policy consistency требует непустой events_df
        if events_df is not None and len(events_df) > 0:
            self._check_policy_consistency(positions_df, events_df)
        
        # P1: Cross-check positions ↔ events ↔ executions
        if self.include_p1:
            self._check_positions_events_consistency(positions_df, indices)
            self._check_events_executions_consistency(positions_df, indices, events_df, effective_executions_df)
        
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
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(row.get("entry_time")),
                exit_time=self._safe_dt(row.get("exit_time")),
                entry_price=row.get("entry_price") if pd.notna(row.get("entry_price")) else None,
                exit_price=row.get("exit_price") if pd.notna(row.get("exit_price")) else None,
                pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                reason=self._safe_str(row.get("reason")) or None,
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
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(row.get("entry_time")),
                exit_time=self._safe_dt(row.get("exit_time")),
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                reason=self._safe_str(row.get("reason")) or None,
                anomaly_type=AnomalyType.ENTRY_PRICE_INVALID,
                severity="P0",
                details={"entry_price": entry_price},
            ))
        
        # Проверка exit_price (только для закрытых позиций)
        status_val = self._safe_str(row.get("status"))
        if status_val == "closed":
            if pd.isna(exit_price) or exit_price <= self.MIN_VALID_PRICE:
                self.anomalies.append(Anomaly(
                    position_id=self._safe_str(row.get("position_id")) or None,
                    strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                    signal_id=self._safe_str(row.get("signal_id")) or None,
                    contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                    entry_time=self._safe_dt(row.get("entry_time")),
                    exit_time=self._safe_dt(row.get("exit_time")),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                    reason=self._safe_str(row.get("reason")) or None,
                anomaly_type=AnomalyType.EXIT_PRICE_INVALID,
                severity="P0",
                details={"exit_price": exit_price},
            ))
    
    def _check_pnl(self, row: pd.Series) -> None:
        """Проверка формулы PnL и разумности значений."""
        status_val = self._safe_str(row.get("status"))
        if status_val != "closed":
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
                    position_id=self._safe_str(row.get("position_id")) or None,
                    strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                    signal_id=self._safe_str(row.get("signal_id")) or None,
                    contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                    entry_time=self._safe_dt(row.get("entry_time")),
                    exit_time=self._safe_dt(row.get("exit_time")),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=pnl_pct,
                    reason=self._safe_str(row.get("reason")) or None,
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
        status_val = self._safe_str(row.get("status"))
        if status_val != "closed":
            return
        
        reason = row.get("reason") or row.get("exit_reason")
        pnl_pct = row.get("pnl_pct") or row.get("pnl_sol")
        
        reason_str = self._safe_str(reason) if reason is not None else ""
        if not reason_str or pd.isna(pnl_pct):
            return
        
        # Нормализуем reason для консистентной проверки
        normalized_reason = normalize_reason(reason_str)
        
        # Проверка: reason=tp, но pnl < 0 (строго отрицательный)
        if normalized_reason == "tp" and pnl_pct < -self.EPSILON:
            self.anomalies.append(Anomaly(
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(row.get("entry_time")),
                exit_time=self._safe_dt(row.get("exit_time")),
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=pnl_pct,
                reason=reason_str,
                anomaly_type=AnomalyType.TP_REASON_BUT_NEGATIVE_PNL,
                severity="P0",
                details={"pnl_pct": pnl_pct, "reason": reason_str, "normalized_reason": normalized_reason},
            ))
        
        # Проверка: reason=sl/stop_loss, но pnl >= 0 (неотрицательный) - строго < 0 согласно ТЗ
        if normalized_reason == "sl" and pnl_pct >= 0:
            self.anomalies.append(Anomaly(
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(row.get("entry_time")),
                exit_time=self._safe_dt(row.get("exit_time")),
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=pnl_pct,
                reason=reason_str,
                anomaly_type=AnomalyType.SL_REASON_BUT_POSITIVE_PNL,
                severity="P0",
                details={"pnl_pct": pnl_pct, "reason": reason_str, "normalized_reason": normalized_reason},
            ))
    
    def _check_time_ordering(self, row: pd.Series) -> None:
        """Проверка порядка времени."""
        status_val = self._safe_str(row.get("status"))
        if status_val != "closed":
            return
        
        entry_time = row.get("entry_time")
        exit_time = row.get("exit_time")
        
        if pd.isna(entry_time) or pd.isna(exit_time):
            return
        
        entry_dt = self._safe_dt(entry_time)
        exit_dt = self._safe_dt(exit_time)
        
        if entry_dt is None or exit_dt is None:
            return
        
        if entry_dt > exit_dt:
            self.anomalies.append(Anomaly(
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=entry_dt,
                exit_time=exit_dt,
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=row.get("pnl_pct") if pd.notna(row.get("pnl_pct")) else None,
                reason=self._safe_str(row.get("reason")) or None,
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
                    position_id=self._safe_str(row.get("position_id")) or None,
                    strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                    signal_id=self._safe_str(row.get("signal_id")) or None,
                    contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                    entry_time=self._safe_dt(row.get("entry_time")),
                    exit_time=self._safe_dt(row.get("exit_time")),
                    entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                    exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                    pnl_pct=pnl_pct,
                    reason=self._safe_str(row.get("reason")) or None,
                    anomaly_type=AnomalyType.PNL_CAP_OR_MAGIC,
                    severity="P0",
                    details={"pnl_pct": pnl_pct, "magic_value": "920%"},
                ))
    
    def _check_events_chain(self, positions_df: pd.DataFrame, events_df: pd.DataFrame) -> None:
        """Проверка цепочки событий для каждой позиции."""
        # Для каждой закрытой позиции проверяем наличие событий по position_id
        for _, pos_row in positions_df.iterrows():
            status_val = self._safe_str(pos_row.get("status"))
            if status_val != "closed":
                continue
            
            position_id = self._safe_str(pos_row.get("position_id")) or None
            signal_id = self._safe_str(pos_row.get("signal_id")) or None
            strategy = self._safe_str(pos_row.get("strategy"), "UNKNOWN")
            contract = self._safe_str(pos_row.get("contract_address"), "UNKNOWN")
            
            # Ищем события для этой позиции по position_id (требование: проверка по position_id)
            if position_id and pd.notna(position_id):
                pos_id_series = self._series(events_df, "position_id", None)
                # Используем явную проверку вместо truthiness
                pos_events = events_df[pos_id_series == position_id]
                # Если events_df имеет zero rows для этого position_id -> MISSING_EVENTS_CHAIN
                if len(pos_events) == 0:
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=strategy,
                        signal_id=signal_id,
                        contract_address=contract,
                        entry_time=self._safe_dt(pos_row.get("entry_time")),
                        exit_time=self._safe_dt(pos_row.get("exit_time")),
                        entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                        exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                        reason=self._safe_str(pos_row.get("reason")) or None,
                        anomaly_type=AnomalyType.MISSING_EVENTS_CHAIN,
                        severity="P0",
                        details={"events_count": 0, "position_id": position_id},
                    ))
    
    def _check_policy_consistency(self, positions_df: pd.DataFrame, events_df: pd.DataFrame) -> None:
        """Проверка консистентности политик (reset, prune)."""
        # Проверяем позиции, закрытые по reset/prune
        # Используем безопасное получение колонок
        closed_by_reset_series = self._series(positions_df, "closed_by_reset", False)
        reset_reason_series = self._series(events_df, "reset_reason", None)
        
        # Используем явные проверки вместо truthiness
        reset_positions = positions_df[
            (closed_by_reset_series == True) |
            (reset_reason_series.notna())
        ]
        
        for _, pos_row in reset_positions.iterrows():
            position_id = self._safe_str(pos_row.get("position_id")) or None
            signal_id = self._safe_str(pos_row.get("signal_id")) or None
            strategy = self._safe_str(pos_row.get("strategy"), "UNKNOWN")
            contract = self._safe_str(pos_row.get("contract_address"), "UNKNOWN")
            
            # Ищем события reset/prune
            event_type_series = self._series(events_df, "event_type", "")
            if position_id and pd.notna(position_id):
                pos_id_series = self._series(events_df, "position_id", None)
                reset_events = events_df[
                    (pos_id_series == position_id) &
                    (event_type_series.str.contains("RESET|PRUNE", case=False, na=False))
                ]
            else:
                signal_id_series = self._series(events_df, "signal_id", None)
                strategy_series = self._series(events_df, "strategy", None)
                contract_series = self._series(events_df, "contract_address", None)
                reset_events = events_df[
                    (signal_id_series == signal_id) &
                    (strategy_series == strategy) &
                    (contract_series == contract) &
                    (event_type_series.str.contains("RESET|PRUNE", case=False, na=False))
                ]
            
            if len(reset_events) == 0:
                self.anomalies.append(Anomaly(
                    position_id=position_id,
                    strategy=strategy,
                    signal_id=signal_id,
                    contract_address=contract,
                    entry_time=self._safe_dt(pos_row.get("entry_time")),
                    exit_time=self._safe_dt(pos_row.get("exit_time")),
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=self._safe_str(pos_row.get("reason")) or None,
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
            position_id = self._safe_str(pos_row.get("position_id")) or None
            signal_id = self._safe_str(pos_row.get("signal_id")) or None
            strategy = self._safe_str(pos_row.get("strategy"), "UNKNOWN")
            contract = self._safe_str(pos_row.get("contract_address"), "UNKNOWN")
            status = self._safe_str(pos_row.get("status")) or "open"
            
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
                    entry_time=self._safe_dt(pos_row.get("entry_time")),
                    exit_time=self._safe_dt(pos_row.get("exit_time")),
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=self._safe_str(pos_row.get("reason")) or None,
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
                    entry_time=self._safe_dt(pos_row.get("entry_time")),
                    exit_time=self._safe_dt(pos_row.get("exit_time")),
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=self._safe_str(pos_row.get("reason")) or None,
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
                    entry_time=self._safe_dt(pos_row.get("entry_time")),
                    exit_time=self._safe_dt(pos_row.get("exit_time")),
                    entry_price=pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price"),
                    exit_price=pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price"),
                    pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                    reason=self._safe_str(pos_row.get("reason")) or None,
                    anomaly_type=AnomalyType.MULTIPLE_OPEN_EVENTS,
                    severity="P1",
                    event_id=event_ids[0] if event_ids else None,
                    details={"open_events_count": len(open_events), "event_ids": event_ids},
                ))
            
            # Проверка: несколько событий закрытия (если должно быть 1)
            if len(close_events) > 1:
                # Для обычных закрытий (tp/sl/timeout) должно быть 1 событие
                reason = self._safe_str(pos_row.get("reason")) or ""
                if reason not in ["prune", "reset", "close_all"]:
                    event_ids = [str(e.get("event_id", i)) for i, e in enumerate(close_events)]
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=strategy,
                        signal_id=signal_id,
                        contract_address=contract,
                        entry_time=self._safe_dt(pos_row.get("entry_time")),
                        exit_time=self._safe_dt(pos_row.get("exit_time")),
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
            reason = self._safe_str(pos_row.get("reason")) or None
            if reason and status == "closed" and len(close_events) > 0:
                # Нормализуем reason для консистентного маппинга
                normalized_reason = normalize_reason(str(reason))
                expected_event_types = self._get_expected_event_types_for_reason(normalized_reason)
                
                if expected_event_types:
                    # Получаем фактические типы событий закрытия
                    actual_event_types = [str(e.get("event_type", "")).strip() for e in close_events]
                    actual_event_types_lower = [et.lower() for et in actual_event_types]
                    
                    # Проверяем соответствие: ищем точное совпадение
                    # НЕ используем подстроку, чтобы избежать ложных совпадений
                    # (например, "close" не должно совпадать с "closed_by_capacity_prune")
                    matches = False
                    expected_event_types_lower = [et.lower() for et in expected_event_types]
                    
                    for actual_et_lower in actual_event_types_lower:
                        # Точное совпадение
                        if actual_et_lower in expected_event_types_lower:
                            matches = True
                            break
                    
                    # Дополнительная проверка для канонических типов (POSITION_CLOSED)
                    # Если событие POSITION_CLOSED, проверяем meta/reset_reason для reset/prune
                    if not matches:
                        for event in close_events:
                            event_type = str(event.get("event_type", "")).strip().upper()
                            if event_type == "POSITION_CLOSED":
                                # Для POSITION_CLOSED проверяем meta/reset_reason
                                import json
                                meta_json = event.get("meta_json")
                                meta = event.get("meta")
                                meta_dict = {}
                                if meta_json and pd.notna(meta_json):
                                    try:
                                        meta_dict = json.loads(str(meta_json))
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                elif meta and isinstance(meta, dict):
                                    meta_dict = meta
                                elif meta and isinstance(meta, str):
                                    try:
                                        meta_dict = json.loads(meta)
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                
                                reset_reason = meta_dict.get("reset_reason") or meta_dict.get("close_reason")
                                if reset_reason:
                                    reset_reason_lower = str(reset_reason).lower()
                                    # Для reason="tp" не должно быть reset_reason
                                    if normalized_reason == "tp" and reset_reason_lower in ("profit_reset", "capacity_prune"):
                                        matches = False  # Несоответствие
                                    # Для reason="profit_reset" или "capacity_prune" проверяем reset_reason
                                    elif normalized_reason in ("reset", "prune"):
                                        if (normalized_reason == "reset" and "profit_reset" in reset_reason_lower) or \
                                           (normalized_reason == "prune" and "capacity_prune" in reset_reason_lower):
                                            matches = True
                                else:
                                    # POSITION_CLOSED без reset_reason - подходит для tp/sl/timeout
                                    if normalized_reason in ("tp", "sl", "timeout"):
                                        matches = True
                    
                    if not matches:
                        self.anomalies.append(Anomaly(
                            position_id=position_id,
                            strategy=strategy,
                            signal_id=signal_id,
                            contract_address=contract,
                            entry_time=self._safe_dt(pos_row.get("entry_time")),
                            exit_time=self._safe_dt(pos_row.get("exit_time")),
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
        
        Поддерживает:
        - Канонические типы: POSITION_CLOSED (новый мир)
        - Legacy типы: closed_by_*, executed_close, capacity_prune, profit_reset и т.д.
        """
        # reason уже должен быть нормализован
        mapping = {
            "tp": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy (убрали "close" и "exit" - слишком общие)
                "closed_by_take_profit", "closed_by_tp",  # Legacy варианты
            ],
            "sl": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy (убрали "close" и "exit" - слишком общие)
                "closed_by_stop_loss", "closed_by_sl",  # Legacy варианты
            ],
            "timeout": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy (убрали "close" и "exit" - слишком общие)
                "closed_by_timeout", "closed_by_max_hold",  # Legacy варианты
            ],
            "prune": [
                "POSITION_CLOSED",  # Канонический тип (с reset_reason="capacity_prune" в meta)
                "capacity_prune", "closed_by_capacity_prune", "prune",  # Legacy
            ],
            "reset": [
                "POSITION_CLOSED",  # Канонический тип (с reset_reason="profit_reset" в meta)
                "profit_reset", "closed_by_profit_reset", "reset",  # Legacy
            ],
            "close_all": [
                "POSITION_CLOSED",  # Канонический тип
                "close_all", "closed_by_capacity_close_all",  # Legacy
            ],
        }
        return mapping.get(reason, [])
    
    @staticmethod
    def build_executions_from_events(events_df: pd.DataFrame) -> pd.DataFrame:
        """
        Строит executions DataFrame из events DataFrame.
        
        Извлекает execution данные из meta_json (или meta) trade-related событий.
        
        Trade-related события определяются по каноническим типам:
        - POSITION_OPENED
        - POSITION_PARTIAL_EXIT
        - POSITION_CLOSED
        
        Args:
            events_df: DataFrame с событиями (portfolio_events.csv)
            
        Returns:
            DataFrame с executions (колонки: signal_id, strategy, event_time, event_type, ...)
        """
        import json
        
        trade_event_types = {"POSITION_OPENED", "POSITION_PARTIAL_EXIT", "POSITION_CLOSED"}
        
        executions_rows = []
        
        for _, row in events_df.iterrows():
            event_type = str(row.get("event_type", "")).upper()
            
            # Пропускаем не trade-related события
            if event_type not in trade_event_types:
                continue
            
            # Пытаемся извлечь meta из meta_json или meta
            meta = {}
            if "meta_json" in row and pd.notna(row.get("meta_json")):
                try:
                    meta_str = str(row.get("meta_json"))
                    if meta_str:
                        meta = json.loads(meta_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif "meta" in row and pd.notna(row.get("meta")):
                meta_val = row.get("meta")
                if isinstance(meta_val, dict):
                    meta = meta_val
                elif isinstance(meta_val, str):
                    try:
                        meta = json.loads(meta_val)
                    except (json.JSONDecodeError, TypeError):
                        pass
            
            # Извлекаем execution данные из meta
            execution_type = meta.get("execution_type")
            if not execution_type:
                continue  # Нет execution данных в meta
            
            # Собираем строку execution
            execution_row = {
                "signal_id": row.get("signal_id"),
                "strategy": row.get("strategy"),
                "event_time": row.get("timestamp"),  # timestamp события = event_time execution
                "event_type": execution_type,  # execution_type из meta
                "event_id": row.get("event_id"),  # ссылка на event
                "position_id": row.get("position_id"),
                "qty_delta": meta.get("qty_delta"),
                "raw_price": meta.get("raw_price"),
                "exec_price": meta.get("exec_price"),
                "fees_sol": meta.get("fees_sol"),
                "pnl_sol_delta": meta.get("pnl_sol_delta"),
                "reason": row.get("reason"),  # reason из события
            }
            
            executions_rows.append(execution_row)
        
        if not executions_rows:
            # Возвращаем пустой DataFrame с правильными колонками
            return pd.DataFrame(columns=[
                "signal_id", "strategy", "event_time", "event_type", "event_id",
                "position_id", "qty_delta", "raw_price", "exec_price", "fees_sol", "pnl_sol_delta", "reason"
            ])
        
        return pd.DataFrame(executions_rows)
    
    def _check_events_executions_consistency(
        self,
        positions_df: pd.DataFrame,
        indices: "AuditIndices",
        events_df: Optional[pd.DataFrame] = None,
        executions_df: Optional[pd.DataFrame] = None,
    ) -> None:
        """P1: Проверка консистентности events ↔ executions по контракту."""
        import json
        
        # Определяем trade-related события (канонические типы)
        trade_event_types = {"POSITION_OPENED", "POSITION_PARTIAL_EXIT", "POSITION_CLOSED"}
        
        # Маппинг event_type -> execution_type
        event_to_exec_type = {
            "POSITION_OPENED": "entry",
            "POSITION_PARTIAL_EXIT": "partial_exit",
            "POSITION_CLOSED": "final_exit",
        }
        
        # Проверяем, есть ли executions_df с нужными колонками
        has_executions_df = (
            executions_df is not None 
            and len(executions_df) > 0 
            and "event_time" in executions_df.columns 
            and "event_type" in executions_df.columns
        )
        
        # Получаем все trade-events глобально
        all_trade_events = []
        if events_df is not None and len(events_df) > 0:
            for _, row in events_df.iterrows():
                event_type = str(row.get("event_type", "")).upper()
                if event_type in trade_event_types:
                    all_trade_events.append(row.to_dict())
        
        # Создаем индекс позиций для быстрого поиска
        positions_by_signal = {}
        for _, pos_row in positions_df.iterrows():
            signal_id = self._safe_str(pos_row.get("signal_id")) or None
            strategy = self._safe_str(pos_row.get("strategy"), "UNKNOWN")
            if signal_id and strategy:
                key = (strategy, signal_id)
                if key not in positions_by_signal:
                    positions_by_signal[key] = []
                positions_by_signal[key].append(pos_row)
        
        # 1. TRADE_EVENT_WITHOUT_EXECUTION: проверяем каждое trade-event
        for event in all_trade_events:
            event_time = self._safe_dt(event.get("timestamp"))
            event_type = str(event.get("event_type", "")).upper()
            event_signal_id = self._safe_str(event.get("signal_id")) or None
            event_strategy = self._safe_str(event.get("strategy"), "UNKNOWN")
            event_id = self._safe_str(event.get("event_id")) or None
            
            # Находим соответствующую позицию
            pos_row = None
            if event_signal_id and event_strategy:
                key = (event_strategy, event_signal_id)
                if key in positions_by_signal and len(positions_by_signal[key]) > 0:
                    pos_row = positions_by_signal[key][0]  # Берем первую
            
            has_execution = False
            
            if has_executions_df:
                # Ищем execution в executions_df по (signal_id, strategy, event_time, event_type)
                expected_exec_type = event_to_exec_type.get(event_type)
                if expected_exec_type and event_time and event_signal_id and event_strategy:
                    for _, exec_row in executions_df.iterrows():
                        exec_signal_id = self._safe_str(exec_row.get("signal_id")) or None
                        exec_strategy = self._safe_str(exec_row.get("strategy"), "UNKNOWN")
                        exec_time = self._safe_dt(exec_row.get("event_time"))
                        exec_type = str(exec_row.get("event_type", "")).lower()
                        exec_event_id = self._safe_str(exec_row.get("event_id")) or None
                        
                        # Матчинг по event_id (приоритет)
                        if event_id and exec_event_id and event_id == exec_event_id:
                            has_execution = True
                            break
                        
                        # Матчинг по (signal_id, strategy, event_time, event_type)
                        # Разрешаем точное совпадение или разницу <= 0 секунд (допускаем в пределах 0 секунд)
                        if (exec_signal_id == event_signal_id and 
                            exec_strategy == event_strategy and
                            exec_time and event_time and
                            abs((exec_time - event_time).total_seconds()) <= 0 and
                            exec_type == expected_exec_type):
                            has_execution = True
                            break
            else:
                # executions_df пустой или нет нужных колонок - проверяем meta_json
                meta_json = event.get("meta_json")
                meta = event.get("meta")
                
                # Пытаемся извлечь meta
                meta_dict = {}
                if meta_json and pd.notna(meta_json):
                    try:
                        meta_dict = json.loads(str(meta_json))
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif meta and isinstance(meta, dict):
                    meta_dict = meta
                elif meta and isinstance(meta, str):
                    try:
                        meta_dict = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                # Проверяем наличие execution_type в meta
                if meta_dict.get("execution_type"):
                    has_execution = True
            
            if not has_execution:
                # Создаем anomaly
                position_id = self._safe_str(event.get("position_id")) or None
                contract = self._safe_str(event.get("contract_address"), "UNKNOWN")
                
                self.anomalies.append(Anomaly(
                    position_id=position_id,
                    strategy=self._safe_str(event_strategy, "UNKNOWN"),
                    signal_id=event_signal_id,
                    contract_address=contract,
                    entry_time=self._safe_dt(pos_row.get("entry_time")) if pos_row is not None else None,
                    exit_time=self._safe_dt(pos_row.get("exit_time")) if pos_row is not None else None,
                    entry_price=pos_row.get("exec_entry_price") if pos_row is not None else None,
                    exit_price=pos_row.get("exec_exit_price") if pos_row is not None else None,
                    pnl_pct=pos_row.get("pnl_pct") if pos_row is not None else None,
                    reason=self._safe_str(pos_row.get("reason")) if pos_row is not None else None,
                    anomaly_type=AnomalyType.TRADE_EVENT_WITHOUT_EXECUTION,
                    severity="P1",
                    event_id=event_id,
                    details={
                        "event_type": event_type,
                        "event_time": event_time.isoformat() if event_time else None,
                        "has_executions_df": has_executions_df,
                    },
                ))
        
        # 2. EXECUTION_WITHOUT_TRADE_EVENT: проверяем каждое execution (если есть executions_df)
        if has_executions_df:
            for _, exec_row in executions_df.iterrows():
                exec_signal_id = str(exec_row.get("signal_id", "")) if pd.notna(exec_row.get("signal_id")) else None
                exec_strategy = str(exec_row.get("strategy", "")) if pd.notna(exec_row.get("strategy")) else None
                exec_time = self._safe_dt(exec_row.get("event_time"))
                exec_type = str(exec_row.get("event_type", "")).lower()
                exec_event_id = str(exec_row.get("event_id", "")) if pd.notna(exec_row.get("event_id")) else None
                
                # Находим соответствующую позицию
                pos_row = None
                if exec_signal_id and exec_strategy:
                    key = (exec_strategy, exec_signal_id)
                    if key in positions_by_signal and len(positions_by_signal[key]) > 0:
                        pos_row = positions_by_signal[key][0]
                
                # Ищем соответствующее событие
                matching_event = None
                
                # Поиск по event_id (приоритет)
                if exec_event_id:
                    for event in all_trade_events:
                        event_id = str(event.get("event_id", "")) if pd.notna(event.get("event_id")) else None
                        if event_id and event_id == exec_event_id:
                            matching_event = event
                            break
                
                # Поиск по (signal_id, strategy, timestamp)
                if not matching_event and exec_time and exec_signal_id and exec_strategy:
                    for event in all_trade_events:
                        event_signal_id = self._safe_str(event.get("signal_id")) or None
                        event_strategy = self._safe_str(event.get("strategy"), "UNKNOWN")
                        event_time = self._safe_dt(event.get("timestamp"))
                        event_type = str(event.get("event_type", "")).upper()
                        
                        # Матчинг по (signal_id, strategy) и типам, допускаем небольшую разницу во времени для проверки EXECUTION_TIME_BEFORE_EVENT
                        time_diff = abs((event_time - exec_time).total_seconds()) if event_time and exec_time else float('inf')
                        if (event_signal_id == exec_signal_id and
                            event_strategy == exec_strategy):
                            # Проверяем соответствие типов
                            expected_exec_type = event_to_exec_type.get(event_type)
                            if expected_exec_type and exec_type == expected_exec_type:
                                # Для точного матчинга требуем <= 0 секунд, для проверки времени допускаем разницу
                                if time_diff <= 0:
                                    matching_event = event
                                    break
                                # Если не точное совпадение, но типы совпадают, тоже считаем match для проверки времени
                                elif time_diff <= 3600:  # До 1 часа для проверки EXECUTION_TIME_BEFORE_EVENT
                                    if matching_event is None:  # Берем первый подходящий
                                        matching_event = event
                
                if not matching_event:
                    # Создаем anomaly
                    position_id = exec_row.get("position_id")
                    contract = self._safe_str(exec_row.get("contract_address"), "UNKNOWN")
                    
                    self.anomalies.append(Anomaly(
                        position_id=position_id,
                        strategy=self._safe_str(exec_strategy, "UNKNOWN"),
                        signal_id=exec_signal_id,
                        contract_address=contract,
                    entry_time=self._safe_dt(pos_row.get("entry_time")) if pos_row is not None else None,
                    exit_time=self._safe_dt(pos_row.get("exit_time")) if pos_row is not None else None,
                        entry_price=pos_row.get("exec_entry_price") if pos_row is not None else None,
                        exit_price=pos_row.get("exec_exit_price") if pos_row is not None else None,
                        pnl_pct=pos_row.get("pnl_pct") if pos_row is not None else None,
                        reason=pos_row.get("reason") if pos_row is not None else None,
                        anomaly_type=AnomalyType.EXECUTION_WITHOUT_TRADE_EVENT,
                        severity="P1",
                        details={
                            "execution_type": exec_type,
                            "execution_time": exec_time.isoformat() if exec_time else None,
                        },
                    ))
                else:
                    # 3. EXECUTION_TIME_BEFORE_EVENT: проверяем, что execution не раньше события
                    # Для этой проверки нужно найти matching событие по (signal_id, strategy, event_type)
                    # даже если время немного отличается
                    matching_event_for_time_check = matching_event
                    if not matching_event_for_time_check:
                        # Ищем событие для проверки времени по (signal_id, strategy, event_type)
                        exec_event_type_for_match = exec_type
                        # Маппинг execution_type -> event_type для поиска
                        exec_to_event_type = {
                            "entry": "POSITION_OPENED",
                            "partial_exit": "POSITION_PARTIAL_EXIT",
                            "final_exit": "POSITION_CLOSED",
                            "forced_close": "POSITION_CLOSED",
                        }
                        expected_event_type = exec_to_event_type.get(exec_event_type_for_match)
                        
                        if expected_event_type and exec_signal_id and exec_strategy:
                            for event in all_trade_events:
                                event_signal_id = self._safe_str(event.get("signal_id")) or None
                                event_strategy = self._safe_str(event.get("strategy"), "UNKNOWN")
                                event_type = str(event.get("event_type", "")).upper()
                                
                                if (event_signal_id == exec_signal_id and
                                    event_strategy == exec_strategy and
                                    event_type == expected_event_type):
                                    matching_event_for_time_check = event
                                    break
                    
                    event_time = self._safe_dt(matching_event_for_time_check.get("timestamp")) if matching_event_for_time_check else None
                    if exec_time and event_time and exec_time < event_time:
                        position_id = matching_event.get("position_id")
                        contract = self._safe_str(matching_event.get("contract_address"), "UNKNOWN")
                        
                        self.anomalies.append(Anomaly(
                            position_id=position_id,
                            strategy=self._safe_str(exec_strategy, "UNKNOWN"),
                            signal_id=exec_signal_id,
                            contract_address=contract,
                    entry_time=self._safe_dt(pos_row.get("entry_time")) if pos_row is not None else None,
                    exit_time=self._safe_dt(pos_row.get("exit_time")) if pos_row is not None else None,
                            entry_price=pos_row.get("exec_entry_price") if pos_row is not None else None,
                            exit_price=pos_row.get("exec_exit_price") if pos_row is not None else None,
                            pnl_pct=pos_row.get("pnl_pct") if pos_row is not None else None,
                            reason=pos_row.get("reason") if pos_row is not None else None,
                            anomaly_type=AnomalyType.EXECUTION_TIME_BEFORE_EVENT,
                            severity="P1",
                            event_id=str(matching_event.get("event_id", "")),
                            details={
                                "event_time": event_time.isoformat(),
                                "execution_time": exec_time.isoformat(),
                                "diff_seconds": (event_time - exec_time).total_seconds(),
                            },
                        ))
                    
                    # 4. EXECUTION_PRICE_OUT_OF_RANGE: проверяем цены
                    if pos_row is not None:
                        entry_price = pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price")
                        exit_price = pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price")
                        exec_price = exec_row.get("exec_price")
                        
                        if exec_price and pd.notna(exec_price) and exec_price > 0:
                            # Для entry: сравниваем с entry_price
                            if exec_type == "entry" and entry_price:
                                price_diff_pct = abs(exec_price - entry_price) / entry_price
                                if price_diff_pct > 0.5:  # Более 50% разница
                                    position_id = matching_event.get("position_id")
                                    contract = self._safe_str(matching_event.get("contract_address"), "UNKNOWN")
                                    
                                    self.anomalies.append(Anomaly(
                                        position_id=position_id,
                                        strategy=self._safe_str(exec_strategy, "UNKNOWN"),
                                        signal_id=exec_signal_id,
                                        contract_address=contract,
                                        entry_time=self._safe_dt(pos_row.get("entry_time")),
                                        exit_time=self._safe_dt(pos_row.get("exit_time")),
                                        entry_price=entry_price,
                                        exit_price=exit_price,
                                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                                        reason=pos_row.get("reason"),
                                        anomaly_type=AnomalyType.EXECUTION_PRICE_OUT_OF_RANGE,
                                        severity="P1",
                                        details={
                                            "execution_type": exec_type,
                                            "execution_price": exec_price,
                                            "position_price": entry_price,
                                            "price_diff_pct": price_diff_pct,
                                        },
                                    ))
                            
                            # Для exit: сравниваем с exit_price
                            if exec_type in ("partial_exit", "final_exit", "forced_close") and exit_price:
                                price_diff_pct = abs(exec_price - exit_price) / exit_price
                                if price_diff_pct > 0.5:  # Более 50% разница
                                    position_id = matching_event.get("position_id")
                                    contract = self._safe_str(matching_event.get("contract_address"), "UNKNOWN")
                                    
                                    self.anomalies.append(Anomaly(
                                        position_id=position_id,
                                        strategy=self._safe_str(exec_strategy, "UNKNOWN"),
                                        signal_id=exec_signal_id,
                                        contract_address=contract,
                                        entry_time=self._safe_dt(pos_row.get("entry_time")),
                                        exit_time=self._safe_dt(pos_row.get("exit_time")),
                                        entry_price=entry_price,
                                        exit_price=exit_price,
                                        pnl_pct=pos_row.get("pnl_pct") if pd.notna(pos_row.get("pnl_pct")) else None,
                                        reason=pos_row.get("reason"),
                                        anomaly_type=AnomalyType.EXECUTION_PRICE_OUT_OF_RANGE,
                                        severity="P1",
                                        details={
                                            "execution_type": exec_type,
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
                        signal_id=self._safe_str(event_row.get("signal_id")) or None,
                        contract_address=self._safe_str(event_row.get("contract_address"), "UNKNOWN"),
                        entry_time=None,
                        exit_time=self._safe_dt(event_row.get("timestamp")),
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


def check_magic_values(pnl_pct: float, magic_values: Optional[List[float]] = None, epsilon: float = 1e-6) -> bool:
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

