# backtester/audit/invariants.py
# Инварианты и проверки для аудита
#
# ВАЖНО: Запрещено использование truthiness проверок на NDFrame (DataFrame/Series).
# Вместо `if df:` или `if series:` используйте явные проверки:
# - `df is not None and not df.empty`
# - `s is not None and len(s) > 0`
# - `s.notna().any()` для проверки наличия не-NaN значений
# - `(s.astype("string") != "").any()` для строковых Series

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import math

import pandas as pd

# Импорт AuditIndices для использования в методах
from .indices import AuditIndices


# Канонические причины закрытия позиций
CANONICAL_REASONS = {
    "ladder_tp",
    "stop_loss",
    "time_stop",
    "capacity_prune",
    "profit_reset",
    "manual_close",
    "no_entry",
    "error",
    "max_hold_minutes",
}

# Алиасы для legacy причин
REASON_ALIASES = {
    "tp": "ladder_tp",
    "sl": "stop_loss",
    "timeout": "time_stop",
}


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
    def _num_series(df: Optional[pd.DataFrame], col: str) -> pd.Series:
        """
        Безопасное получение числовой колонки из DataFrame.
        
        Конвертирует значения в float с обработкой ошибок.
        Гарантирует, что возвращается Series[float] с NaN для невалидных значений.
        
        :param df: DataFrame (может быть None)
        :param col: Имя колонки
        :return: pd.Series[float] (NaN для невалидных значений)
        """
        s = InvariantChecker._series(df, col, None)
        if len(s) == 0:
            return pd.Series([], dtype="float64")
        # Конвертируем в numeric с обработкой ошибок
        result = pd.to_numeric(s, errors="coerce")
        # Гарантируем, что возвращается Series
        if isinstance(result, pd.Series):
            return result
        else:
            return pd.Series([], dtype="float64")
    
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
        
        Структура проверок:
        A) Schema/sanity: колонки, dtype, datetime parse
        B) Per-position invariants: chain opened->partial*->closed, time ordering
        C) Linkage: events<->executions (P1 checks)
        
        :param positions_df: DataFrame с позициями (portfolio_positions.csv)
        :param events_df: Опциональный DataFrame с событиями (portfolio_events.csv)
        :param executions_df: Опциональный DataFrame с исполнениями (portfolio_executions.csv)
        :return: Список обнаруженных аномалий
        """
        self.anomalies = []
        
        # Нормализуем входы: заменяем None на пустые DataFrame
        # Это позволяет дальше по коду не проверять на None
        if positions_df is None:
            positions_df = pd.DataFrame()
        if events_df is None:
            events_df = pd.DataFrame()
        if executions_df is None:
            executions_df = pd.DataFrame()
        
        # Ранний выход, если нет позиций
        if len(positions_df) == 0:
            return []
        
        # ============================================================
        # A) Schema/sanity checks: валидация структуры данных
        # ============================================================
        self._check_schema_sanity(positions_df, events_df, executions_df)
        
        # ============================================================
        # B) Per-position invariants: проверки для каждой позиции
        # ============================================================
        # Строим ledger views для эффективного доступа
        events_by_position_id = self._build_events_by_position_id(events_df)
        executions_by_position_id = self._build_executions_by_position_id(executions_df, events_df)
        
        # Один проход по positions для всех per-position проверок
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
            
            # Проверка времени (используем распарсенные dt series)
            self._check_time_ordering(row)
            
            # Проверка магических значений
            self._check_magic_values(row)
            
            # Проверка цепочки событий для позиции
            position_id = self._safe_str(row.get("position_id")) or None
            if position_id:
                pos_events = events_by_position_id.get(position_id)
                if pos_events is not None:
                    self._check_position_event_chain(row, pos_events)
        
        # Проверка неизвестных причин
        self._check_unknown_reasons(positions_df, events_df)
        
        # Policy consistency
        if len(events_df) > 0:
            self._check_policy_consistency(positions_df, events_df)
        
        # ============================================================
        # C) Linkage checks: positions ↔ events ↔ executions (P1)
        # ============================================================
        if self.include_p1:
            # Определяем effective executions_df: используем переданный или строим из events
            effective_executions_df = executions_df
            if len(effective_executions_df) == 0:
                # Пустой - строим из events
                if len(events_df) > 0:
                    effective_executions_df = self.build_executions_from_events(events_df)
            else:
                # executions_df не пустой - проверяем наличие нужных колонок
                required_cols = ["event_time", "event_type"]
                has_required_cols = all(col in effective_executions_df.columns for col in required_cols)
                if not has_required_cols:
                    # Нет нужных колонок - строим из events
                    if len(events_df) > 0:
                        effective_executions_df = self.build_executions_from_events(events_df)
            
            indices = AuditIndices(events_df=events_df, executions_df=effective_executions_df)
            self._check_positions_events_consistency(positions_df, indices)
            self._check_events_executions_consistency(positions_df, indices, events_df, effective_executions_df)
        
        # P2: Decision proofs (если включено)
        if self.include_p2 and len(events_df) > 0:
            effective_executions_df = executions_df
            if len(effective_executions_df) == 0:
                if len(events_df) > 0:
                    effective_executions_df = self.build_executions_from_events(events_df)
            indices = AuditIndices(events_df=events_df, executions_df=effective_executions_df)
            self._check_decision_proofs(positions_df, events_df, indices)
        
        return self.anomalies
    
    def _check_required_fields(self, row: pd.Series) -> bool:
        """Проверка наличия обязательных полей."""
        required = ["strategy", "contract_address", "status"]
        # Явная проверка на None/NaN для каждого поля (избегаем truthiness на Series)
        missing = []
        for f in required:
            if f not in row.index:
                missing.append(f)
            else:
                val = row.get(f)
                if val is None or pd.isna(val):
                    missing.append(f)
        
        if len(missing) > 0:  # Явная проверка длины вместо truthiness
            entry_price_val = row.get("entry_price")
            exit_price_val = row.get("exit_price")
            pnl_pct_val = row.get("pnl_pct")
            
            # Явные проверки на None/NaN вместо truthiness
            entry_price = entry_price_val if (entry_price_val is not None and not pd.isna(entry_price_val)) else None
            exit_price = exit_price_val if (exit_price_val is not None and not pd.isna(exit_price_val)) else None
            pnl_pct = pnl_pct_val if (pnl_pct_val is not None and not pd.isna(pnl_pct_val)) else None
            
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
        
        # Проверка entry_price - безопасная проверка на None
        entry_price_valid = False
        if entry_price is not None and not pd.isna(entry_price):
            try:
                entry_price_float = float(entry_price)
                entry_price_valid = entry_price_float <= self.MIN_VALID_PRICE
            except (ValueError, TypeError):
                entry_price_valid = True  # Невалидное значение
        
        # Явная проверка на None/NaN вместо truthiness
        entry_price_is_invalid = (
            entry_price is None or 
            pd.isna(entry_price) or 
            entry_price_valid
        )
        
        if entry_price_is_invalid:
            pnl_pct_val = row.get("pnl_pct")
            pnl_pct = pnl_pct_val if (pnl_pct_val is not None and not pd.isna(pnl_pct_val)) else None
            
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
                anomaly_type=AnomalyType.ENTRY_PRICE_INVALID,
                severity="P0",
                details={"entry_price": entry_price},
            ))
        
        # Проверка exit_price (только для закрытых позиций)
        status_val = self._safe_str(row.get("status"))
        if status_val == "closed":
            # Безопасная проверка exit_price на None
            exit_price_valid = False
            if exit_price is not None and not pd.isna(exit_price):
                try:
                    exit_price_float = float(exit_price)
                    exit_price_valid = exit_price_float <= self.MIN_VALID_PRICE
                except (ValueError, TypeError):
                    exit_price_valid = True  # Невалидное значение
            
            # Явная проверка на None/NaN вместо truthiness
            exit_price_is_invalid = (
                exit_price is None or
                pd.isna(exit_price) or 
                exit_price_valid
            )
            
            if exit_price_is_invalid:
                pnl_pct_val = row.get("pnl_pct")
                pnl_pct = pnl_pct_val if (pnl_pct_val is not None and not pd.isna(pnl_pct_val)) else None
                
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
        
        # Безопасная проверка на None перед операциями
        if entry_price is None or exit_price is None:
            return
        if pd.isna(entry_price) or pd.isna(exit_price):
            return  # Уже проверено в _check_prices
        
        try:
            entry_price_float = float(entry_price)
            exit_price_float = float(exit_price)
        except (ValueError, TypeError):
            return  # Невалидные значения
        
        if entry_price_float <= 0:
            return  # Уже проверено в _check_prices
        
        # Проверка формулы PnL (для long позиций)
        expected_pnl_pct = (exit_price_float - entry_price_float) / entry_price_float
        
        # Проверка на магические значения
        if pnl_pct is not None and pd.notna(pnl_pct):
            try:
                pnl_pct_float = float(pnl_pct)
                if abs(pnl_pct_float) > self.MAX_REASONABLE_PNL_PCT:
                    self.anomalies.append(Anomaly(
                        position_id=self._safe_str(row.get("position_id")) or None,
                        strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                        signal_id=self._safe_str(row.get("signal_id")) or None,
                        contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                        entry_time=self._safe_dt(row.get("entry_time")),
                        exit_time=self._safe_dt(row.get("exit_time")),
                        entry_price=entry_price_float,
                        exit_price=exit_price_float,
                        pnl_pct=pnl_pct_float,
                        reason=self._safe_str(row.get("reason")) or None,
                    anomaly_type=AnomalyType.PNL_CAP_OR_MAGIC,
                    severity="P0",
                    details={
                        "pnl_pct": pnl_pct_float,
                        "expected_pnl_pct": expected_pnl_pct,
                        "max_reasonable": self.MAX_REASONABLE_PNL_PCT,
                    },
                ))
            except (ValueError, TypeError):
                pass  # Невалидное значение pnl_pct
    
    def _check_reason_consistency(self, row: pd.Series) -> None:
        """Проверка консистентности reason с фактическими данными."""
        status_val = self._safe_str(row.get("status"))
        if status_val != "closed":
            return
        
        reason = row.get("reason") or row.get("exit_reason")
        pnl_pct = row.get("pnl_pct") or row.get("pnl_sol")
        
        reason_str = self._safe_str(reason) if reason is not None else ""
        if not reason_str:
            return
        
        # Безопасная проверка pnl_pct на None
        if pnl_pct is None or pd.isna(pnl_pct):
            return
        
        try:
            pnl_pct_float = float(pnl_pct)
        except (ValueError, TypeError):
            return  # Невалидное значение
        
        # Нормализуем reason для консистентной проверки
        normalized_reason = normalize_reason(reason_str)
        
        # Проверка: reason=ladder_tp, но pnl < 0 (строго отрицательный)
        if normalized_reason == "ladder_tp" and pnl_pct_float < -self.EPSILON:
            self.anomalies.append(Anomaly(
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(row.get("entry_time")),
                exit_time=self._safe_dt(row.get("exit_time")),
                    entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                    exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                    pnl_pct=pnl_pct_float,
                    reason=reason_str,
                    anomaly_type=AnomalyType.TP_REASON_BUT_NEGATIVE_PNL,
                    severity="P0",
                    details={"pnl_pct": pnl_pct_float, "reason": reason_str, "normalized_reason": normalized_reason},
                ))
        
        # Проверка: reason=stop_loss, но pnl >= 0 (неотрицательный) - строго < 0 согласно ТЗ
        if normalized_reason == "stop_loss" and pnl_pct_float >= 0:
            self.anomalies.append(Anomaly(
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(row.get("entry_time")),
                exit_time=self._safe_dt(row.get("exit_time")),
                    entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                    exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                    pnl_pct=pnl_pct_float,
                    reason=reason_str,
                    anomaly_type=AnomalyType.SL_REASON_BUT_POSITIVE_PNL,
                    severity="P0",
                    details={"pnl_pct": pnl_pct_float, "reason": reason_str, "normalized_reason": normalized_reason},
                ))
    
    def _check_time_ordering(self, row: pd.Series) -> None:
        """Проверка порядка времени."""
        status_val = self._safe_str(row.get("status"))
        if status_val != "closed":
            return
        
        entry_time = row.get("entry_time")
        exit_time = row.get("exit_time")
        
        # Безопасная проверка на None
        if entry_time is None or exit_time is None:
            return
        
        if pd.isna(entry_time) or pd.isna(exit_time):
            return
        
        entry_dt = self._safe_dt(entry_time)
        exit_dt = self._safe_dt(exit_time)
        
        if entry_dt is None or exit_dt is None:
            return
        
        # Безопасное сравнение datetime
        if entry_dt > exit_dt:
            pnl_pct_val = row.get("pnl_pct")
            pnl_pct = pnl_pct_val if (pnl_pct_val is not None and not pd.isna(pnl_pct_val)) else None
            
            self.anomalies.append(Anomaly(
                position_id=self._safe_str(row.get("position_id")) or None,
                strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(row.get("signal_id")) or None,
                contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                entry_time=entry_dt,
                exit_time=exit_dt,
                entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                pnl_pct=pnl_pct,
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
        
        # Безопасная проверка на None
        if pnl_pct is None or pd.isna(pnl_pct):
            return
        
        try:
            pnl_pct_float = float(pnl_pct)
        except (ValueError, TypeError):
            return  # Невалидное значение
        
        # Проверка на известные магические значения
        magic_values = [920.0, 920.0 / 100, -920.0, -920.0 / 100]  # 920% и -920%
        if any(abs(pnl_pct_float - mv) < self.EPSILON for mv in magic_values):
                self.anomalies.append(Anomaly(
                    position_id=self._safe_str(row.get("position_id")) or None,
                    strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                    signal_id=self._safe_str(row.get("signal_id")) or None,
                    contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                    entry_time=self._safe_dt(row.get("entry_time")),
                    exit_time=self._safe_dt(row.get("exit_time")),
                    entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                    exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                    pnl_pct=pnl_pct_float,
                    reason=self._safe_str(row.get("reason")) or None,
                    anomaly_type=AnomalyType.PNL_CAP_OR_MAGIC,
                    severity="P0",
                    details={"pnl_pct": pnl_pct_float, "magic_value": "920%"},
                ))
    
    def _check_unknown_reasons(
        self,
        positions_df: pd.DataFrame,
        events_df: Optional[pd.DataFrame] = None,
    ) -> None:
        """
        Проверка неизвестных причин закрытия.
        
        Собирает все observed reasons из positions и events,
        нормализует их и проверяет на соответствие CANONICAL_REASONS.
        """
        observed_reasons = set()
        
        # Guard: ранний выход, если positions_df пустой
        if positions_df is None or positions_df.empty:
            return
        
        # Собираем reasons из positions
        reason_series = self._str_series(positions_df, "reason")
        for reason in reason_series:
            if reason and reason.strip():
                normalized = normalize_reason(reason)
                if normalized:
                    observed_reasons.add(normalized)
        
        # Собираем reasons из events (если есть)
        if events_df is not None and not events_df.empty:
            event_reason_series = self._str_series(events_df, "reason")
            for reason in event_reason_series:
                if reason and reason.strip():
                    normalized = normalize_reason(reason)
                    if normalized:
                        observed_reasons.add(normalized)
        
        # Находим неизвестные причины
        unknown_reasons = observed_reasons - CANONICAL_REASONS
        
        # Эмитим аномалии для неизвестных причин
        for unknown_reason in unknown_reasons:
            # Находим позиции с этой причиной
            for _, row in positions_df.iterrows():
                reason_val = self._safe_str(row.get("reason"))
                if reason_val:
                    normalized = normalize_reason(reason_val)
                    if normalized == unknown_reason:
                        self.anomalies.append(Anomaly(
                            position_id=self._safe_str(row.get("position_id")) or None,
                            strategy=self._safe_str(row.get("strategy"), "UNKNOWN"),
                            signal_id=self._safe_str(row.get("signal_id")) or None,
                            contract_address=self._safe_str(row.get("contract_address"), "UNKNOWN"),
                            entry_time=self._safe_dt(row.get("entry_time")),
                            exit_time=self._safe_dt(row.get("exit_time")),
                            entry_price=row.get("exec_entry_price") or row.get("raw_entry_price"),
                            exit_price=row.get("exec_exit_price") or row.get("raw_exit_price"),
                            pnl_pct=self._safe_float(row.get("pnl_pct")),
                            reason=reason_val,
                            anomaly_type=AnomalyType.UNKNOWN_REASON,
                            severity="P0",
                            details={
                                "observed_reason": reason_val,
                                "normalized_reason": normalized,
                                "canonical_reasons": list(CANONICAL_REASONS),
                            },
                        ))
                        break  # Одна аномалия на уникальную причину
    
    def _check_schema_sanity(
        self,
        positions_df: pd.DataFrame,
        events_df: Optional[pd.DataFrame] = None,
        executions_df: Optional[pd.DataFrame] = None,
    ) -> None:
        """
        Блок A: Schema/sanity checks.
        
        Проверяет структуру данных: наличие колонок, типы данных, парсинг datetime.
        Не проверяет бизнес-логику, только валидность структуры.
        """
        # Проверка обязательных колонок в positions_df уже делается в _check_required_fields
        # Здесь можно добавить дополнительные проверки структуры, если нужно
        pass
    
    def _build_events_by_position_id(
        self,
        events_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Строит словарь events по position_id.
        
        :param events_df: DataFrame с событиями
        :return: dict[position_id, DataFrame] - события для каждой позиции
        """
        events_by_position_id: Dict[str, pd.DataFrame] = {}
        
        if events_df is None or len(events_df) == 0:
            return events_by_position_id
        
        # Получаем position_id series
        position_id_series = self._str_series(events_df, "position_id")
        
        # Группируем по position_id (пропускаем пустые)
        for position_id in position_id_series.unique():
            if position_id and position_id.strip():
                mask = position_id_series == position_id
                filtered = events_df[mask]
                # Гарантируем, что это DataFrame, а не Series
                if isinstance(filtered, pd.DataFrame):
                    events_by_position_id[position_id] = filtered.copy()
                else:
                    # Если это Series, конвертируем в DataFrame
                    events_by_position_id[position_id] = pd.DataFrame([filtered])
        
        return events_by_position_id
    
    def _build_executions_by_position_id(
        self,
        executions_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Строит словарь executions по position_id.
        
        Если executions_df не передан или пустой, строит из events_df.
        
        :param executions_df: DataFrame с исполнениями
        :param events_df: DataFrame с событиями (используется если executions_df пустой)
        :return: dict[position_id, DataFrame] - исполнения для каждой позиции
        """
        executions_by_position_id: Dict[str, pd.DataFrame] = {}
        
        # Определяем effective executions_df
        effective_executions_df = executions_df
        if effective_executions_df is None or len(effective_executions_df) == 0:
            if events_df is not None and len(events_df) > 0:
                effective_executions_df = self.build_executions_from_events(events_df)
            else:
                return executions_by_position_id
        
        if effective_executions_df is None or len(effective_executions_df) == 0:
            return executions_by_position_id
        
        # Получаем position_id series
        position_id_series = self._str_series(effective_executions_df, "position_id")
        
        # Группируем по position_id (пропускаем пустые)
        for position_id in position_id_series.unique():
            if position_id and position_id.strip():
                mask = position_id_series == position_id
                filtered = effective_executions_df[mask]
                # Гарантируем, что это DataFrame, а не Series
                if isinstance(filtered, pd.DataFrame):
                    executions_by_position_id[position_id] = filtered.copy()
                else:
                    # Если это Series, конвертируем в DataFrame
                    executions_by_position_id[position_id] = pd.DataFrame([filtered])
        
        return executions_by_position_id
    
    def _check_position_event_chain(
        self,
        pos_row: pd.Series,
        pos_events: pd.DataFrame,
    ) -> None:
        """
        Проверка цепочки событий для одной позиции.
        
        Проверяет наличие событий открытия и закрытия для закрытых позиций.
        
        :param pos_row: Строка позиции
        :param pos_events: DataFrame с событиями для этой позиции
        """
        status = self._safe_str(pos_row.get("status"))
        if status != "closed":
            return
        
        position_id = self._safe_str(pos_row.get("position_id")) or None
        if not position_id:
            return
        
        # Проверяем наличие событий
        if len(pos_events) == 0:
            self.anomalies.append(Anomaly(
                position_id=position_id,
                strategy=self._safe_str(pos_row.get("strategy"), "UNKNOWN"),
                signal_id=self._safe_str(pos_row.get("signal_id")) or None,
                contract_address=self._safe_str(pos_row.get("contract_address"), "UNKNOWN"),
                entry_time=self._safe_dt(pos_row.get("entry_time")),
                exit_time=self._safe_dt(pos_row.get("exit_time")),
                entry_price=self._safe_float(pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price")),
                exit_price=self._safe_float(pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price")),
                pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
                reason=self._safe_str(pos_row.get("reason")) or None,
                anomaly_type=AnomalyType.MISSING_EVENTS_CHAIN,
                severity="P0",
                details={"events_count": 0, "position_id": position_id},
            ))
    
    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """
        Безопасное преобразование значения в float.
        
        :param value: Значение (может быть None, Unknown, и т.д.)
        :return: float или None
        """
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _safe_get_value(row: Any, key: str, default: Any = None) -> Any:
        """
        Безопасное получение значения из row с явной проверкой на None/NaN.
        
        Избегает truthiness проверок на NDFrame.
        
        :param row: Series или dict
        :param key: Ключ для получения значения
        :param default: Значение по умолчанию
        :return: Значение или default
        """
        if row is None:
            return default
        value = row.get(key) if hasattr(row, 'get') else None
        if value is None or pd.isna(value):
            return default
        return value
    
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
            # Явная проверка на None/NaN вместо truthiness
            if position_id is not None and not pd.isna(position_id):
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
                        pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
                        reason=self._safe_str(pos_row.get("reason")) or None,
                        anomaly_type=AnomalyType.MISSING_EVENTS_CHAIN,
                        severity="P0",
                        details={"events_count": 0, "position_id": position_id},
                    ))
    
    def _check_policy_consistency(self, positions_df: pd.DataFrame, events_df: pd.DataFrame) -> None:
        """Проверка консистентности политик (reset, prune)."""
        # Guard: ранний выход, если входы пустые
        if positions_df is None or positions_df.empty:
            return
        if events_df is None or events_df.empty:
            return
        
        # Проверяем позиции, закрытые по reset/prune
        # Используем безопасное получение колонок
        closed_by_reset_series = self._series(positions_df, "closed_by_reset", False)
        reset_reason_series = self._series(events_df, "reset_reason", None)
        
        # Используем явные проверки вместо truthiness
        reset_positions = positions_df[
            (closed_by_reset_series == True) |
            (reset_reason_series.notna())
        ]
        
        # Guard: проверяем, что есть позиции для обработки
        if reset_positions.empty:
            return
        
        for _, pos_row in reset_positions.iterrows():
            position_id = self._safe_str(pos_row.get("position_id")) or None
            signal_id = self._safe_str(pos_row.get("signal_id")) or None
            strategy = self._safe_str(pos_row.get("strategy"), "UNKNOWN")
            contract = self._safe_str(pos_row.get("contract_address"), "UNKNOWN")
            
            # Ищем события reset/prune
            event_type_series = self._series(events_df, "event_type", "")
            # Явная проверка на None/NaN вместо truthiness
            if position_id is not None and not pd.isna(position_id):
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
                    pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
                    reason=self._safe_str(pos_row.get("reason")) or None,
                    anomaly_type=AnomalyType.RESET_WITHOUT_EVENTS,
                    severity="P0",
                    details={"reset_reason": pos_row.get("reset_reason")},
                ))
    
    def _check_positions_events_consistency(
        self,
        positions_df: pd.DataFrame,
        indices: AuditIndices,
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
                    pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
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
                    pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
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
                    pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
                    reason=self._safe_str(pos_row.get("reason")) or None,
                    anomaly_type=AnomalyType.MULTIPLE_OPEN_EVENTS,
                    severity="P1",
                    event_id=event_ids[0] if event_ids else None,
                    details={"open_events_count": len(open_events), "event_ids": event_ids},
                ))
            
            # Проверка: несколько событий закрытия (если должно быть 1)
            if len(close_events) > 1:
                # Для обычных закрытий (ladder_tp/stop_loss/time_stop) должно быть 1 событие
                reason = self._safe_str(pos_row.get("reason")) or ""
                normalized_reason = normalize_reason(reason)
                if normalized_reason not in ["capacity_prune", "profit_reset", "manual_close"]:
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
                        pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
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
                
                # Проверяем только известные причины (из CANONICAL_REASONS)
                if normalized_reason not in CANONICAL_REASONS:
                    # Неизвестная причина - пропускаем проверку маппинга
                    # (она уже будет обработана в _check_unknown_reasons)
                    continue
                
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
                                # Явная проверка на None/NaN вместо truthiness
                                if meta_json is not None and not pd.isna(meta_json):
                                    try:
                                        meta_dict = json.loads(str(meta_json))
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                elif meta is not None and isinstance(meta, dict):
                                    meta_dict = meta
                                elif meta is not None and isinstance(meta, str):
                                    try:
                                        meta_dict = json.loads(meta)
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                
                                reset_reason = meta_dict.get("reset_reason") or meta_dict.get("close_reason")
                                if reset_reason is not None:
                                    reset_reason_lower = str(reset_reason).lower()
                                    # Для reason="ladder_tp" не должно быть reset_reason
                                    if normalized_reason == "ladder_tp" and reset_reason_lower in ("profit_reset", "capacity_prune"):
                                        matches = False  # Несоответствие
                                    # Для reason="profit_reset" или "capacity_prune" проверяем reset_reason
                                    elif normalized_reason in ("profit_reset", "capacity_prune"):
                                        if (normalized_reason == "profit_reset" and "profit_reset" in reset_reason_lower) or \
                                           (normalized_reason == "capacity_prune" and "capacity_prune" in reset_reason_lower):
                                            matches = True
                                else:
                                    # POSITION_CLOSED без reset_reason - подходит для ladder_tp/stop_loss/time_stop
                                    if normalized_reason in ("ladder_tp", "stop_loss", "time_stop", "max_hold_minutes"):
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
                            pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
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
        # reason уже должен быть нормализован (каноническая форма)
        mapping = {
            "ladder_tp": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy
                "closed_by_take_profit", "closed_by_tp",  # Legacy варианты
            ],
            "stop_loss": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy
                "closed_by_stop_loss", "closed_by_sl",  # Legacy варианты
            ],
            "time_stop": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy
                "closed_by_timeout", "closed_by_max_hold",  # Legacy варианты
            ],
            "max_hold_minutes": [
                "POSITION_CLOSED",  # Канонический тип
                "executed_close", "position_closed",  # Legacy
                "closed_by_timeout", "closed_by_max_hold",  # Legacy варианты
            ],
            "capacity_prune": [
                "POSITION_CLOSED",  # Канонический тип (с reset_reason="capacity_prune" в meta)
                "capacity_prune", "closed_by_capacity_prune", "prune",  # Legacy
            ],
            "profit_reset": [
                "POSITION_CLOSED",  # Канонический тип (с reset_reason="profit_reset" в meta)
                "profit_reset", "closed_by_profit_reset", "reset",  # Legacy
            ],
            "manual_close": [
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
        
        # Guard: ранний выход, если events_df пустой или None
        if events_df is None or events_df.empty:
            column_names = [
                "signal_id", "strategy", "event_time", "event_type", "event_id",
                "position_id", "qty_delta", "raw_price", "exec_price", "fees_sol", "pnl_sol_delta", "reason"
            ]
            empty_dict = {col: [] for col in column_names}
            return pd.DataFrame.from_dict(empty_dict)
        
        trade_event_types = {"POSITION_OPENED", "POSITION_PARTIAL_EXIT", "POSITION_CLOSED"}
        
        executions_rows = []
        
        for _, row in events_df.iterrows():
            event_type = str(row.get("event_type", "")).upper()
            
            # Пропускаем не trade-related события
            if event_type not in trade_event_types:
                continue
            
            # Пытаемся извлечь meta из meta_json или meta
            meta = {}
            meta_json_val = row.get("meta_json") if "meta_json" in row else None
            # Явная проверка на None/NaN вместо truthiness
            if meta_json_val is not None and not pd.isna(meta_json_val):
                try:
                    meta_str = str(meta_json_val)
                    if len(meta_str) > 0:  # Явная проверка длины вместо truthiness
                        meta = json.loads(meta_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                meta_val = row.get("meta") if "meta" in row else None
                # Явная проверка на None вместо truthiness
                if meta_val is not None and not pd.isna(meta_val):
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
            # Используем pd.DataFrame.from_dict для обхода проблем с типами
            column_names = [
                "signal_id", "strategy", "event_time", "event_type", "event_id",
                "position_id", "qty_delta", "raw_price", "exec_price", "fees_sol", "pnl_sol_delta", "reason"
            ]
            # Создаем пустой DataFrame через from_dict с пустым словарем
            empty_dict = {col: [] for col in column_names}
            return pd.DataFrame.from_dict(empty_dict)
        
        return pd.DataFrame(executions_rows)
    
    def _check_events_executions_consistency(
        self,
        positions_df: pd.DataFrame,
        indices: AuditIndices,
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
        # Явные проверки вместо truthiness
        has_executions_df = (
            executions_df is not None 
            and not executions_df.empty
            and "event_time" in executions_df.columns 
            and "event_type" in executions_df.columns
        )
        
        # Получаем все trade-events глобально
        all_trade_events = []
        if events_df is not None and not events_df.empty:
            for _, row in events_df.iterrows():
                event_type = str(row.get("event_type", "")).upper()
                if event_type in trade_event_types:
                    all_trade_events.append(row.to_dict())
        
        # Создаем индекс позиций для быстрого поиска
        positions_by_signal = {}
        if positions_df is not None and not positions_df.empty:
            for _, pos_row in positions_df.iterrows():
                signal_id = self._safe_str(pos_row.get("signal_id")) or None
                strategy = self._safe_str(pos_row.get("strategy"), "UNKNOWN")
                if signal_id is not None and strategy:
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
            
            if has_executions_df and executions_df is not None and not executions_df.empty:
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
                # Явная проверка на None/NaN вместо truthiness
                if meta_json is not None and not pd.isna(meta_json):
                    try:
                        meta_dict = json.loads(str(meta_json))
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif meta is not None and isinstance(meta, dict):
                    meta_dict = meta
                elif meta is not None and isinstance(meta, str):
                    try:
                        meta_dict = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                # Проверяем наличие execution_type в meta (явная проверка)
                execution_type_val = meta_dict.get("execution_type")
                if execution_type_val is not None:
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
        if has_executions_df and executions_df is not None and not executions_df.empty:
            for _, exec_row in executions_df.iterrows():
                # Явные проверки на None/NaN вместо truthiness
                exec_signal_id_val = exec_row.get("signal_id")
                exec_signal_id = str(exec_signal_id_val) if (exec_signal_id_val is not None and not pd.isna(exec_signal_id_val)) else None
                
                exec_strategy_val = exec_row.get("strategy")
                exec_strategy = str(exec_strategy_val) if (exec_strategy_val is not None and not pd.isna(exec_strategy_val)) else None
                
                exec_time = self._safe_dt(exec_row.get("event_time"))
                exec_type = str(exec_row.get("event_type", "")).lower()
                
                exec_event_id_val = exec_row.get("event_id")
                exec_event_id = str(exec_event_id_val) if (exec_event_id_val is not None and not pd.isna(exec_event_id_val)) else None
                
                # Находим соответствующую позицию
                pos_row = None
                if exec_signal_id and exec_strategy:
                    key = (exec_strategy, exec_signal_id)
                    if key in positions_by_signal and len(positions_by_signal[key]) > 0:
                        pos_row = positions_by_signal[key][0]
                
                # Ищем соответствующее событие
                matching_event = None
                
                # Поиск по event_id (приоритет)
                if exec_event_id is not None:
                    for event in all_trade_events:
                        event_id_val = event.get("event_id")
                        event_id = str(event_id_val) if (event_id_val is not None and not pd.isna(event_id_val)) else None
                        if event_id is not None and event_id == exec_event_id:
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
                        
                        # Явная проверка на None/NaN и > 0
                        if exec_price is not None and not pd.isna(exec_price) and exec_price > 0:
                            # Для entry: сравниваем с entry_price
                            # Явная проверка на None вместо truthiness
                            if exec_type == "entry" and entry_price is not None:
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
                                        pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
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
                            # Явная проверка на None вместо truthiness
                            if exec_type in ("partial_exit", "final_exit", "forced_close") and exit_price is not None:
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
                                        pnl_pct=self._safe_float(pos_row.get("pnl_pct")),
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
        indices: AuditIndices,
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
        # Guard: ранний выход, если events_df пустой или None
        if events_df is None or events_df.empty:
            return
        
        # Ищем события PROFIT_RESET_TRIGGERED
        event_type_series = self._series(events_df, "event_type", "")
        profit_reset_events = events_df[
            event_type_series.str.contains("PROFIT_RESET|profit_reset", case=False, na=False)
        ]
        
        # Guard: проверяем, что есть события для обработки
        if profit_reset_events.empty:
            return
        
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
def normalize_reason(x: Any) -> str:
    """
    Нормализует reason для консистентной обработки.
    
    Правила нормализации:
    - Применяет алиасы: tp -> ladder_tp, sl -> stop_loss, timeout -> time_stop
    - Возвращает нормализованную причину в нижнем регистре
    
    :param x: Исходная причина закрытия (может быть None, str, и т.д.)
    :return: Нормализованная причина (строка в нижнем регистре)
    """
    s = "" if x is None else str(x).strip().lower()
    return REASON_ALIASES.get(s, s)


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
    
    if normalized == "ladder_tp":
        # ladder_tp требует неотрицательный PnL (с допуском epsilon)
        return pnl_pct >= -epsilon
    
    if normalized == "stop_loss":
        # stop_loss требует строго отрицательный PnL
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

