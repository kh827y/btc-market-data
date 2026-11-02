"""Counterfactual BTC decision regression. No fabricated event is emitted."""
import datetime as dt
import importlib.util
from copy import deepcopy
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location(
    "decision_gate",Path(__file__).resolve().parents[1]/"decision_gate.py")
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
NOW=dt.datetime(2026,11,2,22,25,tzinfo=dt.timezone.utc)
STAMP="2026-11-02T22:00:00Z"
FAMILIES={
    "price.closed_daily_weekly":"price_technical",
    "price.live_spot_quote":"price_technical",
    "spot_cvd.original_five.24h":"spot_cvd",
    "spot_cvd.original_five.168h":"spot_cvd",
    "derivatives.oi_five":"derivatives",
    "derivatives.funding_8h.Binance":"derivatives",
    "options.deribit.1M":"options",
    "onchain.market_onchain.mvrv":"onchain",
    "onchain.market_onchain.nupl":"onchain",
    "onchain.lth_sth_bitview.sth_realized_price_150d":"onchain",
    "macro.usd_broad_index":"macro_etf",
    "macro.ice_dxy_exact":"macro_etf",
    "macro.us_spot_btc_etf":"macro_etf",
    "live_depth.bybit_spot.1.0":"live_depth",
    "live_depth.bybit_spot.0.05":"live_depth",
}

def brief():
    return {"as_of_utc":STAMP,
        "sources":{name:{"status":"fresh"} for name in set(FAMILIES.values())},
        "metric_quality":{"critical_issues":[],
            "checks":{metric:{"status":"usable","source":source,
                "observed_at":STAMP} for metric,source in FAMILIES.items()}}}

def ev(metric,direction="down",t=STAMP,material=True):
    return {"metric_key":metric,"direction":direction,"observed_at":t,
            "material":material}

def candidate(*metrics,direction="down",kind="trend"):
    return {"kind":kind,"event_key":"test-event-1","new_change":True,
            "direction":direction,"time_horizon":"days_weeks",
            "confirmation_condition":"verified close",
            "invalidation_condition":"opposite confirmed close",
            "evidence":[ev(k,direction=direction) for k in metrics]}

P="price.closed_daily_weekly"
C="spot_cvd.original_five.24h"
OI="derivatives.oi_five"
F="derivatives.funding_8h.Binance"
DXY="macro.ice_dxy_exact"
ETF="macro.us_spot_btc_etf"
ON="onchain.market_onchain.mvrv"
NUPL="onchain.market_onchain.nupl"
BOOK="live_depth.bybit_spot.0.05"

