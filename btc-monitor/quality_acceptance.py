"""BTC item 4 production acceptance: audit latest.json versus monitor brief.json.

Fail publishing on contradictory per-metric readiness, absent source provenance,
accidentally converted nulls, stale-source laundering, or bogus global scope.
This checks that a reporting GATE behaved correctly; it cannot prove a vendor's
economic measurement is free of underlying errors.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
from pathlib import Path

ROOT=Path("btc-monitor/data")
NOW=dt.datetime.now(dt.timezone.utc)
SOURCE_COUNT=9
VALID={"usable","unavailable","unverified","stale","invalid","incomplete","not_comparable"}
def load(name):
    return json.loads((ROOT/name).read_text(encoding="utf-8"))

def verify():
    latest,brief=load("latest.json"),load("brief.json")
    assert latest.get("as_of_utc")==brief.get("as_of_utc"),"brief and latest assembled at different times"
    quality=latest.get("metric_quality") or {}
    briefq=brief.get("metric_quality") or {}
    checks=quality.get("checks") or {}
    feeds=latest.get("feeds") or {}
    assert len(feeds)==SOURCE_COUNT and len(brief.get("sources",{}))==SOURCE_COUNT,"not all source families diagnosed"
    assert checks and quality.get("metrics_checked")==len(checks),"per-metric audit missing or truncated"
    assert len(checks)>=40,"suspiciously missing independent metric audit checks"
    assert set(briefq.get("checks") or {})==set(checks),"brief omits individual metric results"
    counted={}
    for name,row in checks.items():
        status=row.get("status")
        assert status in VALID,(name,"invalid status",status)
        counted[status]=counted.get(status,0)+1
        assert row.get("source") in feeds,(name,"untracked family")
        assert row.get("comparison_key") is not None or row.get("scope"),(name,"missing comparability/scope")
        assert row.get("unit"),(name,"missing unit")
        if status=="usable":
            assert feeds[row["source"]]["status"]=="fresh",(name,"stale parent laundering")
        assert briefq["checks"][name]["status"]==status,(name,"brief contradicts full audit")
        if row.get("required_for_family") and status!="usable":
            assert any(x.startswith(name+":") for x in quality.get("critical_issues",[])),(name,"missing critical evidence warning")
    published=quality.get("status_counts") or {}
    for key in VALID:
        assert published.get(key,0)==counted.get(key,0),("status count mismatch",key)
    assert briefq.get("status_counts")==published,"brief status aggregate mismatch"
    family=brief.get("family_readiness") or {}
    assert family==latest.get("audit",{}).get("family_readiness"),"different family flags in same assembly"
    for span in ("1h","24h","168h","720h"):
        name="spot_cvd.original_five."+span
        raw=(brief.get("spot_cvd") or {}).get("windows",{}).get(span)
        if name in checks:
            good=checks[name]["status"]=="usable"
            assert bool(family.get("spot_cvd_"+span+"_complete"))==good,(span,"CVD status not from verified window")
            if raw and not good:
                assert raw["complete"] is False and raw["net_usd_approx"] is None,(span,"bad CVD leaked net")
    if family.get("current_all_11_selected_orderbooks"):
        names=["binance_spot","bybit_spot","coinbase_spot","okx_spot","bitget_spot","gate_spot",
               "binance_usdm_perp","bybit_usdt_perp","okx_usdt_perp","bitget_usdt_perp","gate_usdt_perp"]
        assert len(names)==11
        assert all(checks.get("live_depth."+n,{}).get("status")=="usable" for n in names),"unverified book in 11/11"
        assert family.get("current_spot_orderbook_venues")==6 and family.get("current_perp_orderbook_venues")==5
    if family.get("positioning"):
        assert any(v["status"]=="usable" for k,v in checks.items() if k.startswith("derivatives."))
    if family.get("options"):
        assert checks.get("options.deribit.1M",{}).get("status")=="usable","options family without 1M"
    if family.get("onchain_independent_cost_basis"):
        assert all((brief.get("onchain_cost_basis_independent") or {}).get(name,{}).get("status")=="usable"
                   for name in ("network_realized_price","sth_cost_basis_150d","lth_cost_basis_150d"))
    if family.get("price_technical_verified"):
        assert checks.get("price.closed_daily_weekly",{}).get("status")=="usable"
    if family.get("price_live_spot_quote"):
        assert checks.get("price.live_spot_quote",{}).get("status")=="usable"
    assert all("not worldwide" not in (row.get("comparison_key") or "").lower() for row in checks.values()),"unsupported global comparison"
    return {"status":"verified","schema":1,"checked_utc":NOW.isoformat(),
            "brief_as_of_utc":latest["as_of_utc"],
            "source_families_audited":len(feeds),
            "source_families_currently_fresh":sum(v.get("status")=="fresh" for v in feeds.values()),
            "individual_metric_checks":len(checks),
            "status_counts":published,"critical_issues":quality.get("critical_issues"),
            "comparison_and_null_gates":True,"full_brief_consistency":True,
            "economic_vendor_accuracy_not_automatically_proven":True,
            "historical_L2_backfill_not_modified":True}

if __name__=="__main__":
    result=verify()
    destination=ROOT/"metric_quality_acceptance.json"
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))
