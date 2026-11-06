"""Bounded and resumable Kraken BTC/USD public trade-taker recovery.

Only promote a UTC hour when a trade BEFORE its start and a trade at/after
its end have both been observed through an advancing server-side REST cursor.
Partial pages, missing side information, or unproven boundaries NEVER turn
an unknown hour into zero volume.
"""
import datetime as dt
import math
import time

UTC = dt.timezone.utc
URL = "https://api.kraken.com/0/public/Trades"

def hour_key(hour):
    return hour.strftime("%Y-%m-%dT%H:00:00Z")

def parse_page(payload):
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Kraken returned error/not-a-response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Kraken trades result missing")
    pairs = [k for k, v in result.items() if k != "last" and isinstance(v, list)]
    if len(pairs) != 1 or not result.get("last"):
        raise ValueError("Kraken trade pair or progress cursor unverified")
    trades = result[pairs[0]]
    out = []
    for row in trades:
        if not isinstance(row, list) or len(row) < 4:
            raise ValueError("Kraken trade row incomplete")
        price, qty, ts = float(row[0]), float(row[1]), float(row[2])
        side = row[3]
        if not (math.isfinite(price) and price > 0 and math.isfinite(qty) and qty > 0
                and math.isfinite(ts) and side in ("b", "s")):
            raise ValueError("Kraken trade amount/side invalid")
        out.append((ts, side, price * qty))
    if any(a[0] > b[0] for a, b in zip(out, out[1:])):
        raise ValueError("Kraken trade timestamps not ordered")
    return str(result["last"]), out

def repair(state, now, errors, request, max_pages=40):
    end = now.replace(minute=0, second=0, microsecond=0)-dt.timedelta(hours=2)
    known = state.setdefault("hourly", {}).setdefault("kraken", {})
    retry = state.setdefault("kraken_official_retry_after", {})
    active = state.get("kraken_official_cursor")
    if active and (active.get("hour") in known or
                   active.get("hour") < hour_key(end-dt.timedelta(hours=719))):
        active = None
    attempted = 0
    completed = 0
    # Incomplete work is resumed BEFORE switching to another UTC hour.
    while attempted < max_pages:
        if not active:
            hour = next((
                end-dt.timedelta(hours=i) for i in range(720)
                if hour_key(end-dt.timedelta(hours=i)) not in known and
                retry.get(hour_key(end-dt.timedelta(hours=i)), 0) <= now.timestamp()
            ), None)
            if hour is None:
                break
            k = hour_key(hour)
            active = {"hour": k, "since": str(int((hour.timestamp()-60)*1_000_000_000)),
                      "buy": 0.0, "sell": 0.0, "trades": 0,
                      "start_proven": False, "pages": 0}
            state["kraken_official_cursor"] = active
        hour = dt.datetime.fromisoformat(active["hour"].replace("Z", "+00:00"))
        start = hour.timestamp()
        stop = start + 3600
        try:
            page = request(URL, params={"pair": "XBTUSD",
                                        "since": active["since"],
                                        "count": 1000}).json()
            cursor, trades = parse_page(page)
            if not trades:
                raise ValueError("Kraken returned no trades before end boundary")
            if int(cursor) <= int(active["since"]):
                raise ValueError("Kraken server cursor did not advance")
            # The first page must prove access to the beginning of the hour:
            # avoid accepting a service which silently returns only newest data.
            if active["pages"] == 0 and trades[0][0] > start:
                raise ValueError("Kraken did not prove start-of-hour coverage")
            if active["pages"] == 0 and trades[0][0] < start-61:
                raise ValueError("Kraken returned an unexpected time range")
            if active["pages"] > 0 and trades[0][0] < start-60:
                raise ValueError("Kraken cursor jumped backwards")
            seen_end = False
            for ts, side, notional in trades:
                if ts < start:
                    active["start_proven"] = True
                    continue
                if ts >= stop:
                    seen_end = True
                    break
                active["buy" if side=="b" else "sell"] += notional
                active["trades"] += 1
            attempted += 1
            active["pages"] += 1
            if seen_end:
                if not active["start_proven"] or active["trades"] < 1:
                    raise ValueError("Kraken boundaries/trades not proven")
                b, s = active["buy"], active["sell"]
                known[active["hour"]] = {
                    "buy": round(b, 2), "sell": round(s, 2),
                    "net": round(b-s, 2), "trades": active["trades"],
                    "complete": True, "source": "Kraken official public REST Trades",
                    "symbol": "XBTUSD", "quote": "USD", "hour": active["hour"],
                    "hour_basis": "exchange_trade_time",
                    "integrity": "bounded_paginated_trades_start_and_end_proven",
                    "pages_scanned": active["pages"]}
                completed += 1
                retry.pop(active["hour"], None)
                state.setdefault("archive_retry_after", {}).setdefault("kraken", {}).pop(active["hour"],None)
                active = None
                state.pop("kraken_official_cursor", None)
            else:
                active["since"] = cursor
                state["kraken_official_cursor"] = active
                # Do not hammer an endpoint which has stopped serving older
                # trades, even if it keeps giving the same last partial page.
                if len(trades) < 1000:
                    raise ValueError("Kraken exhausted trades before end-of-hour proof")
                time.sleep(1.1)
        except Exception as exc:
            errors.append(f"Kraken official hour {active['hour']}: {str(exc)[:125]}")
            retry[active["hour"]] = now.timestamp() + 1800
            state.pop("kraken_official_cursor", None)
            active = None
            break  # bounded failures: next scheduled run retries after cooldown
    for k in list(retry):
        try:
            if dt.datetime.fromisoformat(k.replace("Z","+00:00")) < now-dt.timedelta(days=31):
                del retry[k]
        except (TypeError, ValueError):
            del retry[k]
    return {"pages_scanned": attempted, "hours_recovered": completed,
            "in_progress_hour": active["hour"] if active else None,
            "method": "official_spot_trade_taker_paginated_and_boundary_verified"}
