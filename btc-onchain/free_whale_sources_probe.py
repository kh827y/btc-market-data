import json, urllib.request, urllib.error, gzip, collections, datetime as dt
HEAD={"User-Agent":"BTC-research/1.0","Accept":"application/json"}
def request(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=55)
try:
    with request("https://cryptokeyhole.com/api/v1/catalog?asset=BTC") as r:
        raw=r.read()
    print("KEYHOLE_CATALOG_BYTES",len(raw))
    obj=json.loads(raw)
    print("KEYHOLE_CATALOG_TYPE",type(obj).__name__,"KEYS",list(obj)[:20] if isinstance(obj,dict) else "")
    if isinstance(obj,dict):
        for k,v in obj.items():
            if isinstance(v,list):
                print("CAT_ARRAY",k,"N",len(v),"sample",str(v[:1])[:500])
                rows=[x for x in v if any(t in str(x).lower() for t in ("whale","exchangesum","transfer volume from whales","deposit"))]
                print("CAT_WHALES",k,"N",len(rows),"SAMPLE",str(rows[:20])[:4400])
except Exception as e:print("KEYHOLE_CATALOG_ERROR",str(e)[:250])
for metric in ("ckh.MayerMultiple","eth.PriceUSD"):
    try:
        with request("https://cryptokeyhole.com/api/v1/series?metric="+metric+"&interval=24h&limit=5") as r: data=json.load(r)
        print("KEYHOLE_SERIES",metric,str(data)[:900])
    except urllib.error.HTTPError as e:print("KEYHOLE_SERIES_ERROR",metric,e.code,e.read(1000))
    except Exception as e:print("KEYHOLE_SERIES_ERROR",metric,str(e)[:300])
try:
    with request("https://whale-alert.io/whale-alerts-archive.json.gzip") as r:
        with gzip.GzipFile(fileobj=r) as gz: alerts=json.load(gz)
    print("ALERTS_N",len(alerts))
    years=collections.Counter()
    targets=collections.Counter()
    examples=[]
    selected=[]
    for item in alerts:
        if item.get("blockchain")!="bitcoin" or item.get("transaction_type")!="transfer":continue
        amt=sum(float(x.get("amount",0)) for x in item.get("amounts",[]) if x.get("symbol","").upper()=="BTC")
        if amt<=0:continue
        day=dt.datetime.fromtimestamp(item["timestamp"],dt.timezone.utc).strftime("%Y-%m-%d")
        years[day[:4]]+=1
        dst=str(item.get("to") or "").strip()
        src=str(item.get("from") or "").strip()
        targets[dst]+=1
        # Use verified destination owners from alert labels, exclude exchange-to-exchange
        if dst.lower() not in ("unknown wallet","unknown","wallet","") and "exchange" not in src.lower() and src.lower()!=dst.lower():
            selected.append((day,amt,src,dst))
            if len(examples)<10: examples.append((day,amt,src,dst))
    print("BTC_YEARS",dict(sorted(years.items())))
    print("BTC_TO_LABELS",targets.most_common(20))
    print("SELECTED_NONUNKNOWN_DEST",len(selected))
    print("SELECTED_EXAMPLES",examples)
    print("SELECTED_YEAR_COUNTS",dict(sorted(collections.Counter(x[0][:4] for x in selected).items())))
except Exception as e:print("ALERTS_ERROR",type(e).__name__,str(e)[:400])
