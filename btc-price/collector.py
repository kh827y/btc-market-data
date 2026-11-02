"""Free BTC spot price/technical indicators from VERIFIED closed UTC candles.

Binance spot BTCUSDT: OHLCV, MA20/50/200, RSI14 Wilder, weekly MA200.
Coinbase BTC-USD daily candle: independent source cross-check.
No incomplete UTC day/week may enter technical calculations.
"""
import datetime as dt
import json
import math
import pathlib
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

UTC=dt.timezone.utc
DAY_MS=86_400_000
WEEK_MS=7*DAY_MS
ROOT=pathlib.Path("btc-price/data")
BINANCE="https://data-api.binance.vision"
COINBASE="https://api.exchange.coinbase.com"

def request_json(url):
    req=urllib.request.Request(url,headers={
        "User-Agent":"btc-market-data-independent-ohlcv/1.0","Accept":"application/json"})
    error=None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=28) as response:
                body=response.read(1_500_001)
                if len(body)>1_500_000:raise ValueError("oversized API response")
                return json.loads(body)
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            error=exc
            if isinstance(exc,urllib.error.HTTPError) and exc.code not in (429,500,502,503,504):
                break
            if attempt<2:time.sleep(attempt+1)
    raise RuntimeError("public API failed: "+str(error)[:140])

def binance_klines(interval,limit):
    if interval not in ("1d","1w") or not 1<=limit<=1000:
        raise ValueError("bad interval or limit")
    query=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":interval,"limit":limit})
    raw=request_json(BINANCE+"/api/v3/klines?"+query)
    if not isinstance(raw,list) or not raw:raise ValueError("empty Binance candles")
    rows=[]
    for x in raw:
        if not isinstance(x,list) or len(x)<8:raise ValueError("invalid Binance candle schema")
        start=int(x[0])
        o,h,l,c,qty,q=(float(x[k]) for k in (1,2,3,4,5,7))
        if start<0 or not all(math.isfinite(v) and v>0 for v in (o,h,l,c,qty,q)):
            raise ValueError("invalid/nonfinite OHLCV")
        if l>min(o,c) or h<max(o,c) or l>h:raise ValueError("crossed OHLC")
        rows.append({"open_ms":start,"open":o,"high":h,"low":l,
                     "close":c,"volume_btc":qty,"quote_volume_usdt":q})
    return rows

def completed(rows,now,interval,required):
    span=DAY_MS if interval=="1d" else WEEK_MS
    closed=[x for x in rows if x["open_ms"]+span<=int(now.timestamp()*1000)]
    if len(closed)<required:raise ValueError("too few complete "+interval+" candles")
    stamps=[x["open_ms"] for x in closed]
    if any(b-a!=span for a,b in zip(stamps,stamps[1:])):
        raise ValueError("missing/duplicate "+interval+" UTC candles")
    if interval=="1d":
        last_date=now.date()-dt.timedelta(days=1)
    else:
        last_date=now.date()-dt.timedelta(days=now.weekday()+7)
    expected=int(dt.datetime.combine(last_date,dt.time(),UTC).timestamp()*1000)
    if stamps[-1]!=expected:raise ValueError("latest "+interval+" complete candle stale")
    if any(dt.datetime.fromtimestamp(t/1000,UTC).hour!=0 for t in stamps):
        raise ValueError("non-midnight UTC candle")
    if interval=="1w" and any(dt.datetime.fromtimestamp(t/1000,UTC).weekday()!=0 for t in stamps):
        raise ValueError("weekly candle not Monday UTC")
    return closed

def sma(values,n):
    if len(values)<n:raise ValueError("SMA insufficient length")
    return round(sum(values[-n:])/n,4)

def rsi_wilder(values,n=14):
    if len(values)<n+1:raise ValueError("RSI insufficient history")
    changes=[b-a for a,b in zip(values,values[1:])]
    gain=sum(max(x,0) for x in changes[:n])/n
    loss=sum(max(-x,0) for x in changes[:n])/n
    for change in changes[n:]:
        gain=(gain*(n-1)+max(0,change))/n
        loss=(loss*(n-1)+max(0,-change))/n
    if gain==0 and loss==0:return 50.0
    if loss==0:return 100.0
    if gain==0:return 0.0
    return round(100-100/(1+gain/loss),4)

