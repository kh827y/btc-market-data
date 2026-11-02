import unittest
from collector import delta_forward,interpolate,fixed_tenor

class OptionsTests(unittest.TestCase):
    def test_call_put_delta_sign(self):
        self.assertGreater(delta_forward(80000,85000,40,30/365,"C"),0)
        self.assertLess(delta_forward(80000,75000,40,30/365,"P"),0)
    def test_interpolation_25d(self):
        self.assertAlmostEqual(interpolate([(0.2,43),(0.3,39)],0.25),41)
        self.assertIsNone(interpolate([(0.02,50),(0.4,25)],0.25))
    def test_interpolate_matched_expiry(self):
        s={}
        for d in [20,40]:
            s[str(d)]={"days":d,"expiration":str(d),
                "atm_iv_pct":40,"call25_iv_pct":38,"put25_iv_pct":42}
        result=fixed_tenor(s,30)
        self.assertEqual(result["status"],"available")
        self.assertAlmostEqual(result["atm_iv_pct"],40,places=3)
        self.assertAlmostEqual(result["rr25_call_minus_put_volpts"],-4,places=3)
        self.assertGreater(result["bf25_volpts"],-0.01)
    def test_no_extrapolation(self):
        one={"x":{"days":20,"expiration":"x","atm_iv_pct":40,"call25_iv_pct":42,"put25_iv_pct":44}}
        self.assertEqual(fixed_tenor(one,30)["status"],"unavailable")
    def test_wide_expiry_quality_flag(self):
        a={"x":{"days":50,"expiration":"x","atm_iv_pct":40,"call25_iv_pct":38,"put25_iv_pct":42},
           "y":{"days":145,"expiration":"y","atm_iv_pct":40,"call25_iv_pct":38,"put25_iv_pct":42}}
        result=fixed_tenor(a,90)
        self.assertEqual(result["quality"],"wide_expiry_bracket")
if __name__=="__main__":
    unittest.main()
