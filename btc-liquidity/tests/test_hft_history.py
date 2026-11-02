import datetime as dt
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

spec=importlib.util.spec_from_file_location("hft_history",Path(__file__).resolve().parents[1]/"hft_history.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def fixture(missing_checkpoint=False, delayed_checkpoint=False, tick=0.01):
    hour=int(dt.datetime(2026,10,31,12,tzinfo=dt.timezone.utc).timestamp()*1e9)
    data=[]
    if delayed_checkpoint:
        data.append({"received_time":hour+int(5e9),"event_type":"update",
                     "side":"bid","price":"100","quantity":"3", "final_update_id":110})
        hour+=int(20*60*1e9)
    for side in ("bid","ask"):
        for n in range(12):
            price=(100-tick*n if side=="bid" else 100+tick+tick*n)
            data.append({"received_time":hour,"event_type":"update" if missing_checkpoint else "snapshot",
                         "side":side,"price":str(price),"quantity":"2",
                         "final_update_id":111})
    data.append({"received_time":hour+int(1e9),"event_type":"update",
                 "side":"bid","price":"100","quantity":"1","final_update_id":112})
    f=io.BytesIO()
    pq.write_table(pa.Table.from_pylist(data),f)
    return f.getvalue()

class HistoricL2Tests(unittest.TestCase):
    def test_verified_checkpoint_depth(self):
        a=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(a["snapshot_rows"],24)
        self.assertEqual(a["levels"],{"bid":12,"ask":12})
        self.assertIsNotNone(a["bands"]["0.05"]["bid_share"])
        self.assertIsNone(a["bands"]["1.0"]["bid_share"])
    def test_very_shallow_bybit_book_has_real_tight_band_not_fake_wide_depth(self):
        r=m.parse_checkpoint(fixture(tick=0.001),"bybit","BTCUSDT",
            "perpetual",1.0,"USDT",dt.date(2026,10,31))
        self.assertIsNotNone(r["bands"]["0.01"]["bid_share"])
        self.assertIsNone(r["bands"]["0.05"]["bid_share"])
    def test_binance_native_split_snapshot_in_two_received_times(self):
        start=int(dt.datetime(2026,10,31,12,tzinfo=dt.timezone.utc).timestamp()*1e9)
        rows=[]
        for side in ("bid","ask"):
            for i in range(16):
                price=100-.01*i if side=="bid" else 100.01+.01*i
                rows.append({"received_time":start+(1000000000 if side=="ask" else 0),
                   "event_time":start,"last_update_id":500,"final_update_id":500,
                   "event_type":"snapshot","side":side,"price":str(price),"quantity":"2"})
        rows.append({"received_time":start+2000000000,"event_time":start+2000000000,
                     "last_update_id":501,"final_update_id":501,
                     "event_type":"update","side":"ask","price":"101","quantity":"3"})
        stream=io.BytesIO()
        pq.write_table(pa.Table.from_pylist(rows),stream)
        measured=m.parse_checkpoint(stream.getvalue(),"binance_spot","BTCUSDT",
                                      "spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(measured["snapshot_rows"],32)
        self.assertEqual(measured["levels"],{"bid":16,"ask":16})
    def test_later_verified_checkpoint_is_accepted(self):
        r=m.parse_checkpoint(fixture(delayed_checkpoint=True),"binance_spot",
            "BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(r["snapshot_rows"],24)
        self.assertEqual(r["sample_utc_hour"],12)
        self.assertEqual(dt.datetime.fromisoformat(r["time"]).minute,20)
    def test_legacy_hour_start_record_is_not_verified_snapshot(self):
        day=dt.date(2026,10,31)
        good=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT",
                                "spot",1.0,"USDT",day)
        self.assertTrue(m.verified_entry({"status":"ok","data":good},"binance_spot",str(day)))
        legacy=dict(good)
        legacy["source"]="CryptoHFTData historical verified L2 hour-start checkpoint"
        legacy["method"]="first complete checkpoint from 12:00 UTC hourly L2 file, not trades or interpolated quotes"
        legacy.pop("sample_utc_hour",None)
        self.assertFalse(m.verified_entry({"status":"ok","data":legacy},"binance_spot",str(day)))
        through=day
        existing={v:{} for v in m.MARKETS}
        existing["binance_spot"][str(day)]={"status":"ok","data":legacy}
        picked=[x for x in m.targets(through,existing,now=dt.datetime(2026,11,2,tzinfo=dt.timezone.utc))
                if x[0]=="binance_spot" and x[1]==day]
        self.assertEqual([x[2] for x in picked],[12,11,13,0])
        valid={v:{d:row for d,row in rows.items() if m.verified_entry(row,v,d)}
               for v,rows in existing.items()}
        self.assertEqual(m.recent_coverage(valid,through)["7d"]["binance_spot"]["verified_days"],0)

    def test_native_older_snapshot_without_tight_band_is_still_verified(self):
        day=dt.date(2026,10,31)
        rec=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",day)
        rec["bands"].pop("0.01")
        row={"status":"ok","data":rec}
        self.assertTrue(m.verified_entry(row,"binance_spot",str(day)))
        # Valid wide bands stay usable; original snapshot may be retried
        # for the tighter band without losing the verified source day.
        existing={v:{} for v in m.MARKETS}
        existing["binance_spot"][str(day)]=row
        todo=[x for x in m.targets(day,existing,now=dt.datetime(2026,11,2,tzinfo=dt.timezone.utc))
              if x[0]=="binance_spot" and x[1]==day]
        self.assertEqual([x[2] for x in todo],[12,11,13,0])

    def test_native_snapshot_must_match_venue_day_and_utc_hour(self):
        day=dt.date(2026,10,31)
        data=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",day)
        self.assertFalse(m.verified_entry({"status":"ok","data":data},"bybit_spot",str(day)))
        self.assertFalse(m.verified_entry({"status":"ok","data":data},"binance_spot","2026-10-30"))
        bad=dict(data);bad["sample_utc_hour"]=11
        self.assertFalse(m.verified_entry({"status":"ok","data":bad},"binance_spot",str(day)))

    def test_failure_for_one_hour_does_not_blacklist_adjacent_hours(self):
        now=dt.datetime(2026,11,2,8,tzinfo=dt.timezone.utc)
        records={name:{} for name in m.MARKETS}
        failed={"binance_spot:2026-11-01:12":{
            "retry_after":(now+dt.timedelta(days=7)).isoformat()}}
        picked=[t for t in m.targets(dt.date(2026,11,1), records,failed,now)
                if t[0]=="binance_spot" and t[1]==dt.date(2026,11,1)]
        self.assertEqual([x[2] for x in picked],[11,13,0])
    def test_00_utc_fallback_is_native_but_not_a_12_utc_comparator(self):
        day=dt.date(2026,10,31)
        record=m.parse_checkpoint(fixture(),"binance_spot",
            "BTCUSDT","spot",1.0,"USDT",day)
        fallback=dict(record)
        fallback["time"]="2026-10-31T00:13:20+00:00"
        fallback["sample_utc_hour"]=0
        fallback["file_path"]="binance_spot/2026-10-31/00/BTCUSDT_orderbook.parquet"
        row={"status":"ok","data":fallback}
        self.assertTrue(m.verified_entry(row,"binance_spot",day.isoformat()))
        coverage=m.recent_coverage({"binance_spot":{day.isoformat():row}},day)
        self.assertEqual(coverage["7d"]["binance_spot"]["verified_days"],1)
        self.assertEqual(coverage["7d"]["binance_spot"]["same_clock_12utc_verified_days"],0)
        self.assertEqual(coverage["7d"]["binance_spot"]["same_clock_12utc_complete_band_days"]["0.01"],0)
        original={"status":"ok","data":record}
        comps,_=m.make_comparisons({"binance_spot":{
            "2026-10-30":{**row,"data":{**fallback,"time":"2026-10-30T00:13:20+00:00"}},
            "2026-10-31":original}})
        self.assertIsNone(comps["binance_spot"]["previous_days"]["1d"])

    def test_00_utc_fallback_preserves_retry_of_primary_hours(self):
        now=dt.datetime(2026,11,2,8,tzinfo=dt.timezone.utc)
        day=dt.date(2026,10,31)
        rec=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",day)
        rec["time"]="2026-10-31T00:13:20+00:00"
        rec["sample_utc_hour"]=0
        rec["file_path"]="binance_spot/2026-10-31/00/BTCUSDT_orderbook.parquet"
        existing={v:{} for v in m.MARKETS}
        existing["binance_spot"][day.isoformat()]={"status":"ok","data":rec}
        failures={f"binance_spot:{day}:{hour:02d}":{
            "retry_after":(now+dt.timedelta(days=7)).isoformat(),
            "last_error":"ValueError: no verified checkpoint snapshot"
        } for hour in m.PRIMARY_SEARCH_HOURS}
        pending=[h for venue,d,h in m.targets(day,existing,failures,now)
                 if venue=="binance_spot" and d==day]
        self.assertEqual(pending,[])
        future=now+dt.timedelta(days=8)
        pending=[h for venue,d,h in m.targets(day,existing,failures,future)
                 if venue=="binance_spot" and d==day]
        self.assertEqual(pending,[12,11,13])

    def test_legacy_audit_explicitly_uses_original_three_hour_scope(self):
        day=m.ARCHIVE_START
        found={v:{} for v in m.MARKETS}
        errors={f"binance_spot:{day}:{h:02d}":{"last_error":"HTTPError: HTTP Error 404"}
                for h in m.PRIMARY_SEARCH_HOURS}
        old=m.audit_source_dates(found,errors,day,search_hours=m.PRIMARY_SEARCH_HOURS)
        new=m.audit_source_dates(found,errors,day)
        self.assertEqual(old["binance_spot"]["explicit_error_days"],1)
        self.assertEqual(new["binance_spot"]["not_fully_checked_days"],1)

    def test_reject_different_time_of_day_for_baseline(self):
        last=m.parse_checkpoint(fixture(),"binance_spot",
            "BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        earlier=dict(last)
        earlier["time"]="2026-10-30T01:00:00+00:00"
        later=dict(last)
        later["time"]="2026-10-31T12:00:00+00:00"
        c,b=m.make_comparisons({"binance_spot":{
            "2026-10-30":{"status":"ok","data":earlier},
            "2026-10-31":{"status":"ok","data":later}}})
        self.assertIsNone(c["binance_spot"]["previous_days"]["1d"])
    def test_nearby_hour_is_not_same_clock_baseline(self):
        current=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT",
            "spot",1.0,"USDT",dt.date(2026,10,31))
        old=dict(current)
        old["time"]="2026-10-30T11:00:00+00:00"
        c,b=m.make_comparisons({"binance_spot":{
            "2026-10-30":{"status":"ok","data":old},
            "2026-10-31":{"status":"ok","data":current}}})
        self.assertIsNone(c["binance_spot"]["previous_days"]["1d"])
        self.assertEqual(b["binance_spot"]["7d"]["available"],1)

    def test_zstd_outer_frame_recovered(self):
        raw=fixture()
        packed=zstd.ZstdCompressor().compress(raw)
        record=m.parse_checkpoint(packed,"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        self.assertEqual(record["snapshot_rows"],24)
    def test_no_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError,"no verified checkpoint snapshot"):
            m.parse_checkpoint(fixture(True),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
    def test_null_missing_baseline(self):
        r=m.parse_checkpoint(fixture(),"binance_spot","BTCUSDT","spot",1.0,"USDT",dt.date(2026,10,31))
        c,b=m.make_comparisons({"binance_spot":{"2026-10-31":{"status":"ok","data":r}}})
        self.assertIsNone(c["binance_spot"]["previous_days"]["7d"])
        self.assertIsNone(b["binance_spot"]["7d"]["bands"]["0.05"])
    def test_30_day_actual_coverage_is_not_492_day_global_ratio(self):
        through=dt.date(2026,11,1)
        found={("2026-11-01" if d==0 else (through-dt.timedelta(days=d)).isoformat()):{}
               for d in range(25)}
        cov=m.recent_coverage({"binance_spot":found},through)
        self.assertEqual(cov["30d"]["binance_spot"]["verified_days"],25)
        self.assertEqual(cov["30d"]["binance_spot"]["eligible_days"],30)
        self.assertEqual(cov["30d"]["binance_spot"]["coverage_pct"],83.33)
        self.assertEqual(cov["7d"]["binance_spot"]["coverage_pct"],100.0)
    def test_recent_window_coverage_empty_is_zero_not_global_missing_history(self):
        cov=m.recent_coverage({"bybit_spot":{}},dt.date(2026,11,1))
        self.assertEqual(cov["30d"]["bybit_spot"]["verified_days"],0)
        self.assertEqual(cov["30d"]["bybit_spot"]["coverage_pct"],0)

    def test_calendar_audit_separates_native_gaps_from_retryable_http_errors(self):
        start=m.ARCHIVE_START
        days=[(start+dt.timedelta(days=i)).isoformat() for i in range(4)]
        observed={v:{d:{} for d in days} for v in m.MARKETS}
        # One market: verified on first day, missing native snapshot on second,
        # three transient 429s on third, one untested hour on fourth.
        observed["binance_spot"]={days[0]:{}}
        failures={}
        for hour in m.SEARCH_HOURS:
            failures[f"binance_spot:{days[1]}:{hour:02d}"]={
                "last_error":"ValueError: no verified checkpoint snapshot found anywhere in the requested UTC hour",
                "retry_after":"2026-11-09T00:00:00+00:00"}
            failures[f"binance_spot:{days[2]}:{hour:02d}"]={
                "last_error":"HTTPError: HTTP Error 429: Too Many Requests",
                "retry_after":"2026-11-03T00:00:00+00:00"}
        for hour in m.SEARCH_HOURS[:2]:
            failures[f"binance_spot:{days[3]}:{hour:02d}"]={
                "last_error":"HTTPError: HTTP Error 429",
                "retry_after":"2026-11-03T00:00:00+00:00"}
        result=m.audit_source_dates(observed,failures,start+dt.timedelta(days=3))
        row=result["binance_spot"]
        self.assertEqual(row["eligible_days"],4)
        self.assertEqual(row["verified_days"],1)
        self.assertEqual(row["explicit_error_days"],2)
        self.assertEqual(row["not_fully_checked_days"],1)
        self.assertFalse(row["all_source_dates_accounted_for"])
        self.assertEqual(row["error_reason_counts"],{
            "no_native_snapshot_in_sampled_hours":1,"transient_or_other_error":1})
        self.assertEqual(row["transient_or_other_error_days"],1)
        self.assertEqual(row["error_date_details"][0]["day"],days[1])
        self.assertEqual(row["error_date_details"][1]["classification"],"transient_or_other_error")
        self.assertEqual(result["bybit"]["verified_days"],4)
        self.assertTrue(result["bybit"]["all_source_dates_accounted_for"])
        self.assertEqual(sum([row["verified_days"],row["explicit_error_days"],
                              row["not_fully_checked_days"]]),row["eligible_days"])

    def test_missing_archive_404_is_explicit_not_zero_or_transient(self):
        start=m.ARCHIVE_START
        days=[(start+dt.timedelta(days=i)).isoformat() for i in range(3)]
        observed={v:{d:{} for d in days} for v in m.MARKETS}
        observed["binance_spot"]={days[0]:{}}
        failures={}
        for hour in m.SEARCH_HOURS:
            failures[f"binance_spot:{days[1]}:{hour:02d}"]={
                "last_error":"HTTPError: HTTP Error 404: Not Found",
                "retry_after":"2026-11-09T00:00:00+00:00"}
            failures[f"binance_spot:{days[2]}:{hour:02d}"]={
                "last_error":"HTTPError: HTTP Error 429: Too Many Requests",
                "retry_after":"2026-11-03T00:00:00+00:00"}
        row=m.audit_source_dates(observed,failures,start+dt.timedelta(days=2))["binance_spot"]
        self.assertEqual(row["verified_days"],1)
        self.assertEqual(row["explicit_error_days"],2)
        self.assertEqual(row["not_fully_checked_days"],0)
        self.assertEqual(row["error_reason_counts"],{
            "source_file_404_in_sampled_hours":1,"transient_or_other_error":1})
        self.assertEqual(row["transient_or_other_error_days"],1)
        self.assertTrue(row["all_source_dates_accounted_for"])
        self.assertEqual(m.retry_delay_days("HTTPError: HTTP Error 404: Not Found"),7)
        self.assertEqual(m.retry_delay_days("ValueError: no verified checkpoint snapshot"),7)
        self.assertEqual(m.retry_delay_days("HTTPError: HTTP Error 429"),1)
        self.assertEqual(m.retry_delay_days("TimeoutError: timed out"),1)

    def test_lossless_calendar_intervals_do_not_fill_unobserved_days(self):
        days=["2026-10-01","2026-10-03","2026-10-02","2026-10-05",
              "2026-10-05","2026-10-08"]
        self.assertEqual(m.compact_date_intervals(days),[
            {"start":"2026-10-01","end":"2026-10-03","days":3},
            {"start":"2026-10-05","end":"2026-10-05","days":1},
            {"start":"2026-10-08","end":"2026-10-08","days":1}])
        self.assertEqual(m.compact_date_intervals([]),[])

    def test_calendar_intervals_partition_verified_errors_and_unchecked(self):
        start=m.ARCHIVE_START
        days=[(start+dt.timedelta(days=i)).isoformat() for i in range(5)]
        found={venue:{} for venue in m.MARKETS}
        found["binance_spot"]={days[0]:{},days[2]:{}}
        errors={}
        for hour in m.SEARCH_HOURS:
            errors[f"binance_spot:{days[1]}:{hour:02d}"]={
                "last_error":"HTTPError: HTTP Error 404: Not Found",
                "retry_after":"2026-11-09T00:00:00+00:00"}
            errors[f"binance_spot:{days[3]}:{hour:02d}"]={
                "last_error":"ValueError: no verified checkpoint snapshot found anywhere in the requested UTC hour",
                "retry_after":"2026-11-09T00:00:00+00:00"}
        row=m.audit_source_dates(found,errors,start+dt.timedelta(days=4))["binance_spot"]
        self.assertEqual(row["verified_date_intervals"],[
            {"start":days[0],"end":days[0],"days":1},
            {"start":days[2],"end":days[2],"days":1}])
        self.assertEqual(row["explicit_error_date_intervals"],[
            {"start":days[1],"end":days[1],"days":1},
            {"start":days[3],"end":days[3],"days":1}])
        self.assertEqual(row["unchecked_date_intervals"],[
            {"start":days[4],"end":days[4],"days":1}])
        self.assertEqual(set(row["explicit_error_intervals_by_reason"]),{
            "source_file_404_in_sampled_hours","no_native_snapshot_in_sampled_hours"})
        self.assertEqual(row["eligible_days"],5)
        self.assertEqual(row["verified_days"]+row["explicit_error_days"]+
                         row["not_fully_checked_days"],5)


    def test_source_eligibility_does_not_count_bitget_prelaunch_dates_as_missing(self):
        through=dt.date(2025,7,16)
        observed={v:{} for v in m.MARKETS}
        audit=m.audit_source_dates(observed,{},through)
        self.assertEqual(m.MARKET_START["bitget_spot"],dt.date(2025,7,15))
        self.assertEqual(audit["bitget_spot"]["source_market_start"],"2025-07-15")
        self.assertEqual(audit["bitget_spot"]["eligible_days"],2)
        self.assertEqual(audit["bitget_spot"]["not_fully_checked_days"],2)
        self.assertEqual(audit["binance_spot"]["eligible_days"],19)
        # The scheduler never probes Bitget before its actual archive launch.
        targets=list(m.targets(dt.date(2025,7,14),observed,
                              now=dt.datetime(2026,11,2,tzinfo=dt.timezone.utc)))
        self.assertFalse(any(v=="bitget_spot" for v,day,h in targets))
        self.assertEqual(m.recent_coverage(observed,through)["30d"]["bitget_spot"]["eligible_days"],2)

    def test_obsolete_45mb_failures_reopened_only_when_safety_cap_increased(self):
        self.assertEqual(m.MAX_COMPRESSED_BYTES,128_000_000)
        self.assertEqual(m.download.__defaults__[0],m.MAX_COMPRESSED_BYTES)
        failures={
          "binance_futures:2026-09-11:12":{"last_error":"ValueError: File exceeds 45 MB cap; not silently truncated",
                                              "retry_after":"2026-11-09T00:00:00+00:00"},
          "binance_futures:2026-09-11:13":{"last_error":"ValueError: File exceeds 128 MB cap; not silently truncated"},
          "binance_futures:2026-09-11:11":{"last_error":"HTTPError: HTTP Error 429: Too Many Requests"},
        }
        self.assertEqual(m.invalidate_obsolete_size_cap_failures(failures),1)
        self.assertNotIn("binance_futures:2026-09-11:12",failures)
        self.assertIn("binance_futures:2026-09-11:13",failures)
        self.assertIn("binance_futures:2026-09-11:11",failures)


    def test_strict_same_clock_7d_30d_does_not_invent_wide_band_depth(self):
        day=dt.date(2026,10,31)
        tight=m.parse_checkpoint(fixture(tick=0.001),"bybit","BTCUSDT",
                                 "perpetual",1.0,"USDT",day)
        earlier=dict(tight)
        earlier["time"]="2026-10-30T11:00:00+00:00"
        observed={"bybit":{
            "2026-10-31":{"status":"ok","data":tight},
            "2026-10-30":{"status":"ok","data":earlier},
        }}
        for width in ("7d","30d"):
            row=m.recent_coverage(observed,day)[width]["bybit"]
            self.assertEqual(row["verified_days"],2)
            self.assertEqual(row["same_clock_12utc_verified_days"],1)
            self.assertEqual(row["same_clock_12utc_complete_band_days"]["0.01"],1)
            self.assertEqual(row["same_clock_12utc_complete_band_days"]["0.05"],0)
            self.assertEqual(row["same_clock_12utc_complete_band_days"]["1.0"],0)

    def test_compressed_download_cap_fails_closed_without_truncating(self):
        with patch.object(m.urllib.request,"urlopen",side_effect=lambda *a,**k:io.BytesIO(b"x"*12)):
            with patch.object(m.time,"sleep",return_value=None):
                with self.assertRaisesRegex(ValueError,"File exceeds"):
                    m.download("https://example.invalid/file",limit=10)
                self.assertEqual(m.download("https://example.invalid/file",limit=12),b"x"*12)

if __name__=="__main__":
    unittest.main()
