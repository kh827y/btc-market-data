"""Daily Bitview history. LTH threshold: 150 days (not Glassnode 155)."""
import datetime as dt
import json
import pathlib
import urllib.request

SERIES = {
    "lth_supply_150d": "lth_supply",
    "sth_supply_150d": "sth_supply",
    "lth_change_30d_150d": "lth_supply_delta_1m",
    "lth_change_7d_150d": "lth_supply_delta_1w",
    "lth_realized_price_150d": "lth_realized_price",
    "sth_realized_price_150d": "sth_realized_price",
    "realized_price_bitview": "realized_price",
    "lth_nupl_150d": "lth_nupl",
    "sth_nupl_150d": "sth_nupl",
}

def fetch_series(slug, start, end):
    url = "https://bitview.space/api/series/" + slug + "/day1/data"
    url += "?start=" + start.isoformat() + "&end=" + end.isoformat()
    request = urllib.request.Request(url, headers={
        "User-Agent": "BTC-Onchain-Public-Research/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=35) as response:
        values = json.load(response)
    expected = (end - start).days
    if not isinstance(values, list) or len(values) != expected:
        raise ValueError("expected " + str(expected) + " daily values")
    rows = {}
    for index, val in enumerate(values):
        if val is None:
            continue
        val = float(val)
        if not float("-inf") < val < float("inf"):
            raise ValueError("nonfinite numerical observation")
        day = (start + dt.timedelta(days=index)).isoformat()
        rows[day] = val
    if len(rows) < 360:
        raise ValueError("insufficient dates")
    return rows

def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    start = dt.date(2022, 11, 1)
    history = {}
    latest = {}
    errors = []
    for name, slug in SERIES.items():
        try:
            observations = fetch_series(slug, start, today)
            history[name] = observations
            day = max(observations)
            latest[name] = {
                "date": day,
                "value": observations[day],
                "rows": len(observations),
                "lag_days": (today - dt.date.fromisoformat(day)).days,
            }
        except Exception as exc:
            errors.append({"metric": name, "reason": str(exc)[:170]})
            latest[name] = {"date": None, "value": None, "rows": 0}
