# backtester/audit
# Global Audit: Pricing, PnL, Exit Reasons, Policy Decisions (Runner-only)

from .invariants import (
    AnomalyType,
    Anomaly,
    InvariantChecker,
    check_pnl_formula,
    check_reason_consistency,
    check_magic_values,
    check_time_ordering,
    check_policy_consistency,
)
from .data_loader import AuditDataLoader, load_positions, load_events, load_executions
from .indices import AuditIndices
from .audit_pipeline import run_audit
from .trade_replay import TradeReplay, replay_position
from .report import AuditReport, generate_audit_report

__all__ = [
    "AnomalyType",
    "Anomaly",
    "InvariantChecker",
    "check_pnl_formula",
    "check_reason_consistency",
    "check_magic_values",
    "check_time_ordering",
    "check_policy_consistency",
    "AuditDataLoader",
    "load_positions",
    "load_events",
    "load_executions",
    "AuditIndices",
    "run_audit",
    "TradeReplay",
    "replay_position",
    "AuditReport",
    "generate_audit_report",
]

