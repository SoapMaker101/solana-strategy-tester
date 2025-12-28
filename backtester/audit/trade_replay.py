# backtester/audit/trade_replay.py
# Детальный разбор (replay) одной позиции

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import json

import pandas as pd

from .data_loader import AuditDataLoader
from ..infrastructure.price_loader import CsvPriceLoader


@dataclass
class TradeReplay:
    """Детальный разбор одной позиции."""
    
    position_id: Optional[str]
    strategy: str
    signal_id: str
    contract_address: str
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    pnl_pct: Optional[float]
    reason: Optional[str]
    
    # Контекст
    candles: List[Dict[str, Any]]  # Свечи после entry
    tp_levels: List[float]  # Уровни TP
    sl_level: Optional[float]  # Уровень SL
    max_hold_minutes: Optional[int]  # Максимальное время удержания
    
    # Анализ
    trigger_candle: Optional[Dict[str, Any]]  # Свеча, на которой сработал exit
    trigger_reason: Optional[str]  # Детальная причина срабатывания
    expected_exit_price: Optional[float]  # Ожидаемая цена выхода
    price_discrepancy: Optional[float]  # Расхождение между expected и actual
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для JSON экспорта."""
        return {
            "position_id": self.position_id,
            "strategy": self.strategy,
            "signal_id": self.signal_id,
            "contract_address": self.contract_address,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "reason": self.reason,
            "tp_levels": self.tp_levels,
            "sl_level": self.sl_level,
            "max_hold_minutes": self.max_hold_minutes,
            "trigger_candle": self.trigger_candle,
            "trigger_reason": self.trigger_reason,
            "expected_exit_price": self.expected_exit_price,
            "price_discrepancy": self.price_discrepancy,
            "candles_count": len(self.candles),
        }


def replay_position(
    run_dir: Path,
    position_id: Optional[str] = None,
    signal_id: Optional[str] = None,
    strategy: Optional[str] = None,
    contract_address: Optional[str] = None,
    candles_dir: Optional[Path] = None,
) -> Optional[TradeReplay]:
    """
    Воспроизводит (replay) одну позицию по входным данным.
    
    :param run_dir: Директория с результатами прогона
    :param position_id: ID позиции (приоритетный)
    :param signal_id: ID сигнала (если нет position_id)
    :param strategy: Название стратегии (если нет position_id)
    :param contract_address: Адрес контракта (если нет position_id)
    :param candles_dir: Директория со свечами (по умолчанию data/candles/)
    :return: TradeReplay или None если позиция не найдена
    """
    # Загружаем позиции
    loader = AuditDataLoader(run_dir)
    positions_df = loader.load_positions()
    
    if positions_df is None or len(positions_df) == 0:
        return None
    
    # Ищем позицию
    if position_id:
        pos_row = positions_df[positions_df.get("position_id") == position_id]
    elif signal_id and strategy and contract_address:
        pos_row = positions_df[
            (positions_df.get("signal_id") == signal_id) &
            (positions_df.get("strategy") == strategy) &
            (positions_df.get("contract_address") == contract_address)
        ]
    else:
        return None
    
    if len(pos_row) == 0:
        return None
    
    pos_row = pos_row.iloc[0]
    
    # Извлекаем данные позиции
    entry_time = pd.to_datetime(pos_row.get("entry_time"))
    exit_time = pd.to_datetime(pos_row.get("exit_time")) if pd.notna(pos_row.get("exit_time")) else None
    entry_price = pos_row.get("exec_entry_price") or pos_row.get("raw_entry_price") or pos_row.get("entry_price")
    exit_price = pos_row.get("exec_exit_price") or pos_row.get("raw_exit_price") or pos_row.get("exit_price")
    
    if pd.isna(entry_time) or pd.isna(entry_price):
        return None
    
    # Загружаем свечи
    if candles_dir is None:
        candles_dir = Path("data/candles")
    
    price_loader = CsvPriceLoader(str(candles_dir), timeframe="1m")
    contract = pos_row.get("contract_address")
    
    try:
        candles = price_loader.load_prices(contract, start_time=entry_time)  # Загружаем свечи начиная с entry_time
    except Exception:
        return None
    
    # Фильтруем свечи после entry
    entry_candles = [c for c in candles if c.timestamp >= entry_time]
    
    # Извлекаем параметры стратегии из meta (если есть)
    meta_str = pos_row.get("meta_json") or "{}"
    try:
        meta = json.loads(meta_str) if isinstance(meta_str, str) else {}
    except Exception:
        meta = {}
    
    # Пытаемся извлечь TP/SL уровни
    tp_levels = []
    sl_level = None
    
    # Для Runner стратегий ищем levels_hit или take_profit_levels
    if "levels_hit" in meta:
        tp_levels = [float(k) for k in meta["levels_hit"].keys() if isinstance(k, (int, float, str))]
    elif "take_profit_levels" in meta:
        tp_levels = [float(level.get("xn", 0)) for level in meta["take_profit_levels"] if isinstance(level, dict)]
    
    # Анализируем свечи для поиска trigger
    trigger_candle = None
    trigger_reason = None
    expected_exit_price = None
    
    if exit_time:
        # Ищем свечу, на которой произошёл exit
        for candle in entry_candles:
            if candle.timestamp <= exit_time:
                # Проверяем TP
                for tp_level in tp_levels:
                    tp_price = entry_price * tp_level
                    if candle.high >= tp_price:
                        trigger_candle = {
                            "timestamp": candle.timestamp.isoformat(),
                            "open": candle.open,
                            "high": candle.high,
                            "low": candle.low,
                            "close": candle.close,
                        }
                        trigger_reason = f"tp_{tp_level}x_high_cross"
                        expected_exit_price = tp_price
                        break
                
                # Проверяем SL
                if sl_level and candle.low <= entry_price * sl_level:
                    trigger_candle = {
                        "timestamp": candle.timestamp.isoformat(),
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                    }
                    trigger_reason = f"sl_{sl_level}_low_cross"
                    expected_exit_price = entry_price * sl_level
                    break
    
    # Вычисляем расхождение
    price_discrepancy = None
    if expected_exit_price and exit_price:
        price_discrepancy = abs(exit_price - expected_exit_price) / entry_price
    
    return TradeReplay(
        position_id=pos_row.get("position_id"),
        strategy=pos_row.get("strategy"),
        signal_id=pos_row.get("signal_id"),
        contract_address=contract,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=float(entry_price),
        exit_price=float(exit_price) if pd.notna(exit_price) else None,
        pnl_pct=float(pos_row.get("pnl_pct")) if pd.notna(pos_row.get("pnl_pct")) else None,
        reason=pos_row.get("reason"),
        candles=[{
            "timestamp": c.timestamp.isoformat(),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        } for c in entry_candles[:100]],  # Ограничиваем до 100 свечей
        tp_levels=tp_levels,
        sl_level=sl_level,
        max_hold_minutes=int(pos_row.get("hold_minutes")) if pd.notna(pos_row.get("hold_minutes")) else None,
        trigger_candle=trigger_candle,
        trigger_reason=trigger_reason,
        expected_exit_price=expected_exit_price,
        price_discrepancy=price_discrepancy,
    )

