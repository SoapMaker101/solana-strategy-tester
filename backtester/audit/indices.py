# backtester/audit/indices.py
# Индексы для быстрого поиска по событиям и исполнениям

from __future__ import annotations

from typing import Dict, List, Optional, Set, Any
from collections import defaultdict
import pandas as pd
from ..utils.typing_utils import is_nonempty_df, is_nonempty_series


class AuditIndices:
    """Индексы для быстрого поиска событий и исполнений по позициям."""
    
    def __init__(
        self,
        events_df: Optional[pd.DataFrame] = None,
        executions_df: Optional[pd.DataFrame] = None,
    ):
        """
        Создаёт индексы из DataFrame событий и исполнений.
        
        :param events_df: DataFrame с событиями (portfolio_events.csv)
        :param executions_df: DataFrame с исполнениями (portfolio_executions.csv)
        """
        self.events_by_position_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.events_by_signal_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.events_by_strategy_signal_contract: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
        self.executions_by_position_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.executions_by_signal_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Индексы по типам событий
        self.reset_events: List[Dict[str, Any]] = []
        self.prune_events: List[Dict[str, Any]] = []
        self.close_all_events: List[Dict[str, Any]] = []
        
        if is_nonempty_df(events_df):
            self._build_events_indices(events_df)
        
        if is_nonempty_df(executions_df):
            self._build_executions_indices(executions_df)
    
    def _build_events_indices(self, events_df: Optional[pd.DataFrame]) -> None:
        """Строит индексы по событиям."""
        if events_df is None or events_df.empty:
            return
        for _, row in events_df.iterrows():
            event_dict = row.to_dict()
            event_type = str(row.get("event_type", "")).lower()
            
            # Индекс по position_id
            position_id = row.get("position_id")
            if position_id is not None and pd.notna(position_id):
                position_id_str = str(position_id).strip()
                if position_id_str:
                    self.events_by_position_id[position_id_str].append(event_dict)
            
            # Индекс по signal_id
            signal_id = row.get("signal_id")
            if signal_id is not None and pd.notna(signal_id):
                signal_id_str = str(signal_id).strip()
                if signal_id_str:
                    self.events_by_signal_id[signal_id_str].append(event_dict)
            
            # Индекс по (strategy, signal_id, contract_address)
            strategy = row.get("strategy")
            contract = row.get("contract_address")
            if (strategy is not None and pd.notna(strategy) and 
                signal_id is not None and pd.notna(signal_id) and 
                contract is not None and pd.notna(contract)):
                key = (str(strategy), str(signal_id), str(contract))
                self.events_by_strategy_signal_contract[key].append(event_dict)
            
            # Индексы по типам событий
            if "reset" in event_type or "profit_reset" in event_type:
                self.reset_events.append(event_dict)
            if "prune" in event_type:
                self.prune_events.append(event_dict)
            if "close_all" in event_type:
                self.close_all_events.append(event_dict)
    
    def _build_executions_indices(self, executions_df: Optional[pd.DataFrame]) -> None:
        """Строит индексы по исполнениям."""
        if executions_df is None or executions_df.empty:
            return
        for _, row in executions_df.iterrows():
            exec_dict = row.to_dict()
            
            # Индекс по position_id
            position_id = row.get("position_id")
            if position_id is not None and pd.notna(position_id):
                position_id_str = str(position_id).strip()
                if position_id_str:
                    self.executions_by_position_id[position_id_str].append(exec_dict)
            
            # Индекс по signal_id
            signal_id = row.get("signal_id")
            if signal_id is not None and pd.notna(signal_id):
                signal_id_str = str(signal_id).strip()
                if signal_id_str:
                    self.executions_by_signal_id[signal_id_str].append(exec_dict)
    
    def get_events_for_position(
        self,
        position_id: Optional[str] = None,
        signal_id: Optional[str] = None,
        strategy: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Получает все события для позиции.
        
        Приоритет поиска:
        1. По position_id (если есть)
        2. По (strategy, signal_id, contract_address)
        3. По signal_id (fallback)
        """
        if position_id and pd.notna(position_id):
            return self.events_by_position_id.get(str(position_id), [])
        
        if strategy and signal_id and contract_address:
            key = (str(strategy), str(signal_id), str(contract_address))
            return self.events_by_strategy_signal_contract.get(key, [])
        
        if signal_id and pd.notna(signal_id):
            return self.events_by_signal_id.get(str(signal_id), [])
        
        return []
    
    def get_executions_for_position(
        self,
        position_id: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Получает все исполнения для позиции."""
        if position_id and pd.notna(position_id):
            return self.executions_by_position_id.get(str(position_id), [])
        
        if signal_id and pd.notna(signal_id):
            return self.executions_by_signal_id.get(str(signal_id), [])
        
        return []
    
    def has_open_event(
        self,
        position_id: Optional[str] = None,
        signal_id: Optional[str] = None,
        strategy: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> bool:
        """Проверяет наличие события открытия позиции."""
        events = self.get_events_for_position(position_id, signal_id, strategy, contract_address)
        open_keywords = ["attempt_accepted_open", "executed_open", "position_opened", "open"]
        return any(
            any(kw in str(e.get("event_type", "")).lower() for kw in open_keywords)
            for e in events
        )
    
    def has_close_event(
        self,
        position_id: Optional[str] = None,
        signal_id: Optional[str] = None,
        strategy: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> bool:
        """Проверяет наличие события закрытия позиции."""
        events = self.get_events_for_position(position_id, signal_id, strategy, contract_address)
        close_keywords = [
            "executed_close", "closed_by", "close", "exit",
            "capacity_prune", "profit_reset", "close_all",
        ]
        return any(
            any(kw in str(e.get("event_type", "")).lower() for kw in close_keywords)
            for e in events
        )
    
    def get_close_events(
        self,
        position_id: Optional[str] = None,
        signal_id: Optional[str] = None,
        strategy: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Получает все события закрытия для позиции."""
        events = self.get_events_for_position(position_id, signal_id, strategy, contract_address)
        close_keywords = [
            "executed_close", "closed_by", "close", "exit",
            "capacity_prune", "profit_reset", "close_all",
        ]
        return [
            e for e in events
            if any(kw in str(e.get("event_type", "")).lower() for kw in close_keywords)
        ]

