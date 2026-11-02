"""Independent source-date and provenance consistency audit of BTC historical L2.

Does not claim full depth, full ZIP CRC, missing-book zeros, or 24-hour data.
Only checks that the published coverage numbers correspond to verified records
and explicitly recorded source-date exceptions. Incomplete backfills PASS
integrity checks but remain incomplete in the reported coverage.
"""
import datetime as dt
import json
import pathlib
import sys

BASE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
import hft_history as hft

UTC=dt.timezone.utc
DATA=BASE/"data"
BYBIT_START={"bybit_independent_linear":dt.date(2023,1,18),
             "bybit_independent_spot":dt.date(2025,4,29)}
BYBIT_KIND={"bybit_independent_linear":"perpetual","bybit_independent_spot":"spot"}

def load(name,root=DATA):
    return json.loads((root/name).read_text(encoding="utf8"))

def require(test,message):
    if not test:raise ValueError(message)

def audit_bybit(history,status,latest):
    through=dt.date.fromisoformat(status["worker_source_through"])
    require(latest["full_source_crc_verified"] is False,
            "Bybit partial ZIP is not a complete CRC validation")
    require(latest["snapshot_not_daily_average"] is True,"Bybit point snapshot label")
    result={}
    for venue,start in BYBIT_START.items():
        rows=history["records"][venue]
        errs=history.get("failures",{})
        reported=status["day_audit"][venue]
        expected=(through-start).days+1
        require(expected>0,"Bybit source date range invalid")
        verified=0;explicit=0;missing=[]
        for offset in range(expected):
            day=(start+dt.timedelta(days=offset)).isoformat()
            row=rows.get(day)
            err=errs.get(venue+":"+day)
            if row is not None:
                require(not err,"Bybit both valid and failed: "+venue+":"+day)
                t=dt.datetime.fromisoformat(row["time"])
                seconds=(t-dt.datetime.combine(dt.date.fromisoformat(day),dt.time(),UTC)).total_seconds()
                require(-0.010<=seconds<=180,"Bybit invalid 00 UTC snapshot "+venue+":"+day)
                require(row.get("source_type")=="independent Bybit daily native snapshot"
                        and row.get("venue")==venue and row.get("market")==BYBIT_KIND[venue]
                        and row.get("symbol")=="BTCUSDT" and isinstance(row.get("bands"),dict),
                        "Bybit invalid source provenance "+venue+":"+day)
                for band in row["bands"].values():
                    if band.get("bid_share") is not None:
                        require(band.get("bid_coverage_complete") and band.get("ask_coverage_complete")
                                and band.get("bid_usd") is not None and band.get("ask_usd") is not None,
                                "Bybit partial band reported complete "+venue+":"+day)
                verified+=1
            elif err is not None:explicit+=1
            else:missing.append(day)
        require(reported["eligible_days"]==expected
                and reported["verified_days"]==verified
                and reported["explicit_error_days"]==explicit
                and reported["unaccounted_days"]==missing
                and reported["source_dates_accounted_for"]==(not missing),
                "Bybit source-date audit mismatch "+venue)
        require(status["coverage"][venue]["verified_days"]==verified
                and status["coverage"][venue]["eligible_days"]==expected
                and latest["coverage"][venue]["verified_days"]==verified,
                "Bybit coverage mismatch "+venue)
        result[venue]={"eligible_days":expected,"verified_days":verified,
                       "explicit_error_days":explicit,"unchecked_days":len(missing),
                       "all_source_dates_accounted_for":not missing}
    require(status["all_source_dates_accounted_for"]==
            all(x["all_source_dates_accounted_for"] for x in result.values()),
            "Bybit global completion flag mismatch")
    return result

