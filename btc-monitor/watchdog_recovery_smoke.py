"""One-shot real GitHub Actions watchdog recovery API smoke test.

Does NOT alter source measurements or the scheduled ChatGPT tasks. It creates
exactly one genuine workflow_dispatch using a simulated stale condition, then
verifies the dispatch appears as a GitHub Actions workflow run. A receipt is
stored for idempotency.
"""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watchdog as wd

UTC = dt.timezone.utc
RECEIPT = Path("btc-monitor/data/watchdog_recovery_test.json")
if RECEIPT.exists():
    try:
        previous = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if previous.get("verified") is True:
            print("Already passed live dispatch verification; no second dispatch")
            raise SystemExit(0)
    except (ValueError, OSError):
        pass

started = dt.datetime.now(UTC)
chosen = None
for name in ("macro_etf", "price_technical", "options"):
    workflow = wd.latest_workflow_run(wd.FEEDS[name]["workflow"])
    if not workflow["active"]:
        chosen = (name, workflow)
        break
if chosen is None:
    raise RuntimeError("No safe idle lightweight collector for real recovery smoke test")
name, run_state = chosen
fixture = {"needs_recovery": True, "reason": "simulated_missed_run_test_only"}
state = {}
decision = wd.recovery_decision(name, fixture, run_state, state, started,
                                1, dispatch_fn=wd.api)
if decision.get("action") != "dispatched":
    raise RuntimeError("Actual workflow dispatch failed: "+json.dumps(decision))
workflow_file = wd.FEEDS[name]["workflow"]
found = None
for i in range(12):
    state_now = wd.latest_workflow_run(workflow_file)
    for run in [state_now.get("latest"), state_now.get("active"),
                state_now.get("completed")]:
        if not isinstance(run, dict):
            continue
        t = wd.parse_time(run.get("created_at"))
        if (run.get("event") == "workflow_dispatch" and t and
                (t-started).total_seconds() >= -40):
            found = run
            break
    if found:
        break
    time.sleep(3)
if not found:
    raise RuntimeError("GitHub accepted dispatch but no matching actual workflow run appeared")
receipt = {"verified": True, "tested_utc": started.isoformat(),
           "finished_utc": dt.datetime.now(UTC).isoformat(),
           "test_type": "single_real_actions_dispatch_from_simulated_stale_condition",
           "collector": name, "workflow": workflow_file,
           "recovery_action": decision["action"], "run_id": found["id"],
           "run_url": found["html_url"], "run_event": found["event"],
           "source_market_files_intentionally_unmodified": True,
           "separate_chatgpt_l2_automation_unmodified": True,
           "note": "Verifies a real GitHub dispatch, not automatic repair of a live outage."}
RECEIPT.parent.mkdir(parents=True, exist_ok=True)
RECEIPT.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n",
                   encoding="utf-8")
print(json.dumps(receipt,ensure_ascii=False))
