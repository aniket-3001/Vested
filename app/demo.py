"""
Mock accounts, so the product can be tried by someone who has no PF documents.

Vested began as an upload form. That is a reasonable way to build a checker and
a terrible way to be evaluated: a person who has never filed an EPF claim has no
Form 26AS, no passbook and no service history, so they reach the first screen
and stop. Everything past that screen may as well not exist.

Two accounts, because one is not enough to show what this does:

  RAHUL   a record with real defects - a wrong exit date, a missing one, and an
          employer who paid him with no PF account to show for it. This is the
          product working.
  PRIYA   a record that reconciles. Needed to prove the checker can say yes,
          and that a green verdict means something because it can be withheld.

The passwords are printed on the sign-in page on purpose. There is nothing
behind them but synthetic data.
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from app.engine import (  # noqa: E402
    SAMPLE_26AS, SAMPLE_BANK, SAMPLE_PASSBOOKS, SAMPLE_SERVICE_HISTORY, analyse,
)

# ---------------------------------------------------------------------------
# A record with nothing wrong with it
# ---------------------------------------------------------------------------
# One employer, and every source agrees: 26AS runs Jun-2021 to May-2022, the
# passbook carries the same twelve months, and the service history opens and
# closes on the dates the money actually moved.

_CLEAN_MONTHS = [
    ("30-Jun-2021", "15-Jul-2021"), ("31-Jul-2021", "15-Aug-2021"),
    ("31-Aug-2021", "15-Sep-2021"), ("30-Sep-2021", "14-Oct-2021"),
    ("31-Oct-2021", "15-Nov-2021"), ("30-Nov-2021", "14-Dec-2021"),
    ("31-Dec-2021", "15-Jan-2022"), ("31-Jan-2022", "15-Feb-2022"),
    ("28-Feb-2022", "15-Mar-2022"), ("31-Mar-2022", "14-Apr-2022"),
    ("30-Apr-2022", "15-May-2022"), ("31-May-2022", "14-Jun-2022"),
]

_rows = "\n".join(
    f"{i:<9}192      {txn:<18}F                  {bk:<26}72000.00              "
    f"4320.00       4320.00"
    for i, (txn, bk) in enumerate(_CLEAN_MONTHS, 1))

CLEAN_26AS = f"""\
Form 26AS - Annual Tax Statement
Part A - Details of Tax Deducted at Source

Sr. No.  Name of Deductor                 TAN of Deductor  Total Amount Paid/Credited  Total Tax Deducted  Total TDS Deposited
1        HELIOS ANALYTICS PRIVATE LIMITED   BLRH55555C       864000.00                   51840.00            51840.00
Sr. No.  Section  Transaction Date  Status of Booking  Date of Booking  Remarks  Amount Paid/Credited  Tax Deducted  TDS Deposited
{_rows}
"""

_pb_months = "\n".join(
    f"{m}      10200             3600              1250"
    for m in ["Jun-2021", "Jul-2021", "Aug-2021", "Sep-2021", "Oct-2021",
              "Nov-2021", "Dec-2021", "Jan-2022", "Feb-2022", "Mar-2022",
              "Apr-2022", "May-2022"])

CLEAN_PASSBOOK = f"""\
EPF Member Passbook

Establishment ID / Name   BGBNG0099887000 / HELIOS ANALYTICS PVT LTD
Member ID                 BGBNG00998870000009876
Member Name               PRIYA MENON
Date of Birth             02-02-1995
Date of Joining (EPF)     01-06-2021
UAN                       100777666555

Wage Month    Employee Share    Employer Share    Pension Contribution
{_pb_months}
"""

CLEAN_SERVICE_HISTORY = """\
Service History

Member ID                     Establishment            Date of Joining   Date of Exit
BGBNG00998870000009876        HELIOS ANALYTICS PVT LTD   01-06-2021        31-05-2022
"""

CLEAN_BANK = """\
Statement of Account
Account Holder   PRIYA MENON

