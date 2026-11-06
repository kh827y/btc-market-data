"""Bounded, independently validated Binance SPOT executed-taker fallback.

Binance's CLOSED 1h spot klines publish quote turnover and taker-buy quote
turnover. Their difference is executed taker-sell quote turnover (not orders).
These hours use EXCHANGE TRADE time, whereas CryptoHFTData uses receive time.
That distinction must remain visible to the monitor.
"""
import datetime as dt
import math

URL = "https://data-api.binance.vision/api/v3/klines"
UTC = dt.timezone.utc

def validated_hour(hour, rows):
    """Reject unclosed, partial, duplicate or wrong-symbol/time bars."""
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Binance did not return exactly one closed 1h kline")
    row = rows[0]
    if not isinstance(row, (list, tuple)) or len(row) < 11:
        raise ValueError("Binance OHLCV schema missing fields")
    start_ms = int(hour.timestamp() * 1000)
    if int(row[0]) != start_ms or int(row[6]) != start_ms + 3600000 - 1:
        raise ValueError("Binance kline does not cover the requested UTC hour")
    total = float(row[7])
    taker_buy = float(row[10])
    n_trades = int(row[8])
    if not (math.isfinite(total) and math.isfinite(taker_buy) and
            total > 0 and -0.00001 <= taker_buy <= total + 0.00001 and n_trades > 0):
        raise ValueError("Binance zero/invalid or inconsistent executed turnover")
    sell = max(0.0, total-taker_buy)
    return {
        "buy": round(taker_buy, 2), "sell": round(sell, 2),
        "net": round(taker_buy-sell, 2), "trades": n_trades,
        "complete": True, "source": "Binance official SPOT closed 1h kline",
        "symbol": "BTCUSDT", "quote": "USDT",
        "hour": hour.strftime("%Y-%m-%dT%H:00:00Z"),
        "integrity": "closed_1h_quote_and_taker_buy_quote_verified",
        "hour_basis": "exchange_trade_time",
    }

def repair(state, now, errors, request, max_hours=24):
    """Fill only missing closed hours, recent-first, with bounded API calls.

    This never overwrites verified historical trade aggregates. Transient
    failure is cooled down for 30 minutes; no missing value becomes zero.
    """
    end = now.replace(minute=0, second=0, microsecond=0)-dt.timedelta(hours=2)
    known = state.setdefault("hourly", {}).setdefault("binance", {})
    retry = state.setdefault("binance_kline_retry_after", {})
    recovered = 0
    attempted = 0
    for i in range(720):
        if attempted >= max_hours:
            break
        hour = end-dt.timedelta(hours=i)
        key = hour.strftime("%Y-%m-%dT%H:00:00Z")
        if known.get(key, {}).get("complete") is True:
            continue
        if retry.get(key, 0) > now.timestamp():
            continue
        attempted += 1
        try:
            response = request(URL, params={
                "symbol": "BTCUSDT", "interval": "1h",
                "startTime": int(hour.timestamp()*1000),
                "endTime": int(hour.timestamp()*1000)+3599999,
                "limit": 1,
            })
            row = validated_hour(hour, response.json())
            known[key] = row
            retry.pop(key, None)
            state.setdefault("archive_retry_after", {}).setdefault("binance", {}).pop(key, None)
            recovered += 1
        except Exception as exc:
            retry[key] = now.timestamp()+1800
            errors.append(f"binance official closed kline {key}: {str(exc)[:110]}")
    for k in list(retry):
        try:
            if dt.datetime.fromisoformat(k.replace("Z", "+00:00")) < now-dt.timedelta(days=31):
                del retry[k]
        except (TypeError, ValueError):
            del retry[k]
    return {"attempted": attempted, "recovered": recovered,
            "method": "official_spot_closed_1h_taker_quote",
            "time_basis": "exchange_trade_time_not_CryptoHFTData_receive_time"}
