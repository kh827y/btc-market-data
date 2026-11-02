import datetime as dt
import importlib.util
import io
from pathlib import Path
import unittest

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
    def test_failure_for_one_hour_does_not_blacklist_adjacent_hours(self):
        now=dt.datetime(2026,11,2,8,tzinfo=dt.timezone.utc)
        records={name:{} for name in m.MARKETS}
        failed={"binance_spot:2026-11-01:12":{
            "retry_after":(now+dt.timedelta(days=7)).isoformat()}}
        picked=[t for t in m.targets(dt.date(2026,11,1), records,failed,now)
                if t[0]=="binance_spot" and t[1]==dt.date(2026,11,1)]
        self.assertEqual([x[2] for x in picked],[11,13])
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

if __name__=="__main__":
    unittest.main()
