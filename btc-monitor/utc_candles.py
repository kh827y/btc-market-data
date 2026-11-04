"""UTC close-date validity for Binance BTC daily/weekly price observations.

Fail closed for trend indicators: the most recent expected UTC day AND most
recent completed UTC week must be present. A short post-midnight publication
window only suppresses redundant repair calls; it never makes old candles
current or makes them eligible for a trend signal.
"""
from __future__ import annotations

import datetime as dt

UTC = dt.timezone.utc
PUBLICATION_GRACE_MINUTES = 15


def utc_now(now: dt.datetime) -> dt.datetime:
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ValueError("UTC-aware datetime required")
    return now.astimezone(UTC)


def expected_utc_closes(now: dt.datetime) -> tuple[str, str]:
    now = utc_now(now)
    daily = now.date() - dt.timedelta(days=1)
    weekly = now.date() - dt.timedelta(days=now.weekday() + 7)
    return daily.isoformat(), weekly.isoformat()


def assess_price_dates(day: str | None, week: str | None, now: dt.datetime) -> dict:
    """current | publication_pending | stale, with exact UTC calendar dates.

    A date from a still-open daily or weekly period is always rejected.
    The pending state applies only to one-period-old *real* completed candles
    in the first 15 minutes of UTC day turnover. A pending source is NOT fresh.
    """
    now = utc_now(now)
    expected_day, expected_week = expected_utc_closes(now)
    daily_ok = day == expected_day
    weekly_ok = week == expected_week
    status = "current" if daily_ok and weekly_ok else "stale"
    minutes_since_midnight = (
        now - dt.datetime.combine(now.date(), dt.time(), UTC)
    ).total_seconds() / 60.0
    if status != "current" and 0 <= minutes_since_midnight < PUBLICATION_GRACE_MINUTES:
        earlier_day = (now.date() - dt.timedelta(days=2)).isoformat()
        earlier_week = (
            dt.date.fromisoformat(expected_week) - dt.timedelta(days=7)
        ).isoformat()
        # A weekly rollover only happens at Monday 00:00 UTC.
        # On Tue-Sun an older week means a genuine multi-day outage.
        acceptable_week = (week == expected_week or
                           (now.weekday() == 0 and week == earlier_week))
        if (day in (expected_day, earlier_day) and acceptable_week):
            status = "publication_pending"
    return {
        "status": status,
        "expected_day_utc": expected_day,
        "expected_week_monday_utc": expected_week,
        "day_current": daily_ok,
        "week_current": weekly_ok,
        "publication_grace_minutes": PUBLICATION_GRACE_MINUTES,
    }


def pending_short_publication_lag(record: dict, now: dt.datetime) -> bool:
    """Suppress *retry*, not signal-quality failure, for a new UTC close.

    Do not suppress repairs if the collector itself stopped publishing or
    current spot quotes are absent. This is independent of weekend/US hours.
    """
    if not isinstance(record, dict) or record.get("status") != "ok":
        return False
    verdict = assess_price_dates(
        record.get("last_closed_day_utc"),
        record.get("last_closed_week_monday_utc"), now)
    if verdict["status"] != "publication_pending":
        return False
    generated = _parse_datetime(record.get("generated_utc"))
    quote = record.get("spot_quote") or {}
    observed = _parse_datetime(quote.get("observed_utc"))
    price = quote.get("price_usdt")
    now = utc_now(now)
    if generated is None or observed is None:
        return False
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return False
    generated_age = (now - generated).total_seconds() / 3600
    quote_age = (now - observed).total_seconds() / 3600
    return (-0.2 <= generated_age <= 2.5 and
            -0.2 <= quote_age <= 2.5)


def _parse_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return utc_now(t)
    except (ValueError, TypeError):
        return None
