# backtester/decision/selection_aggregator.py
# Aggregates strategy metrics across split_count values

from __future__ import annotations

from typing import Optional
import pandas as pd
import numpy as np


def aggregate_stability(stability_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates strategy stability metrics across split_count values.
    
    Input: DataFrame from strategy_stability.csv with columns:
        strategy, split_count, survival_rate, worst_window_pnl, median_window_pnl,
        pnl_variance, windows_total, trades_total, etc.
    
    Output: DataFrame with ONE row per strategy, aggregated metrics:
        - splits_total = count of rows per strategy
        - worst_case_window_pnl = min(worst_window_pnl)
        - median_survival_rate = median(survival_rate)
        - median_median_window_pnl = median(median_window_pnl)
        - max_pnl_variance = max(pnl_variance)
        - For other numeric columns: median if varies, keep if constant
    
    :param stability_df: DataFrame from strategy_stability.csv.
    :return: Aggregated DataFrame with one row per strategy.
    """
    if len(stability_df) == 0:
        return stability_df.copy()
    
    # Check required columns
    required_cols = ["strategy"]
    if "split_count" not in stability_df.columns:
        # If no split_count, assume each row is already unique per strategy
        return stability_df.copy()
    
    # Group by strategy
    grouped = stability_df.groupby("strategy")
    
    aggregated_rows = []
    
    for strategy_name, group_df in grouped:
        row = {"strategy": strategy_name}
        
        # Count splits
        row["splits_total"] = len(group_df)
        
        # Robustness metrics
        if "worst_window_pnl" in group_df.columns:
            row["worst_case_window_pnl"] = group_df["worst_window_pnl"].min()
        
        if "survival_rate" in group_df.columns:
            row["median_survival_rate"] = group_df["survival_rate"].median()
        
        if "median_window_pnl" in group_df.columns:
            row["median_median_window_pnl"] = group_df["median_window_pnl"].median()
        
        if "pnl_variance" in group_df.columns:
            row["max_pnl_variance"] = group_df["pnl_variance"].max()
        
        # For other numeric columns, take median if varies, keep if constant
        numeric_cols = group_df.select_dtypes(include=[np.number]).columns
        exclude_cols = {"split_count", "worst_window_pnl", "survival_rate", 
                       "median_window_pnl", "pnl_variance"}
        
        for col in numeric_cols:
            if col not in exclude_cols and col != "strategy":
                values = group_df[col].dropna()
                if len(values) > 0:
                    # Check if constant (all same value within tolerance)
                    if values.nunique() == 1:
                        row[col] = values.iloc[0]
                    else:
                        # Take median for varying values
                        row[col] = values.median()
        
        # For non-numeric columns (except strategy), take first value if constant
        non_numeric_cols = group_df.select_dtypes(exclude=[np.number]).columns
        for col in non_numeric_cols:
            if col != "strategy":
                values = group_df[col].dropna().unique()
                if len(values) == 1:
                    row[col] = values[0]
                # If varies, don't include (or could concatenate, but for now skip)
        
        aggregated_rows.append(row)
    
    result_df = pd.DataFrame(aggregated_rows)
    
    # Ensure numeric columns are proper types
    numeric_metrics = ["splits_total", "worst_case_window_pnl", "median_survival_rate",
                      "median_median_window_pnl", "max_pnl_variance"]
    for col in numeric_metrics:
        if col in result_df.columns:
            result_df[col] = pd.to_numeric(result_df[col], errors="coerce")
    
    return result_df


def aggregate_selection(selection_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates strategy selection results across split_count values.
    
    Input: DataFrame from strategy_selection.csv with columns:
        strategy, split_count, survival_rate, worst_window_pnl, median_window_pnl,
        pnl_variance, windows_total, trades_total, passed, failed_reasons, etc.
        Optionally: selection_status
    
    Output: DataFrame with ONE row per strategy, aggregated metrics:
        - splits_total = count of rows per strategy
        - robust_pass_rate = mean(passed_split)
        - passed_any = any(passed_split)
        - passed_all = all(passed_split)
        - worst_case_window_pnl = min(worst_window_pnl)
        - median_survival_rate = median(survival_rate)
        - median_median_window_pnl = median(median_window_pnl)
        - max_pnl_variance = max(pnl_variance)
        - insufficient_data_rate = mean(selection_status == "insufficient_data")
        - rejected_rate = mean(selection_status == "rejected")
    
    :param selection_df: DataFrame from strategy_selection.csv.
    :return: Aggregated DataFrame with one row per strategy.
    """
    if len(selection_df) == 0:
        return selection_df.copy()
    
    # Check required columns
    required_cols = ["strategy", "passed"]
    missing_cols = [col for col in required_cols if col not in selection_df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # If no split_count, assume each row is already unique per strategy
    if "split_count" not in selection_df.columns:
        # Still compute robust_pass_rate from passed column
        result_df = selection_df.copy()
        if "passed" in result_df.columns:
            result_df["robust_pass_rate"] = result_df["passed"].astype(float)
            result_df["passed_any"] = result_df["passed"]
            result_df["passed_all"] = result_df["passed"]
        return result_df
    
    # Group by strategy
    grouped = selection_df.groupby("strategy")
    
    aggregated_rows = []
    
    for strategy_name, group_df in grouped:
        row = {"strategy": strategy_name}
        
        # Count splits
        row["splits_total"] = len(group_df)
        
        # Robustness metrics from passed column
        if "passed" in group_df.columns:
            passed_series = group_df["passed"].astype(bool)
            row["robust_pass_rate"] = passed_series.mean()
            row["passed_any"] = passed_series.any()
            row["passed_all"] = passed_series.all()
        
        # Window PnL metrics
        if "worst_window_pnl" in group_df.columns:
            row["worst_case_window_pnl"] = group_df["worst_window_pnl"].min()
        
        if "survival_rate" in group_df.columns:
            row["median_survival_rate"] = group_df["survival_rate"].median()
        
        if "median_window_pnl" in group_df.columns:
            row["median_median_window_pnl"] = group_df["median_window_pnl"].median()
        
        if "pnl_variance" in group_df.columns:
            row["max_pnl_variance"] = group_df["pnl_variance"].max()
        
        # Selection status metrics (if exists)
        if "selection_status" in group_df.columns:
            status_series = group_df["selection_status"]
            row["insufficient_data_rate"] = (status_series == "insufficient_data").mean()
            row["rejected_rate"] = (status_series == "rejected").mean()
        
        # For other numeric columns, take median if varies, keep if constant
        numeric_cols = group_df.select_dtypes(include=[np.number]).columns
        exclude_cols = {"split_count", "worst_window_pnl", "survival_rate",
                       "median_window_pnl", "pnl_variance", "passed"}
        
        for col in numeric_cols:
            if col not in exclude_cols and col != "strategy":
                values = group_df[col].dropna()
                if len(values) > 0:
                    # Check if constant
                    if values.nunique() == 1:
                        row[col] = values.iloc[0]
                    else:
                        # Take median for varying values
                        row[col] = values.median()
        
        # For non-numeric columns (except strategy, failed_reasons), take first if constant
        non_numeric_cols = group_df.select_dtypes(exclude=[np.number]).columns
        for col in non_numeric_cols:
            if col not in {"strategy", "failed_reasons", "selection_status"}:
                values = group_df[col].dropna().unique()
                if len(values) == 1:
                    row[col] = values[0]
                # If varies, skip
        
        # For failed_reasons, we could aggregate but for now skip (could join, but complex)
        # For selection_status, we already computed rates above
        
        aggregated_rows.append(row)
    
    result_df = pd.DataFrame(aggregated_rows)
    
    # Ensure numeric columns are proper types
    numeric_metrics = ["splits_total", "robust_pass_rate", "worst_case_window_pnl",
                      "median_survival_rate", "median_median_window_pnl", "max_pnl_variance",
                      "insufficient_data_rate", "rejected_rate"]
    for col in numeric_metrics:
        if col in result_df.columns:
            result_df[col] = pd.to_numeric(result_df[col], errors="coerce")
    
    # Ensure boolean columns
    bool_metrics = ["passed_any", "passed_all"]
    for col in bool_metrics:
        if col in result_df.columns:
            result_df[col] = result_df[col].astype(bool)
    
    return result_df
