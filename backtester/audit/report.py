# backtester/audit/report.py
# Генерация отчётов аудита

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import json

import pandas as pd

from .invariants import Anomaly, AnomalyType


@dataclass
class AuditReport:
    """Отчёт аудита."""
    
    run_dir: Path
    anomalies: List[Anomaly]
    positions_count: int
    positions_closed: int = 0
    events_count: int = 0
    executions_count: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """Получает сводную статистику по аномалиям."""
        if len(self.anomalies) == 0:
            return {
                "total_anomalies": 0,
                "by_type": {},
                "by_strategy": {},
                "by_severity": {},
                "by_code": {},
            }
        
        by_type: Dict[str, int] = {}
        by_strategy: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        by_code: Dict[str, int] = {}
        
        for anomaly in self.anomalies:
            # По типу (legacy, для совместимости)
            anomaly_type = anomaly.anomaly_type.value
            by_type[anomaly_type] = by_type.get(anomaly_type, 0) + 1
            
            # По коду (новое)
            code = anomaly.anomaly_type.value
            by_code[code] = by_code.get(code, 0) + 1
            
            # По стратегии
            strategy = anomaly.strategy
            by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
            
            # По severity
            severity = anomaly.severity
            by_severity[severity] = by_severity.get(severity, 0) + 1
        
        return {
            "total_anomalies": len(self.anomalies),
            "by_type": by_type,
            "by_strategy": by_strategy,
            "by_severity": by_severity,
            "by_code": by_code,
        }


def generate_audit_report(report: AuditReport, output_dir: Path, verbose: bool = True) -> None:
    """
    Генерирует отчёты аудита.
    
    Создаёт:
    - audit_anomalies.csv — список всех аномалий
    - audit_summary.md — человеческий отчёт
    - audit_metrics.csv — агрегированные метрики (опционально)
    
    :param report: AuditReport с результатами
    :param output_dir: Директория для сохранения отчётов
    :param verbose: Выводить ли прогресс
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. CSV с аномалиями
    if len(report.anomalies) > 0:
        anomalies_df = pd.DataFrame([a.to_dict() for a in report.anomalies])
        anomalies_path = output_dir / "audit_anomalies.csv"
        anomalies_df.to_csv(anomalies_path, index=False)
        if verbose:
            print(f"[audit] Saved {len(report.anomalies)} anomalies to {anomalies_path}")
        else:
            # Создаём пустой CSV с правильными колонками
            empty_df = pd.DataFrame(columns=pd.Index([
                "severity", "code", "position_id", "event_id", "strategy", "signal_id", "contract_address",
                "entry_time", "exit_time", "entry_price", "exit_price",
                "pnl_pct", "reason", "anomaly_type", "details_json",
            ]))
            anomalies_path = output_dir / "audit_anomalies.csv"
            empty_df.to_csv(anomalies_path, index=False)
        if verbose:
            print(f"[audit] No anomalies found. Created empty file: {anomalies_path}")
    
    # 2. Markdown отчёт
    summary_path = output_dir / "audit_summary.md"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(f"# Audit Report\n\n")
        f.write(f"**Run Directory:** `{report.run_dir}`\n")
        f.write(f"**Timestamp:** {report.timestamp.isoformat()}\n\n")
        
        f.write(f"## Summary\n\n")
        f.write(f"- **Positions:** {report.positions_count} (closed: {report.positions_closed})\n")
        f.write(f"- **Events:** {report.events_count}\n")
        f.write(f"- **Executions:** {report.executions_count}\n")
        f.write(f"- **Anomalies:** {len(report.anomalies)}\n\n")
        
        stats = report.get_summary_stats()
        if stats["total_anomalies"] > 0:
            f.write(f"## Anomalies by Severity\n\n")
            for severity, count in sorted(stats["by_severity"].items(), key=lambda x: ("P0", "P1", "P2").index(x[0]) if x[0] in ("P0", "P1", "P2") else 999):
                f.write(f"- **{severity}**: {count}\n")
            f.write("\n")
            
            f.write(f"## Anomalies by Code\n\n")
            for code, count in sorted(stats["by_code"].items(), key=lambda x: -x[1])[:20]:  # Топ-20
                f.write(f"- **{code}**: {count}\n")
            f.write("\n")
            
            f.write(f"## Anomalies by Strategy\n\n")
            for strategy, count in sorted(stats["by_strategy"].items(), key=lambda x: -x[1])[:10]:  # Топ-10
                f.write(f"- **{strategy}**: {count}\n")
            f.write("\n")
            
            f.write(f"## Top Anomalies (by Severity)\n\n")
            f.write(f"| Severity | Code | Position ID | Strategy | Reason | PnL % |\n")
            f.write(f"|----------|------|-------------|----------|--------|-------|\n")
            # Сортируем по severity (P0 → P1 → P2)
            sorted_anomalies = sorted(report.anomalies, key=lambda a: ("P0", "P1", "P2").index(a.severity) if a.severity in ("P0", "P1", "P2") else 999)
            for anomaly in sorted_anomalies[:20]:  # Топ-20
                f.write(f"| {anomaly.severity} | {anomaly.anomaly_type.value} | {anomaly.position_id or 'N/A'} | {anomaly.strategy} | {anomaly.reason or 'N/A'} | {anomaly.pnl_pct or 'N/A'} |\n")
        else:
            f.write(f"## ✅ No Anomalies Found\n\n")
            f.write(f"All positions passed invariant checks.\n")
    
    if verbose:
        print(f"[audit] Saved summary to {summary_path}")
    
    # 3. Метрики (расширенные)
    metrics_path = output_dir / "audit_metrics.csv"
    stats = report.get_summary_stats()
    
    metrics_rows = [
        {"metric": "positions_total", "value": report.positions_count},
        {"metric": "positions_closed", "value": report.positions_closed},
        {"metric": "events_total", "value": report.events_count},
        {"metric": "executions_total", "value": report.executions_count},
        {"metric": "anomalies_total", "value": len(report.anomalies)},
        {"metric": "anomaly_rate_pct", "value": (len(report.anomalies) / report.positions_count * 100) if report.positions_count > 0 else 0.0},
        {"metric": "share_positions_with_any_anomaly", "value": (len(set(a.position_id for a in report.anomalies if a.position_id)) / report.positions_count * 100) if report.positions_count > 0 else 0.0},
    ]
    
    # Добавляем метрики по severity
    for severity, count in stats["by_severity"].items():
        metrics_rows.append({"metric": f"anomalies_{severity.lower()}", "value": count})
    
    # Добавляем метрики по кодам (топ-10)
    for code, count in sorted(stats["by_code"].items(), key=lambda x: -x[1])[:10]:
        metrics_rows.append({"metric": f"anomalies_by_code_{code}", "value": count})
    
    # Добавляем метрики по стратегиям (топ-10)
    for strategy, count in sorted(stats["by_strategy"].items(), key=lambda x: -x[1])[:10]:
        metrics_rows.append({"metric": f"anomalies_by_strategy_{strategy}", "value": count})
    
    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(metrics_path, index=False)
    if verbose:
        print(f"[audit] Saved metrics to {metrics_path}")

