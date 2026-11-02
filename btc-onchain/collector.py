"""Daily Bitcoin on-chain historical snapshots. Missing/delayed data are explicit."""
import datetime as dt, json, pathlib, urllib.request, urllib.error, time
ROOT=pathlib.Path("btc-onchain/data")
METRICS={
"mvrv":"mvrv","mvrv_zscore":"mvrv-zscore","nupl":"nupl",
"sth_sopr":"sth-sopr","lth_sopr":"lth-sopr",
"lth_realized_profit":"realized_profit_lth","lth_realized_loss":"realized_loss_lth",
"sth_realized_profit":"realized_profit_sth","sth_realized_loss":"realized_loss_sth",
"sth_realized_price":"sth-realized-price","lth_realized_price":"lth-realized-price",
"realized_price":"realized-price"}
CM={"exchange_in_btc":"FlowInExNtv","exchange_out_btc":"FlowOutExNtv","exchange_reserves_btc":"SplyExNtv"}
def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-Onchain-Monitor/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=35) as r:return json.load(r)
def parse_rows(data):
    if not isinstance(data,list):raise ValueError("non-array response")
    out={}
    for item in data:
        if not isinstance(item,dict):continue
        d=item.get("d")
        if not isinstance(d,str) or len(d)!=10:continue
        names=[k for k in item if k not in ("d","unixTs","delayed","message")]
        if len(names)!=1:continue
        try:v=float(item[names[0]])
        except (TypeError,ValueError):continue
        if abs(v)>1e28 or v!=v:continue
        out[d]=v
    if not out:raise ValueError("no numerical dated observations")
    return out
def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    now=dt.datetime.now(dt.timezone.utc)
    previous=ROOT/"history.json"
    data=json.loads(previous.read_text()) if previous.exists() else {}
    errors=[]
    # Free BGeometrics: max 15/day. Rotate lower-priority metrics to stay <= 10 API calls/day.
    required=["mvrv","mvrv_zscore","nupl","sth_sopr","lth_sopr","lth_realized_profit","lth_realized_loss","sth_realized_profit","sth_realized_loss"]
    optional=["sth_realized_price","lth_realized_price","realized_price"]
    rotation=optional[now.toordinal()%len(optional)]
    for name in required+[rotation]:
        slug=METRICS[name]
        try:
            rows=parse_rows(fetch("https://bitcoin-data.com/v1/"+slug+"?startday=2022-11-01"))
            data.setdefault(name,{}).update(rows)
        except Exception as exc:errors.append({"metric":name,"reason":str(exc)[:160]})
    try:
        keys=",".join(CM.values())
        records=fetch("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics="+keys+"&start_time=2022-11-01&frequency=1d&page_size=10000")
        while True:
            if not isinstance(records,dict):raise ValueError("bad Coin Metrics response")
            for x in records.get("data",[]):
                d=x.get("time","")[:10]
                for name,metric in CM.items():
                    v=x.get(metric)
                    if v is None:continue
                    try:data.setdefault(name,{})[d]=float(v)
                    except (ValueError,TypeError):pass
            if not records.get("next_page_url"):break
            records=fetch(records["next_page_url"])
    except Exception as exc:errors.append({"metric":"coinmetrics_exchange","reason":str(exc)[:160]})
    today=now.date()
    latest={}
    for name in [*METRICS,*CM]:
        series=data.get(name,{})
        if not series:
            latest[name]={"status":"missing","value":None,"date":None,"lag_days":None,"count":0}
            continue
        last=max(series)
        lag=(today-dt.date.fromisoformat(last)).days
        latest[name]={"status":"fresh" if lag<=2 else "delayed","value":series[last],"date":last,"lag_days":lag,"count":len(series)}
    out={"generated_utc":now.isoformat(),"data_source":{"bgeometrics":"free tier last four years; LTH/STH last seven days may be delayed","coinmetrics":"community API free exchange metrics; data revisions/status possible"},"latest":latest,"errors":errors}
    previous.write_text(json.dumps(data,separators=(",",":"),sort_keys=True)+"\n")
    (ROOT/"latest.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"generated_utc":out["generated_utc"],"metric_status":{k:(v["status"],v["date"],v["count"]) for k,v in latest.items()},"errors":errors},ensure_ascii=False))
if __name__=="__main__":main()
