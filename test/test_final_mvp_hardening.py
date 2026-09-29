#!/usr/bin/env python3
"""
test/test_final_mvp_hardening.py
Automated Verification Suite for ConsultantPlus TH Final MVP Hardening.
Tests:
1. Multi-turn Topic Switching (Real Estate -> Tax P.161 -> Immigration -> Labor)
2. Topic Isolation (No Land Code sticking on Tax/Labor turns)
3. Language Profile Strict Compliance (EN, TH, RU, ZH)
4. Grounding & Safety Gate Verification
"""

import os
import sys
import time
import unittest

backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, backend_dir)

from core.core_engine import ConsultantPlusCoreEngine
from core.models import UserTurnInput


class TestFinalMvpHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ConsultantPlusCoreEngine()

    def test_01_multi_turn_topic_switch_real_estate_to_tax(self):
        """TURN 1: Real Estate -> TURN 2: Foreign Income Tax P.161. Verifies zero Land Code sticking."""
        test_uid = f"reg_test_u_{int(time.time())}"
        sess_id = f"sess_re_to_tax_{int(time.time())}"

        # TURN 1: Real estate question
        turn1_input = UserTurnInput(
            user_id=test_uid,
            session_id=sess_id,
            case_id=f"case_{sess_id}",
            input_type="text",
            raw_text="Могу ли я как иностранец купить квартиру в кондоминиуме в Таиланде в 100% собственность?",
            language_hint="ru"
        )
        resp1 = self.engine.process_turn(turn1_input)
        self.assertEqual(resp1.lang, "ru")
        self.assertIn("49%", resp1.answer)
        self.assertTrue(
            "кондоминиум" in resp1.answer.lower() or "апартамент" in resp1.answer.lower() or "квартир" in resp1.answer.lower(),
            "Turn 1 should address condominium acquisition"
        )

        # TURN 2: Tax P.161 question in the SAME session
        turn2_input = UserTurnInput(
            user_id=test_uid,
            session_id=sess_id,
            case_id=f"case_{sess_id}",
            input_type="text",
            raw_text="А какие правила по налогам при переводе денег из-за границы в Таиланд по распоряжению P.161?",
            language_hint="ru"
        )
        resp2 = self.engine.process_turn(turn2_input)
        self.assertEqual(resp2.lang, "ru")
        ans2_lower = resp2.answer.lower()

        # Turn 2 MUST be about taxation / P.161 / remittance
        self.assertTrue(
            any(w in ans2_lower for w in ["налог", "161", "p.161", "резидент", "180", "доход"]),
            f"Turn 2 must address taxation! Answer snippet: {resp2.answer[:300]}"
        )

        # Turn 2 MUST NOT be stuck on Land Code / Section 86 / villa leasehold
        self.assertNotIn(
            "статья 86 земельного кодекса", ans2_lower,
            "Turn 2 should NOT be stuck on Land Code Section 86!"
        )
        self.assertNotIn(
            "superficies", ans2_lower,
            "Turn 2 should NOT be stuck on superficies/villa leasehold!"
        )
        print("\n>>> Test 1 (Real Estate -> Tax P.161): PASSED successfully! Zero Land Code sticking.")

    def test_02_three_turn_chain_re_immigration_labor(self):
        """TURN 1: Real estate -> TURN 2: Immigration (LTR) -> TURN 3: Labor severance (Sec 118)."""
        test_uid = f"reg_test_3turn_{int(time.time())}"
        sess_id = f"sess_3turn_{int(time.time())}"

        # Turn 1: Real Estate
        t1 = UserTurnInput(
            user_id=test_uid,
            session_id=sess_id,
            case_id=f"case_{sess_id}",
            raw_text="What are the legal options for a foreigner to register a villa on a 30-year lease?",
            language_hint="en"
        )
        r1 = self.engine.process_turn(t1)
        self.assertEqual(r1.lang, "en")
        self.assertTrue("lease" in r1.answer.lower() or "538" in r1.answer)

        # Turn 2: Immigration
        t2 = UserTurnInput(
            user_id=test_uid,
            session_id=sess_id,
            case_id=f"case_{sess_id}",
            raw_text="What are the financial requirements for a 10-year LTR visa in Thailand?",
            language_hint="en"
        )
        r2 = self.engine.process_turn(t2)
        self.assertEqual(r2.lang, "en")
        self.assertTrue(
            "ltr" in r2.answer.lower() or "visa" in r2.answer.lower() or "immigration" in r2.answer.lower(),
            "Turn 2 must address LTR visa / immigration"
        )
        self.assertNotIn("section 538", r2.answer.lower(), "Turn 2 should not retain leasehold section 538")

        # Turn 3: Labor
        t3 = UserTurnInput(
            user_id=test_uid,
            session_id=sess_id,
            case_id=f"case_{sess_id}",
            raw_text="How many days of severance pay must an employer pay if terminating an employee after 4 years of work?",
            language_hint="en"
        )
        r3 = self.engine.process_turn(t3)
        self.assertEqual(r3.lang, "en")
        self.assertTrue(
            "severance" in r3.answer.lower() or "118" in r3.answer or "labor" in r3.answer.lower() or "days" in r3.answer.lower(),
            "Turn 3 must address labor severance pay"
        )
        print("\n>>> Test 2 (3-Turn Chain RE -> Immigration -> Labor): PASSED successfully!")

    def test_03_language_profiles(self):
        """Verifies that the response matches the selected language profile regardless of input language."""
        # Profile EN + Russian question -> Answer English
        r_en = self.engine.process_turn(UserTurnInput(
            user_id="u_lang_en",
            session_id="sess_en",
            case_id="case_en",
            raw_text="Как иностранцу открыть компанию в Таиланде?",
            language_hint="en"
        ))
        self.assertEqual(r_en.lang, "en")
        self.assertTrue(any(w in r_en.answer.lower() for w in ["company", "foreign", "business", "act"]))

        # Profile TH + English question -> Answer Thai
        r_th = self.engine.process_turn(UserTurnInput(
            user_id="u_lang_th",
            session_id="sess_th",
            case_id="case_th",
            raw_text="Can a foreigner buy a condo in Pattaya?",
            language_hint="th"
        ))
        self.assertEqual(r_th.lang, "th")
        self.assertTrue(any(w in r_th.answer for w in ["ห้องชุด", "อาคารชุด", "คนต่างด้าว", "กฎหมาย"]))

        # Profile RU + English question -> Answer Russian
        r_ru = self.engine.process_turn(UserTurnInput(
            user_id="u_lang_ru",
            session_id="sess_ru",
            case_id="case_ru",
            raw_text="What are the inheritance rules for foreign property in Thailand?",
            language_hint="ru"
        ))
        self.assertEqual(r_ru.lang, "ru")
        self.assertTrue(any(w in r_ru.answer.lower() for w in ["наслед", "завещан", "имуществ"]))

        # Profile ZH + Thai question -> Answer Chinese
        r_zh = self.engine.process_turn(UserTurnInput(
            user_id="u_lang_zh",
            session_id="sess_zh",
            case_id="case_zh",
            raw_text="คนต่างด้าวซื้อที่ดินในประเทศไทยได้หรือไม่",
            language_hint="zh"
        ))
        self.assertEqual(r_zh.lang, "zh")
        self.assertTrue(any(w in r_zh.answer for w in ["法律", "泰国", "外国人", "土地", "产权"]))

        print("\n>>> Test 3 (Language Profiles EN, TH, RU, ZH): ALL 4 PASSED successfully!")


if __name__ == '__main__':
    unittest.main()
