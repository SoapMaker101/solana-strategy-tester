# backtester/audit/audit_pipeline.py
# Основной пайплайн аудита

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict, Any
import pandas as pd

from .data_loader import AuditDataLoader
from .invariants import InvariantChecker, Anomaly
from .report import AuditReport, generate_audit_report


def run_audit(
    run_dir: Path,
    output_dir: Optional[Path] = None,
    verbose: bool = True,
) -> AuditReport:
    """
    Запускает полный аудит прогона.
    
    :param run_dir: Директория с результатами прогона
    :param output_dir: Директория для сохранения отчётов (по умолчанию run_dir/audit/)
    :param verbose: Выводить ли прогресс в консоль
    :return: AuditReport с результатами аудита
    """
    if verbose:
        print(f"[audit] Starting audit for: {run_dir}")
    
    # Загружаем данные
    loader = AuditDataLoader(run_dir)
    data = loader.load_all()
    
    positions_df = data.get("positions")
    events_df = data.get("events")
    executions_df = data.get("executions")
    
    if positions_df is None or len(positions_df) == 0:
        if verbose:
            print("[audit] WARNING: No positions found. Cannot run audit.")
        return AuditReport(
            run_dir=run_dir,
            anomalies=[],
            positions_count=0,
            events_count=0,
            executions_count=0,
        )
    
    if verbose:
        print(f"[audit] Loaded {len(positions_df)} positions")
        if events_df is not None:
            print(f"[audit] Loaded {len(events_df)} events")
        if executions_df is not None:
            print(f"[audit] Loaded {len(executions_df)} executions")
    
    # Фильтруем только Runner стратегии (Runner-only проект)
    if "strategy" in positions_df.columns:
        runner_positions = positions_df[
            positions_df["strategy"].str.contains("Runner", case=False, na=False)
        ]
        if len(runner_positions) < len(positions_df):
            if verbose:
                print(f"[audit] Filtered to {len(runner_positions)} Runner positions (from {len(positions_df)} total)")
            positions_df = runner_positions
    
    # Запускаем проверки инвариантов
    if verbose:
        print("[audit] Running invariant checks...")
    
    checker = InvariantChecker(include_p1=True, include_p2=True)
    anomalies = checker.check_all(positions_df, events_df, executions_df)
    
    if verbose:
        print(f"[audit] Found {len(anomalies)} anomalies")
    
    # Подсчитываем закрытые позиции
    positions_closed = len(positions_df[positions_df.get("status") == "closed"]) if "status" in positions_df.columns else 0
    
    # Создаём отчёт
    report = AuditReport(
        run_dir=run_dir,
        anomalies=anomalies,
        positions_count=len(positions_df),
        positions_closed=positions_closed,
        events_count=len(events_df) if events_df is not None else 0,
        executions_count=len(executions_df) if executions_df is not None else 0,
    )
    
    # Сохраняем отчёт
    if output_dir is None:
        output_dir = run_dir / "audit"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if verbose:
        print(f"[audit] Generating report in: {output_dir}")
    
    generate_audit_report(report, output_dir, verbose=verbose)
    
    if verbose:
        print(f"[audit] Audit complete. Found {len(anomalies)} anomalies.")
        if len(anomalies) > 0:
            print(f"[audit] See {output_dir / 'audit_anomalies.csv'} for details")
    
    return report