Date         Narration                                  Credit
05-07-2021   NEFT-HELIOS ANALYTICS-SALARY JUN            67680.00
05-08-2021   NEFT-HELIOS ANALYTICS-SALARY JUL            67680.00
06-09-2021   NEFT-HELIOS ANALYTICS-SALARY AUG            67680.00
"""


# ---------------------------------------------------------------------------

ACCOUNTS = {
    "100999888777": {
        "password": "rahul",
        "name": "Rahul Kumar Singh",
        "blurb": "Three employers, a wrong exit date, and money he does not know about.",
        "args": dict(text_26as=SAMPLE_26AS, passbooks=SAMPLE_PASSBOOKS,
                     service_history=SAMPLE_SERVICE_HISTORY, bank=SAMPLE_BANK),
    },
    "100777666555": {
        "password": "priya",
        "name": "Priya Menon",
        "blurb": "One employer, and every record agrees. This is what a clean answer looks like.",
        # Her name is spelled identically everywhere. Without this the analysis
        # falls back to the shared sample names and she inherits Rahul's four
        # spellings, which would report a name risk on a record built to have
        # none.
        "args": dict(text_26as=CLEAN_26AS, passbooks=[CLEAN_PASSBOOK],
                     service_history=CLEAN_SERVICE_HISTORY, bank=CLEAN_BANK,
                     names={"PAN / Form 26AS": "PRIYA MENON",
                            "EPFO passbook": "PRIYA MENON",
                            "Bank statement": "PRIYA MENON"}),
    },
}

# ---------------------------------------------------------------------------
# Past claims
# ---------------------------------------------------------------------------
# EPFO's own tracker shows a status word and no reason, so a member refiles the
# same broken claim and is rejected again. Rahul's history has that exact
# shape; Priya has never filed.

from datetime import date as _date  # noqa: E402

CLAIM_HISTORY = {
    "100999888777": [
        {"tracking_id": "100999888777401001", "form": "Form-19",
         "filed": _date(2021, 10, 8), "sent": _date(2021, 10, 9),
         "status": "Claim Rejected"},
        {"tracking_id": "100999888777404001", "form": "Form-10C",
         "filed": _date(2021, 10, 9), "sent": _date(2021, 10, 10),
         "status": "Claim Rejected"},
    ],
    "100777666555": [],
}


_cache: dict = {}


def authenticate(uan: str, password: str) -> str | None:
    """Return the account key, or None. Mock accounts, deliberately trivial."""
    acct = ACCOUNTS.get((uan or "").strip())
    if acct and (password or "").strip().lower() == acct["password"]:
        return uan.strip()
    return None


def build(uan: str):
    """The analysis behind a demo account. Deterministic, so it is cached."""
    if uan not in _cache:
        args = ACCOUNTS[uan]["args"]
        a = analyse(**args)
        # Carry the source documents, so typing in a service history here
        # re-reconciles the record the same way it does for a real upload.
        a.docs = {"26as": args["text_26as"], "passbook": args["passbooks"],
                  "service_history": args["service_history"], "bank": args["bank"]}
        a.claim_history = CLAIM_HISTORY.get(uan, [])
        _cache[uan] = a
    return _cache[uan]


def _self_test() -> int:
    checks = []

    rahul = build("100999888777")
    priya = build("100777666555")

    checks += [
        ("the demo record with defects reports them",
         rahul.result["blocking_count"] > 0),
        ("it was actually checked", rahul.checked),
        ("it is not claimable", not rahul.claimable),
        ("it finds a forgotten account", len(rahul.orphans) > 0),
    ]

    checks += [
        ("the clean record was checked too", priya.checked),
        # If this ever fails, the green verdict has stopped meaning anything.
        ("the clean record reports nothing blocking",
         priya.result["blocking_count"] == 0),
        ("the clean record is claimable", priya.claimable),
        ("the clean record invents no orphans", len(priya.orphans) == 0),
        ("the clean record has a balance", priya.total_balance > 0),
        ("the clean record reads its UAN", priya.identity["uan"] == "100777666555"),
        ("the two accounts are different people",
         rahul.identity["uan"] != priya.identity["uan"]),
    ]

    checks += [
        ("a correct password signs in",
         authenticate("100999888777", "rahul") == "100999888777"),
        ("a wrong password does not",
         authenticate("100999888777", "nope") is None),
        ("an unknown UAN does not",
         authenticate("000000000000", "rahul") is None),
        ("passwords are not case-sensitive",
         authenticate("100777666555", "PRIYA") == "100777666555"),
        ("surrounding whitespace is forgiven",
         authenticate("  100777666555  ", " priya ") == "100777666555"),
        ("an empty submission does not sign in",
         authenticate("", "") is None),
    ]

    print("=" * 64)
    print("  demo accounts")
    bad = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        bad += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad else f'{bad} FAILURE(S)'}")
    print("=" * 64)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