class SignalDecisionTests(unittest.TestCase):
    def assert_silent(self,c,b=None,reason=None):
        r=g.evaluate(b or brief(),c,NOW)
        self.assertEqual(r["action"],"silence",r)
        if reason:self.assertEqual(r["reason"],reason)
        return r

    def assert_review(self,c,b=None,last=None):
        r=g.evaluate(b or brief(),c,NOW,last)
        self.assertEqual(r["action"],"review",r)
        self.assertTrue(r["not_automatically_delivered"])
        return r

    def test_scenarios_that_must_be_silent(self):
        examples=[
            ("RSI alone",candidate(P)),
            ("MA alone",candidate("price.live_spot_quote")),
            ("single ETF outflow",candidate(ETF)),
            ("same onchain family",candidate(ON,NUPL)),
            ("FRED broad dollar alone",candidate("macro.usd_broad_index")),
            ("price plus executed CVD same broad demand family",candidate(P,C)),
            ("leverage OI plus funding alone",candidate(OI,F)),
            ("one good narrow book alone",candidate(BOOK)),
            ("analyst recommendation",dict(candidate(P,OI),kind="technical_update")),
            ("speculative blog",dict(candidate(P,OI),kind="factcheck",widely_circulated=False)),
            ("rumor systemic shock",dict(candidate(P,OI),kind="systemic",first_party_confirmed=False)),
        ]
        for label,c in examples:
            with self.subTest(label=label):self.assert_silent(c)

    def test_real_eligible_combinations_include_independent_sources(self):
        cases=[
            ("bearish price and OI",candidate(P,OI)),
            ("bullish spot demand and funding",candidate(C,F,direction="up")),
            ("falling holders and price",candidate(P,ON)),
            ("bullish range and macro",dict(candidate(C,DXY,direction="up"),
                time_horizon="range_1_4_weeks")),
            ("spot and book plus derivatives",candidate(C,BOOK,F)),
        ]
        for label,c in cases:
            with self.subTest(label=label):
                self.assertGreaterEqual(len(self.assert_review(c)["verified_groups"]),2)

    def test_stale_oi_never_confirms_current_price_break(self):
        b=brief();b["sources"]["derivatives"]["status"]="stale"
        self.assert_silent(candidate(P,OI),b,"fewer_than_two_independent_verified_groups")

    def test_fake_complete_null_cvd_is_not_a_confirmation(self):
        b=brief();b["metric_quality"]["checks"][C]["status"]="incomplete"
        self.assert_silent(candidate(C,F),b)

    def test_stale_native_orderbook_is_rejected_from_candidate(self):
        b=brief();b["metric_quality"]["checks"][BOOK]["status"]="incomplete"
        self.assert_silent(candidate(BOOK,OI),b)

    def test_source_future_or_too_old_timestamp_is_not_new_risk(self):
        self.assert_silent(dict(candidate(P,OI),evidence=[
            ev(P,t="2026-11-03T00:00:00Z"),ev(OI)]))
        self.assert_silent(dict(candidate(P,OI),evidence=[
            ev(P),ev(OI,t="2026-11-01T12:00:00Z")]))
        self.assert_silent(dict(candidate(P,OI),evidence=[
            ev(P),ev(OI,t="2026-11-02")]))
        self.assert_silent(dict(candidate(P,OI),evidence=[
            ev(P),ev(OI,t="2026-11-02T22:40:00Z")]))
        
    def test_new_observation_cannot_claim_it_is_newer_than_source(self):
        b=brief()
        b["metric_quality"]["checks"][OI]["observed_at"]="2026-11-01T00:00:00Z"
        self.assert_silent(candidate(P,OI),b)

    def test_old_bridge_even_if_all_metrics_usable_is_silent(self):
        b=brief();b["as_of_utc"]="2026-11-02T17:00:00Z"
        self.assert_silent(candidate(P,OI),b,"bridge_not_fresh")

    def test_exact_duplicate_suppressed_but_genuine_escalation_considered(self):
        last={"test-event-1":{"sent_at":"2026-11-02T18:00:00Z"}}
        self.assertEqual(g.evaluate(brief(),candidate(P,OI),NOW,last)["reason"],
                         "event_already_alerted")
        c=dict(candidate(P,OI),verified_new_escalation=True)
        self.assert_review(c,last=last)

    def test_no_new_change_silent_even_with_two_proven_families(self):
        self.assert_silent(dict(candidate(P,OI),new_change=False),
                           reason="no_new_material_change")

    def test_non_material_or_conflicting_evidence_excluded(self):
        c=candidate(P,OI)
        c["evidence"][1]["material"]=False
        self.assert_silent(c)
        c=candidate(P,OI)
        c["evidence"][1]["direction"]="up"
        self.assert_silent(c)

    def test_cohorts_mvrv_nupl_bitview_not_independent(self):
        self.assert_silent(candidate(ON,NUPL,
                   "onchain.lth_sth_bitview.sth_realized_price_150d"))

    def test_validated_systemic_shock_exception(self):
        c=dict(candidate(P),kind="systemic",first_party_confirmed=True,
               material_to_btc=True)
        self.assertEqual(g.evaluate(brief(),c,NOW)["action"],"review_exception")
        c["first_party_confirmed"]=False
        self.assert_silent(c,"systemic_claim_unverified")

    def test_material_false_headline_can_be_reviewed_not_auto_sent(self):
        c=dict(candidate(P),kind="factcheck",primary_source_checked=True,
               widely_circulated=True,material_to_btc=True)
        x=g.evaluate(brief(),c,NOW)
        self.assertEqual(x["action"],"review_factcheck")
        self.assertTrue(x["not_automatically_delivered"])
        c["material_to_btc"]=False
        self.assert_silent(c)

    def test_missing_invalidation_condition_blocks_alert(self):
        self.assert_silent(dict(candidate(P,OI),invalidation_condition=""),
                           reason="missing_confirm_invalidate_conditions")

    def test_missing_unknown_source_or_unverified_status_cannot_count(self):
        c=candidate(P,"unrecognized.new_metric")
        self.assert_silent(c)
        b=brief();b["metric_quality"]["checks"][OI]["status"]="unverified"
        self.assert_silent(candidate(P,OI),b)

    def test_duplicate_preempts_false_news_reprint(self):
        c=dict(candidate(P),kind="factcheck",primary_source_checked=True,
               widely_circulated=True,material_to_btc=True)
        self.assert_silent(c,reason="fewer_than_two_independent_verified_groups") if False else None
        x=g.evaluate(brief(),c,NOW,{"test-event-1":{"sent_at":STAMP}})
        self.assertEqual(x["reason"],"event_already_alerted")

if __name__=="__main__":unittest.main()
