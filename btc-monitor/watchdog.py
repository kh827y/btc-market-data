"""Independent GitHub Actions collector watchdog for the BTC hourly monitor.

This verifies actual source observations AND GitHub workflow runs. It never
turns coverage gaps into zero, never replays market trades, and never touches
the user's separate ChatGPT L2 history-backfill automation.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
ROOT = Path("btc-monitor/data")
OWNER_REPO = os.environ.get("GITHUB_REPOSITORY", "kh827y/btc-market-data")
BASE = f"https://api.github.com/repos/{OWNER_REPO}"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MAX_DISPATCHES = 2
MAX_RETRIES_24H = 3
COOLDOWN_H = 2.0

# Independent from the bridge's freshness labels. Never derive one source's
# health from the overall monitor feed being fresh.
FEEDS = {
    "price_technical": {
        "path": "btc-price/data/latest.json",
        "workflow": "btc-price-technicals.yml", "max_age_h": 4.0, "priority": 1},
    "spot_cvd": {
        "path": "btc-spot-cvd/data/latest.json",
        "workflow": "btc-spot-cvd.yml", "max_age_h": 4.0, "priority": 2},
    "derivatives": {
        "path": "btc-derivatives/data/latest.json",
        "workflow": "btc-derivatives-history.yml", "max_age_h": 4.5, "priority": 3},
    "options": {
        "path": "btc-options/data/latest.json",
        "workflow": "btc-options-history.yml", "max_age_h": 4.5, "priority": 4},
    "macro_etf": {
        "path": "btc-macro/data/latest.json",
        "workflow": "btc-macro-etf.yml", "max_age_h": 4.5, "priority": 5},
    "live_depth": {
        "path": "btc-liquidity/data/latest.json",
        "workflow": "btc-liquidity.yml", "max_age_h": 4.0, "priority": 6},
    "onchain": {
        "path": "btc-onchain/data/monitor_latest.json",
        "workflow": "btc-onchain-consolidate.yml", "max_age_h": 30.0, "priority": 7},
    # Historical collectors are already maintained by the active separate
    # L2 backfill. Observe health, never dispatch another backfill here.
    "hft_depth": {
        "path": "btc-liquidity/data/hft_latest.json",
        "workflow": "btc-hft-l2.yml", "max_age_h": 40.0,
        "priority": 10, "repair": False},
    "bybit_depth": {
        "path": "btc-liquidity/data/bybit_independent_latest.json",
        "workflow": "btc-bybit-independent.yml", "max_age_h": 40.0,
        "priority": 11, "repair": False},
    "monitor_bridge": {
        "path": "btc-monitor/data/brief.json",
        "workflow": "btc-monitor-bridge.yml", "max_age_h": 4.0, "priority": 9},
}


def parse_time(v):
    if not v:
        return None
    try:
        v = str(v)
        if len(v) == 10:
            v += "T00:00:00Z"
        x = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def age_h(now, value):
    x = parse_time(value)
    return round((now-x).total_seconds()/3600, 3) if x else None


def get(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def loaded(path):
    try:
        j = json.loads(Path(path).read_text(encoding="utf-8"))
        return j if isinstance(j, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def assess(name, record, now):
    """Return machine-verifiable freshness; historical gaps are separate."""
    cfg = FEEDS[name]
    result = {"status": "healthy", "reason": None, "needs_recovery": False,
              "workflow": cfg["workflow"], "source_path": cfg["path"],
              "repair_enabled": cfg.get("repair", True), "coverage_gaps": []}
    if not isinstance(record, dict):
        result.update(status="missing_file", reason="no_parseable_json", needs_recovery=True)
        return result
    timestamp = (record.get("as_of_utc") if name == "monitor_bridge"
                 else record.get("generated_utc") or record.get("generated_at"))
    age = age_h(now, timestamp)
    result["generated_utc"] = timestamp
    result["file_age_h"] = age
    if age is None or age < -0.2:
        result.update(status="invalid_timestamp", reason="missing_or_future_timestamp",
                      needs_recovery=True)
        return result
    if age > cfg["max_age_h"]:
        result.update(status="stale_file", reason="collector_not_publishing",
                      needs_recovery=True)
        # Do not return: the observation may separately be stale or valid.
    if name == "monitor_bridge":
        result["coverage_gaps"] = record.get("coverage_gaps") or []
        if not isinstance(record.get("sources"), dict):
            result.update(status="invalid_schema", reason="bridge_sources_missing",
                          needs_recovery=True)
    if name == "price_technical":
        day = parse_time(record.get("last_closed_day_utc"))
        week = parse_time(record.get("last_closed_week_monday_utc"))
        expected_week = now.date()-dt.timedelta(days=now.weekday()+7)
        valid_day = day is not None and day.date() == now.date()-dt.timedelta(days=1)
        valid_week = week is not None and week.date() == expected_week
        result["closed_day_utc"] = record.get("last_closed_day_utc")
        result["closed_week_utc"] = record.get("last_closed_week_monday_utc")
        quote_age = age_h(now, get(record, "spot_quote", "observed_utc"))
        result["live_quote_age_h"] = quote_age
        result["closed_candles_valid"] = bool(valid_day and valid_week)
        if not valid_day or not valid_week:
            result.update(status="stale_observation", reason="closed_utc_candles_missing",
                          needs_recovery=True)
        elif quote_age is None or not (-0.2 <= quote_age <= 2.5) or not get(record, "spot_quote", "price_usdt"):
            result["coverage_gaps"].append("live_quote_stale_or_missing")
            if result["status"] == "healthy":
                result.update(status="stale_observation", reason="live_quote_stale",
                              needs_recovery=True)
    elif name == "spot_cvd":
        hour = parse_time(record.get("last_complete_hour"))
        observed_end = hour + dt.timedelta(hours=1) if hour else None
        observation_age = round((now-observed_end).total_seconds()/3600, 3) if observed_end else None
        result["last_complete_hour"] = record.get("last_complete_hour")
        result["observation_age_h"] = observation_age
        if observation_age is None or not (-0.2 <= observation_age <= 4.5):
            result.update(status="stale_observation", reason="no_new_verified_taker_hour",
                          needs_recovery=True)
        for window in ("24h", "168h", "720h"):
            if get(record, "windows", window, "complete") is not True:
                result["coverage_gaps"].append(f"five_venue_cvd_{window}_incomplete")
    elif name == "derivatives":
        oi_age = age_h(now, get(record, "results", "open_interest", "latest_hour"))
        result["oi_observation_age_h"] = oi_age
        if oi_age is None or oi_age > 5.5 or oi_age < -0.2:
            result.update(status="stale_observation", reason="derivatives_oi_hour_stale",
                          needs_recovery=True)
    elif name == "options":
        live_age = age_h(now, get(record, "results", "deribit_live_surface", "as_of_utc"))
        result["deribit_surface_age_h"] = live_age
        if live_age is None or live_age > 5.5 or live_age < -0.2:
            result.update(status="stale_observation", reason="deribit_surface_stale",
                          needs_recovery=True)
    elif name == "live_depth":
        if (record.get("spot_usable_venues") or 0) < 1 and (record.get("perpetual_usable_venues") or 0) < 1:
            result.update(status="unavailable", reason="no_verified_orderbooks",
                          needs_recovery=True)
        errors = record.get("errors") or []
        if errors:
            result["coverage_gaps"].append(f"{len(errors)}_failed_live_book_venues")
    elif name == "macro_etf":
        if record.get("status") == "partial":
            result["coverage_gaps"].append("partial_macro_source")
        if get(record, "etf", "status") != "usable":
            result["coverage_gaps"].append("etf_flow_unusable_or_reporting_lag")
    elif name == "onchain":
        for gap in record.get("stale", []) or []:
            result["coverage_gaps"].append(str(gap)[:160])
        for gap in record.get("missing", []) or []:
            result["coverage_gaps"].append(str(gap)[:160])
    elif name in ("hft_depth", "bybit_depth"):
        date = (record.get("target_anchor_date") if name == "hft_depth"
                else record.get("target_day"))
        snapshot_age = age_h(now, date)
        result["snapshot_date"] = date
        result["snapshot_age_h"] = snapshot_age
        # Historical L2 is a once-daily point-in-time snapshot. No 1h norm.
        if snapshot_age is None or snapshot_age > 96 or snapshot_age < -24:
            result.update(status="stale_observation", reason="daily_historical_snapshot_missing",
                          needs_recovery=True)
        errors = record.get("errors_recent_run") or []
        if errors:
            result["coverage_gaps"].append(f"{len(errors)}_historical_source_errors")
    if record.get("status") not in (None, "ok", "partial") and name != "monitor_bridge":
        result.update(status="collector_error", reason="source_status_not_ok",
                      needs_recovery=True)
    if result["needs_recovery"] and not cfg.get("repair", True):
        result["recovery_policy"] = "separate_existing_L2_backfill_only"
    return result


def checkout_auth_header():
    """Use Git checkout's already configured credential without exposing it.

    In some workflow environments the passed GITHUB_TOKEN is not the token
    actually used by actions/checkout for authenticated Git operations.
    """
    try:
        line = subprocess.check_output(
            ["git", "config", "--local", "--get",
             "http.https://github.com/.extraheader"],
            text=True, timeout=5).strip()
        if line.lower().startswith("authorization: basic "):
            return line.split(":", 1)[1].strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return None


def api(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    shared = {"Accept": "application/vnd.github+json",
              "X-GitHub-Api-Version": "2022-11-28",
              "User-Agent": "btc-collector-watchdog/1.1",
              "Content-Type": "application/json"}
    auths = []
    if TOKEN:
        auths.append("Bearer "+TOKEN)
    checkout_auth = checkout_auth_header()
    if checkout_auth and checkout_auth not in auths:
        auths.append(checkout_auth)
    # Unauthenticated public reads can diagnose failures even when token
    # permissions are broken; they cannot dispatch recovery actions.
    if method == "GET":
        auths.append(None)
    last_error = "No GitHub API credential available"
    for auth in auths:
        headers = dict(shared)
        if auth is not None:
            headers["Authorization"] = auth
        request = urllib.request.Request(
            BASE+path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=22) as response:
                raw = response.read(1_500_000)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = error.read(300).decode("utf-8", "replace")
            last_error = f"GitHub_HTTP_{error.code}: {detail[:120]}"
            # Only invalid credentials are grounds to try the next supported
            # credential. A 403/429 resource or rate-limit failure must not
            # trigger multiple retries with different identities.
            if error.code != 401:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = type(error).__name__+":"+str(error)[:140]
            break
    raise RuntimeError(last_error)


def latest_workflow_run(workflow):
    path = "/actions/workflows/"+urllib.parse.quote(workflow)+"/runs?branch=main&per_page=12"
    runs = api("GET", path).get("workflow_runs") or []
    # GitHub creates skipped workflow_run jobs after unrelated failed workflows.
    # They are NOT successes and must not mask actual failures or missing runs.
    meaningful = [x for x in runs if x.get("conclusion") not in ("skipped", "cancelled")]
    active = [x for x in meaningful if x.get("status") in ("queued", "in_progress", "waiting", "pending", "requested")]
    completed = [x for x in meaningful if x.get("status") == "completed"]
    return {"latest": (meaningful or [None])[0],
            "active": active[0] if active else None,
            "completed": completed[0] if completed else None,
            "ignored_skipped_cancelled": len(runs)-len(meaningful)}


def recent_attempts(state, name, now):
    source = state.setdefault("sources", {}).setdefault(name, {})
    times = [t for t in (parse_time(v) for v in source.get("dispatched_utc", []))
             if t and 0 <= (now-t).total_seconds() <= 24*3600]
    source["dispatched_utc"] = [t.isoformat() for t in times]
    return times


def recovery_decision(name, report, workflow_state, state, now, dispatch_budget,
                      dry_run=False, dispatch_fn=None):
    cfg = FEEDS[name]
    if not report["needs_recovery"]:
        return {"action": "none", "reason": "verified_current_observation"}
    if not cfg.get("repair", True):
        return {"action": "observe_only", "reason": "external_L2_backfill_already_active"}
    if workflow_state is None:
        return {"action": "blocked", "reason": "github_actions_api_unavailable"}
    active = workflow_state.get("active")
    if active:
        start = parse_time(active.get("created_at"))
        stalled = bool(start and (now-start).total_seconds() > 3600)
        return {"action": "waiting_existing_run" if not stalled else "long_running_run",
                "run_id": active.get("id"),
                "reason": "avoid_duplicate_dispatch"}
    attempts = recent_attempts(state, name, now)
    if len(attempts) >= MAX_RETRIES_24H:
        return {"action": "exhausted", "reason": "max_three_dispatches_in_24h"}
    if attempts and (now-max(attempts)).total_seconds() < COOLDOWN_H*3600:
        return {"action": "cooldown", "reason": "wait_two_hours_before_retry"}
    if dispatch_budget <= 0:
        return {"action": "deferred", "reason": "global_two_dispatch_limit"}
    if dry_run:
        return {"action": "would_dispatch", "reason": report["reason"]}
    if dispatch_fn is None:
        dispatch_fn = api
    try:
        dispatch_fn("POST",
                    "/actions/workflows/"+urllib.parse.quote(cfg["workflow"])+"/dispatches",
                    {"ref":"main"})
    except Exception as exc:
        return {"action": "dispatch_failed", "reason": str(exc)[:350]}
    state["sources"][name]["dispatched_utc"].append(now.isoformat())
    return {"action": "dispatched", "workflow": cfg["workflow"],
            "at_utc": now.isoformat(), "reason": report["reason"]}


def run(dry_run=False, now=None):
    now = now or dt.datetime.now(UTC)
    ROOT.mkdir(parents=True, exist_ok=True)
    previous = loaded(ROOT/"watchdog_state.json") or {"sources": {}}
    states = {}
    workflows = {}
    for name, cfg in FEEDS.items():
        states[name] = assess(name, loaded(cfg["path"]), now)
    for name, cfg in FEEDS.items():
        try:
            workflows[name] = latest_workflow_run(cfg["workflow"])
            v = workflows[name]
            r = states[name]
            r["workflow_latest"] = {
                "status": get(v, "latest", "status"),
                "conclusion": get(v, "completed", "conclusion"),
                "run_id": get(v, "latest", "id"),
                "created_at": get(v, "latest", "created_at"),
                "skipped_or_cancelled_ignored": v["ignored_skipped_cancelled"]}
            completed = v.get("completed")
            if completed and completed.get("conclusion") == "failure":
                r["workflow_warning"] = "latest_meaningful_completed_run_failed"
        except Exception as exc:
            workflows[name] = None
            states[name]["workflow_api_error"] = str(exc)[:250]
    candidates = sorted(FEEDS, key=lambda x: FEEDS[x]["priority"])
    budget = MAX_DISPATCHES
    for name in candidates:
        decision = recovery_decision(
            name, states[name], workflows[name], previous, now, budget,
            dry_run=dry_run)
        states[name]["recovery"] = decision
        if decision["action"] == "dispatched":
            budget -= 1
    state_sources = previous.setdefault("sources", {})
    for name, value in states.items():
        source = state_sources.setdefault(name, {})
        if value["status"] == "healthy":
            source["last_healthy_utc"] = now.isoformat()
        else:
            source.setdefault("first_unhealthy_utc", now.isoformat())
            # Clearing prior incidents on a real recovery prevents false
            # "new outage" alarms on the next collector update.
        if value["status"] == "healthy":
            source.pop("first_unhealthy_utc", None)
    unavailable = [k for k,v in states.items() if v["needs_recovery"]]
    api_errors = [k for k,v in states.items() if v.get("workflow_api_error")]
    report = {
        "schema": 1, "checked_utc": now.isoformat(), "dry_run": dry_run,
        "status": ("monitoring_blind" if len(api_errors)==len(FEEDS) else
                   "degraded" if unavailable or api_errors else "healthy"),
        "sources_checked": len(FEEDS),
        "workflow_api_checked": True,
        "workflow_api_reachable": len(api_errors)==0,
        "workflow_api_errors": api_errors,
        "unavailable_or_stale": unavailable,
        "separate_l2_backfill_managed": ["hft_depth", "bybit_depth"],
        "auto_recovery": {
            "dispatched": [k for k,v in states.items() if get(v,"recovery","action")=="dispatched"],
            "pending_or_blocked": [k for k,v in states.items()
               if v["needs_recovery"] and get(v,"recovery","action")!="dispatched"],
            "max_dispatch_per_check": MAX_DISPATCHES,
            "max_dispatch_per_source_24h": MAX_RETRIES_24H},
        "sources": states,
        "note": ("Fresh JSON != fresh observation. Unavailable/null != zero. "
                 "Coinbase CVD 24h coverage gaps do not trigger endless collector retries. "
                 "An externally disabled GitHub Actions service needs a truly independent watcher.")}
    if not dry_run:
        (ROOT/"watchdog_state.json").write_text(json.dumps(previous,indent=2,ensure_ascii=False)+"\n")
        (ROOT/"health_latest.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"checked_utc":report["checked_utc"],"status":report["status"],
        "unavailable":unavailable,"dispatched":report["auto_recovery"]["dispatched"],
        "actions_api_issues":api_errors},
        ensure_ascii=False))
    return report


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
