"""
The check that needs no service history.

Every defect class before this one hung off EPFO's asserted service history -
the hardest of the four documents to obtain, and the one most members cannot
get when the portal is down. A member holding only their passbook and their
Form 26AS got a page that said "not yet known" about everything.

A contribution gap needs neither. If the Income Tax Department records an
employer deducting tax from your salary in a month, and your own PF passbook
shows nothing deposited that month, and you were demonstrably employed either
side of it, then money was withheld and did not arrive. No service history is
required to say that, because nothing is being compared to EPFO's claim about
you - only two records of what actually happened.

The tests below are mostly about the ways this could be WRONG, because a false
accusation against an employer is worse than a missed one.

Run:  python tests/test_gaps.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from datetime import date

import app.engine as E
from core.parsers import parse_passbook
from core.reconcile import Observation, Reconciler, _next_month

MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def pb(months, mid="BLBNG00123450000001234", est="ACME TECHNOLOGIES PVT LTD"):
    rows = "\n".join(f"{m}-2020      7800              2385              1250"
                     for m in months)
    return f"""EPF Member Passbook

Establishment ID / Name   BLBNG0012345000 / {est}
Member ID                 {mid}
Member Name               RAHUL K SINGH
Date of Birth             14-08-1992
Date of Joining (EPF)     01-04-2020
UAN                       100999888777

