"""Verified hourly BTC spot CVD; incomplete data are null, not zero."""
import datetime as dt
import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

UTC = dt.timezone.utc
BASE = "https://api.cryptohftdata.com/v1"
VENUES = {
    "binance": ("binance_spot", ["BTCUSDT","BTCUSD"]),
    "okx": ("okx_spot", ["BTC-USDT","BTC-USD"]),
    "bybit": ("bybit_spot", ["BTCUSDT","BTCUSD"]),
    "kraken": ("kraken_spot", ["BTC_USD","BTC/USD","XBTUSD","XBT/USD","BTCUSD"]),
    "bitget": ("bitget_spot", ["BTCUSDT","BTCUSDC","BTCUSD"]),
}
ALL = ["binance","coinbase","okx","bybit","kraken"]  # original exact five-venue coverage
ALT_FIVE = ["binance","okx","bybit","kraken","bitget"]  # fixed alternate scope, no Coinbase
OBSERVED = ALL + ["bitget"]  # six tracked sources; never call this the entire market
_LAST_HFT_REQUEST_AT = 0.0
_HFT_INTERVAL_SECONDS = 1.15  # Provider free tier: 60 requests/minute; cap ~52/min


def key(t):
    return t.strftime("%Y-%m-%dT%H:00:00Z")


def get(url, **kwargs):
    global _LAST_HFT_REQUEST_AT
    for n in range(3):
        try:
            if url.startswith(BASE):
                remaining = _HFT_INTERVAL_SECONDS-(time.monotonic()-_LAST_HFT_REQUEST_AT)
                if remaining > 0: time.sleep(remaining)
                _LAST_HFT_REQUEST_AT = time.monotonic()
            r = requests.get(url, timeout=35, **kwargs)
            if r.status_code in (429,500,502,503,504):
                # Bound retries and respect the vendor's 60/min free limit;
                # never hammer a failed endpoint indefinitely.
                time.sleep(min(15,3+n*5))
                continue
            r.raise_for_status()
            return r
        except (requests.ConnectionError,requests.Timeout):
            if n == 2: raise
            time.sleep(2+n*3)
    raise RuntimeError("request failed")


def symbol(exchange, desired):
    data = get(BASE+"/symbols", params={"exchange":exchange,"data_type":"trades"}).json()
    options = data.get("symbols",[])
    for want in desired:
        if want in options: return want
    raise ValueError("No verified spot BTC symbol: "+exchange+" "+str(options[:12]))


def calculate_parquet(blob, hour):
    tab = pd.read_parquet(io.BytesIO(blob), columns=["price","quantity","is_buyer_maker","received_time"])
    if tab.empty: raise ValueError("No trades; completeness not verified")
    if tab.isna().any().any(): raise ValueError("Null trade")
    # CryptoHFTData partitions files by RECEIVED hour; trade_time can cross
    # hour boundaries when the exchange publication arrives late.
    ts = pd.to_numeric(tab.received_time) / 1e9
    if not ((ts>=hour.timestamp()) & (ts<hour.timestamp()+3600)).all():
        raise ValueError("Received timestamps outside source file UTC hour")
    p = pd.to_numeric(tab.price); q=pd.to_numeric(tab.quantity)
    if not ((p>0)&(q>0)).all(): raise ValueError("Invalid trade prices/sizes")
    # is_buyer_maker=True means SELL taker
    if not tab.is_buyer_maker.isin([True,False]).all(): raise ValueError("Invalid taker-side")
    notional=p*q
    buy=float(notional[~tab.is_buyer_maker.astype(bool)].sum())
    sell=float(notional[tab.is_buyer_maker.astype(bool)].sum())
    return {"buy":round(buy,2),"sell":round(sell,2),"net":round(buy-sell,2),"trades":len(tab),"complete":True}


