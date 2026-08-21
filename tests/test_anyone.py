"""
Does this work for someone who is not the sample?

This suite exists because it did not. The first version resolved employers
through hardcoded lookup tables keyed on the sample's TANs and member IDs, so
a real member's documents produced:

    accounts: 0    balance: 0    findings: []

No error, no warning - it simply reported that a record it had never examined
was clean. For a product whose entire purpose is telling someone whether their
claim will be rejected, that is the worst possible failure.

Everything must now be derived from the uploaded documents: employer identity,
UAN, PAN, and name.

Run:  python tests/test_anyone.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import app.engine as E

# Longest strings first, so replacing an establishment prefix does not clobber
# the member IDs that embed it.
SWAPS = [
    ("BLBNG00123450000001234", "TNMAS00345670000009876"),
    ("PNPUN00678900000005678", "KABLR00998870000004321"),
    ("BLBNG0012345000", "TNMAS0034567000"),
    ("PNPUN0067890000", "KABLR0099887000"),
    ("ACME TECHNOLOGIES PRIVATE LIMITED", "VAYU LOGISTICS PRIVATE LIMITED"),
    ("ACME TECHNOLOGIES PVT LTD", "VAYU LOGISTICS PVT LTD"),
    ("ACME TECHNOLOGIES", "VAYU LOGISTICS"),
    ("BOREAL SYSTEMS PRIVATE LIMITED", "NILGIRI FOODS PRIVATE LIMITED"),
    ("BOREAL SYSTEMS PVT LTD", "NILGIRI FOODS PVT LTD"),
    ("STARLIT RETAIL PRIVATE LIMITED", "HELIOS MEDTECH PRIVATE LIMITED"),
    ("MUMS45678B", "CHEH55512D"),
    ("BLRA12345E", "CHEV77823Q"),
    ("PNEB67890K", "BLRN33445F"),
    ("AAAPZ1234C", "BXYPK9876Z"),
    ("100999888777", "101777666555"),
    ("RAHUL KUMAR SINGH", "MEENA IYER"),
    ("RAHUL K SINGH", "MEENA IYER"),
    ("RAHUL SINGH", "MEENA IYER"),
]


def swap(text: str) -> str:
    for a, b in SWAPS:
        text = text.replace(a, b)
    return text


def main() -> int:
    as26 = swap(E.SAMPLE_26AS)
    pbs = [swap(p) for p in E.SAMPLE_PASSBOOKS]
    hist = swap(E.SAMPLE_SERVICE_HISTORY)
    bank = swap(E.SAMPLE_BANK)

    names = E.extract_names({"26as": as26, "passbook": pbs, "bank": bank})
    a = E.analyse(text_26as=as26, passbooks=pbs, service_history=hist,
                  bank=bank, names=names)

    kinds = [c["kind"] for c in a.result["contradictions"]]
    employers = [ac.employer for ac in a.accounts]
    key = next((c["employer"] for c in a.result["contradictions"]
                if c["kind"] == "EXIT_TOO_EARLY"), None)
    doc = a.documents.get(key)
    body = doc["doc"].body if doc else ""

    checks = [
        # identity comes from the documents, not a constant
        ("name read from the documents", a.identity["name"] == "MEENA IYER"),
        ("UAN read from the passbook", a.identity["uan"] == "101777666555"),
        ("PAN read from Form 26AS", a.identity["pan"] == "BXYPK9876Z"),

        # employers resolved dynamically, not from a lookup table
        ("both accounts found", len(a.accounts) == 2),
        ("employer names come from the documents",
         "Vayu Logistics Private Limited" in employers
         and "Nilgiri Foods Private Limited" in employers),
        ("balances parsed", a.total_balance > 0),
        ("pension parsed", a.total_pension > 0),

        # the engine still finds the same defects for a stranger
        ("wrong exit date still detected", "EXIT_TOO_EARLY" in kinds),
        ("missing exit still detected", "MISSING_EXIT" in kinds),
        ("orphan account still detected", "ORPHAN_ACCOUNT" in kinds),
        ("does not invent extra orphans", kinds.count("ORPHAN_ACCOUNT") == 1),

        # generated paperwork must belong to THIS person
        ("a letter was generated", bool(body)),
        ("letter carries their UAN", "101777666555" in body),
        ("letter carries their name", "MEENA IYER" in body),
        ("letter passes the claim gate", doc is not None and not doc["violations"]),

        # nothing from the sample may leak into a real record
        ("no sample name leaks", "RAHUL" not in body),
        ("no sample UAN leaks", "100999888777" not in body),
        ("no sample employer leaks", "ACME" not in body.upper()),
    ]

    print("=" * 70)
    print("  works for someone who is not the sample")
    failures = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    print("=" * 70)
    return 1 if failures else 0


if __name__ == "__main__":
    _s.exit(main())
