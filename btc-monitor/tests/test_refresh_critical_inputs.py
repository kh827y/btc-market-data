"""Offline regression tests for bounded freshness fallback (no API calls)."""
import datetime as dt
import json
import os
import tempfile
import sys
from unittest import mock
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import refresh_critical_inputs as refresh

UTC = dt.timezone.utc

class CriticalFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 4, 0, 20, tzinfo=UTC)
        self.current = (self.now - dt.timedelta(minutes=40)).isoformat()

    def price(self):
        return {
            "generated_utc": self.current,
            "status": "ok",
            "last_closed_day_utc": "2026-11-03",
            "last_closed_week_monday_utc": "2026-10-26",
            "spot_quote": {"observed_utc": self.current},
        }

    def test_price_valid_closed_candles_do_not_refresh(self):
        self.assertFalse(refresh.needs_refresh("price_technical", self.price(), self.now))

    def test_price_prior_day_after_utc_rollover_must_refresh(self):
        row = self.price()
        row["last_closed_day_utc"] = "2026-11-02"
        self.assertTrue(refresh.needs_refresh("price_technical", row, self.now))

    def test_unclosed_new_week_not_mistaken_for_last_closed_week(self):
        row = self.price()
        row["last_closed_week_monday_utc"] = "2026-11-02"
        self.assertTrue(refresh.needs_refresh("price_technical", row, self.now))

    def test_derivatives_need_oi_observation_not_just_fresh_file(self):
        row = {"generated_utc": self.current,
               "coverage": {"core_feeds_available": True},
               "results": {"open_interest": {"latest_hour": "2026-11-03T18:00:00Z"}}}
        self.assertTrue(refresh.needs_refresh("derivatives", row, self.now))
        row["results"]["open_interest"]["latest_hour"] = "2026-11-03T23:00:00Z"
        self.assertFalse(refresh.needs_refresh("derivatives", row, self.now))

    def test_options_need_actual_deribit_surface(self):
        row = {"generated_utc": self.current,
               "results": {"deribit_live_surface": {"as_of_utc": "2026-11-03T21:00:00Z"}}}
        self.assertTrue(refresh.needs_refresh("options", row, self.now))
        row["results"]["deribit_live_surface"]["as_of_utc"] = self.current
        self.assertFalse(refresh.needs_refresh("options", row, self.now))

    def test_live_depth_requires_current_book_and_not_just_new_file(self):
        row = {"generated_at": self.current, "status": "ok",
               "current": {"time": self.current},
               "errors": ["one_venue_missing"]}
        self.assertFalse(refresh.needs_refresh("live_depth", row, self.now))
        row["current"]["time"] = "2026-11-03T20:00:00Z"
        self.assertTrue(refresh.needs_refresh("live_depth", row, self.now))

    def test_backoff_prevents_repeated_failed_source_calls(self):
        last = (self.now - dt.timedelta(minutes=30)).isoformat()
        state = {"last_attempts": {"options": {"at": last, "status": "failed"}}}
        self.assertTrue(refresh.cooldown_active("options", state, self.now))
        later = self.now + dt.timedelta(hours=2)
        self.assertFalse(refresh.cooldown_active("options", state, later))

    def test_missing_and_future_timestamps_are_not_fresh(self):
        self.assertTrue(refresh.too_old(None, self.now, 2))
        self.assertTrue(refresh.too_old("2026-11-05T00:00:00Z", self.now, 2))

    def test_successful_refresh_survives_git_reset_without_new_api_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            try:
                os.chdir(tmp)
                Path("option").mkdir()
                fresh = {
                    "generated_utc": self.current,
                    "results": {"deribit_live_surface": {"as_of_utc": self.current}},
                }
                Path("option/latest.json").write_text(json.dumps(fresh), encoding="utf-8")
                changed_spec = {
                    "source": "option/latest.json",
                    "outputs": ["option/latest.json"],
                    "preempt_age_h": 2.0,
                    "retry_minutes": 75,
                    "timeout_seconds": 5,
                }
                with mock.patch.dict(refresh.SPECS, {"options": changed_spec}), mock.patch.object(
                        refresh, "CACHE", Path(tmp) / "cache"):
                    self.assertTrue(refresh.save_cached("options"))
                    # A failed Git push resets checkout to the older stale source.
                    Path("option/latest.json").write_text('{"generated_utc":"2026-10-01T00:00:00Z"}', encoding="utf-8")
                    self.assertTrue(refresh.restore_cached("options", self.now))
                    self.assertEqual(json.loads(Path("option/latest.json").read_text()), fresh)
            finally:
                os.chdir(cwd)

if __name__ == "__main__":
    unittest.main()
