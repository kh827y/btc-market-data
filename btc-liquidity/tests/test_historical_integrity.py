"""Regression checks: bulk Bybit source cutoff may lag daily snapshots."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location(
    "historical_integrity",Path(__file__).resolve().parents[1]/"historical_integrity.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

START=dt.date(2026,10,30)
BULK=dt.date(2026,11,1)
LATEST=dt.date(2026,11,2)
VENUES=("bybit_independent_linear","bybit_independent_spot")

def fixture():
    history={"records":{},"failures":{}}
    status={"worker_source_through":BULK.isoformat(),"coverage":{},
            "day_audit":{},"all_source_dates_accounted_for":True}
    latest={"target_day":LATEST.isoformat(),"coverage":{},
            "full_source_crc_verified":False,"snapshot_not_daily_average":True}
    for venue in VENUES:
        kind=m.BYBIT_KIND[venue]
        rows={}
        for i in range(4):
            day=(START+dt.timedelta(days=i)).isoformat()
            rows[day]={"time":day+"T00:00:00.500000+00:00",
                       "source_type":"independent Bybit daily native snapshot",
                       "venue":venue,"market":kind,"symbol":"BTCUSDT",
                       "bands":{"0.01":{"bid_share":0.5,
                                         "bid_coverage_complete":True,
                                         "ask_coverage_complete":True,
                                         "bid_usd":100,"ask_usd":100}}}
        history["records"][venue]=rows
        status["coverage"][venue]={"verified_days":3,"eligible_days":3}
        status["day_audit"][venue]={"eligible_days":3,"verified_days":3,
                                     "explicit_error_days":0,"unaccounted_days":[],
                                     "source_dates_accounted_for":True}
        latest["coverage"][venue]={"verified_days":4,"eligible_days":4}
    return history,status,latest

class BybitCutoffAuditTests(unittest.TestCase):
    def setUp(self):
        self.patcher=patch.dict(m.BYBIT_START,{v:START for v in VENUES},clear=True)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_daily_valid_snapshot_ahead_of_bulk_is_allowed(self):
        h,s,l=fixture()
        result=m.audit_bybit(h,s,l)
        self.assertEqual(result["bybit_independent_linear"]["verified_days"],3)
        self.assertEqual(result["bybit_independent_spot"]["verified_days"],3)

    def test_daily_coverage_cannot_invent_new_verified_day(self):
        h,s,l=fixture()
        del h["records"]["bybit_independent_linear"][LATEST.isoformat()]
        with self.assertRaisesRegex(ValueError,"Bybit coverage mismatch"):
            m.audit_bybit(h,s,l)

    def test_extra_daily_snapshot_must_have_real_source_provenance(self):
        h,s,l=fixture()
        h["records"]["bybit_independent_spot"][LATEST.isoformat()]["source_type"]="unverified"
        with self.assertRaisesRegex(ValueError,"invalid source provenance"):
            m.audit_bybit(h,s,l)

    def test_daily_latest_can_predate_bulk_cutoff_without_false_mismatch(self):
        h,s,l=fixture()
        l["target_day"]=(BULK-dt.timedelta(days=1)).isoformat()
        for venue in VENUES:
            l["coverage"][venue].update(eligible_days=2,verified_days=2)
        self.assertEqual(m.audit_bybit(h,s,l)["bybit_independent_linear"]["verified_days"],3)

    def test_daily_older_cutoff_cannot_claim_future_verified_days(self):
        h,s,l=fixture()
        l["target_day"]=(BULK-dt.timedelta(days=1)).isoformat()
        for venue in VENUES:
            l["coverage"][venue]["eligible_days"]=2
        with self.assertRaisesRegex(ValueError,"Bybit coverage mismatch"):
            m.audit_bybit(h,s,l)

    def test_bulk_explicit_error_stays_explicit_not_zero(self):
        h,s,l=fixture()
        missing=(START+dt.timedelta(days=1)).isoformat()
        del h["records"]["bybit_independent_spot"][missing]
        h["failures"]["bybit_independent_spot:"+missing]={"last_error":"source missing"}
        s["coverage"]["bybit_independent_spot"]["verified_days"]=2
        s["day_audit"]["bybit_independent_spot"].update(
            verified_days=2,explicit_error_days=1,unaccounted_days=[])
        l["coverage"]["bybit_independent_spot"]["verified_days"]=3
        self.assertEqual(m.audit_bybit(h,s,l)["bybit_independent_spot"]["explicit_error_days"],1)

    def test_unaccounted_bulk_date_is_not_silently_accepted(self):
        h,s,l=fixture()
        del h["records"]["bybit_independent_spot"][START.isoformat()]
        l["coverage"]["bybit_independent_spot"]["verified_days"]=3
        with self.assertRaisesRegex(ValueError,"source-date audit mismatch"):
            m.audit_bybit(h,s,l)

if __name__=="__main__":
    unittest.main()
