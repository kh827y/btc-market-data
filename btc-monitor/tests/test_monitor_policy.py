"""Versioned prompt contract: structural checks only, not model delivery tests."""
import pathlib
import unittest

TEXT=(pathlib.Path(__file__).resolve().parents[1]/"automation_prompt_v2.md").read_text(encoding="utf8")

class MonitorPolicyTests(unittest.TestCase):
    def test_single_compact_noncontradictory_policy(self):
        self.assertGreater(len(TEXT),9000)
        self.assertLess(len(TEXT),20000)
        self.assertEqual(TEXT.count("ЗАДАЧА: «Новости и риски BTC»"),1)
        self.assertNotIn("ЧАСТЬ 19.",TEXT)
        self.assertNotIn("ИМЕЕТ ПРИОРИТЕТ над",TEXT)
    def test_regular_source_reads_and_bad_data_not_rebranded(self):
        for phrase in ("btc-monitor/data/brief.json","btc-monitor/data/latest.json",
                       "as_of_utc","family_readiness","coverage_gaps",
                       "stale","invalid_schema","null ≠ 0","не делай >2"):
            self.assertIn(phrase,TEXT)
    def test_critical_sources_referenced(self):
        for path in ("btc-price/data/latest.json","btc-spot-cvd/data/latest.json",
                "btc-derivatives/data/latest.json","btc-options/data/latest.json",
                "btc-onchain/data/monitor_latest.json","btc-macro/data/latest.json",
                "btc-liquidity/data/latest.json","btc-liquidity/data/hft_latest.json",
                "btc-liquidity/data/bybit_independent_latest.json"):
            self.assertIn(path,TEXT)
    def test_distinct_market_methodologies(self):
        for phrase in ("fixed_five_ex_coinbase","150","155","CME",
                "DXY","НЕ ICE DXY","Wilder","MA200","Coinbase",
                "не ноль","00 UTC","11–13 UTC","25Δ"):
            self.assertIn(phrase,TEXT)
    def test_news_verification_and_impact_are_separate(self):
        for phrase in ("ДОСТОВЕРНОСТЬ","✅ Подтверждено",
            "⚠️ Заголовок вводит в заблуждение","❔ Не подтверждено",
            "Значимость 0–3","официальный документ","даты события"):
            self.assertIn(phrase,TEXT)
    def test_trend_positive_negative_sideways(self):
        for phrase in ("продолжения падения","разворота вверх",
            "боковика","1–4 недели","перегрева","долгий"):
            self.assertIn(phrase,TEXT)
    def test_risk_alert_gate_and_systemic_exception(self):
        for phrase in ("минимум две","НЕЗАВИСИМЫЕ","системный шок",
                "один документально подтверждённый",
                "НЕ доказательство","не механически"):
            self.assertIn(phrase.lower(),TEXT.lower())
    def test_silence_and_anti_spam(self):
        for phrase in ("НИ ОДНОГО сообщения","12–24 ч",
          "не чаще","НИЧЕГО НЕ ОТПРАВЛЯЙ","не отправляй почасовое"):
            self.assertIn(phrase.lower(),TEXT.lower())
    def test_all_significant_contributors_and_data_status(self):
        for phrase in ("Что повлияло на оценку","ВСЕ реальные значимые",
            "Данные (часовой мониторинг)","Данные (полный анализ)",
            "последняя строка","одна заключительная строка"):
            self.assertIn(phrase,TEXT)
    def test_no_explicit_investment_horizon_or_hourly_status(self):
        self.assertIn("Никакой привязки к инвестиционному горизонту 12–24 месяца",TEXT)
        self.assertIn("не отправляй почасовое",TEXT.lower())

if __name__=="__main__":
    unittest.main()
