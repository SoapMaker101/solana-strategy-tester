"""
Unit tests for strategy_selector module
"""
import pytest
import pandas as pd
from pathlib import Path

from backtester.decision.strategy_selector import (
    check_strategy_criteria,
    select_strategies,
    load_stability_csv,
    save_selection_table,
)
from backtester.decision.selection_rules import SelectionCriteria, DEFAULT_CRITERIA


@pytest.fixture
def sample_stability_df():
    """Создаёт sample DataFrame с метриками стратегий"""
    return pd.DataFrame({
        "strategy": ["strategy1", "strategy2", "strategy3"],
        "survival_rate": [0.8, 0.5, 0.9],
        "pnl_variance": [0.05, 0.15, 0.03],
        "worst_window_pnl": [-0.1, -0.3, -0.05],
        "best_window_pnl": [0.2, 0.1, 0.3],
        "median_window_pnl": [0.05, -0.05, 0.1],
        "windows_positive": [4, 2, 5],
        "windows_total": [5, 4, 5],
    })


@pytest.fixture
def strict_criteria():
    """Создаёт строгие критерии"""
    return SelectionCriteria(
        min_survival_rate=0.7,
        max_pnl_variance=0.10,
        min_worst_window_pnl=-0.15,
        min_median_window_pnl=0.0,
        min_windows=4,
    )


def test_check_strategy_criteria_passes_all(sample_stability_df, strict_criteria):
    """Проверяет, что стратегия проходит все условия → passed=True"""
    # strategy1: survival=0.8 (>=0.7), variance=0.05 (<=0.10), worst=-0.1 (>=-0.15), 
    #            median=0.05 (>=0.0), windows=5 (>=4)
    row = sample_stability_df.iloc[0]
    
    passed, failed_reasons = check_strategy_criteria(row, strict_criteria)
    
    assert passed is True
    assert len(failed_reasons) == 0


def test_check_strategy_criteria_fails_survival_rate(sample_stability_df, strict_criteria):
    """Проверяет, что стратегия падает по survival_rate → failed_reasons содержит причину"""
    # strategy2: survival=0.5 (<0.7) - должна упасть
    row = sample_stability_df.iloc[1]
    
    passed, failed_reasons = check_strategy_criteria(row, strict_criteria)
    
    assert passed is False
    assert len(failed_reasons) > 0
    assert any("survival_rate" in reason for reason in failed_reasons)


def test_check_strategy_criteria_fails_variance(sample_stability_df, strict_criteria):
    """Проверяет, что стратегия падает по pnl_variance"""
    # strategy2: variance=0.15 (>0.10) - должна упасть
    row = sample_stability_df.iloc[1]
    
    passed, failed_reasons = check_strategy_criteria(row, strict_criteria)
    
    assert passed is False
    assert any("pnl_variance" in reason for reason in failed_reasons)


def test_check_strategy_criteria_fails_worst_pnl(sample_stability_df, strict_criteria):
    """Проверяет, что стратегия падает по worst_window_pnl"""
    # strategy2: worst=-0.3 (<-0.15) - должна упасть
    row = sample_stability_df.iloc[1]
    
    passed, failed_reasons = check_strategy_criteria(row, strict_criteria)
    
    assert passed is False
    assert any("worst_window_pnl" in reason for reason in failed_reasons)


def test_check_strategy_criteria_fails_median_pnl(sample_stability_df, strict_criteria):
    """Проверяет, что стратегия падает по median_window_pnl"""
    # strategy2: median=-0.05 (<0.0) - должна упасть
    row = sample_stability_df.iloc[1]
    
    passed, failed_reasons = check_strategy_criteria(row, strict_criteria)
    
    assert passed is False
    assert any("median_window_pnl" in reason for reason in failed_reasons)


def test_check_strategy_criteria_fails_windows_total(sample_stability_df):
    """Проверяет, что стратегия с windows_total < min_windows → reject"""
    criteria = SelectionCriteria(
        min_survival_rate=0.0,
        max_pnl_variance=1.0,
        min_worst_window_pnl=-1.0,
        min_median_window_pnl=-1.0,
        min_windows=5,  # Требуем минимум 5 окон
    )
    
    # strategy2: windows_total=4 (<5) - должна упасть
    row = sample_stability_df.iloc[1]
    
    passed, failed_reasons = check_strategy_criteria(row, criteria)
    
    assert passed is False
    assert any("windows_total" in reason for reason in failed_reasons)


