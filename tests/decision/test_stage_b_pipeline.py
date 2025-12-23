"""
Integration test for Stage B pipeline
"""
import pytest
import pandas as pd
from pathlib import Path
import tempfile
import shutil

from backtester.decision.run_stage_b import main
from backtester.decision.strategy_selector import (
    generate_selection_table_from_stability,
    load_stability_csv,
    select_strategies,
)
from backtester.decision.selection_rules import DEFAULT_CRITERIA, DEFAULT_CRITERIA_V1, DEFAULT_RUNNER_CRITERIA_V1


@pytest.fixture
def fake_stability_csv(tmp_path):
    """Создаёт fake strategy_stability.csv"""
    stability_df = pd.DataFrame({
        "strategy": [
            "strategy_pass_1",
            "strategy_pass_2",
            "strategy_fail_survival",
            "strategy_fail_variance",
            "strategy_fail_worst",
        ],
        "survival_rate": [0.8, 0.75, 0.4, 0.7, 0.8],  # fail_survival < 0.60 (v1)
        "pnl_variance": [0.05, 0.08, 0.03, 0.20, 0.04],  # fail_variance > 0.15 (v1: max=0.15)
        "worst_window_pnl": [-0.1, -0.15, -0.05, -0.1, -0.30],  # fail_worst < -0.25 (v1: min=-0.25)
        "best_window_pnl": [0.2, 0.3, 0.15, 0.2, 0.1],
        "median_window_pnl": [0.05, 0.08, 0.02, 0.05, 0.03],
        "windows_positive": [4, 3, 2, 4, 4],
        "windows_total": [5, 4, 5, 5, 5],
    })
    
    csv_path = tmp_path / "strategy_stability.csv"
    stability_df.to_csv(csv_path, index=False)
    return csv_path


def test_stage_b_pipeline_full(fake_stability_csv, monkeypatch, capsys):
    """Проверяет полный pipeline Stage B"""
    import sys
    monkeypatch.setattr(sys, "argv", [
        "run_stage_b.py",
        "--stability-csv",
        str(fake_stability_csv),
    ])
    
    # Запускаем Stage B
    main()
    
    # Проверяем, что создан файл strategy_selection.csv
    selection_path = fake_stability_csv.parent / "strategy_selection.csv"
    assert selection_path.exists(), "strategy_selection.csv should be created"
    
    # Проверяем содержимое файла
    df = pd.read_csv(selection_path)
    
    assert len(df) == 5, "Should have all strategies from stability table"
    assert "strategy" in df.columns
    assert "passed" in df.columns
    assert "failed_reasons" in df.columns
    
    # Проверяем, что некоторые стратегии прошли, а некоторые нет
    passed_count = df["passed"].sum()
    assert passed_count > 0, "At least one strategy should pass"
    assert passed_count < len(df), "At least one strategy should fail"


def test_stage_b_pipeline_selection_table_exists(fake_stability_csv):
    """Проверяет наличие итогового CSV после pipeline"""
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=fake_stability_csv,
        output_path=fake_stability_csv.parent / "strategy_selection.csv",
        criteria=DEFAULT_CRITERIA_V1,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    assert len(selection_df) == 5, "Should have all strategies"
    
    # Проверяем обязательные колонки
    required_cols = [
        "strategy",
        "passed",
        "failed_reasons",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "median_window_pnl",
        "windows_positive",
        "windows_total",
    ]
    
    for col in required_cols:
        assert col in selection_df.columns, f"Missing column: {col}"


def test_stage_b_pipeline_passed_strategies_less_than_input(fake_stability_csv):
    """Проверяет, что passed стратегий ≤ входных"""
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=fake_stability_csv,
        criteria=DEFAULT_CRITERIA_V1,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    total_strategies = len(selection_df)
    passed_count = selection_df["passed"].sum()
    
    assert passed_count <= total_strategies, "Passed strategies should be <= total"
    
    # С DEFAULT_CRITERIA_V1 должны пройти только strategy_pass_1 и strategy_pass_2
    # strategy_fail_survival: survival_rate=0.4 < 0.60 (v1)
    # strategy_fail_variance: pnl_variance=0.20 > 0.15 (v1)
    # strategy_fail_worst: worst_window_pnl=-0.30 < -0.25 (v1)
    
    passed_strategies = selection_df[selection_df["passed"]]["strategy"].tolist()
    assert "strategy_pass_1" in passed_strategies
    assert "strategy_pass_2" in passed_strategies


def test_stage_b_pipeline_failed_reasons_correct(fake_stability_csv):
    """Проверяет, что failed_reasons корректно заполнены"""
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=fake_stability_csv,
        criteria=DEFAULT_CRITERIA_V1,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    # strategy_fail_survival должна иметь failed_reasons с survival_rate
    fail_survival = selection_df[selection_df["strategy"] == "strategy_fail_survival"].iloc[0]
    assert fail_survival["passed"] == False  # Используем == вместо is для pandas bool
    failed_reasons = fail_survival["failed_reasons"]
    if isinstance(failed_reasons, str):
        assert "survival_rate" in failed_reasons
    elif isinstance(failed_reasons, list):
        assert any("survival_rate" in reason for reason in failed_reasons)
    
    # strategy_fail_variance должна иметь failed_reasons с pnl_variance
    fail_variance = selection_df[selection_df["strategy"] == "strategy_fail_variance"].iloc[0]
    assert fail_variance["passed"] == False  # Используем == вместо is для pandas bool
    failed_reasons = fail_variance["failed_reasons"]
    if isinstance(failed_reasons, str):
        assert "pnl_variance" in failed_reasons
    elif isinstance(failed_reasons, list):
        assert any("pnl_variance" in reason for reason in failed_reasons)


def test_stage_b_pipeline_no_sorting(fake_stability_csv):
    """Проверяет, что таблица НЕ отсортирована по pnl"""
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=fake_stability_csv,
        criteria=DEFAULT_CRITERIA_V1,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    # Загружаем оригинальный порядок из stability CSV
    stability_df = load_stability_csv(fake_stability_csv)
    
    # Порядок стратегий должен совпадать с исходным (не отсортирован по pnl)
    assert list(selection_df["strategy"]) == list(stability_df["strategy"])


def test_stage_b_pipeline_empty_stability(tmp_path):
    """Проверяет обработку пустого stability CSV"""
    empty_csv = tmp_path / "empty_stability.csv"
    empty_df = pd.DataFrame(columns=[
        "strategy",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "best_window_pnl",
        "median_window_pnl",
        "windows_positive",
        "windows_total",
    ])
    empty_df.to_csv(empty_csv, index=False)
    
    selection_df = generate_selection_table_from_stability(
        stability_csv_path=empty_csv,
        criteria=DEFAULT_CRITERIA_V1,
        runner_criteria=DEFAULT_RUNNER_CRITERIA_V1,
    )
    
    assert len(selection_df) == 0
    assert "passed" in selection_df.columns
    assert "failed_reasons" in selection_df.columns



















