# -*- coding: utf-8 -*-
"""30.09, багрепорты #73 и #65/#74/#75: тексты отказов.

#73: бесплатный дейлик «опыт» получал «Крустики вернутся» — денег не было, зритель
решал, что дейлик сгорел. #65/#74/#75: отказ «не то оружие» не называл оружие.
Запуск: python tests/test_refusal_free_daily.py (код возврата = число провалов).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.bannerlord.refusals import describe, _EXACT  # noqa: E402

failed = 0


def check(ok, text):
    global failed
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failed += 1


t = describe("skill_xp_not_applied:Leadership", free=True, daily=True)
check("рустики" not in t, "дейлик: нет обещания крустиков — " + t)
check("Дейлик не потрачен" in t, "дейлик: сказано, что можно нажать ещё раз")
paid = describe("skill_xp_not_applied:Leadership")
check("Крустики вернутся" in paid, "платное действие: обещание возврата на месте")
for code, text in _EXACT.items():
    free = describe(code, free=True)
    check("рустики вернутся" not in free and free[:1] == free[:1].upper() and free.endswith((".", "!", "?")),
          f"бесплатное {code}: без обещания, с заглавной и точкой — {free}")
w = describe("required_weapon_not_wielded", weapon="two_handed")
check("двуручное оружие" in w and "Крустики вернутся" in w, "оружие названо, возврат обещан — " + w)
check(describe("required_weapon_not_wielded", weapon="нечто") == _EXACT["required_weapon_not_wielded"],
      "незнакомое оружие — прежний текст")
sys.exit(failed)
