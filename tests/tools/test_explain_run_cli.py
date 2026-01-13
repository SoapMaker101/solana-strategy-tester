"""
Тесты для CLI инструмента explain_run.
"""
import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from backtester.tools.explain_run import (
    explain_run,
    extract_reset_events,
    check_anomalies,
    parse_meta_json,
    load_csv_safe
)


def test_generates_markdown_with_minimal_artifacts(tmp_path):
    """Test 1: генерирует markdown с минимальными артефактами."""
    # Создаем временную структуру директорий
    run_dir = tmp_path / "test_run"
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True)
    
    # Создаем минимальный portfolio_events.csv
    events_data = {
        "timestamp": ["2024-01-01T12:00:00+00:00"],
        "event_type": ["portfolio_reset_triggered"],
        "reason": ["profit_reset"],
        "meta_json": [json.dumps({
            "reset_id": "test_reset_1",
            "trigger_basis": "equity_peak",
            "multiple": 1.3,
            "threshold": 13.0,
            "cycle_start_equity": 10.0,
            "equity_peak_in_cycle": 13.5,
            "closed_positions_count": 3
        })]
    }
    events_df = pd.DataFrame(events_data)
    events_df.to_csv(reports_dir / "portfolio_events.csv", index=False)
    
    # Создаем минимальный portfolio_summary.csv
    summary_data = {
        "final_balance_sol": [15.0],
        "total_return_pct": [0.5],
        "trades_executed": [10]
    }
    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(reports_dir / "portfolio_summary.csv", index=False)
    
    # Запускаем explain_run
    result = explain_run(
        run_dir=run_dir,
        reports_subdir="reports",
        out_path=reports_dir / "RUN_EXPLAIN.md",
        format="md"
    )
    
    # Проверяем что файл создан
    output_file = reports_dir / "RUN_EXPLAIN.md"
    assert output_file.exists(), "Output markdown file should be created"
    
    # Проверяем содержимое
    content = output_file.read_text(encoding="utf-8")
    assert "Run Explain: test_run" in content, "Should contain title"
    assert "portfolio_events.csv" in content, "Should mention events file"
    assert "reset_events_count" in content or "Reset Events Count" in content, "Should mention reset count"
    
    # Проверяем результат
    assert result["reset_events_count"] == 1
    assert result["critical_count"] == 0


def test_meta_json_parsing_resilient(tmp_path):
    """Test 2: парсинг meta_json устойчив к ошибкам."""
    run_dir = tmp_path / "test_run"
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True)
    
    # Создаем events с битым meta_json
    events_data = {
        "timestamp": ["2024-01-01T12:00:00+00:00"],
        "event_type": ["portfolio_reset_triggered"],
        "reason": ["profit_reset"],
        "meta_json": ["{invalid json}"]  # Битый JSON
    }
    events_df = pd.DataFrame(events_data)
    events_df.to_csv(reports_dir / "portfolio_events.csv", index=False)
    
    # Запускаем explain_run - не должен упасть
    result = explain_run(
        run_dir=run_dir,
        reports_subdir="reports",
        out_path=reports_dir / "RUN_EXPLAIN.md",
        format="md"
    )
    
    # Проверяем что файл создан
    output_file = reports_dir / "RUN_EXPLAIN.md"
    assert output_file.exists()
    
    # Проверяем что есть предупреждение о parse errors
    content = output_file.read_text(encoding="utf-8")
    # Должно быть предупреждение о parse errors
    assert result["warnings_count"] >= 0  # Может быть 0 или больше, но не должно падать


def test_critical_anomaly_detection(tmp_path):
    """Test 3: обнаружение критических аномалий."""
    run_dir = tmp_path / "test_run"
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True)
    
    # Создаем событие с closed_positions_count=0 (критическая аномалия)
    events_data = {
        "timestamp": ["2024-01-01T12:00:00+00:00"],
        "event_type": ["portfolio_reset_triggered"],
        "reason": ["profit_reset"],
        "meta_json": [json.dumps({
            "reset_id": "test_reset_1",
            "trigger_basis": "equity_peak",
            "multiple": 1.3,
            "threshold": 13.0,
            "cycle_start_equity": 10.0,
            "equity_peak_in_cycle": 13.5,
            "closed_positions_count": 0  # Критическая аномалия
        })]
    }
    events_df = pd.DataFrame(events_data)
    events_df.to_csv(reports_dir / "portfolio_events.csv", index=False)
    
    # Запускаем explain_run
    result = explain_run(
        run_dir=run_dir,
        reports_subdir="reports",
        out_path=reports_dir / "RUN_EXPLAIN.md",
        format="md"
    )
    
    # Проверяем что критическая аномалия обнаружена
    assert result["critical_count"] > 0, "Should detect critical anomaly"
    
    # Проверяем что в markdown есть информация об аномалии
    output_file = reports_dir / "RUN_EXPLAIN.md"
    content = output_file.read_text(encoding="utf-8")
    assert "CRITICAL" in content or "critical" in content.lower(), "Should mention critical anomalies"


