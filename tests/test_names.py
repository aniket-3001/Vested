"""
SPIKE G - Person-name matching across scripts, and the model-backed layer.

Two questions:
    1. Can we decide whether two document spellings are the same person -
       accepting real spelling variation while refusing genuinely different
       names? False positives here are catastrophic: merging two people's
       provident fund records.
    2. Does the model integration hold its contract, with a deterministic
       fallback that keeps the suite runnable without a key?

Run:  python tests/test_names.py
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from pathlib import Path


from app.models import OfflineBackend, get_backend  # noqa: E402
from app.name_match import _strip_vowels_to_skeleton, compare, worst_pair  # noqa: E402
from core.gate import (  # noqa: E402
    EvidenceLedger, RenderedDoc, claim_gate,
)

# (name A, name B, should_match, label)
CORPUS = [
    # --- same person, real document variation ---------------------------
    ("RAHUL KUMAR SINGH", "RAHUL KUMAR SINGH", True, "identical"),
    ("RAHUL KUMAR SINGH", "RAHUL K SINGH", True, "middle name abbreviated"),
    ("RAHUL KUMAR SINGH", "RAHUL SINGH", True, "middle name dropped"),
    ("RAHUL SINGH", "RAHOOL SINGH", True, "vowel spelling variant"),
    ("RAHUL SINGH", "RAAHUL SINGH", True, "vowel lengthening"),
    ("SHRI RAHUL KUMAR SINGH", "RAHUL KUMAR SINGH", True, "honorific present"),
    ("राहुल कुमार सिंह", "RAHUL KUMAR SINGH", True, "Devanagari vs Latin"),
    ("राहुल सिंह", "RAHUL SINGH", True, "Devanagari, no middle name"),
    ("PRIYA SHARMA", "PRIYA SHARMAA", True, "trailing vowel"),
    ("VENKATESH IYER", "WENKATESH IYER", True, "v/w equivalence"),
    ("JAYESH PATEL", "ZAYESH PATEL", True, "j/z equivalence"),

    # --- different people. These are the dangerous ones. -----------------
    ("RAHUL KUMAR SINGH", "RAHUL KUMAR SINHA", False, "Singh vs Sinha"),
    ("RAHUL KUMAR SINGH", "RAHUL KUMAR SHARMA", False, "different surname"),
    ("RAHUL KUMAR SINGH", "ROHIT KUMAR SINGH", False, "different given name"),
    ("PRIYA SHARMA", "PRIYA VERMA", False, "Sharma vs Verma"),
    ("RAHUL PRASAD SINGH", "RAHUL MOHAN SINGH", False, "conflicting middle names"),
    ("ANIL KUMAR", "SUNIL KUMAR", False, "Anil vs Sunil"),
    ("RAMESH IYER", "RAMESH IYENGAR", False, "Iyer vs Iyengar"),
    ("DEEPAK JOSHI", "DEEPAK JOSHUA", False, "Joshi vs Joshua"),
]


def main() -> int:
    backend = OfflineBackend()
    failures = 0

    print("=" * 78)
    print(f"  backend in use: {get_backend().name}"
          f"{'  (set OPENAI_API_KEY for live calls)' if get_backend().name == 'offline' else ''}")
    print("=" * 78)

    print("\n  consonant skeletons - the basis of the decision")
    for w in ["RAHUL", "RAHOOL", "RAAHUL", "SINGH", "SINHA", "SHARMA", "VERMA",
              "IYER", "IYENGAR", "VENKATESH", "WENKATESH"]:
        print(f"    {w:12} -> {_strip_vowels_to_skeleton(w)}")

    print("\n  match decisions")
    tp = fp = tn = fn = 0
    for a, b, expected, label in CORPUS:
        m = compare(a, b, backend)
        ok = m.same_person == expected
        if expected and m.same_person: tp += 1
        elif expected and not m.same_person: fn += 1
        elif not expected and m.same_person: fp += 1
        else: tn += 1
        if not ok:
            failures += 1
        mark = "ok  " if ok else "MISS"
        verdict = "same" if m.same_person else "diff"
        print(f"    {mark} {verdict}  {m.confidence:.2f}  {label}")
        if not ok:
            print(f"           {m.explain()}")

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    print(f"\n    TP={tp} FP={fp} TN={tn} FN={fn}   precision={precision:.3f} recall={recall:.3f}")

    # --- the real-world case ------------------------------------------------
    print("\n  four documents, one person - find the weakest link")
    docs = {
        "Aadhaar": "राहुल कुमार सिंह",
        "PAN": "RAHUL KUMAR SINGH",
        "EPFO": "RAHUL K SINGH",
        "Bank": "RAHUL SINGH",
    }
    for k, v in docs.items():
        print(f"    {k:9} {v}")
    w = worst_pair(docs, backend)
    print(f"    weakest: {w[0]} vs {w[1]} -> "
          f"{'same person' if w[2].same_person else 'MISMATCH'} ({w[2].confidence:.2f})")
    print(f"    reason : {w[2].explain()}")

    # --- ABHA-style hard reject ---------------------------------------------
    print("\n  ABHA linkage check (auto-rejects mismatched names as fraud)")
    abha = compare("RAHUL KUMAR SINGH", "RAHUL KUMAR SINHA", backend)
    print(f"    EPF 'RAHUL KUMAR SINGH' vs ABHA 'RAHUL KUMAR SINHA'")
    print(f"    -> {'same' if abha.same_person else 'DIFFERENT PERSON'}: {abha.explain()}")

    # --- model contract -----------------------------------------------------
    print("\n  model backend contract")
    t_dev = backend.transliterate("राहुल कुमार सिंह")
    n1 = backend.classify_narration("NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY JUN21")
    n2 = backend.classify_narration("INT.CR QUARTERLY INTEREST CREDIT")
    print(f"    transliterate  : राहुल कुमार सिंह -> {t_dev}")
    print(f"    salary credit  : is_salary={n1['is_salary']} employer={n1['employer_hint']}")
    print(f"    interest credit: is_salary={n2['is_salary']}")

    # --- gate holds against model-shaped output -----------------------------
    print("\n  claim gate vs model-shaped output")
    led = EvidenceLedger()
    led.admit("UAN", "100999888777", "passbook:header")
    led.admit("DATE", "31-03-2021", "26AS:txn#12", employer="ACME_TECH")
    hallucinated = RenderedDoc(
        title="drafted", scope="ACME_TECH",
        body=("I, RAHUL KUMAR SINGH, UAN 100999888777, state that I worked until "
              "31-03-2021 and was possibly paid Rs 4,20,000 in arrears on 15-08-2021."),
        annexure=["DATE: 31-03-2021  [26AS:txn#12]"],
    )
    v = claim_gate(hallucinated, led)
    for x in v:
        print(f"    BLOCKED  {x.kind}: {x.token} - {x.detail}")
    gate_ok = len(v) >= 2

    print("\n" + "-" * 78)
    print("  spike assertions")
    checks = [
        ("zero false matches (never merge two people)", fp == 0),
        ("recall >= 0.90 on real spelling variation", recall >= 0.90),
        ("Devanagari matches its Latin spelling", compare("राहुल कुमार सिंह", "RAHUL KUMAR SINGH", backend).same_person),
        ("Singh != Sinha", not abha.same_person),
        ("Iyer != Iyengar", not compare("RAMESH IYER", "RAMESH IYENGAR", backend).same_person),
        ("conflicting middle names rejected", not compare("RAHUL PRASAD SINGH", "RAHUL MOHAN SINGH", backend).same_person),
        ("four-document set resolves to one person", w[2].same_person),
        ("offline backend romanises Devanagari to Latin",
         t_dev.isascii() and "SINGH" in t_dev.upper()),
        ("narration classifier separates salary from interest",
         n1["is_salary"] and not n2["is_salary"]),
        ("gate blocks invented figures in drafted prose", gate_ok),
    ]
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1

    print(f"\n  RESULT: {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