def check_weekly_against_daily(daily,weekly):
    lookup={x["open_ms"]:x for x in daily}
    checked=0
    for week in weekly[-8:]:
        days=[lookup.get(week["open_ms"]+DAY_MS*i) for i in range(7)]
        if any(x is None for x in days):continue
        checked+=1
        for a,b in ((week["open"],days[0]["open"]), (week["close"],days[-1]["close"]),
                    (week["high"],max(d["high"] for d in days)),
                    (week["low"],min(d["low"] for d in days))):
            if abs(a-b)>max(1e-5,abs(b)*1e-7):
                raise ValueError("weekly and daily OHLC disagree on identical Binance market")
    if checked<4:raise ValueError("weekly/day series too short for consistency check")
    return checked

def swings(daily,span=3):
    seq=daily[-126:]
    peaks=[];troughs=[]
    for i in range(span,len(seq)-span):
        window=seq[i-span:i+span+1]
        if seq[i]["high"]>max(v["high"] for j,v in enumerate(window) if j!=span):
            peaks.append(seq[i])
        if seq[i]["low"]<min(v["low"] for j,v in enumerate(window) if j!=span):
            troughs.append(seq[i])
    def fmt(rows,key):
        return [{"day":dt.datetime.fromtimestamp(x["open_ms"]/1000,UTC).date().isoformat(),
                 "value_usdt":round(x[key],2)} for x in rows[-2:]]
    label="insufficient_confirmed_pivots"
    if len(peaks)>=2 and len(troughs)>=2:
        high1,high2=(x["high"] for x in peaks[-2:])
        low1,low2=(x["low"] for x in troughs[-2:])
        label="HH_HL" if high2>high1 and low2>low1 else "LH_LL" if high2<high1 and low2<low1 else "mixed"
    return {"classification":label,"recent_highs":fmt(peaks,"high"),
            "recent_lows":fmt(troughs,"low"),"confirmed_right_bars":span,
            "not_forecast":True}

def coinbase_close_for(day):
    begin=day-dt.timedelta(days=2)
    end=day+dt.timedelta(days=1)
    query=urllib.parse.urlencode({
        "start":dt.datetime.combine(begin,dt.time(),UTC).isoformat(),
        "end":dt.datetime.combine(end,dt.time(),UTC).isoformat(),
        "granularity":86400})
    candles=request_json(COINBASE+"/products/BTC-USD/candles?"+query)
    if not isinstance(candles,list):raise ValueError("Coinbase candles not list")
    target=int(dt.datetime.combine(day,dt.time(),UTC).timestamp())
    for x in candles:
        if isinstance(x,list) and len(x)>=6 and int(x[0])==target:
            price=float(x[4])
            if not math.isfinite(price) or price<=0:raise ValueError("invalid Coinbase USD close")
            return price
    raise ValueError("Coinbase source has no same UTC closed day")