Wage Month    Employee Share    Employer Share    Pension Contribution
{rows}
"""


def obs(emp, months, source):
    return [Observation(emp, date(2020, m, 28), source) for m in months]


def run(observations):
    return Reconciler(observations, [], date(2021, 6, 1)).run()


def gaps(res):
    return [c for c in res["contradictions"] if c["kind"] == "CONTRIBUTION_GAP"]


def main() -> int:
    checks = []

    # ---- the core comparison ---------------------------------------------
    # Tax deducted Apr-Sep; PF deposited every month except Jun and Jul.
    r = run(obs("acme", [4, 5, 6, 7, 8, 9], "TDS_26AS")
            + obs("acme", [4, 5, 8, 9], "EPF_CONTRIB"))
    g = gaps(r)
    checks += [
        ("a gap between two contributions is found", len(g) == 1),
        ("both missing months are counted", "2 months" in g[0]["detail"]),
        ("consecutive months collapse into one finding", len(g) == 1),
        ("the run is described as a span", "2020-06 to 2020-07" in g[0]["detail"]),
        ("it blocks a claim", g[0]["severity"] == "BLOCKING"),
        ("it routes to a grievance, not the employer's goodwill",
         "EPFiGMS" in g[0]["correction_route"]),
        ("it cites the tax record as evidence",
         any("TDS_26AS@2020-06" in e for e in g[0]["evidence"])),
        ("it says the money was withheld, not that service broke",
         "not a break in service" in g[0]["detail"]),
    ]

    # Two separate gaps must not be merged into one span.
    r2 = run(obs("acme", [4, 5, 6, 7, 8, 9], "TDS_26AS")
             + obs("acme", [4, 6, 8, 9], "EPF_CONTRIB"))
    d2 = gaps(r2)[0]["detail"]
    checks += [
        ("non-consecutive gaps are listed separately", "2020-05, 2020-07" in d2),
        ("and counted correctly", "2 months" in d2),
    ]

    # ---- the ways this could be wrong ------------------------------------
    checks += [
        # March PF is routinely deposited in April, and a final settlement
        # produces TDS after the last contribution. At the edges a missing
        # month is ordinary; between two contributions it is not.
        ("a trailing TDS month is not a gap",
         gaps(run(obs("acme", [4, 5, 6, 7], "TDS_26AS")
                  + obs("acme", [4, 5], "EPF_CONTRIB"))) == []),
        ("a leading TDS month is not a gap",
         gaps(run(obs("acme", [4, 5, 6, 7], "TDS_26AS")
                  + obs("acme", [6, 7], "EPF_CONTRIB"))) == []),
        # An employer with no passbook may simply not be EPF-covered. That is
        # a different finding and cannot be made without the service history.
        ("an employer with no passbook is not accused",
         gaps(run(obs("nopb", [4, 5, 6], "TDS_26AS"))) == []),
        ("an employer with no 26AS is not accused",
         gaps(run(obs("nopf", [4, 5, 6], "EPF_CONTRIB"))) == []),
        ("a fully reconciled employer produces nothing",
         gaps(run(obs("acme", [4, 5, 6], "TDS_26AS")
                  + obs("acme", [4, 5, 6], "EPF_CONTRIB"))) == []),
        ("more PF months than TDS months is not a gap",
         gaps(run(obs("acme", [5], "TDS_26AS")
                  + obs("acme", [4, 5, 6], "EPF_CONTRIB"))) == []),
        ("a bank statement alone cannot accuse anyone",
         gaps(run(obs("acme", [4, 5, 6], "BANK_SALARY"))) == []),
        # One employer's gap must never be attributed to another.
        ("employers are kept separate",
         len(gaps(run(obs("a", [4, 5, 6], "TDS_26AS") + obs("a", [4, 6], "EPF_CONTRIB")
                      + obs("b", [4, 5, 6], "TDS_26AS")
                      + obs("b", [4, 5, 6], "EPF_CONTRIB")))) == 1),
    ]

    checks += [
        ("December rolls into January", _next_month("2020-12") == "2021-01"),
        ("months are zero-padded", _next_month("2020-08") == "2020-09"),
    ]

    # ---- the mid-line establishment name ---------------------------------
    # Found on real passbooks: the establishment sits mid-line after a pipe,
    # so a parser requiring the line to START with the word found nothing - and
    # an employer with no name cannot be matched to the same employer in 26AS,
    # which silently disabled this entire check on every real file.
    real = pb(["Apr", "May"]).replace(
        "Establishment ID / Name   BLBNG0012345000 / ACME TECHNOLOGIES PVT LTD",
        "EPFO Portal user@epfo | Establishment ID/Name BLBNG0012345000 / ACME TECHNOLOGIES PVT LTD")
    parsed = parse_passbook(real)
    checks += [
        ("a mid-line establishment name is read",
         parsed["establishment"] == "ACME TECHNOLOGIES PVT LTD"),
        ("the establishment code is read too",
         parsed["establishment_code"] == "BLBNG0012345000"),
        ("a line-start establishment still works",
         parse_passbook(pb(["Apr"]))["establishment"] == "ACME TECHNOLOGIES PVT LTD"),
        ("the header word is not mistaken for a name",
         not (parse_passbook(pb(["Apr"]))["establishment"] or "").lower().startswith("id")),
    ]

    # ---- end to end, with no service history at all -----------------------
    gappy = E.SAMPLE_PASSBOOKS[0]
    for m in ("Aug-2020", "Sep-2020"):
        gappy = "\n".join(l for l in gappy.splitlines() if not l.startswith(m))
    a = E.analyse(text_26as=E.SAMPLE_26AS, passbooks=[gappy, E.SAMPLE_PASSBOOKS[1]],
                  service_history="", bank="")
    kinds = [c["kind"] for c in a.result["contradictions"]]
    checks += [
        ("the gap is found with no service history", "CONTRIBUTION_GAP" in kinds),
        ("dates are still reported as unchecked", not a.dates_checked),
        ("contributions are reported as checked", a.contributions_checked),
        # Both must remain true at once: a real finding, and an honest admission
        # that a different question was never asked.
        ("a real finding does not imply the dates were checked", not a.checked),
        ("no date findings are invented", "MISSING_EXIT" not in kinds),
        ("no orphan is invented either", "ORPHAN_ACCOUNT" not in kinds),
    ]

    clean = E.analyse(text_26as=E.SAMPLE_26AS, passbooks=E.SAMPLE_PASSBOOKS,
                      service_history="", bank="")
    checks += [
        ("a reconciling record reports no gap",
         "CONTRIBUTION_GAP" not in [c["kind"] for c in clean.result["contradictions"]]),
        ("and still admits the dates were not checked", not clean.dates_checked),
        ("but does say contributions were", clean.contributions_checked),
    ]

    # The pages must say both things without either drowning the other.
    from app.server import create_app
    import io, re
    c = create_app().test_client()
    up = c.post("/analyse", data={
        "f26as": [(io.BytesIO(E.SAMPLE_26AS.encode()), "26as.txt")],
        "passbook": [(io.BytesIO(gappy.encode()), "a.txt"),
                     (io.BytesIO(E.SAMPLE_PASSBOOKS[1].encode()), "b.txt")]},
        content_type="multipart/form-data")
    tok = re.search(r"s=([A-Za-z0-9_-]+)", up.headers["Location"]).group(1)
    home = c.get(f"/home?s={tok}").get_data(as_text=True)
    rec = c.get(f"/record?s={tok}").get_data(as_text=True)
    checks += [
        ("the verdict is No, not 'not yet known'", "<h1>No</h1>" in home),
        ("the home page still says dates were not checked",
         "not</strong> checked" in home),
        ("the finding is on the record page in plain language",
         "deducted tax but deposited no PF" in rec),
        ("a clean-contribution record says so rather than staying silent",
         "every month an employer deducted tax" in
         c.get("/home?s=" + re.search(r"s=([A-Za-z0-9_-]+)", c.post(
             "/analyse", data={
                 "f26as": [(io.BytesIO(E.SAMPLE_26AS.encode()), "26as.txt")],
                 "passbook": [(io.BytesIO(p.encode()), f"p{i}.txt")
                              for i, p in enumerate(E.SAMPLE_PASSBOOKS)]},
             content_type="multipart/form-data").headers["Location"]).group(1)
         ).get_data(as_text=True)),
    ]

    print("=" * 70)
    print("  contribution gaps - the check that needs no service history")
    bad = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        bad += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad else f'{bad} FAILURE(S)'}")
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    _s.exit(main())