def audit_hft(history,latest):
    through=dt.date.fromisoformat(latest["target_anchor_date"])
    require(latest["archive_start"]==hft.ARCHIVE_START.isoformat(),
            "HFT archive start changed")
    verified={}
    for venue in hft.MARKETS:
        rows=history["markets"].get(venue,{})
        verified[venue]={day:row for day,row in rows.items()
                         if hft.verified_entry(row,venue,day)}
    recomputed=hft.audit_source_dates(verified,history.get("failures",{}),through,
                                      search_hours=latest.get("searched_utc_hours",hft.PRIMARY_SEARCH_HOURS))
    recent=hft.recent_coverage(verified,through)
    result={}
    for venue in hft.MARKETS:
        current=latest["source_date_audit"][venue]
        actual=recomputed[venue]
        for key in ("eligible_days","verified_days","explicit_error_days",
                    "not_fully_checked_days","all_source_dates_accounted_for"):
            require(current[key]==actual[key],"HFT calendar mismatch "+venue+"."+key)
        # Existing published schema v2 predates date-interval reporting.
        # Require the stronger exact partition ONLY for newly built schema v3;
        # otherwise a test of old published data must not fail a migration.
        if latest.get("schema_version",2)>=3:
            for key in ("verified_date_intervals","explicit_error_date_intervals",
                        "explicit_error_intervals_by_reason","unchecked_date_intervals"):
                require(current[key]==actual[key],"HFT calendar mismatch "+venue+"."+key)
            def interval_days(intervals):
                return sum(item["days"] for item in intervals)
            require(interval_days(current["verified_date_intervals"])==current["verified_days"]
                    and interval_days(current["explicit_error_date_intervals"])==current["explicit_error_days"]
                    and interval_days(current["unchecked_date_intervals"])==current["not_fully_checked_days"]
                    and sum(interval_days(group) for group in
                            current["explicit_error_intervals_by_reason"].values())==current["explicit_error_days"]
                    and sum(current[key] for key in
                            ("verified_days","explicit_error_days","not_fully_checked_days"))==current["eligible_days"],
                    "HFT calendar interval partition mismatch "+venue)
        require(latest["coverage_days"][venue]==len(verified[venue]),
                "HFT source verified count mismatch "+venue)
        if latest.get("schema_version",2)>=4:
            start=hft.MARKET_START[venue]
            eligible=(through-start).days+1
            coverage=latest["coverage"][venue]
            require(current["source_market_start"]==start.isoformat()
                    and coverage["source_market_start"]==start.isoformat()
                    and coverage["eligible_days_since_market_start"]==eligible
                    and current["eligible_days"]==eligible,
                    "HFT market-specific start/denominator mismatch "+venue)
            expected_pct=round(len(verified[venue])/eligible*100,2) if eligible>0 else 0
            require(coverage["coverage_pct_of_eligible_window"]==expected_pct,
                    "HFT eligible-window coverage percentage mismatch "+venue)
        for width in ("7d","30d","90d","365d"):
            require(latest["recent_window_coverage"][width][venue]==recent[width][venue],
                    "HFT "+width+" verified coverage mismatch "+venue)
        result[venue]={"eligible_days":actual["eligible_days"],
                       "verified_days":actual["verified_days"],
                       "explicit_error_days":actual["explicit_error_days"],
                       "unchecked_days":actual["not_fully_checked_days"],
                       "verified_7d":recent["7d"][venue]["verified_days"],
                       "verified_30d":recent["30d"][venue]["verified_days"],
                       "all_source_dates_accounted_for":actual["all_source_dates_accounted_for"]}
    require(latest["all_source_dates_accounted_for"]==
            all(x["all_source_dates_accounted_for"] for x in result.values()),
            "HFT global completion flag mismatch")
    return result

def run(root=DATA):
    b=audit_bybit(load("bybit_independent_history.json",root),
                  load("bybit_full_backfill_status.json",root),
                  load("bybit_independent_latest.json",root))
    hft_latest=load("hft_latest.json",root)
    h=audit_hft(load("hft_history.json",root),hft_latest)
    hft_hours="/".join(str(hour) for hour in hft_latest.get("searched_utc_hours",hft.PRIMARY_SEARCH_HOURS))
    return {"verified_at_utc":dt.datetime.now(UTC).isoformat(),
            "status":"verified_source_date_counts_consistent",
            "scope":f"source date snapshots only, Bybit partial ZIP, HFT sampled {hft_hours} UTC (00 fallback not noon comparable); not continuous orderbook",
            "bybit":b,"cryptohftdata":h,
            "all_source_dates_accounted_for":
                all(x["all_source_dates_accounted_for"] for x in [*b.values(),*h.values()])}

if __name__=="__main__":
    result=run()
    target=DATA/"historical_integrity_status.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
                      encoding="utf8")
    print(json.dumps({"status":result["status"],
        "bybit":{k:(v["verified_days"],v["eligible_days"]) for k,v in result["bybit"].items()},
        "hft":{k:(v["verified_days"],v["eligible_days"]) for k,v in result["cryptohftdata"].items()},
        "all_source_dates_accounted_for":result["all_source_dates_accounted_for"]}))
