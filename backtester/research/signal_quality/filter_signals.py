# backtester/research/signal_quality/filter_signals.py
"""
Модуль для фильтрации сигналов по порогам market cap proxy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, cast

import pandas as pd

from ...domain.models import Signal
from ...infrastructure.signal_loader import CsvSignalLoader


def _signals_to_dataframe(signals: list[Signal]) -> pd.DataFrame:
    """
    Преобразует список Signal в DataFrame.
    
    :param signals: Список сигналов
    :return: DataFrame с колонками id, contract_address, timestamp, source, narrative
    """
    signals_data = []
    for sig in signals:
        signals_data.append({
            "id": sig.id,
            "contract_address": sig.contract_address,
            "timestamp": sig.timestamp,
            "source": sig.source,
            "narrative": sig.narrative,
        })
    return pd.DataFrame(signals_data)


def filter_signals(
    signals_path: str | Path,
    features_df: pd.DataFrame,
    min_market_cap_proxy: float,
    require_status_ok: bool = True
) -> pd.DataFrame:
    """
    Фильтрует сигналы по порогу market_cap_proxy.
    
    :param signals_path: Путь к исходному CSV файлу с сигналами
    :param features_df: DataFrame с признаками сигналов (должна быть колонка market_cap_proxy)
    :param min_market_cap_proxy: Минимальный порог market cap proxy
    :param require_status_ok: Если True, фильтрует только сигналы со status="ok"
    :return: Отфильтрованный DataFrame с сигналами
    """
    # Загружаем исходные сигналы
    loader = CsvSignalLoader(str(signals_path))
    signals = loader.load_signals()
    
    # Преобразуем в DataFrame
    signals_df = _signals_to_dataframe(signals)
    
    # Объединяем с признаками
    merged = signals_df.merge(
        features_df[["signal_id", "market_cap_proxy", "status"]],
        left_on="id",
        right_on="signal_id",
        how="inner"
    )
    
    # Применяем фильтры
    filtered = merged[
        (merged["market_cap_proxy"] >= min_market_cap_proxy)
    ]
    
    if require_status_ok:
        filtered = filtered[filtered["status"] == "ok"]
    
    # Убираем служебные колонки
    # Selecting multiple columns always returns a DataFrame, but type checker needs help
    result = cast(
        pd.DataFrame,
        filtered[["id", "contract_address", "timestamp", "source", "narrative"]].copy()
    )
    
    return result


def _normalize_timestamp_column(df: pd.DataFrame, column: str = "timestamp") -> pd.DataFrame:
    """
    Нормализует колонку timestamp в ISO формат строки.
    
    :param df: DataFrame с колонкой timestamp
    :param column: Имя колонки с timestamp (default: "timestamp")
    :return: DataFrame с нормализованным timestamp
    """
    df = df.copy()
    
    if column not in df.columns:
        return df
    
    if pd.api.types.is_datetime64_any_dtype(df[column]):
        df[column] = df[column].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif len(df) > 0 and not isinstance(df[column].iloc[0], str):
        # Пытаемся преобразовать в datetime и затем в строку
        df[column] = pd.to_datetime(df[column]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Если уже строка, оставляем как есть
    
    return df


def save_filtered_signals(
    filtered_df: pd.DataFrame,
    output_path: str | Path
) -> None:
    """
    Сохраняет отфильтрованные сигналы в CSV.
    
    :param filtered_df: DataFrame с отфильтрованными сигналами
    :param output_path: Путь для сохранения CSV
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Преобразуем timestamp в ISO формат
    df_to_save = _normalize_timestamp_column(filtered_df)
    
    df_to_save.to_csv(output_path, index=False)
    print(f"[filter] Saved {len(filtered_df)} filtered signals to {output_path}")


def generate_filter_summary(
    original_count: int,
    filtered_count: int,
    features_df: pd.DataFrame,
    min_market_cap_proxy: float
) -> dict:
    """
    Генерирует summary фильтрации.
    
    :param original_count: Количество исходных сигналов
    :param filtered_count: Количество отфильтрованных сигналов
    :param features_df: DataFrame с признаками
    :param min_market_cap_proxy: Применённый порог
    :return: Словарь с summary
    """
    valid_features = features_df[features_df["status"] == "ok"]
    removed_count = original_count - filtered_count
    removed_pct = (removed_count / original_count * 100) if original_count > 0 else 0.0
    
    summary = {
        "original_signals": original_count,
        "filtered_signals": filtered_count,
        "removed_signals": removed_count,
        "removed_pct": round(removed_pct, 2),
        "min_market_cap_proxy": min_market_cap_proxy,
        "valid_signals_before_filter": len(valid_features),
        "valid_signals_after_filter": len(valid_features[valid_features["market_cap_proxy"] >= min_market_cap_proxy]) if not valid_features.empty else 0,
    }
    
    return summary


def save_filter_summary(
    summary: dict,
    output_path: str | Path
) -> None:
    """
    Сохраняет summary фильтрации в JSON.
    
    :param summary: Словарь с summary
    :param output_path: Путь для сохранения JSON
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"[summary] Saved filter summary to {output_path}")
