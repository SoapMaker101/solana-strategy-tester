from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import math
import pandas as pd
from ..utils.typing_utils import safe_float, isin_values


@dataclass(frozen=True)
class AuditAnomaly:
    severity: str  # P0 / P1
    code: str
    message: str
    context: Dict[str, Any]


class InvariantChecker:
    def __init__(
        self,
        positions_df: Optional[pd.DataFrame],
        events_df: Optional[pd.DataFrame],
        executions_df: Optional[pd.DataFrame],
    ) -> None:
        self.positions_df = positions_df
        self.events_df = events_df
        self.executions_df = executions_df
        self.anomalies: List[AuditAnomaly] = []

    def _add(self, severity: str, code: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self.anomalies.append(
            AuditAnomaly(severity=severity, code=code, message=message, context=context or {})
        )

    def _require_columns(self, df: Optional[pd.DataFrame], columns: Iterable[str], scope: str) -> bool:
        if df is None:
            self._add("P1", "missing_dataframe", f"{scope} dataframe not provided", {})
            return False
        missing = [col for col in columns if col not in df.columns]
        if missing:
            self._add(
                "P1",
                "missing_columns",
                f"{scope} missing columns: {missing}",
                {"missing": missing},
            )
            return False
        return True

    def check(self) -> List[AuditAnomaly]:
        self._check_pnl_caps()
        self._check_reset_chain()
        self._check_position_event_links()
        self._check_execution_event_links()
        self._check_execution_price_bounds()
        return self.anomalies

    def _check_pnl_caps(self) -> None:
        if not self._require_columns(self.positions_df, ["position_id"], "positions"):
            return

        df = self.positions_df
        if df is None:
            return

        pnl_col = "pnl_pct_total" if "pnl_pct_total" in df.columns else "pnl_pct"
        if pnl_col not in df.columns:
            self._add("P1", "missing_columns", "positions missing pnl_pct_total/pnl_pct", {})
            return

        for _, row in df.iterrows():
            pnl_val = row.get(pnl_col)
            if pnl_val is None or (isinstance(pnl_val, float) and (math.isnan(pnl_val) or math.isinf(pnl_val))):
                self._add(
                    "P0",
                    "pnl_cap_or_magic",
                    f"Invalid pnl value for position {row.get('position_id')}",
                    {"position_id": row.get("position_id"), "pnl": pnl_val},
                )
                continue
            try:
                pnl_val = float(pnl_val)
            except (TypeError, ValueError):
                self._add(
                    "P0",
                    "pnl_cap_or_magic",
                    f"Non-numeric pnl value for position {row.get('position_id')}",
                    {"position_id": row.get("position_id"), "pnl": pnl_val},
                )
                continue
            if abs(pnl_val) > 1000:
                self._add(
                    "P0",
                    "pnl_cap_or_magic",
                    f"PnL cap exceeded for position {row.get('position_id')}",
                    {"position_id": row.get("position_id"), "pnl": pnl_val},
                )

        if "reason" in df.columns:
            for _, row in df.iterrows():
                reason = row.get("reason")
                if reason == "stop_loss":
                    pnl_val_raw = row.get(pnl_col)
                    pnl_val = safe_float(pnl_val_raw, default=0.0)
                    # Skip if value was actually NaN (not just 0.0)
                    if pnl_val == 0.0 and (pnl_val_raw is None or (isinstance(pnl_val_raw, (int, float)) and pd.isna(pnl_val_raw))):
                        continue
                    if pnl_val >= 0:
                        self._add(
                            "P1",
                            "stop_loss_non_negative",
                            f"stop_loss with non-negative pnl for position {row.get('position_id')}",
                            {"position_id": row.get("position_id"), "pnl": pnl_val},
                        )

    def _check_reset_chain(self) -> None:
        if self.events_df is None and self.positions_df is None:
            return

        reset_events = []
        if self.events_df is not None and "event_type" in self.events_df.columns:
            reset_events = self.events_df[
                self.events_df["event_type"] == "PORTFOLIO_RESET_TRIGGERED"
            ]

        reset_reasons = {"profit_reset", "capacity_prune"}

        positions_reset = []
        if self.positions_df is not None and "reset_reason" in self.positions_df.columns:
            positions_reset = self.positions_df[
                self.positions_df["reset_reason"].isin(isin_values(reset_reasons))
            ]

        events_reset = []
        if self.events_df is not None and "reason" in self.events_df.columns:
            events_reset = self.events_df[
                (self.events_df["event_type"] == "POSITION_CLOSED")
                & (self.events_df["reason"].isin(isin_values(reset_reasons)))
            ]

        if (len(positions_reset) > 0 or len(events_reset) > 0) and len(reset_events) == 0:
            self._add(
                "P0",
                "reset_without_events",
                "Reset activity detected without PORTFOLIO_RESET_TRIGGERED events",
                {},
            )

    def _check_position_event_links(self) -> None:
        if not self._require_columns(self.positions_df, ["position_id", "status"], "positions"):
            return
        if not self._require_columns(self.events_df, ["position_id", "event_type"], "events"):
            if self.positions_df is not None and not self.positions_df.empty:
                self._add(
                    "P1",
                    "missing_events_chain",
                    "Positions exist but events are missing",
                    {},
                )
            return

        positions = self.positions_df
        events = self.events_df
        if positions is None or events is None:
            return

        close_events = events[events["event_type"] == "POSITION_CLOSED"]
        close_event_ids = set(pd.Series(close_events["position_id"]).dropna().astype(str))

        for _, row in positions.iterrows():
            if str(row.get("status")).lower() == "closed":
                pid = str(row.get("position_id"))
                if pid not in close_event_ids:
                    self._add(
                        "P1",
                        "missing_events_chain",
                        f"Closed position {pid} has no POSITION_CLOSED event",
                        {"position_id": pid},
                    )

        open_positions = positions[positions["status"].astype(str).str.lower() == "open"]
        open_ids = set(pd.Series(open_positions["position_id"]).dropna().astype(str))
        for _, row in close_events.iterrows():
            pid = str(row.get("position_id"))
            if pid in open_ids:
                self._add(
                    "P1",
                    "close_event_but_position_open",
                    f"POSITION_CLOSED event exists for open position {pid}",
                    {"position_id": pid},
                )

    def _check_execution_event_links(self) -> None:
        if self.executions_df is None or self.events_df is None:
            return

        if not self._require_columns(self.executions_df, ["position_id"], "executions"):
            return
        if not self._require_columns(self.events_df, ["position_id", "event_type"], "events"):
            return

        executions = self.executions_df
        events = self.events_df

        event_positions = set(events["position_id"].dropna().astype(str))
        for _, row in executions.iterrows():
            pid = str(row.get("position_id"))
            if pid and pid not in event_positions:
                self._add(
                    "P1",
                    "execution_without_trade_event",
                    f"Execution found without matching event for position {pid}",
                    {"position_id": pid},
                )

        if "event_id" in executions.columns and "event_id" in events.columns:
            execution_event_ids = set(executions["event_id"].dropna().astype(str))
            for _, row in events.iterrows():
                if row.get("event_type") in ("POSITION_PARTIAL_EXIT", "POSITION_CLOSED"):
                    event_id = str(row.get("event_id"))
                    if event_id and event_id not in execution_event_ids:
                        self._add(
                            "P1",
                            "trade_event_without_execution",
                            f"Event {event_id} missing execution record",
                            {"event_id": event_id},
                        )

    def _check_execution_price_bounds(self) -> None:
        if self.executions_df is None or self.positions_df is None:
            return
        if not self._require_columns(self.executions_df, ["position_id", "exec_price"], "executions"):
            return

        positions = self.positions_df.set_index("position_id") if self.positions_df is not None else None
        if positions is None:
            return

        for _, row in self.executions_df.iterrows():
            pid = row.get("position_id")
            exec_price = row.get("exec_price")
            if exec_price is None or (isinstance(exec_price, float) and (math.isnan(exec_price) or math.isinf(exec_price))):
                self._add(
                    "P1",
                    "execution_price_out_of_range",
                    "Execution price missing/invalid",
                    {"position_id": pid},
                )
                continue
            try:
                exec_price = float(exec_price)
            except (TypeError, ValueError):
                self._add(
                    "P1",
                    "execution_price_out_of_range",
                    "Execution price non-numeric",
                    {"position_id": pid, "exec_price": exec_price},
                )
                continue
            if exec_price <= 0:
                self._add(
                    "P1",
                    "execution_price_out_of_range",
                    "Execution price <= 0",
                    {"position_id": pid, "exec_price": exec_price},
                )
                continue

            if pid in positions.index:
                entry_price = positions.loc[pid].get("entry_price")
                exit_price = positions.loc[pid].get("exit_price")
                try:
                    entry_price = float(entry_price) if entry_price is not None else None
                    exit_price = float(exit_price) if exit_price is not None else None
                except (TypeError, ValueError):
                    entry_price = None
                    exit_price = None

                bounds = [p for p in [entry_price, exit_price] if p is not None and p > 0]
                if bounds:
                    min_bound = min(bounds) * 0.5
                    max_bound = max(bounds) * 1.5
                    if not (min_bound <= exec_price <= max_bound):
                        self._add(
                            "P1",
                            "execution_price_out_of_range",
                            "Execution price outside expected range",
                            {
                                "position_id": pid,
                                "exec_price": exec_price,
                                "min_bound": min_bound,
                                "max_bound": max_bound,
                            },
                        )
