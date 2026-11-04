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


def coinbase(state,now,errors,pages=280,window_hours=720):
    # Coinbase returns descending IDs; 'after' walks older transactions.
    # Only closed hours with a fully observed subsequent older hour are published.
    cp=state.setdefault("coinbase_cursor",{"after":None,"pending":None,"bucket":None})
    known=state.setdefault("hourly",{}).setdefault("coinbase",{})
    end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
    if not 1<=window_hours<=720:
        raise ValueError("Coinbase trade backfill window out of bounds")
    cutoff=end-dt.timedelta(hours=window_hours-1)
    # The short rolling window must restart after reaching its cutoff to
    # capture new recent hours; the 30-day cursor stays independent.
    if cp.get("complete") and (cp.get("cutoff") != key(cutoff) or window_hours<=30):
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
            if any(a-b!=1 for a,b in zip(ids,ids[1:])):
                raise ValueError("Coinbase trade IDs missing within REST page")
            if cp.get("after") and ids[0]!=int(cp["after"])-1:
                raise ValueError("Coinbase lost trades at REST pagination boundary")
            for tr in trades:
                when=dt.datetime.fromisoformat(tr["time"].replace("Z","+00:00"))
                hk=key(when.replace(minute=0,second=0,microsecond=0))
                if cp["pending"] is not None and hk>cp["pending"]: raise ValueError("Time not descending")
                if hk!=cp["pending"]:
                    if cp["pending"] is not None:
                        if cp["bucket"]["trades"] and cp["pending"]<=key(end):
                            b=cp["bucket"]
                            newrow={"buy":round(b["buy"],2),"sell":round(b["sell"],2),
                                    "net":round(b["buy"]-b["sell"],2),"trades":b["trades"],
                                    "complete":True,"source":"Coinbase Exchange public REST",
                                    "symbol":"BTC-USD","quote":"USD","hour":cp["pending"],
                                    "time_basis":"exchange_trade_time"}
                            oldrow=known.get(cp["pending"])
                            # Never overwrite a stronger fully ID-continuous
                            # archived hour with a less rigorously audited
                            # rolling or deep-cursor pass. Alert on a mismatch.
                            if oldrow and oldrow.get("integrity")=="id_continuous_verified":
                                difference=abs(float(oldrow["net"])-newrow["net"])
                                if difference>max(1.0,abs(float(oldrow["net"]))*1e-5):
                                    errors.append("coinbase: conflicting official trade totals for "
                                                  +cp["pending"]+" (verified history retained)")
                            else:
                                known[cp["pending"]]=newrow
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
            after=r.headers.get("CB-AFTER")
            if not after or int(after)!=ids[-1]:
                raise ValueError("Coinbase pagination header inconsistent with final trade")
            if cp.get("after") and int(after)>=int(cp["after"]):
                raise ValueError("Cursor stalled")
            cp["after"]=after
            if cp.get("complete"): break
        except Exception as e:
            errors.append("coinbase: "+str(e)[:150]);break


def coinbase_recent(state,now,errors,pages=95):
    """Keep both the newest Coinbase hour AND a persistent rolling 30h scan.

    A head refresh catches fresh trades every run; the other page budget
    resumes a saved rolling cursor until it reaches the last 30h cutoff.
    Deep 720h backfill continues under its original, untouched cursor.
    No incomplete UTC hour is silently marked zero or complete.
    """
    saved=state.get("coinbase_cursor")
    head_pages=min(18,pages)
    rolling_pages=max(0,pages-head_pages)
    try:
        if head_pages:
            state["coinbase_cursor"]={"after":None,"pending":None,"bucket":None}
            coinbase(state,now,errors,pages=head_pages,window_hours=30)
        if rolling_pages:
            state["coinbase_cursor"]=state.get("coinbase_recent_cursor") or {
                "after":None,"pending":None,"bucket":None}
            try:
                coinbase(state,now,errors,pages=rolling_pages,window_hours=30)
            finally:
                state["coinbase_recent_cursor"]=state["coinbase_cursor"]
    finally:
        if saved is None:state.pop("coinbase_cursor",None)
        else:state["coinbase_cursor"]=saved


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
        kraken_official_rest_hours=sum(
            state.get("hourly",{}).get("kraken",{}).get(t,{}).get("source")
            =="Kraken official public REST Trades" for t in times)
        alt={"complete":alt_full,"venues":ALT_FIVE,
             "net":round(sum(per[n]["net"] for n in ALT_FIVE),2) if alt_full else None,
             "scope":"fixed five spot venues EXCLUDING Coinbase; not worldwide CVD",
             "kraken_official_rest_hours":kraken_official_rest_hours,
             "kraken_hour_basis_mixed":kraken_official_rest_hours>0,
             "kraken_hour_basis_note":(
                 "Kraken REST recovered UTC hours use exchange trade time; "
                 "CryptoHFTData files use collector receive time"
                 if kraken_official_rest_hours else "CryptoHFTData received-time UTC hours")}
        out["windows"][str(h)+"h"]={"complete":full,"net":round(sum(per[n]["net"] for n in ALL),2) if full else None,
                                      "by_venue":per,"complete_venue_subset":subset,
                                      "fixed_five_ex_coinbase":alt}
    # Audit hour-by-hour integrity independently of the older count-only
    # completeness flags. A complete interval may still have legacy rows
    # without proof of original Coinbase trade-ID continuity.
    coinbase=state.get("hourly",{}).get("coinbase",{})
    audit={}
    for span in (24,168,720):
        required=[key(end-dt.timedelta(hours=i)) for i in range(span)]
        missing=[k for k in required if not coinbase.get(k,{}).get("complete")]
        unverified=[k for k in required
                    if coinbase.get(k,{}).get("complete") and
                    coinbase[k].get("integrity")!="id_continuous_verified"]
        audit[str(span)+"h"]={
            "required_hours":span,
            "complete_hours":span-len(missing),
            "coinbase_missing_utc_hours":missing[:20],
            "coinbase_missing_hours_count":len(missing),
            "id_continuous_proof_hours":span-len(missing)-len(unverified),
            "legacy_without_id_proof_count":len(unverified),
            "all_hours_id_continuous_verified":not missing and not unverified}
    out["coinbase_window_integrity"]=audit
    out["time_basis_note"]=(
        "Coinbase official REST is grouped by exchange trade timestamp; "
        "CryptoHFTData's other spot venues are grouped by received UTC hour. "
        "Do not assume exact per-hour execution-timestamp equivalence.")
    return out



