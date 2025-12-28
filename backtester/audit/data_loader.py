# backtester/audit/data_loader.py
# Загрузка данных для аудита

from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd


class AuditDataLoader:
    """Загрузчик данных для аудита."""
    
    def __init__(self, run_dir: Path):
        """
        Инициализация загрузчика.
        
        :param run_dir: Директория с результатами прогона (содержит portfolio_positions.csv, portfolio_events.csv и т.д.)
        """
        self.run_dir = Path(run_dir)
        if not self.run_dir.exists():
            raise ValueError(f"Run directory does not exist: {run_dir}")
    
    def load_positions(self) -> Optional[pd.DataFrame]:
        """
        Загружает portfolio_positions.csv.
        
        :return: DataFrame с позициями или None если файл не найден
        """
        positions_path = self.run_dir / "portfolio_positions.csv"
        if not positions_path.exists():
            return None
        
        try:
            df = pd.read_csv(positions_path)
            # Конвертируем datetime колонки
            for col in ["entry_time", "exit_time"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
            return df
        except Exception as e:
            raise ValueError(f"Failed to load positions: {e}")
    
    def load_events(self) -> Optional[pd.DataFrame]:
        """
        Загружает portfolio_events.csv.
        
        :return: DataFrame с событиями или None если файл не найден
        """
        events_path = self.run_dir / "portfolio_events.csv"
        if not events_path.exists():
            return None
        
        try:
            df = pd.read_csv(events_path)
            # Конвертируем datetime колонки
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            return df
        except Exception as e:
            raise ValueError(f"Failed to load events: {e}")
    
    def load_executions(self) -> Optional[pd.DataFrame]:
        """
        Загружает portfolio_executions.csv (если есть).
        
        :return: DataFrame с исполнениями или None если файл не найден
        """
        executions_path = self.run_dir / "portfolio_executions.csv"
        if not executions_path.exists():
            return None
        
        try:
            df = pd.read_csv(executions_path)
            # Конвертируем datetime колонки
            if "event_time" in df.columns:
                df["event_time"] = pd.to_datetime(df["event_time"], utc=True, errors="coerce")
            return df
        except Exception as e:
            raise ValueError(f"Failed to load executions: {e}")
    
    def load_all(self) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Загружает все доступные файлы.
        
        :return: Словарь с ключами: positions, events, executions
        """
        return {
            "positions": self.load_positions(),
            "events": self.load_events(),
            "executions": self.load_executions(),
        }


# Convenience functions
def load_positions(run_dir: Path) -> Optional[pd.DataFrame]:
    """Загружает portfolio_positions.csv."""
    loader = AuditDataLoader(run_dir)
    return loader.load_positions()


def load_events(run_dir: Path) -> Optional[pd.DataFrame]:
    """Загружает portfolio_events.csv."""
    loader = AuditDataLoader(run_dir)
    return loader.load_events()


def load_executions(run_dir: Path) -> Optional[pd.DataFrame]:
    """Загружает portfolio_executions.csv."""
    loader = AuditDataLoader(run_dir)
    return loader.load_executions()

