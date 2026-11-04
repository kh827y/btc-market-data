"""UTC rollover policy regression tests, no live network traffic."""
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utc_candles import (
    PUBLICATION_GRACE_MINUTES,
    assess_price_dates,
    expected_utc_closes,
    pending_short_publication_lag,
)
import watchdog as watchdog
import refresh_critical_inputs as refresh

UTC = dt.timezone.utc


def sample(now, day, week, generated=None, quote=None):
    stamp = (now - dt.timedelta(minutes=2)).isoformat()
    return {
        "status": "ok",
        "generated_utc": generated if generated is not None else stamp,
        "last_closed_day_utc": day,
        "last_closed_week_monday_utc": week,
        "spot_quote": {
            "price_usdt": 77555,
            "observed_utc": quote if quote is not None else stamp,
        },
    }


class UtcRolloverTests(unittest.TestCase):
    def test_exact_day_and_week_expected_from_closed_utc_periods(self):
        self.assertEqual(
            expected_utc_closes(dt.datetime(2026, 11, 4, 0, 5, tzinfo=UTC)),
            ("2026-11-03", "2026-10-26"),
        )
        self.assertEqual(
            expected_utc_closes(dt.datetime(2026, 11, 9, 0, 5, tzinfo=UTC)),
            ("2026-11-08", "2026-11-02"),
        )
        self.assertEqual(
            expected_utc_closes(dt.datetime(2027, 1, 1, 0, 5, tzinfo=UTC)),
            ("2026-12-31", "2026-12-21"),
        )

    def test_minute_before_midnight_is_current_but_not_after(self):
        before = dt.datetime(2026, 11, 3, 23, 59, tzinfo=UTC)
        after = before + dt.timedelta(minutes=2)
        self.assertEqual(assess_price_dates("2026-11-02", "2026-10-26", before)["status"], "current")
        self.assertEqual(assess_price_dates("2026-11-02", "2026-10-26", after)["status"], "publication_pending")

    def test_grace_ends_at_exact_deadline(self):
        for minute in (0, 4, PUBLICATION_GRACE_MINUTES-1):
            now = dt.datetime(2026, 11, 4, 0, minute, tzinfo=UTC)
            self.assertEqual(assess_price_dates("2026-11-02", "2026-10-26", now)["status"], "publication_pending")
        now = dt.datetime(2026, 11, 4, 0, PUBLICATION_GRACE_MINUTES, tzinfo=UTC)
        self.assertEqual(assess_price_dates("2026-11-02", "2026-10-26", now)["status"], "stale")

    def test_current_candles_valid_immediately_at_midnight(self):
        now = dt.datetime(2026, 11, 4, 0, 2, tzinfo=UTC)
        self.assertEqual(assess_price_dates("2026-11-03", "2026-10-26", now)["status"], "current")

    def test_pending_weekly_close_only_on_monday(self):
        mon = dt.datetime(2026, 11, 9, 0, 4, tzinfo=UTC)
        self.assertEqual(assess_price_dates("2026-11-07", "2026-10-26", mon)["status"], "publication_pending")
        self.assertEqual(assess_price_dates("2026-11-08", "2026-10-26", mon)["status"], "publication_pending")
        tue = dt.datetime(2026, 11, 10, 0, 4, tzinfo=UTC)
        self.assertEqual(assess_price_dates("2026-11-09", "2026-10-26", tue)["status"], "stale")

    def test_future_or_old_candles_cannot_use_publication_grace(self):
        now = dt.datetime(2026, 11, 4, 0, 4, tzinfo=UTC)
        for day, week in (
            ("2026-11-04", "2026-10-26"),
            ("2026-11-01", "2026-10-26"),
            ("2026-11-02", "2026-10-19"),
            (None, "2026-10-26"),
        ):
            with self.subTest(day=day, week=week):
                self.assertEqual(assess_price_dates(day, week, now)["status"], "stale")

    def test_time_zone_offset_is_converted_to_utc(self):
        zurich = dt.timezone(dt.timedelta(hours=1))
        now = dt.datetime(2026, 11, 4, 1, 5, tzinfo=zurich)
        self.assertEqual(assess_price_dates("2026-11-02", "2026-10-26", now)["status"], "publication_pending")

    def test_only_recent_collector_and_live_quote_may_defer_retry(self):
        now = dt.datetime(2026, 11, 4, 0, 5, tzinfo=UTC)
        row = sample(now, "2026-11-02", "2026-10-26")
        self.assertTrue(pending_short_publication_lag(row, now))
        self.assertTrue(refresh.needs_refresh("price_technical", row, now))  # NOT a current bar
        row["spot_quote"]["observed_utc"] = "2026-11-03T16:00:00Z"
        self.assertFalse(pending_short_publication_lag(row, now))
        row["spot_quote"]["observed_utc"] = now.isoformat()
        row["generated_utc"] = "2026-11-03T16:00:00Z"
        self.assertFalse(pending_short_publication_lag(row, now))

    def test_watchdog_does_not_dispatch_during_normal_utc_grace(self):
        now = dt.datetime(2026, 11, 4, 0, 5, tzinfo=UTC)
        row = sample(now, "2026-11-02", "2026-10-26")
        result = watchdog.assess("price_technical", row, now)
        self.assertFalse(result["closed_candles_valid"])
        self.assertFalse(result["needs_recovery"])
        self.assertEqual(result["status"], "pending_utc_close")
        self.assertEqual(
            watchdog.recovery_decision("price_technical", result, {}, {}, now, 2)["action"],
            "none")

    def test_watchdog_recovers_if_close_is_still_missing_after_grace(self):
        now = dt.datetime(2026, 11, 4, 0, 16, tzinfo=UTC)
        row = sample(now, "2026-11-02", "2026-10-26")
        result = watchdog.assess("price_technical", row, now)
        self.assertTrue(result["needs_recovery"])
        self.assertEqual(result["status"], "stale_observation")

    def test_watchdog_accepts_real_newly_closed_daily_and_weekly(self):
        now = dt.datetime(2026, 11, 9, 0, 4, tzinfo=UTC)
        result = watchdog.assess("price_technical", sample(now, "2026-11-08", "2026-11-02"), now)
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["closed_candles_valid"])
        self.assertFalse(result["needs_recovery"])


if __name__ == "__main__":
    unittest.main()
