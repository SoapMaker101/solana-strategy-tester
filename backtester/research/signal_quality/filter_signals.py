# backtester/research/signal_quality/filter_signals.py
"""
Модуль для фильтрации сигналов по порогам market cap proxy.
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path
from typing import Dict, Any


def filter_signals(
    signals_path: str | Path,
    features_df: pd.DataFrame,
    min_market_cap_proxy: float,
    require_status_ok: bool = True,
) -> pd.DataFrame:
    """
    Фильтрует сигналы по порогу market cap proxy.
    
    :param signals_path: Путь к CSV файлу с сигналами
    :param features_df: DataFrame с признаками сигналов (должен содержать market_cap_proxy и status)
    :param min_market_cap_proxy: Минимальный порог market cap proxy
    :param require_status_ok: Требовать статус 'ok' для включения сигнала
    :return: Отфильтрованный DataFrame с сигналами
    """
    # Загружаем исходные сигналы
    signals_df = pd.read_csv(signals_path)
    
    # Объединяем с признаками
    merged_df = signals_df.merge(
        features_df[['id', 'market_cap_proxy', 'status']],
        on='id',
        how='inner'
    )
    
    # Фильтруем по порогу market cap proxy
    filtered = merged_df[merged_df['market_cap_proxy'] >= min_market_cap_proxy]
    
    # Фильтруем по статусу, если требуется
    if require_status_ok:
        filtered = filtered[filtered['status'] == 'ok']
    
    # Удаляем служебные колонки перед возвратом
    result = filtered.drop(columns=['market_cap_proxy', 'status'], errors='ignore')
    
    return result


def generate_filter_summary(
    original_count: int,
    filtered_count: int,
    features_df: pd.DataFrame,
    min_market_cap_proxy: float,
) -> Dict[str, Any]:
    """
    Генерирует сводку по фильтрации сигналов.
    
    :param original_count: Исходное количество сигналов
    :param filtered_count: Количество сигналов после фильтрации
    :param features_df: DataFrame с признаками
    :param min_market_cap_proxy: Использованный порог market cap proxy
    :return: Словарь со сводкой
    """
    removed_count = original_count - filtered_count
    removed_pct = (removed_count / original_count * 100) if original_count > 0 else 0.0
    
    # Статистика по статусам
    status_counts = features_df['status'].value_counts().to_dict() if 'status' in features_df.columns else {}
    
    return {
        'original_count': original_count,
        'filtered_count': filtered_count,
        'removed_count': removed_count,
        'removed_pct': removed_pct,
        'min_market_cap_proxy': min_market_cap_proxy,
        'status_distribution': status_counts,
    }


def save_filtered_signals(filtered_df: pd.DataFrame, output_path: str | Path) -> None:
    """
    Сохраняет отфильтрованные сигналы в CSV файл.
    
    :param filtered_df: DataFrame с отфильтрованными сигналами
    :param output_path: Путь для сохранения
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filtered_df.to_csv(output_path, index=False)


def save_filter_summary(summary: Dict[str, Any], output_path: str | Path) -> None:
    """
    Сохраняет сводку фильтрации в JSON файл.
    
    :param summary: Словарь со сводкой
    :param output_path: Путь для сохранения
    """
    import json
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)





















