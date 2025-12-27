# backtester/infrastructure/xlsx_writer.py
# Utility for saving DataFrames to XLSX format with multiple sheets

from __future__ import annotations

from typing import Dict
from pathlib import Path
import pandas as pd
import warnings


def has_excel_engine() -> bool:
    """
    Проверяет наличие доступного Excel engine.
    
    Returns:
        True если есть xlsxwriter или openpyxl, иначе False
    """
    try:
        import xlsxwriter  # noqa
        return True
    except Exception:
        pass
    try:
        import openpyxl  # noqa
        return True
    except Exception:
        return False


def _pick_excel_engine() -> str:
    """
    Выбирает engine для Excel writer с fallback.
    
    Приоритет:
    1. xlsxwriter (если установлен)
    2. openpyxl (fallback, обычно установлен с pandas)
    
    Raises:
        ImportError если ни один движок не установлен
    """
    try:
        import xlsxwriter  # noqa
        return "xlsxwriter"
    except Exception:
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
            # Ограничиваем длину имени листа (Excel ограничение: 31 символ)
            sheet_name_limited = sheet_name[:31]
            df.to_excel(writer, sheet_name=sheet_name_limited, index=False)
    
    print(f"📊 Saved XLSX report to {path} ({len(sheets)} sheets)")

