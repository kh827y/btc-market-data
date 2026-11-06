import datetime as dt
import importlib.util
from pathlib import Path
import unittest

s=importlib.util.spec_from_file_location("macro",Path(__file__).resolve().parents[1]/"collector.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
NOW=dt.datetime(2026,11,2,10,tzinfo=m.UTC)

def latest(day="2026-10-30"):
 return {"name":"US Spot Bitcoin ETF Flows, latest session",
   "license":"https://creativecommons.org/licenses/by/4.0/",
   "methodologyUrl":"https://www.tftc.io/bitcoin-etf-flows/methodology",
   "latestSession":{"date":day,"netFlowUsd":-643330345.885,
     "perEtfUsd":{"IBIT":-233701200,"FBTC":-201039905.825,
       "ARKB":-129546134.34,"GBTC":-53324820,"BITB":-25718285.72,
       "BTC":0,"BRRR":0,"HODL":0,"BTCW":0,"BTCO":0,"EZBC":0,"MSBT":0}},
   "recentSessions":[{"date":"2026-10-30","netFlowUsd":-643330345.885},
     {"date":"2026-10-29","netFlowUsd":17071922.455},
     {"date":"2026-10-28","netFlowUsd":137330298.95},
     {"date":"2026-10-27","netFlowUsd":175993377},
     {"date":"2026-10-26","netFlowUsd":110344120}]}

class CollectorTests(unittest.TestCase):
 def test_official_fred_csv_parsing_excludes_missing_holidays(self):
  lines="observation_date,DGS10\n"+ "".join(
       f"2026-10-{d:02d},{4.01+d/100}\n" for d in range(1,28))
  rows=m.fred_csv(lines.encode(),"DGS10")
  self.assertEqual(len(rows),27)
  self.assertEqual(rows["2026-10-26"],4.27)
 def test_fred_missing_are_not_inferred_zero(self):
  b=("observation_date,DGS2\n"+
    "".join(f"2026-10-{d:02d},"+("." if d==20 else "4.00")+"\n" for d in range(1,27))).encode()
  rows=m.fred_csv(b,"DGS2")
  self.assertNotIn("2026-10-20",rows)
  self.assertEqual(len(rows),25)
 def test_etf_latest_and_five_sessions_reconcile(self):
  j=m.validate_etf_latest(latest(),NOW)
  self.assertEqual(j["date"],"2026-10-30")
  self.assertEqual(j["status"],"usable")
  self.assertTrue(j["per_fund_verified"])
  self.assertEqual(j["five_sessions_positive"],4)
  self.assertEqual(j["five_sessions_negative"],1)
  self.assertLess(j["five_sessions_net_flow_usd"],0)
 def test_etf_fund_missing_cannot_be_assumed_zero(self):
  j=latest()
  j["latestSession"]["perEtfUsd"]["IBIT"]=None
  o=m.validate_etf_latest(j,NOW)
  self.assertFalse(o["per_fund_verified"])
  self.assertIsNone(o["per_fund_flow_usd"])
 def test_etf_total_fund_mismatch_rejected(self):
  j=latest()
  j["latestSession"]["perEtfUsd"]["IBIT"]=150_000_000
  with self.assertRaisesRegex(ValueError,"per-fund sum"):
   m.validate_etf_latest(j,NOW)
 def test_no_etf_flow_on_weekends_is_not_a_new_zero(self):
  o=m.validate_etf_latest(latest(),NOW)
  self.assertEqual(o["date"],"2026-10-30")
  self.assertLess(o["latest_net_flow_usd"],0)
  future=latest("2026-11-03")
  with self.assertRaisesRegex(ValueError,"future"):
   m.validate_etf_latest(future,NOW)
 def test_too_old_etf_quarantined(self):
  o=m.validate_etf_latest(latest(),NOW+dt.timedelta(days=11))
  self.assertEqual(o["status"],"delayed")
  self.assertIsNone(o["latest_net_flow_usd"])
 def test_etf_21_sessions_from_verified_history_only(self):
  rows=[{"date":(dt.date(2026,10,1)+dt.timedelta(days=i)).isoformat(),
         "netFlowUsd":1000} for i in range(31)]
  o=m.etf_history({"sessions":rows},NOW)
  self.assertEqual(o["last_21_reported_sessions_net_usd"],21000)
 def test_no_fred_broad_dxy_misidentification(self):
  # index has separate instrument field and must NEVER supply DXY
  j={"metrics":{"usd_broad_trade_weighted":{
      "series_id":"DTWEXBGS","value":120.0}}}
  self.assertNotIn("ice_dxy",j["metrics"])
 def test_fred_stale_is_not_usable(self):
  rows={f"2026-08-{day:02d}":3.0 for day in range(1,24)}
  j=m.summarized_fred(rows,"DGS10",NOW)
  self.assertEqual(j["status"],"delayed")
  self.assertIsNone(j["value"])

 def test_dxy_preserves_previous_closed_session_when_today_quote_is_unfinished(self):
  import json
  from unittest.mock import patch
  today=dt.datetime(2026,11,6,6,0,tzinfo=m.UTC)
  d0=dt.datetime(2026,11,5,15,0,tzinfo=m.UTC)
  d1=dt.datetime(2026,11,6,5,0,tzinfo=m.UTC)
  payload={"chart":{"result":[{"timestamp":[int(d0.timestamp()),int(d1.timestamp())],
      "indicators":{"quote":[{"close":[101.5,101.8]}]}}]}}
  with patch.object(m,"fetch",return_value=json.dumps(payload).encode()):
   got=m.dxy_optional(today)
  self.assertEqual(got["observation_kind"],"unfinished_current_session")
  self.assertEqual(got["date"],"2026-11-06")
  self.assertEqual(got["completed_prior_session"]["date"],"2026-11-05")
  self.assertEqual(got["completed_prior_session"]["value"],101.5)

if __name__=="__main__":unittest.main()
