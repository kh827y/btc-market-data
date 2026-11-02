import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import unittest
import zipfile

spec=importlib.util.spec_from_file_location("bybit_independent",Path(__file__).resolve().parents[1]/"bybit_independent.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def archive(day=dt.date(2026,10,31),depth=200,ask_reach=0.3):
    base=78000
    qty=lambda: "0.5"
    # Use 200 levels with a 0.4% price window per side.
    message={"topic":f"orderbook.{depth}.BTCUSDT","type":"snapshot",
             "ts":int(dt.datetime.combine(day,dt.time(0),dt.timezone.utc).timestamp()*1000)+700,
             "data":{"s":"BTCUSDT","u":132,"seq":777,
                     "b":[[f"{base-i*2:.1f}",qty()] for i in range(depth)],
                     "a":[[f"{base+0.1+i*2:.1f}",qty()] for i in range(depth)]}}
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("sample.data",json.dumps(message)+"\n"+json.dumps(
            {**message,"type":"delta","ts":message["ts"]+1000})+"\n")
    return out.getvalue()

class BybitIndependentTests(unittest.TestCase):
    def test_partial_zip_works_without_central_directory(self):
        blob=archive()
        header=blob[:min(len(blob)-22,50000)]
        obj=m.first_zip_snapshot(header)
        self.assertEqual(obj["type"],"snapshot")
        r=m.measure(obj,dt.date(2026,10,31),"bybit_independent_spot",200,"src")
        self.assertIsNotNone(r["bands"]["0.05"]["bid_share"])
        self.assertIn("0.2",r["bands"])
    def test_non_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            m.first_zip_snapshot(b"not a zip")
    def test_unavailable_wide_band_is_null(self):
        day=dt.date(2026,10,31)
        obj=m.first_zip_snapshot(archive(depth=200))
        r=m.measure(obj,day,"bybit_independent_spot",200,"src")
        self.assertFalse(r["bands"]["1.0"]["bid_coverage_complete"])
        self.assertIsNone(r["bands"]["1.0"]["bid_usd"])
    def test_invalid_date_rejected(self):
        obj=m.first_zip_snapshot(archive())
        with self.assertRaisesRegex(ValueError,"not near midnight"):
            m.measure(obj,dt.date(2026,10,30),"bybit_independent_spot",200,"src")
    def test_comparisons_require_same_band(self):
        day=dt.date(2026,10,31)
        obj=m.first_zip_snapshot(archive(day))
        obj2=m.first_zip_snapshot(archive(day-dt.timedelta(days=1)))
        recent=m.measure(obj,day,"bybit_independent_spot",200,"src")
        previous=m.measure(obj2,day-dt.timedelta(days=1),"bybit_independent_spot",200,"src")
        ret=m.comparisons({"bybit_independent_spot":{
            "2026-10-30":previous,"2026-10-31":recent}})
        self.assertIsNotNone(ret["bybit_independent_spot"]["comparisons"]["1d"])
        self.assertNotIn("1.0",ret["bybit_independent_spot"]["comparisons"]["1d"]["bands"])

    def test_valid_short_complete_zip_http_range_is_accepted(self):
        from unittest.mock import patch
        class Response:
            status=206
            headers={"Content-Range":"bytes 0-99/100"}
            def __enter__(self):return self
            def __exit__(self,*args):return None
            def read(self,n):return b"x"*100
        with patch.object(m.urllib.request,"urlopen",return_value=Response()):
            self.assertEqual(len(m.range_bytes("https://example.invalid/archive.zip",length=512)),100)
    def test_partial_http_range_must_have_exact_reported_end(self):
        from unittest.mock import patch
        class Response:
            status=206
            headers={"Content-Range":"bytes 0-45/100"}
            def __enter__(self):return self
            def __exit__(self,*args):return None
            def read(self,n):return b"x"*46
        with patch.object(m.urllib.request,"urlopen",return_value=Response()):
            with self.assertRaisesRegex(ValueError,"invalid range end"):
                m.range_bytes("https://example.invalid/archive.zip",length=512)

if __name__=="__main__":
    unittest.main()