def calculate(raw_daily,raw_weekly,now,coinbase=None,coinbase_error=None):
    daily=completed(raw_daily,now,"1d",250)
    weekly=completed(raw_weekly,now,"1w",210)
    checked=check_weekly_against_daily(daily,weekly)
    closes=[x["close"] for x in daily]
    week_closes=[x["close"] for x in weekly]
    close=closes[-1]
    ma={f"ma{n}":sma(closes,n) for n in (20,50,200)}
    ma200w=sma(week_closes,200)
    delta=round(abs(coinbase/close-1)*100,4) if coinbase is not None else None
    if delta is not None and delta>3:
        raise ValueError("Coinbase/Binance daily close differs over 3%")
    day=dt.datetime.fromtimestamp(daily[-1]["open_ms"]/1000,UTC).date().isoformat()
    week=dt.datetime.fromtimestamp(weekly[-1]["open_ms"]/1000,UTC).date().isoformat()
    high20=max(x["high"] for x in daily[-21:-1])
    low20=min(x["low"] for x in daily[-21:-1])
    breakout=("above_prev20_high" if close>high20 else
              "below_prev20_low" if close<low20 else "within_prev20_range")
    structure=swings(daily)
    trend=("bullish" if close>ma["ma200"] and ma["ma20"]>ma["ma50"]>ma["ma200"] and weekly[-1]["close"]>ma200w
           else "bearish" if close<ma["ma200"] and ma["ma20"]<ma["ma50"]<ma["ma200"] and weekly[-1]["close"]<ma200w
           else "mixed")
    return {"schema":1,"generated_utc":now.isoformat(),"status":"ok",
      "instrument":{"venue":"Binance","symbol":"BTCUSDT","market":"spot","quote":"USDT",
                    "scope":"one exchange spot, not a worldwide USD index"},
      "last_closed_day_utc":day,"last_closed_week_monday_utc":week,
      "daily":{"close_usdt":round(close,2),
               "ohlcv":{k:round(daily[-1][k],6) for k in ("open","high","low","close","volume_btc","quote_volume_usdt")},
               "ma":ma,"rsi14_wilder":rsi_wilder(closes),
               "rsi14_previous":rsi_wilder(closes[:-1]),
               "change_pct":{str(n)+"d":round((close/closes[-n-1]-1)*100,3) for n in (1,7,30)},
               "volume_vs_prev20d_median":round(daily[-1]["volume_btc"]/
                    statistics.median(x["volume_btc"] for x in daily[-21:-1]),4),
               "previous20_high":round(high20,2),"previous20_low":round(low20,2),
               "breakout20":breakout,"swings":structure},
      "weekly":{"last_close_usdt":round(weekly[-1]["close"],2),
                "ma200":ma200w,"prev_ma200":sma(week_closes[:-1],200),
                "above_ma200":weekly[-1]["close"]>ma200w,"closed_week_monday":week},
      "trend":{"classification":trend,"structure":structure["classification"],
               "breakout":breakout,"rule":"CLOSED day MA20/50/200 alignment, CLOSED week MA200, daily close"},
      "cross_checks":{"same_venue_daily_weekly_weeks":checked,
        "coinbase_daily":{"status":"verified" if delta is not None else "unavailable",
          "source":"Coinbase Exchange BTC-USD closed UTC daily candle","close_usd":coinbase,
          "absolute_difference_pct":delta,"error":coinbase_error if delta is None else None}},
      "coverage":{"daily_complete":len(daily),"weekly_complete":len(weekly),"daily_missing":0,"weekly_missing":0},
      "caveats":["All MA and RSI use completed UTC candles only","Wilder RSI 14 with historical seed",
                 "USDT is not exact USD and the venue is not a global price index",
                 "Independent cross-venue check unavailable does not mean corroborated",
                 "Technicals are context, not standalone reversal decisions"]}

def main():
    now=dt.datetime.now(UTC)
    daily=binance_klines("1d",800)
    weekly=binance_klines("1w",300)
    day=dt.datetime.fromtimestamp(completed(daily,now,"1d",250)[-1]["open_ms"]/1000,UTC).date()
    coinbase=None;cb_error=None
    try:coinbase=coinbase_close_for(day)
    except Exception as exc:cb_error=str(exc)[:180]
    out=calculate(daily,weekly,now,coinbase,cb_error)
    try:
        ticker=request_json(BINANCE+"/api/v3/ticker/price?symbol=BTCUSDT")
        price=float(ticker["price"])
        if not math.isfinite(price) or price<=0:raise ValueError("invalid ticker")
        if abs(price/out["daily"]["close_usdt"]-1)>0.3:
            raise ValueError("ticker >30% from last close")
        out["spot_quote"]={"price_usdt":round(price,2),"observed_utc":now.isoformat(),
                           "source":"Binance Spot public ticker price",
                           "vs_last_daily_close_pct":round((price/out["daily"]["close_usdt"]-1)*100,3)}
    except Exception as exc:
        out["spot_quote"]={"price_usdt":None,"observed_utc":None,"error":str(exc)[:160]}
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/"latest.json").write_text(json.dumps(out,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n")
    hist={"generated_utc":out["generated_utc"],"instrument":out["instrument"],
      "daily_closed":[{"day":dt.datetime.fromtimestamp(x["open_ms"]/1000,UTC).date().isoformat(),
          "open":x["open"],"high":x["high"],"low":x["low"],"close":x["close"],
          "volume_btc":x["volume_btc"]} for x in completed(daily,now,"1d",250)],
      "weekly_closed":[{"monday":dt.datetime.fromtimestamp(x["open_ms"]/1000,UTC).date().isoformat(),
          "open":x["open"],"high":x["high"],"low":x["low"],"close":x["close"]}
          for x in completed(weekly,now,"1w",210)]}
    (ROOT/"history.json").write_text(json.dumps(hist,separators=(",",":"),allow_nan=False)+"\n")
    print(json.dumps({"closed_day":out["last_closed_day_utc"],"rsi":out["daily"]["rsi14_wilder"],
         "ma":out["daily"]["ma"],"weekly_ma200":out["weekly"]["ma200"],
         "coinbase_crosscheck":out["cross_checks"]["coinbase_daily"]["status"]}))

if __name__=="__main__":main()