def historical_coinbase_gaps(state,end,horizon=720,recent_hours=30):
    """Only gaps older than the handled recent window need deep backfill.

    A present but non-ID-verified older Coinbase record is NOT a verified
    executed-trade hour, even when an old legacy collector tagged it complete.
    """
    if horizon<recent_hours or recent_hours<1:
        raise ValueError("Invalid Coinbase deep/recent horizon")
    known=state.get("hourly",{}).get("coinbase",{})
    return [key(end-dt.timedelta(hours=i)) for i in range(recent_hours,horizon)
            if (known.get(key(end-dt.timedelta(hours=i)),{}).get("complete") is not True
                or known[key(end-dt.timedelta(hours=i))].get("integrity")
                   !="id_continuous_verified")]


def main():
    now=dt.datetime.now(UTC)
    path=Path("btc-spot-cvd/data/state.json")
    state=json.loads(path.read_text()) if path.exists() else {}
    errors=[]
    # Production defaults grow the archive; env caps allow short real
    # integration runs that still commit verified market observations.
    batch=max(0,min(120,int(os.getenv("BTC_CVD_ARCHIVE_BATCH","36"))))
    recent_pages=max(0,min(1000,int(os.getenv("BTC_CVD_COINBASE_RECENT_PAGES","250"))))
    deep_pages=max(0,min(500,int(os.getenv("BTC_CVD_COINBASE_DEEP_PAGES","120"))))
    archives(state,now,errors,batch=batch)
    # Unlike restarting the head every run, jump to exactly the missing
    # recent UTC-hour intervals and certify contiguous REST trade IDs.
    if recent_pages:
        from coinbase_recent_repair import repair
        recent_result=repair(state,now,errors,pages=recent_pages,horizon=30)
    else:
        recent_result={"status":"disabled","pages_scanned":0}
    # Historical cursor progresses until 720h are really complete. Once the
    # verified 30d archive is present, avoid endlessly refetching all history.
    end=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=2)
    # Do not spend deep Coinbase pages just because the newest rolling
    # hour is incomplete; recent ID-verified repair handles that hour.
    deep_missing=historical_coinbase_gaps(state,end)
    if deep_pages and deep_missing:
        coinbase(state,now,errors,pages=deep_pages)
    cutoff=now-dt.timedelta(days=31)
    for failures in state.get("archive_retry_after",{}).values():
        for k in list(failures):
            if dt.datetime.fromisoformat(k.replace("Z","+00:00"))<cutoff: del failures[k]
    for records in state.get("hourly",{}).values():
        for k in list(records):
            if dt.datetime.fromisoformat(k.replace("Z","+00:00"))<cutoff: del records[k]
    output=summarise(state,now,errors)
    output["coinbase_recent_repair"]=recent_result
    output["coinbase_720h_gap_free"]=output["windows"]["720h"]["by_venue"]["coinbase"]["complete"]
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(state,separators=(",",":"))+"\n")
    Path("btc-spot-cvd/data/latest.json").write_text(json.dumps(output,indent=2)+"\n")
    print("UTC",now.isoformat(),"errors",len(errors),"complete 24h",output["windows"]["24h"]["complete"])
    for e in errors[:10]:print("MISSING",e)


if __name__=="__main__":main()
