# backtester/infrastructure/xlsx_writer.py
# Utility for saving DataFrames to XLSX format with multiple sheets

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import pandas as pd
import warnings

try:
    import xlsxwriter  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    xlsxwriter = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import xlsxwriter as xlsxwriter_typed  # type: ignore[import-not-found]


def has_excel_engine() -> bool:
    """
    Проверяет наличие доступного Excel engine.
    
    Returns:
        True если есть xlsxwriter или openpyxl, иначе False
    """
    if xlsxwriter is not None:
        return True
    try:
        import openpyxl  # noqa
        return True
    except Exception:
        return False


def _normalize_datetime_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Конвертирует tz-aware datetime колонки в tz-naive (UTC-naive) для совместимости с Excel.
    
    Excel не поддерживает timezone-aware datetimes, поэтому нужно конвертировать их
    в naive перед записью.
    
    :param df: Исходный DataFrame
    :return: DataFrame с конвертированными datetime колонками
    """
    work_df = df.copy()
    
    for col in work_df.columns:
        # Проверяем pandas datetime dtype с timezone
        if pd.api.types.is_datetime64_any_dtype(work_df[col]):
            col_dtype = work_df[col].dtype
            if hasattr(col_dtype, 'tz') and col_dtype.tz is not None:  # type: ignore[attr-defined]
                # Конвертируем tz-aware в UTC, затем убираем timezone
                work_df[col] = work_df[col].dt.tz_convert("UTC").dt.tz_localize(None)
        
        # Best-effort для object колонок, которые могут содержать datetime с tzinfo
        elif work_df[col].dtype == "object" and len(work_df[col].dropna()) > 0:
            # Проверяем первый не-null элемент
            sample = work_df[col].dropna().iloc[0]
            if isinstance(sample, datetime) and sample.tzinfo is not None:
                # Пытаемся конвертировать через pandas
                try:
                    converted = pd.to_datetime(work_df[col], utc=True, errors="coerce")
                    # Проверяем что конвертация не потеряла слишком много данных
                    if converted.notna().sum() >= len(work_df[col].dropna()) * 0.8:
                        work_df[col] = converted.dt.tz_localize(None)
                except Exception:
                    # Если конвертация не удалась, оставляем как есть
                    pass
    
    return work_df


def _pick_excel_engine() -> str:
    """
    Выбирает engine для Excel writer с fallback.
    
    Приоритет:
    1. xlsxwriter (если установлен)
    2. openpyxl (fallback, обычно установлен с pandas)
    
    Raises:
        ImportError если ни один движок не установлен
    """
    if xlsxwriter is not None:
        return "xlsxwriter"
    else:
        try:
            import openpyxl  # noqa
            return "openpyxl"
        except Exception:
            raise ImportError("Neither xlsxwriter nor openpyxl is installed")


def save_xlsx(
    path: str | Path,
    sheets: Dict[str, pd.DataFrame]
) -> None:
    """
    Сохраняет несколько DataFrame в один XLSX файл с несколькими листами.
    
    Если нет доступного Excel engine (xlsxwriter/openpyxl), функция
    молча пропускает XLSX-экспорт и выводит предупреждение.
    CSV-файлы продолжают создаваться нормально.
    
    :param path: Путь к файлу для сохранения.
    :param sheets: Словарь {sheet_name: DataFrame} с данными для каждого листа.
    
    Пример:
        save_xlsx(
            "report.xlsx",
            {
                "positions": positions_df,
                "equity_curve": equity_df,
                "stats": stats_df,
            }
        )
    """
    if not has_excel_engine():
        warnings.warn(
            "Excel engine (xlsxwriter/openpyxl) not installed; skipping XLSX export. "
            "CSV files will still be created.",
            UserWarning,
            stacklevel=2
        )
        return
    
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    engine = _pick_excel_engine()
    with pd.ExcelWriter(path, engine=engine) as writer:
        for sheet_name, df in sheets.items():
            # Конвертируем tz-aware datetime колонки в tz-naive для Excel
            work_df = _normalize_datetime_columns(df)
            
            # Ограничиваем длину имени листа (Excel ограничение: 31 символ)
            sheet_name_limited = sheet_name[:31]
            work_df.to_excel(writer, sheet_name=sheet_name_limited, index=False)
    
    print(f"📊 Saved XLSX report to {path} ({len(sheets)} sheets)")