def test_select_strategies_passes_all_criteria(sample_stability_df):
    """Проверяет отбор стратегий, которые проходят все критерии"""
    # Используем мягкие критерии, чтобы strategy1 и strategy3 прошли
    criteria = SelectionCriteria(
        min_survival_rate=0.0,
        max_pnl_variance=1.0,
        min_worst_window_pnl=-1.0,
        min_median_window_pnl=-1.0,
        min_windows=0,
    )
    
    result_df = select_strategies(sample_stability_df, criteria)
    
    assert len(result_df) == len(sample_stability_df)  # Все стратегии
    assert "passed" in result_df.columns
    assert "failed_reasons" in result_df.columns
    assert result_df["passed"].all()  # Все прошли


def test_select_strategies_filters_by_criteria(sample_stability_df, strict_criteria):
    """Проверяет, что отбор фильтрует стратегии по критериям"""
    result_df = select_strategies(sample_stability_df, strict_criteria)
    
    # strategy1 должна пройти, strategy2 и strategy3 могут не пройти
    assert len(result_df) == len(sample_stability_df)  # Все стратегии в результате
    assert "passed" in result_df.columns
    
    # Проверяем, что strategy1 прошла
    strategy1_row = result_df[result_df["strategy"] == "strategy1"].iloc[0]
    assert strategy1_row["passed"] == True  # Используем == вместо is для pandas bool


def test_select_strategies_no_sorting(sample_stability_df):
    """Проверяет, что порядок строк не влияет на результат (нет сортировки)"""
    criteria = SelectionCriteria(
        min_survival_rate=0.0,
        max_pnl_variance=1.0,
        min_worst_window_pnl=-1.0,
        min_median_window_pnl=-1.0,
        min_windows=0,
    )
    
    # Оригинальный порядок
    result1 = select_strategies(sample_stability_df, criteria)
    
    # Перемешанный порядок
    shuffled_df = sample_stability_df.sample(frac=1.0).reset_index(drop=True)
    result2 = select_strategies(shuffled_df, criteria)
    
    # Порядок стратегий должен сохраниться (не отсортирован по pnl)
    # Проверяем, что стратегии в том же порядке, что и во входном DataFrame
    assert list(result1["strategy"]) == list(sample_stability_df["strategy"])
    assert list(result2["strategy"]) == list(shuffled_df["strategy"])


def test_select_strategies_empty_dataframe():
    """Проверяет обработку пустого DataFrame"""
    empty_df = pd.DataFrame(columns=[
        "strategy",
        "survival_rate",
        "pnl_variance",
        "worst_window_pnl",
        "median_window_pnl",
        "windows_total",
    ])
    
    result_df = select_strategies(empty_df, DEFAULT_CRITERIA)
    
    assert len(result_df) == 0
    assert "passed" in result_df.columns
    assert "failed_reasons" in result_df.columns


def test_select_strategies_missing_columns():
    """Проверяет обработку отсутствующих колонок"""
    invalid_df = pd.DataFrame({
        "strategy": ["test"],
        "survival_rate": [0.5],
        # Отсутствуют другие обязательные колонки
    })
    
    with pytest.raises(ValueError, match="Missing required columns"):
        select_strategies(invalid_df, DEFAULT_CRITERIA)


def test_load_stability_csv(tmp_path, sample_stability_df):
    """Проверяет загрузку stability CSV"""
    csv_path = tmp_path / "stability.csv"
    sample_stability_df.to_csv(csv_path, index=False)
    
    loaded_df = load_stability_csv(csv_path)
    
    assert len(loaded_df) == len(sample_stability_df)
    assert list(loaded_df.columns) == list(sample_stability_df.columns)


def test_load_stability_csv_missing_file(tmp_path):
    """Проверяет обработку отсутствующего файла"""
    csv_path = tmp_path / "nonexistent.csv"
    
    with pytest.raises(FileNotFoundError):
        load_stability_csv(csv_path)


def test_save_selection_table(tmp_path, sample_stability_df):
    """Проверяет сохранение таблицы отбора"""
    # Добавляем колонки отбора
    sample_stability_df["passed"] = [True, False, True]
    sample_stability_df["failed_reasons"] = [[], ["survival_rate"], []]
    
    output_path = tmp_path / "selection.csv"
    save_selection_table(sample_stability_df, output_path)
    
    assert output_path.exists()
    
    # Проверяем, что файл можно прочитать
    loaded_df = pd.read_csv(output_path)
    assert len(loaded_df) == len(sample_stability_df)