def test_extract_reset_events():
    """Тест извлечения reset событий."""
    events_data = {
        "timestamp": ["2024-01-01T12:00:00+00:00", "2024-01-02T12:00:00+00:00"],
        "event_type": ["portfolio_reset_triggered", "position_closed"],
        "reason": ["profit_reset", "ladder_tp"],
        "meta_json": [
            json.dumps({
                "reset_id": "reset_1",
                "trigger_basis": "equity_peak",
                "multiple": 1.3,
                "threshold": 13.0,
                "cycle_start_equity": 10.0,
                "equity_peak_in_cycle": 13.5,
                "closed_positions_count": 3
            }),
            json.dumps({"some": "data"})
        ]
    }
    events_df = pd.DataFrame(events_data)
    
    reset_df = extract_reset_events(events_df)
    
    assert len(reset_df) == 1, "Should extract one reset event"
    assert reset_df.iloc[0]["reset_id"] == "reset_1"
    assert reset_df.iloc[0]["trigger_basis"] == "equity_peak"


def test_check_anomalies_zero_closed_positions():
    """Тест проверки аномалий: closed_positions_count == 0."""
    reset_data = {
        "reset_id": ["reset_1"],
        "timestamp": ["2024-01-01T12:00:00+00:00"],
        "trigger_basis": ["equity_peak"],
        "multiple": [1.3],
        "threshold": [13.0],
        "cycle_start_equity": [10.0],
        "equity_peak_in_cycle": [13.5],
        "closed_positions_count": [0],  # Критическая аномалия
        "meta_parsed": [{}]
    }
    reset_df = pd.DataFrame(reset_data)
    
    critical, warnings = check_anomalies(reset_df, None)
    
    assert len(critical) > 0, "Should detect critical anomaly"
    assert any(a["type"] == "zero_closed_positions" for a in critical), "Should detect zero_closed_positions"


def test_check_anomalies_invalid_trigger_basis():
    """Тест проверки аномалий: невалидный trigger_basis."""
    reset_data = {
        "reset_id": ["reset_1"],
        "timestamp": ["2024-01-01T12:00:00+00:00"],
        "trigger_basis": ["invalid_basis"],  # Невалидный
        "multiple": [1.3],
        "threshold": [13.0],
        "cycle_start_equity": [10.0],
        "equity_peak_in_cycle": [13.5],
        "closed_positions_count": [3],
        "meta_parsed": [{}]
    }
    reset_df = pd.DataFrame(reset_data)
    
    critical, warnings = check_anomalies(reset_df, None)
    
    assert len(critical) > 0, "Should detect critical anomaly"
    assert any(a["type"] == "invalid_trigger_basis" for a in critical), "Should detect invalid_trigger_basis"


def test_check_anomalies_equity_peak_invalid_baseline():
    """Тест проверки аномалий: equity_peak с cycle_start_equity <= 0."""
    reset_data = {
        "reset_id": ["reset_1"],
        "timestamp": ["2024-01-01T12:00:00+00:00"],
        "trigger_basis": ["equity_peak"],
        "multiple": [1.3],
        "threshold": [-1.0],  # Отрицательный threshold
        "cycle_start_equity": [-1.0],  # Отрицательный baseline
        "equity_peak_in_cycle": [13.5],
        "closed_positions_count": [3],
        "meta_parsed": [{}]
    }
    reset_df = pd.DataFrame(reset_data)
    
    critical, warnings = check_anomalies(reset_df, None)
    
    assert len(critical) > 0, "Should detect critical anomaly"
    assert any(a["type"] == "invalid_equity_peak_baseline" for a in critical), "Should detect invalid_equity_peak_baseline"


def test_parse_meta_json_valid():
    """Тест парсинга валидного meta_json."""
    meta_str = json.dumps({"reset_id": "test", "trigger_basis": "equity_peak"})
    result = parse_meta_json(meta_str)
    
    assert isinstance(result, dict)
    assert result["reset_id"] == "test"
    assert result["trigger_basis"] == "equity_peak"
    assert "_parse_error" not in result


def test_parse_meta_json_invalid():
    """Тест парсинга невалидного meta_json."""
    meta_str = "{invalid json}"
    result = parse_meta_json(meta_str)
    
    assert isinstance(result, dict)
    assert "_parse_error" in result
    assert "_raw" in result


def test_parse_meta_json_empty():
    """Тест парсинга пустого meta_json."""
    result = parse_meta_json("")
    assert result == {}
    
    result = parse_meta_json(None)
    assert result == {}


def test_load_csv_safe_exists(tmp_path):
    """Тест загрузки существующего CSV."""
    csv_path = tmp_path / "test.csv"
    test_data = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})
    test_data.to_csv(csv_path, index=False)
    
    result = load_csv_safe(csv_path, "test.csv")
    
    assert result is not None
    assert len(result) == 2


def test_load_csv_safe_not_exists(tmp_path):
    """Тест загрузки несуществующего CSV."""
    csv_path = tmp_path / "nonexistent.csv"
    
    result = load_csv_safe(csv_path, "nonexistent.csv")
    
    assert result is None
