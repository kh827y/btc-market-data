"""Close missing recent Coinbase BTC-USD taker CVD UTC hours using exact ID seeks.

Unlike an always-resetting rolling cursor, seek directly to each missing group,
prove upper/lower hour boundaries, and scan every contiguous trade ID. This
keeps an already verified 720h snapshot current as each new hour closes.
"""
import datetime as dt
import json
import requests
from coinbase_parallel_backfill import seek,fetch,accumulate,hour_key,UTC

def missing_groups(state,end,horizon=30):
    existing=state.setdefault("hourly",{}).setdefault("coinbase",{})
    hours=[end-dt.timedelta(hours=i) for i in range(horizon)
           if not existing.get(hour_key(end-dt.timedelta(hours=i)),{}).get("complete")]
    groups=[]
    for hour in hours:
        if groups and groups[-1][-1]-hour==dt.timedelta(hours=1):
            groups[-1].append(hour)
        else:
            groups.append([hour])
    return groups

def scan_group(session, hours, page_cap):
    if not hours or page_cap<1:
        raise ValueError("No Coinbase recent hours or page budget")
    upper=hours[0]+dt.timedelta(hours=1)
    lower=hours[-1]
    cursor=seek(session,upper)
    buckets={}
    previous=None
    pages=0
    crossed=False
    for _ in range(page_cap):
        rows,ids,times,after=fetch(session,after=cursor,limit=1000)
        if previous is not None and ids[0]!=previous-1:
            raise ValueError("Coinbase gap-repair page ID discontinuity")
        previous=ids[-1]
        pages+=1
        crossed=accumulate(rows,times,lower,upper,buckets)
        cursor=int(after)
        if crossed:break
    if not crossed:
        return None,pages,{"reason":"page_cap_reached_without_lower_boundary",
                            "needed_hours":len(hours),"pages_attempted":pages}
    wanted={hour_key(h) for h in hours}
    if set(buckets)!=wanted:
        raise ValueError("Coinbase seek returned missing/extra UTC trading hours")
    completed={}
    for k,b in buckets.items():
        buy=round(b["buy"],2);sell=round(b["sell"],2)
        completed[k]={"buy":buy,"sell":sell,"net":round(buy-sell,2),
                      "trades":b["trades"],"complete":True,
                      "source":"Coinbase Exchange public REST BTC-USD validated ID-continuous scan",
                      "symbol":"BTC-USD","quote":"USD","hour":k,
                      "time_basis":"exchange_trade_time",
                      "integrity":"id_continuous_verified",
                      "newest_trade_id":b["newest_trade_id"],
                      "oldest_trade_id":b["oldest_trade_id"]}
    return completed,pages,None

def repair(state,now,errors,pages=250,horizon=30):
    if pages<0 or pages>1000:raise ValueError("Coinbase repair pages out of bounds")
    end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
    groups=missing_groups(state,end,horizon=horizon)
    row={"checked_utc":now.isoformat(),"status":"complete" if not groups else "running",
         "prior_incomplete_groups":len(groups),"prior_missing_hours":sum(map(len,groups)),
         "hours_recovered":0,"pages_scanned":0,"hours_remaining":0,
         "coverage_note":"ID-continuous official Coinbase BTC-USD trade-time hours, not the other venues receive-time hours"}
    if not groups or not pages:
        row["status"]="complete" if not groups else "page_budget_disabled"
        row["hours_remaining"]=sum(map(len,groups))
        return row
    session=requests.Session()
    session.headers.update({"User-Agent":"btc-spot-cvd-recent-gap-repair/1.0"})
    available=pages
    for group in groups:
        if available<=0:break
        try:
            verified,count,problem=scan_group(session,group,available)
            row["pages_scanned"]+=count
            available-=count
            if verified is None:
                row["status"]="partial"
                row["note"]=problem
                break
            current=state.setdefault("hourly",{}).setdefault("coinbase",{})
            # Only commit a group after its entire source time interval was
            # traversed with uninterrupted verified trade IDs.
            current.update(verified)
            row["hours_recovered"]+=len(verified)
        except Exception as ex:
            row["status"]="error"
            row["note"]=str(ex)[:250]
            errors.append("coinbase_recent_repair: "+str(ex)[:140])
            break
    row["hours_remaining"]=sum(map(len,missing_groups(state,end,horizon=horizon)))
    if row["hours_remaining"]==0:row["status"]="complete"
    elif row["status"]=="running":row["status"]="partial"
    session.close()
    return row
