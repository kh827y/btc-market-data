"""Bounded source-side freshness fallback for the BTC monitor bridge.

The independent collectors and their schedules remain authoritative. This only
refreshes *stale* critical inputs before publishing a bridge snapshot. It does
not relax data quality gates, infer missing market depth, or touch L2 backfill.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

UTC = dt.timezone.utc
STATE = Path("btc-monitor/data/critical_refresh_state.json")
ROOT = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
SESSION = ROOT / ("btc-critical-refresh-" + os.environ.get("GITHUB_RUN_ID", "local") + ".json")
CACHE = ROOT / ("btc-critical-cache-" + os.environ.get("GITHUB_RUN_ID", "local"))
SPECS = {
    "price_technical": {
        "source": "btc-price/data/latest.json",
        "script": "btc-price/collector.py",
        "outputs": ["btc-price/data/latest.json", "btc-price/data/history.json"],
        "preempt_age_h": 1.65, "retry_minutes": 12, "timeout_seconds": 100,
    },
    "derivatives": {
        "source": "btc-derivatives/data/latest.json",
        "script": "btc-derivatives/collector.py",
        "outputs": ["btc-derivatives/data/latest.json"],
        "preempt_age_h": 2.0, "retry_minutes": 75, "timeout_seconds": 165,
    },
    "options": {
        "source": "btc-options/data/latest.json",
        "script": "btc-options/collector.py",
        "outputs": ["btc-options/data/latest.json", "btc-options/data/derived_history.json"],
        "preempt_age_h": 2.0, "retry_minutes": 75, "timeout_seconds": 165,
    },
    "live_depth": {
        "source": "btc-liquidity/data/latest.json",
        "script": "btc-liquidity/collector.py",
        "outputs": ["btc-liquidity/data/latest.json", "btc-liquidity/data/history.json"],
        "preempt_age_h": 1.65, "retry_minutes": 75, "timeout_seconds": 185,
    },
}

def parse(value):
    if not value:
        return None
    try:
        result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=UTC)
    except (ValueError, TypeError, OverflowError):
        return None

def too_old(value, now, max_hours):
    observed = parse(value)
    if observed is None:
        return True
    hours = (now - observed).total_seconds() / 3600
    return hours < -0.2 or hours > max_hours

def needs_refresh(name, data, now):
    """Conservative: require both a recent file and its actual observations."""
    if not isinstance(data, dict):
        return True
    spec = SPECS[name]
    if too_old(data.get("generated_utc") or data.get("generated_at"), now, spec["preempt_age_h"]):
        return True
    if name == "price_technical":
        expected_day = (now.date() - dt.timedelta(days=1)).isoformat()
        expected_week = (now.date() - dt.timedelta(days=now.weekday() + 7)).isoformat()
        quote = data.get("spot_quote") or {}
        return (data.get("status") != "ok"
                or data.get("last_closed_day_utc") != expected_day
                or data.get("last_closed_week_monday_utc") != expected_week
                or too_old(quote.get("observed_utc"), now, 1.65))
    if name == "derivatives":
        oi = ((data.get("results") or {}).get("open_interest") or {})
        return (data.get("coverage", {}).get("core_feeds_available") is not True
                or too_old(oi.get("latest_hour"), now, 4.75))
    if name == "options":
        surface = ((data.get("results") or {}).get("deribit_live_surface") or {})
        return too_old(surface.get("as_of_utc"), now, 2.0)
    if name == "live_depth":
        book = data.get("current") or {}
        return data.get("status") != "ok" or too_old(book.get("time"), now, 1.65)
    raise KeyError(name)

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def cooldown_active(name, state, now):
    record = (state.get("last_attempts") or {}).get(name) or {}
    instant = parse(record.get("at"))
    if instant is None:
        return False
    minutes = (now - instant).total_seconds() / 60
    return -2 <= minutes < SPECS[name]["retry_minutes"]

def save_cached(name):
    """Keep freshly fetched files outside the checkout across git push races."""
    for output in SPECS[name]["outputs"]:
        source = Path(output)
        if not source.is_file():
            return False
    for output in SPECS[name]["outputs"]:
        dest = CACHE / output
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, dest)
    return True

def restore_cached(name, now):
    """Restore only if canonical upstream is stale and our snapshot is valid."""
    spec = SPECS[name]
    cached = CACHE / spec["source"]
    if needs_refresh(name, read_json(cached), now):
        return False
    if any(not (CACHE / p).is_file() for p in spec["outputs"]):
        return False
    for output in spec["outputs"]:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CACHE / output, target)
    return True

def refresh(now=None):
    now = now or dt.datetime.now(UTC)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    state = read_json(STATE)
    state.setdefault("schema", 1)
    attempts = state.setdefault("last_attempts", {})
    session = read_json(SESSION)
    session.setdefault("last_attempts", {})
    attempted = []

    # One source per family and one execution per bridge run. Both persisted and
    # runner-local receipts block runaway retries during concurrent git pushes.
    for name, spec in SPECS.items():
        before = read_json(spec["source"])
        if not needs_refresh(name, before, now):
            continue
        receipt = (session.get("last_attempts") or {}).get(name) or {}
        if receipt.get("status") == "refreshed" and restore_cached(name, now):
            # A concurrent writer moved main forward after our successful
            # collection. Reuse the exact checked bytes, never re-call APIs.
            attempts[name] = dict(receipt)
            attempted.append(name)
            print("CRITICAL_FRESHNESS_RESTORED_FROM_SESSION", name, flush=True)
            continue
        if cooldown_active(name, state, now) or cooldown_active(name, session, now):
            # Persist the attempt receipt even when the first git push raced.
            if receipt and not attempts.get(name):
                attempts[name] = dict(receipt)
                attempted.append(name)
            print("CRITICAL_FRESHNESS_COOLDOWN", name, flush=True)
            continue
        stamp = dt.datetime.now(UTC).isoformat()
        record = {"at": stamp, "status": "attempting"}
        attempts[name] = dict(record)
        session["last_attempts"][name] = dict(record)
        SESSION.write_text(json.dumps(session, sort_keys=True) + "\n", encoding="utf-8")
        print("CRITICAL_FRESHNESS_REFRESH", name, flush=True)
        outcome = "failed"
        try:
            run = subprocess.run(
                [sys.executable, "-u", spec["script"]],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=spec["timeout_seconds"], check=False)
            output = run.stdout[-900:] if run.stdout else ""
            if run.returncode == 0:
                after = read_json(spec["source"])
                if not needs_refresh(name, after, dt.datetime.now(UTC)):
                    outcome = "refreshed" if save_cached(name) else "collector_missing_output"
                else:
                    outcome = "collector_returned_without_fresh_observation"
            else:
                outcome = "collector_exit_" + str(run.returncode)
            print("CRITICAL_FRESHNESS_RESULT", name, outcome, output, flush=True)
        except (subprocess.TimeoutExpired, OSError) as exc:
            outcome = "collector_timeout_or_error"
            print("CRITICAL_FRESHNESS_RESULT", name, outcome, str(exc)[:220], flush=True)
        if outcome != "refreshed":
            # Do not publish partially written / invalid source outputs.
            subprocess.run(["git", "restore", "--", *spec["outputs"]], check=False)
        record["status"] = outcome
        attempts[name] = dict(record)
        session["last_attempts"][name] = dict(record)
        SESSION.write_text(json.dumps(session, sort_keys=True) + "\n", encoding="utf-8")
        attempted.append(name)
    if attempted:
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CRITICAL_FRESHNESS_FINISHED", json.dumps(attempted), flush=True)

if __name__ == "__main__":
    refresh()