def archives(state, now, errors, batch=60):
    end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
    first=end-dt.timedelta(hours=719)
    for name,(ex,preferred) in VENUES.items():
        try:
            sym=state.setdefault("symbols",{}).get(name) or symbol(ex,preferred)
            state["symbols"][name]=sym
            known=state.setdefault("hourly",{}).setdefault(name,{})
            retry=state.setdefault("archive_retry_after",{}).setdefault(name,{})
            # Fill the freshest 24h FIRST. Earlier forward walk from ~30
            # days ago left current 24h CVD permanently incomplete despite
            # many valid historical hours being downloaded.
            candidates=[end-dt.timedelta(hours=i) for i in range(720)]
            done=0
            for hour in dict.fromkeys(candidates):
                k=key(hour)
                if k in known: continue
                if retry.get(k,0)>now.timestamp(): continue
                if done>=batch: break
                done+=1
                path=f"{ex}/{hour:%Y-%m-%d}/{hour:%H}/{sym}_trades.parquet"
                try:
                    data=get(BASE+"/download",params={"file":path}).content
                    rec=calculate_parquet(data,hour)
                    rec.update({"source":"CryptoHFTData","symbol":sym,"quote":"USDT" if "USDT" in sym else "USD","hour":k})
                    known[k]=rec
                    retry.pop(k,None)
                except Exception as e:
                    # A persistent missing hour must not consume the whole quota
                    # again on every run; retry after a bounded cooldown.
                    retry[k]=now.timestamp()+(12*3600 if "404" in str(e) else 30*60)
                    errors.append(f"{name} {k}: {str(e)[:120]}")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:120]}")


def coinbase(state,now,errors,pages=280):
    # Coinbase returns descending IDs; 'after' walks older transactions.
    # Only closed hours with a fully observed subsequent older hour are published.
    cp=state.setdefault("coinbase_cursor",{"after":None,"pending":None,"bucket":None})
    known=state.setdefault("hourly",{}).setdefault("coinbase",{})
    end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
    cutoff=end-dt.timedelta(hours=719)
    if cp.get("complete") and cp.get("cutoff") != key(cutoff):
        cp.update({"after":None,"pending":None,"bucket":None,"complete":False})
    cp["cutoff"]=key(cutoff)
    for i in range(pages):
        try:
            params={"limit":1000}
            if cp.get("after"): params["after"]=cp["after"]
            r=get("https://api.exchange.coinbase.com/products/BTC-USD/trades",params=params)
            trades=r.json()
            if not trades: break
            ids=[int(x["trade_id"]) for x in trades]
            if any(a<=b for a,b in zip(ids,ids[1:])): raise ValueError("IDs not descending")
            for tr in trades:
                when=dt.datetime.fromisoformat(tr["time"].replace("Z","+00:00"))
                hk=key(when.replace(minute=0,second=0,microsecond=0))
                if cp["pending"] is not None and hk>cp["pending"]: raise ValueError("Time not descending")
                if hk!=cp["pending"]:
                    if cp["pending"] is not None:
                        if cp["bucket"]["trades"] and cp["pending"]<=key(end):
                            b=cp["bucket"];known[cp["pending"]]={"buy":round(b["buy"],2),"sell":round(b["sell"],2),"net":round(b["buy"]-b["sell"],2),"trades":b["trades"],"complete":True,"source":"Coinbase REST","symbol":"BTC-USD","quote":"USD","hour":cp["pending"]}
                    cp["pending"]=hk;cp["bucket"]={"buy":0.0,"sell":0.0,"trades":0}
                if hk<key(cutoff):
                    cp["complete"]=True;break
                value=float(tr["price"])*float(tr["size"])
                if value<=0: raise ValueError("Invalid trade")
                # Coinbase REST side is maker side
                side=tr["side"]
                if side not in ("buy","sell"): raise ValueError("Invalid maker side")
                cp["bucket"]["buy" if side=="sell" else "sell"]+=value
                cp["bucket"]["trades"]+=1
            after=r.headers.get("CB-AFTER") or str(ids[-1])
            if cp.get("after") and int(after)>=int(cp["after"]): raise ValueError("Cursor stalled")
            cp["after"]=after
            if cp.get("complete"): break
        except Exception as e:
            errors.append("coinbase: "+str(e)[:150]);break


