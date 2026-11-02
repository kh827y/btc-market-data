"""Audit of free BTC realized-price alternatives and same-day vendor agreement.

The original BGeometrics 155-day holder cutoffs and independent Bitview UTXO
150-day cohorts are separately labeled: a proxy is never the exact same series.
Do not extrapolate dates or fill missing metrics with zero.
"""
import datetime as dt
import json
import math
from pathlib import Path

UTC=dt.timezone.utc
DATA=Path("btc-onchain/data")
SERIES={
 "network_realized_price":{
  "primary":"realized_price","alternate":"realized_price_bitview",
  "method":"network_wide_utxo_realized_price",
  "same_cohort_definition":True},
 "sth_cost_basis_150d":{
  "primary":"sth_realized_price","alternate":"sth_realized_price_150d",
  "method":"bitview_utxo_age_under_150_days",
  "same_cohort_definition":False},
 "lth_cost_basis_150d":{
  "primary":"lth_realized_price","alternate":"lth_realized_price_150d",
  "method":"bitview_utxo_age_at_least_150_days",
  "same_cohort_definition":False}
}
def data(path):
 return json.loads(Path(path).read_text(encoding="utf8"))

def quality(main,independent,now):
 """Use only actually dated observations; include last 30 same-day comparisons."""
 today=now.date()
 result={}
 for name,model in SERIES.items():
  a=main.get(model["primary"],{})
  b=independent.get(model["alternate"],{})
  verified=[]
  for day in sorted(set(a)&set(b),reverse=True)[:30]:
   if day>today.isoformat():continue
   try:
    x=float(a[day]);y=float(b[day])
    if not all(math.isfinite(z) and z>0 for z in (x,y)):continue
    delta=100*abs(x-y)/x
    verified.append((day,round(delta,4)))
   except (TypeError,ValueError,ZeroDivisionError):continue
  date=max((d for d,v in b.items() if d<=today.isoformat() and
            isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) and v>0),
           default=None)
  lag=(today-dt.date.fromisoformat(date)).days if date else None
  latest=float(b[date]) if date else None
  result[name]={
    "alternate":{"source":"Bitview","source_url":"https://bitview.space/api/",
                  "date":date,"lag_days":lag,
                  "value":latest if lag is not None and 0<=lag<=3 else None,
                  "status":"usable" if lag is not None and 0<=lag<=3 else "missing_or_delayed",
                  "methodology":model["method"]},
    "primary":{"source":"BGeometrics","latest_date":max(a,default=None),
               "methodology":"source_original_no_proxy_substitution"},
    "cross_source_same_day":{"n":len(verified),
               "latest_compared_day":verified[0][0] if verified else None,
               "latest_absolute_difference_pct":verified[0][1] if verified else None,
               "max_absolute_difference_pct_last_30_observations":max((v for _,v in verified),default=None),
               "interpretation":"different data pipelines and cohort definitions; diagnostic only, not identical metrics"},
    "identical_cohort_definition":model["same_cohort_definition"]
  }
 return result

def main():
 now=dt.datetime.now(UTC)
 main_records=data(DATA/"history.json")
 independent=data(DATA/"bitview_history.json")
 result=quality(main_records,independent,now)
 summary={"generated_utc":now.isoformat(),"sources":["BGeometrics historical free measurements",
           "Bitview public UTXO series"],"snapshots":result,
          "all_independent_three_fresh":all(v["alternate"]["status"]=="usable" for v in result.values()),
          "scope":"cross-provider audit, not a new onchain network source; avoid conflating 150d UTXO and 155d/entity cutoffs"}
 path=DATA/"realized_audit.json"
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")
 print(json.dumps({k:{"date":v["alternate"]["date"],"status":v["alternate"]["status"],
                      "last_matched_day":v["cross_source_same_day"]["latest_compared_day"]}
                   for k,v in result.items()},ensure_ascii=False))
if __name__=="__main__":main()
