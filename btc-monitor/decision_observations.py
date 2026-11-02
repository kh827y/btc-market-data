"""Persistent 7-day BTC monitor *data pipeline* observation ledger.

Never converts market movement into trade alerts. Does NOT claim an actual LLM
decision was correct or that a notification reached the user's device. Data
freshness / quality checks are evaluated at real UTC execution time; missed
hours are never interpolated or replayed from an old JSON file.
"""
import datetime as dt
import json
from pathlib import Path

UTC=dt.timezone.utc
ROOT=Path("btc-monitor/data")
REQUIRED=("price_technical","spot_cvd","derivatives","options","macro_etf",
          "onchain","live_depth")
EXPECTED_HOURS=168

def stamp(v):
    try:
        t=dt.datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return t.astimezone(UTC) if t.tzinfo else None
    except (ValueError,TypeError,OverflowError):
        return None

def age(now,value,max_minutes):
    t=stamp(value)
    return t is not None and -3<=(now-t).total_seconds()/60<=max_minutes

def evaluate_data(brief,health,quality,policy,now):
    reasons=[]
    if not age(now,brief.get("as_of_utc"),180):
        reasons.append("source_bridge_old_or_future")
    if not age(now,health.get("checked_utc"),90):
        reasons.append("watchdog_old_or_future")
    if not age(now,quality.get("checked_utc"),180):
        reasons.append("metric_quality_old_or_future")
    if quality.get("brief_as_of_utc")!=brief.get("as_of_utc"):
        reasons.append("quality_different_source_checkpoint")
    if health.get("status")!="healthy" or health.get("workflow_api_reachable") is not True:
        reasons.append("watchdog_not_healthy_or_unreachable")
    if health.get("unavailable_or_stale") or health.get("degraded_input_quality_no_duplicate_recovery"):
        reasons.append("independently_detected_source_fault")
    if quality.get("status")!="verified" or quality.get("critical_issues"):
        reasons.append("metric_quality_unverified_or_critical")
    if int(quality.get("individual_metric_checks") or 0)<40:
        reasons.append("metric_quality_missing_checks")
    if (policy.get("bridge_quality_tests_ok") is not True or
        policy.get("automation_policy_contract_tests_ok") is not True):
        reasons.append("decision_policy_tests_not_passed")
    feeds=brief.get("sources") or {}
    for f in REQUIRED:
        if (feeds.get(f) or {}).get("status")!="fresh":
            reasons.append("required_family_not_fresh:"+f)
    if not isinstance(brief.get("family_readiness"),dict):
        reasons.append("readiness_missing")
    # Optional 1%-depth, delayed original vendor cohorts and incomplete
    # historical L2 are NOT automatic failures for a medium-term trend model.
    return {"status":"ready" if not reasons else "degraded",
            "reasons":reasons,
            "brief_as_of_utc":brief.get("as_of_utc"),
            "health_checked_utc":health.get("checked_utc"),
            "metric_quality_checked_utc":quality.get("checked_utc"),
            "selected_required_families":len(REQUIRED),
            "metric_checks":quality.get("individual_metric_checks")}

def update_ledger(prior,verdict,now):
    if now.tzinfo is None:raise ValueError("aware UTC required")
    now=now.astimezone(UTC)
    slot=now.replace(minute=0,second=0,microsecond=0).isoformat().replace("+00:00","Z")
    entries={r["hour_utc"]:r for r in (prior.get("hours") or [])
             if isinstance(r,dict) and isinstance(r.get("hour_utc"),str)}
    # One honest real-run receipt per UTC hour. A concurrent rerun may replace
    # that same actual hour; it cannot silently create synthetic past hours.
    entries[slot]={"hour_utc":slot,**verdict}
    # Bounded history; exact hour keys, never filled by interpolation.
    minimum=now-dt.timedelta(days=15)
    hours=[entries[k] for k in sorted(entries) if stamp(k) is not None
           and minimum<=stamp(k)<=now]
    consecutive=0
    for row in reversed(hours):
        if row["status"]!="ready":
            break
        t=stamp(row["hour_utc"])
        if t is None:break
        if consecutive>0:
            newer=stamp(hours[len(hours)-consecutive]["hour_utc"])
            if newer-t!=dt.timedelta(hours=1):
                break
        consecutive+=1
    # Confirm a full seven days only after 168 elapsed hours from the oldest
    # point of a minimum 169 successive hourly source-health checkpoints.
    qualified=consecutive>=EXPECTED_HOURS+1
    start=hours[-consecutive]["hour_utc"] if consecutive else None
    return {"schema":1,"generated_utc":now.isoformat(),
            "tracking_since_utc":hours[0]["hour_utc"] if hours else None,
            "hours":hours,"current":hours[-1] if hours else None,
            "rolling_7d_operational_data":{
                "verified":qualified,"required_elapsed_hours":EXPECTED_HOURS,
                "consecutive_ready_hour_checkpoints":consecutive,
                "first_consecutive_ready_utc":start,
                "latest_check_utc":slot,
                "missing_hour_looks_like_failure_not_zero":True},
            "model_decision_accuracy":"not_established_by_data_pipeline_tests",
            "user_notification_delivery":"not_observable_from_github_actions",
            "separate_l2_backfill_task_unmodified":True}

def load(name):
    try:return json.loads((ROOT/name).read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}

def main():
    now=dt.datetime.now(UTC)
    verdict=evaluate_data(load("brief.json"),load("health_latest.json"),
                          load("metric_quality_acceptance.json"),
                          load("policy_test_status.json"),now)
    prior=load("decision_7day_observations.json")
    result=update_ledger(prior,verdict,now)
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/"decision_7day_observations.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"at":now.isoformat(),"verdict":verdict,
          "operational":result["rolling_7d_operational_data"],
          "delivery":result["user_notification_delivery"]},ensure_ascii=False))

if __name__=="__main__":main()