def coinbase_recent(state,now,errors,pages=95):
    """Refresh the latest fully closed Coinbase hours independently of deep backfill.

    A single continuing historical cursor crawls backwards for 30 days and
    otherwise stops seeing NEW Coinbase hours. Re-scan a bounded head window
    every run without destroying the persistent long-history cursor.
    Only wholly traversed source hours are committed by coinbase().
    """
    saved=state.get("coinbase_cursor")
    state["coinbase_cursor"]={"after":None,"pending":None,"bucket":None}
    try:
        coinbase(state,now,errors,pages=pages)
    finally:
        if saved is None:
            state.pop("coinbase_cursor",None)
        else:
            state["coinbase_cursor"]=saved


def summarise(state,now,errors):
    end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
    out={"generated_utc":now.isoformat(),"last_complete_hour":key(end),"units":"quote-USD or USDT approximately USD; no stablecoin FX adjustment","source":"actual BTC spot trades","errors":errors[:30],"windows":{}}
    for h in (1,24,168,720):
        times=[key(end-dt.timedelta(hours=i)) for i in range(h)]
        per={}
        for name in OBSERVED:
            data=state.get("hourly",{}).get(name,{})
            rows=[data[k] for k in times if k in data and data[k].get("complete")]
            full=len(rows)==h
            per[name]={"hours":len(rows),"required":h,"complete":full,"net":round(sum(x["net"] for x in rows),2) if full else None}
        full=all(per[name]["complete"] for name in ALL)
        alt_full=all(per[name]["complete"] for name in ALT_FIVE)
        complete_names=[name for name in OBSERVED if per[name]["complete"]]
        # Strict published 5/5 window still requires all venues. Also expose
        # a separately labeled fixed-venue subset so missing Coinbase history
        # does not erase genuine Binance/OKX/Bybit/Kraken observations.
        subset_usable=len(complete_names)>=3
        subset={"available":subset_usable,
                "venue_count":len(complete_names),
                "venues":complete_names,
                "net":round(sum(per[n]["net"] for n in complete_names),2) if subset_usable else None,
                "scope":"observed complete venues among six tracked sources; not global BTC CVD"}
        alt={"complete":alt_full,"venues":ALT_FIVE,
             "net":round(sum(per[n]["net"] for n in ALT_FIVE),2) if alt_full else None,
             "scope":"fixed five spot venues EXCLUDING Coinbase; not worldwide CVD"}
        out["windows"][str(h)+"h"]={"complete":full,"net":round(sum(per[n]["net"] for n in ALL),2) if full else None,
                                      "by_venue":per,"complete_venue_subset":subset,
                                      "fixed_five_ex_coinbase":alt}
    return out


def main():
    now=dt.datetime.now(UTC)
    path=Path("btc-spot-cvd/data/state.json")
    state=json.loads(path.read_text()) if path.exists() else {}
    errors=[]
    archives(state,now,errors)
    coinbase_recent(state,now,errors)
    coinbase(state,now,errors)
    cutoff=now-dt.timedelta(days=31)
    for failures in state.get("archive_retry_after",{}).values():
        for k in list(failures):
            if dt.datetime.fromisoformat(k.replace("Z","+00:00"))<cutoff: del failures[k]
    for records in state.get("hourly",{}).values():
        for k in list(records):
            if dt.datetime.fromisoformat(k.replace("Z","+00:00"))<cutoff: del records[k]
    output=summarise(state,now,errors)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(state,separators=(",",":"))+"\n")
    Path("btc-spot-cvd/data/latest.json").write_text(json.dumps(output,indent=2)+"\n")
    print("UTC",now.isoformat(),"errors",len(errors),"complete 24h",output["windows"]["24h"]["complete"])
    for e in errors[:10]:print("MISSING",e)


if __name__=="__main__":main()
