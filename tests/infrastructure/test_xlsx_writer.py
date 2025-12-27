# tests/infrastructure/test_xlsx_writer.py
# Tests for XLSX writer utility

import pytest
import pandas as pd
from pathlib import Path
from backtester.infrastructure.xlsx_writer import save_xlsx, has_excel_engine

# Скипаем все тесты если нет Excel engine
pytestmark = pytest.mark.skipif(
    not has_excel_engine(),
    reason="No Excel engine (xlsxwriter/openpyxl) installed in environment"
)


def test_xlsx_created(tmp_path):
    """Smoke-test: проверяем что XLSX файл создается."""
    path = tmp_path / "test.xlsx"
    
    df1 = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    df2 = pd.DataFrame({"x": [10, 20], "y": [30, 40]})
    
    save_xlsx(path, {"sheet1": df1, "sheet2": df2})
    
    assert path.exists()


def test_xlsx_sheets(tmp_path):
    """Проверяем что все листы создаются правильно."""
    path = tmp_path / "test.xlsx"
    
    df1 = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    df2 = pd.DataFrame({"x": [10, 20], "y": [30, 40]})
    
    save_xlsx(path, {"sheet_a": df1, "sheet_b": df2})
    
    # Проверяем что файл существует
    assert path.exists()
    
    # Проверяем листы
    xls = pd.ExcelFile(path)
    assert set(xls.sheet_names) == {"sheet_a", "sheet_b"}


def test_xlsx_data_integrity(tmp_path):
    """Проверяем что данные сохраняются и читаются корректно."""
    path = tmp_path / "test.xlsx"
    
    df1 = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
    df2 = pd.DataFrame({"x": [10.5, 20.5], "y": [30.5, 40.5]})
    
    save_xlsx(path, {"data": df1, "numbers": df2})
    
    # Читаем обратно
    xls = pd.ExcelFile(path)
    
    # Проверяем первый лист
    read_df1 = pd.read_excel(xls, sheet_name="data")
    pd.testing.assert_frame_equal(read_df1, df1, check_index=False)
    
    # Проверяем второй лист
    read_df2 = pd.read_excel(xls, sheet_name="numbers")
    pd.testing.assert_frame_equal(read_df2, df2, check_index=False)


def test_xlsx_empty_dataframes(tmp_path):
    """Проверяем что пустые DataFrame обрабатываются корректно."""
    path = tmp_path / "test.xlsx"
    
    df1 = pd.DataFrame([], columns=["a", "b"])
    df2 = pd.DataFrame([], columns=["x", "y"])
    
    save_xlsx(path, {"empty1": df1, "empty2": df2})
    
    assert path.exists()
    
    xls = pd.ExcelFile(path)
    assert set(xls.sheet_names) == {"empty1", "empty2"}
    
    # Проверяем что листы пустые но с правильными колонками
    read_df1 = pd.read_excel(xls, sheet_name="empty1")
    assert list(read_df1.columns) == ["a", "b"]
    assert len(read_df1) == 0


def test_xlsx_sheet_name_truncation(tmp_path):
    """Проверяем что длинные имена листов обрезаются (Excel ограничение 31 символ)."""
    path = tmp_path / "test.xlsx"
    
    df = pd.DataFrame({"a": [1, 2]})
    
    # Имя листа длиннее 31 символа
    long_name = "a" * 40
    save_xlsx(path, {long_name: df})
    
    xls = pd.ExcelFile(path)
    # Проверяем что имя обрезано до 31 символа
    assert len(xls.sheet_names[0]) == 31
    assert xls.sheet_names[0] == "a" * 31


def test_xlsx_regression_csv_exists(tmp_path):
    """
    Regression-инвариант: проверяем что CSV файлы не исчезают.
    Это тест для демонстрации принципа - XLSX дополняет CSV, не заменяет.
    """
    # Этот тест демонстрирует концепцию, что CSV и XLSX должны существовать вместе
    # В реальных тестах это будет проверяться в интеграционных тестах
    
    csv_path = tmp_path / "test.csv"
    xlsx_path = tmp_path / "test.xlsx"
    
    df = pd.DataFrame({"a": [1, 2, 3]})
    
    # Сохраняем CSV
    df.to_csv(csv_path, index=False)
    
    # Сохраняем XLSX
    save_xlsx(xlsx_path, {"data": df})
    
    # Оба файла должны существовать
    assert csv_path.exists()
    assert xlsx_path.exists()

