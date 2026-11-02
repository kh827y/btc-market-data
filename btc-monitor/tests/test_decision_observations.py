"""Seven-day acceptance simulation exercises missing hours and stale sources.

Synthetic time horizons are ONLY unit-test fixtures, never historic production
evidence. Real production ledger is created by scheduled GitHub Actions.
"""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from copy import deepcopy

spec=importlib.util.spec_from_file_location(
    "decision_observations",Path(__file__).resolve().parents[1]/"decision_observations.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
UTC=dt.timezone.utc
NOW=dt.datetime(2026,11,3,0,49,tzinfo=UTC)

def data(now=NOW):
    stamp=lambda t:t.isoformat()
    brief={"as_of_utc":stamp(now-dt.timedelta(minutes=8)),
        "sources":{n:{"status":"fresh"} for n in m.REQUIRED},
        "family_readiness":{"price_technical_verified":True}}
    health={"checked_utc":stamp(now-dt.timedelta(minutes=6)),
            "status":"healthy","workflow_api_reachable":True,
            "unavailable_or_stale":[],"degraded_input_quality_no_duplicate_recovery":[]}
    quality={"checked_utc":stamp(now-dt.timedelta(minutes=7)),
             "brief_as_of_utc":brief["as_of_utc"],
             "status":"verified","critical_issues":[],"individual_metric_checks":195}
    policy={"bridge_quality_tests_ok":True,"automation_policy_contract_tests_ok":True}
    return brief,health,quality,policy

class SevenDayValidationTests(unittest.TestCase):
    def test_current_good_data_does_not_claim_model_success_or_delivery(self):
        item=m.evaluate_data(*data(),NOW)
        self.assertEqual(item["status"],"ready")
        output=m.update_ledger({},item,NOW)
        self.assertFalse(output["rolling_7d_operational_data"]["verified"])
        self.assertEqual(output["rolling_7d_operational_data"]["consecutive_ready_hour_checkpoints"],1)
        self.assertEqual(output["user_notification_delivery"],"not_observable_from_github_actions")
        self.assertEqual(output["model_decision_accuracy"],"not_established_by_data_pipeline_tests")

    def test_stale_watchdog_invalidates_hourly_checkpoint(self):
        args=list(data());args[1]["checked_utc"]=(NOW-dt.timedelta(hours=4)).isoformat()
        item=m.evaluate_data(*args,NOW)
        self.assertEqual(item["status"],"degraded")
        self.assertIn("watchdog_old_or_future",item["reasons"])

    def test_false_quality_integrity_and_critical_inputs_fail(self):
        for mutation in ("quality_mismatch","critical","stale_parent","bad_policy","bad_health"):
            args=list(data())
            if mutation=="quality_mismatch":args[2]["brief_as_of_utc"]="2026-11-02T12:00:00Z"
            elif mutation=="critical":args[2]["critical_issues"]=["spot_cvd.original_five.24h:incomplete"]
            elif mutation=="stale_parent":args[0]["sources"]["spot_cvd"]["status"]="stale"
            elif mutation=="bad_policy":args[3]["automation_policy_contract_tests_ok"]=False
            else:args[1]["status"]="degraded"
            with self.subTest(mutation=mutation):
                self.assertEqual(m.evaluate_data(*args,NOW)["status"],"degraded")

    def test_168_hours_are_not_a_full_seven_days_until_169_real_checkpoints(self):
        state={}
        base=NOW.replace(minute=0,second=0,microsecond=0)
        for h in range(169):
            now=base+dt.timedelta(hours=h)
            state=m.update_ledger(state,{"status":"ready","reasons":[]},now)
            if h<168:
                self.assertFalse(state["rolling_7d_operational_data"]["verified"])
        self.assertTrue(state["rolling_7d_operational_data"]["verified"])
        self.assertEqual(state["rolling_7d_operational_data"]["consecutive_ready_hour_checkpoints"],169)

    def test_skipped_hour_does_not_get_interpolated(self):
        state={}
        base=NOW.replace(minute=0,second=0,microsecond=0)
        for h in list(range(40))+list(range(41,180)):
            state=m.update_ledger(state,{"status":"ready","reasons":[]},base+dt.timedelta(hours=h))
        self.assertEqual(state["rolling_7d_operational_data"]["consecutive_ready_hour_checkpoints"],139)
        self.assertFalse(state["rolling_7d_operational_data"]["verified"])

    def test_single_bad_checkpoint_resets_continuity(self):
        state={}
        base=NOW.replace(minute=0,second=0,microsecond=0)
        for h in range(170):
            v="degraded" if h==42 else "ready"
            state=m.update_ledger(state,{"status":v,"reasons":[]},base+dt.timedelta(hours=h))
        self.assertEqual(state["rolling_7d_operational_data"]["consecutive_ready_hour_checkpoints"],127)
        self.assertFalse(state["rolling_7d_operational_data"]["verified"])

    def test_same_hour_recheck_does_not_inflate_continuity(self):
        good={"status":"ready","reasons":[]}
        state=m.update_ledger({},good,NOW)
        newer=m.update_ledger(state,good,NOW+dt.timedelta(minutes=2))
        self.assertEqual(len(newer["hours"]),1)
        self.assertEqual(newer["rolling_7d_operational_data"]["consecutive_ready_hour_checkpoints"],1)


    def test_counterfactual_gate_uses_real_compact_brief_metric_rows(self):
        # The actual brief has NO proof.source field. Its canonical metric
        # names, unit/scope and fresh parent are required instead.
        import sys
        folder=str(Path(__file__).resolve().parents[1])
        if folder not in sys.path:sys.path.insert(0,folder)
        brief,health,quality,policy=data()
        brief["metric_quality"]={"checks":{
            "spot_cvd.original_five.24h":{
                "status":"usable","unit":"USD net executed trades",
                "scope":"named BTC spot markets",
                "observed_at":(NOW-dt.timedelta(hours=1)).isoformat()},
            "derivatives.oi_five":{
                "status":"usable","unit":"USD notional",
                "scope":"named BTC perpetual markets",
                "observed_at":(NOW-dt.timedelta(hours=2)).isoformat()}}}
        ok=m.real_brief_counterfactual_smoke(brief,NOW)
        self.assertEqual(ok["status"],"passed")
        self.assertEqual(ok["probe_type"],"counterfactual_not_actual_market_event")
        self.assertTrue(ok["does_not_send_alert"])
        brief["metric_quality"]["checks"]["derivatives.oi_five"]["status"]="stale"
        bad=m.real_brief_counterfactual_smoke(brief,NOW)
        self.assertEqual(bad["status"],"failed")
        self.assertEqual(bad["gate_action"],"silence")

if __name__=="__main__":unittest.main()
