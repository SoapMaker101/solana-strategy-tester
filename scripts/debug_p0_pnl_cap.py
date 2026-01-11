# scripts/debug_p0_pnl_cap.py
import json
import pandas as pd
from pathlib import Path

REPORTS = Path(r"runs\A\reports")
POS_ID = "25bcc9bf698e4371ae9c2f6e225a978d"

positions = pd.read_csv(REPORTS / "portfolio_positions.csv")
events = pd.read_csv(REPORTS / "portfolio_events.csv")
execs = pd.read_csv(REPORTS / "portfolio_executions.csv")
anom = pd.read_csv(REPORTS / "audit_anomalies.csv")

print("\n=== ANOMALY ROW ===")
if "position_id" in anom.columns:
    a = anom[anom["position_id"] == POS_ID]
else:
    # Try to find position_id in context or message fields
    a = anom[
        anom["context"].astype(str).str.contains(POS_ID, na=False) |
        anom["message"].astype(str).str.contains(POS_ID, na=False)
    ]
print(a.to_string(index=False))
if len(a) and "details_json" in a.columns:
    try:
        print("\nDetails JSON:\n", json.dumps(json.loads(a.iloc[0]["details_json"]), indent=2))
    except Exception:
        pass

print("\n=== POSITION ROW ===")
p = positions[positions["position_id"] == POS_ID]
print(p.to_string(index=False))

print("\n=== EVENTS (by position_id) ===")
e = events[events["position_id"] == POS_ID].sort_values("timestamp")
cols = [c for c in ["timestamp","event_type","reason","event_id","meta_json"] if c in e.columns]
print(e[cols].to_string(index=False))

print("\n=== EXECUTIONS (by position_id) ===")
x = execs[execs["position_id"] == POS_ID].sort_values("event_time" if "event_time" in execs.columns else execs.columns[0])
print(x.to_string(index=False))

# Extra quick checks
if len(p):
    row = p.iloc[0].to_dict()
    pnl_pct = row.get("pnl_pct")
    pnl_sol = row.get("pnl_sol")
    print("\n=== QUICK CHECKS ===")
    print("pnl_pct:", pnl_pct, "pnl_sol:", pnl_sol)
    try:
        if pd.notna(pnl_pct):
            print("abs(pnl_pct) =", abs(float(pnl_pct)))
    except Exception:
        pass
    try:
        if pd.notna(pnl_sol):
            print("abs(pnl_sol) =", abs(float(pnl_sol)))
    except Exception:
        pass
