"""
The screens, and the four capabilities that are ours.

The assertions that matter most here are the negative ones. A page that says
"all good" because it had nothing to look at, or a verdict on a record we never
checked, would be the same defect this product exists to prevent - dressed up
as a new feature.

Run:  python tests/test_screens.py
"""

from __future__ import annotations

import io
import re
import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from app.demo import build
from app.engine import SAMPLE_26AS, analyse
from app.server import create_app
from app import solver

BAD, GOOD = "100999888777", "100777666555"


def unchecked_token(c) -> str:
    """A session with 26AS only - no service history to test anything against."""
    up = c.post("/analyse", data={
        "f26as": (io.BytesIO(SAMPLE_26AS.encode()), "26as.txt")},
        content_type="multipart/form-data")
    return re.search(r"s=([A-Za-z0-9_-]+)", up.headers["Location"]).group(1)


def main() -> int:
    checks: list[tuple[str, bool]] = []
    c = create_app().test_client()
    bad_a, good_a = build(BAD), build(GOOD)
    un = unchecked_token(c)

    def get(path, tok):
        return c.get(f"{path}?s={tok}").get_data(as_text=True)

    ALL = ["/home", "/timeline", "/check", "/corrections", "/why-rejected",
           "/kyc", "/exit", "/joint-declaration", "/transfer", "/notifications",
           "/history", "/claim", "/track-old", "/passbook", "/profile"]

    # ---- renders in every account state -----------------------------------
    for tok, label in [(BAD, "defects"), (GOOD, "clean"), (un, "unchecked")]:
        for p in ALL:
            r = c.get(f"{p}?s={tok}")
            b = r.get_data(as_text=True)
            checks.append((f"{p} renders for a {label} record",
                           r.status_code == 200 and len(b) > 400
                           and "Traceback" not in b))

    # ---- the timeline -----------------------------------------------------
    tl = get("/timeline", BAD)
    checks += [
        ("the timeline draws evidence tracks", tl.count('class="tk"') >= 3),
        ("it names every source in a legend",
         all(s in tl for s in ("EPFO record", "PF contributions",
                               "Tax deducted", "Salary credits"))),
        ("it marks evidence falling after the recorded exit", "sg bad" in tl),
        ("it proposes a date to enter", "Date to enter" in tl),
        ("it states confidence in words, not a percentage",
         "confidence" in tl and "%" not in tl.split("confidence")[0][-40:]),
        ("a clean record proposes no new dates",
         "Date to enter" not in get("/timeline", GOOD)),
        # Absence of evidence must never render as agreement.
        ("an unchecked record is not told its dates match",
         "Matches the evidence" not in get("/timeline", un)),
    ]
    # The core claim has to be a fact, not a guess.
    for r in solver.reconstruct(bad_a):
        if r.exit_best:
            checks.append((f"proposed exit is never before the evidence ({r.key[:12]})",
                           r.exit_best >= r.last_seen))

    # ---- the validator twin ----------------------------------------------
    ck = get("/check", BAD)
    checks += [
        ("all fourteen gates are listed", len(solver.gates(bad_a)) == 14),
        ("each gate shows its code", "G01" in ck and "G14" in ck),
        ("a failing gate offers the page that fixes it", "fix this</a>" in ck),
        ("what EPFO holds privately is disclosed, not guessed",
         "not visible" in ck and "do not guess" in ck),
        ("a defective record fails at least one gate",
         solver.gate_summary(solver.gates(bad_a))[1] >= 1),
        ("a clean record fails none",
         solver.gate_summary(solver.gates(good_a))[1] == 0),
    ]

    # ---- blocking vs advisory --------------------------------------------
    # G11 once read the blocking-severity set, which never contains
    # ORPHAN_ACCOUNT, so the claim check said "all accounts linked" while the
    # transfer page said one was not. Two screens contradicting each other on
    # the same record is worse than either being wrong alone.
    gg = solver.gates(bad_a)
    orphan_gate = next(x for x in gg if x.code == "G11")
    has_orphan = any(getattr(o.assessment, "verdict", "") == "LIKELY"
                     for o in (bad_a.orphans or []))
    checks += [
        ("G11 agrees with the transfer page about unlinked accounts",
         (orphan_gate.status == "fail") == has_orphan),
        ("an unlinked account does not read as a refusal",
         orphan_gate.advisory is True),
        ("and the check page says so", "does not block settlement" in ck),
        ("the home verdict counts only blocking failures",
         f"{len(solver.blocking_failures(gg))} of {len(gg)} checks fail"
         in get("/home", BAD)),
        ("but the money left behind is still surfaced",
         "Money left behind" in get("/home", BAD)),
        ("every gate is accounted for in the summary",
         solver.gate_summary(gg)[0] + len(solver.blocking_failures(gg))
         + len(solver.advisory_failures(gg)) + solver.gate_summary(gg)[2] == 14),
        ("a clean record has no advisory failures either",
         not solver.advisory_failures(solver.gates(good_a))),
    ]

    # ---- the planner ------------------------------------------------------
    co = get("/corrections", BAD)
    p = solver.plan(bad_a)
    checks += [
        ("the plan is numbered and ordered", 'class="stp"' in co),
        ("it says how long the whole thing takes", f"{p.critical_days} days" in co),
        ("it warns that order matters", "Order matters" in co),
        ("it names what a blocked step is waiting for", "Blocked until step" in co),
        ("it quantifies the cost of the wrong order",
         f"{p.wasted_days} days wasted" in co),
        ("a clean record is not given busywork",
         "Nothing to correct" in get("/corrections", GOOD)),
        ("an unchecked record gets no plan",
         "has not been read" in get("/corrections", un)),
        ("every step names a route the member can actually take",
         all(s.route for s in p.steps)),
    ]

    # ---- retro-diagnosis --------------------------------------------------
    wr = get("/why-rejected", BAD)
    checks += [
        ("a past rejection is diagnosed", "Form-19" in wr),
        ("it points out EPFO gave no reason", "none given" in wr),
        ("it names a likely cause", "Correct the date of exit" in wr),
        ("it is labelled likely or possible, never certain",
         "Likely cause" in wr or "Possible cause" in wr),
        ("a record with no rejections claims none",
         "No rejected claims" in get("/why-rejected", GOOD)),
        ("the old tracker links to the diagnosis",
         "/why-rejected?s=" in get("/track-old", BAD)),
    ]

    # ---- Mark Exit --------------------------------------------------------
    ex = get("/exit", BAD)
    checks += [
        ("Mark Exit offers a date when one is missing", "Dates to enter" in ex),
        ("it warns the entry is one-shot", "One &mdash;" in ex),
        ("it is honest about what it does not cover",
         "already recorded and wrong" in ex),
        ("a clean record has nothing to mark", "Nothing to mark" in get("/exit", GOOD)),
        ("an unchecked record is not told it is clean",
         "Not yet known" in get("/exit", un)),
    ]

    # ---- the two-month wait, enforced rather than only described ---------
    # The page stated this rule for weeks without checking it, which would send
    # a member to a form EPFO turns away.
    from app.solver import Reconstructed, SELF_EXIT_WAIT_MONTHS, TODAY
    from datetime import date

    def missing(last):
        return Reconstructed(key="K", employer="E", member_id="M",
                             asserted_doj=date(2020, 1, 1), asserted_doe=None,
                             first_seen=date(2020, 1, 1), last_seen=last,
                             exit_best=last, sources=("EPF_CONTRIB",),
                             verdict="exit_missing")

    def _plus_two(d):
        y, m = d.year, d.month + SELF_EXIT_WAIT_MONTHS
        return date(y + (m - 1) // 12, (m - 1) % 12 + 1, 1)

    def months_ago(n):
        y, m = TODAY.year, TODAY.month - n
        while m < 1:
            m += 12
            y -= 1
        return date(y, m, 15)

    checks += [
        ("a contribution last month blocks self-service",
         not missing(months_ago(1)).self_service_ready),
        ("exactly two months opens it",
         missing(months_ago(SELF_EXIT_WAIT_MONTHS)).self_service_ready),
        ("an old contribution is obviously fine",
         missing(months_ago(30)).self_service_ready),
        ("a blocked one names the date it opens",
         missing(months_ago(1)).wait_until is not None),
        ("a ready one names no wait", missing(months_ago(6)).wait_until is None),
        # wait_until only exists while the wait is still running, so the
        # arithmetic has to be checked against a recent contribution.
        ("the wait date is two months after the last contribution",
         missing(months_ago(1)).wait_until
         == _plus_two(months_ago(1))),
        ("a contribution this month waits longest",
         missing(months_ago(0)).wait_until == _plus_two(months_ago(0))),
        # The demo record's evidence is years old, so the page still offers it.
        ("the demo record is still offered self-service",
         "You can do this yourself" in ex),
    ]

    # ---- Joint Declaration ------------------------------------------------
    jd = get("/joint-declaration", BAD)
    checks += [
        ("the JD mirrors the portal's three-column shape",
         "Entity" in jd and "Available details" in jd and "Changes requested" in jd),
        ("the correction arrives pre-filled", "Changes requested" in jd
         and "color:#2f9e44" in jd),
        ("it names the evidence that produced the date", "derived from" in jd),
        ("it lists what EPFO accepts", "Appointment letter" in jd),
        # The distinction that stops a member turning up with the wrong paper.
        ("it does not pass 26AS off as accepted evidence",
         "Not on the list" in jd),
        ("submitting issues a reference and says it went nowhere",
         "Submitted" in c.post(f"/joint-declaration?s={BAD}",
                               data={"key": "x"}).get_data(as_text=True)),
    ]

    # ---- KYC and contact --------------------------------------------------
    ky = get("/kyc", BAD)
    checks += [
        ("KYC does not vouch for what it cannot see",
         "held" in ky.lower() and "unknown" in ky.lower()),
        ("a name spelled four ways closes the gate", not bad_a.kyc_ok),
        ("a consistently spelled name opens it", good_a.kyc_ok),
    ]
    ct = get("/contact", BAD)
    checks.append(("contact names what an unverified number blocks",
                   "Auto-settlement" in ct and "UPI withdrawal" in ct))

    # ---- claim ------------------------------------------------------------
    checks += [
        ("a defective record is told it would be rejected",
         "would be rejected" in get("/claim", BAD)),
        ("a clean record reaches auto-settlement",
         "auto-settlement" in get("/claim", GOOD).lower()),
        ("an unchecked record gets no settlement verdict",
         "Not yet known" in get("/claim", un)),
        ("UPI and ATM are withheld on a defective record",
         "By UPI" not in get("/claim", BAD)),
        ("and offered on a clean one", "By UPI" in get("/claim", GOOD)),
        ("the Rs 5 lakh ceiling is stated", "5,00,000" in get("/claim", GOOD)),
    ]

    # ---- transfer ---------------------------------------------------------
    tr = get("/transfer", BAD)
    checks += [
        ("a forgotten account is offered", "not linked to your UAN" in tr),
        ("the Form 13 route is named", "One Member" in tr),
        ("a clean record has nothing left behind",
         "Nothing left behind" in get("/transfer", GOOD)),
    ]

    # ---- an empty result means two different things ----------------------
    # The transfer page read an empty orphan list as "nothing left behind",
    # but that list is also empty when there was no service history to look
    # at. Absence of evidence must never render as good news.
    un_tr = get("/transfer", un)
    un_cl = get("/claim", un)
    checks += [
        ("an unchecked record is not told its accounts are all accounted for",
         "Not yet known" in un_tr and "Nothing left behind" not in un_tr),
        ("it is offered the way to find out", "/history-entry?s=" in un_tr),
        ("a checked record with no orphans still says so plainly",
         "Nothing left behind" in get("/transfer", GOOD)),
        ("claim forms are not called Open on an unchecked record",
         "Not yet known" in un_cl and ">Open<" not in un_cl),
        ("but they are Open on a clean one", ">Open<" in get("/claim", GOOD)),
        ("and Blocked on a defective one", ">Blocked<" in get("/claim", BAD)),
        ("counts read as English, not account(s)",
         "account(s)" not in get("/transfer", BAD)
         and "account(s)" not in get("/home", BAD)),
    ]

    # ---- notifications ----------------------------------------------------
    nt = get("/notifications", BAD)
    checks += [
        ("alerts are listed", "Alerts" in nt),
        ("an email preview is shown", "Email preview" in nt),
        ("and it is clear nothing was sent",
         "not sent" in nt and "no outbound connection" in nt),
        ("a clean record is not sent busywork",
         "Nothing to report" in get("/notifications", GOOD)),
    ]

    # ---- one record, one set of numbers -----------------------------------
    # The alert counted every failing gate while the dashboard counted only the
    # blocking ones, so the same record was described as 3 checks in one place
    # and 2 in another.
    nb = len(solver.blocking_failures(solver.gates(bad_a)))
    checks += [
        ("the alert and the dashboard agree on the count",
         f"{nb} checks would reject" in nt
         and f"{nb} of 14 checks fail" in get("/home", BAD)),
        ("counts read as English, not check(s)", "check(s)" not in nt),
        ("money uses Indian digit grouping everywhere",
         "5,00,000" in ck and "500,000" not in ck),
        ("no card title is double-escaped",
         "&amp;mdash;" not in get("/transfer", BAD)
         and "&amp;middot;" not in get("/why-rejected", BAD)),
    ]

    # ---- PMVBRY, faithfully unhelpful -------------------------------------
    checks.append(("PMVBRY refuses you exactly as the real one does",
                   "not authorized to access" in get("/pmvbry", BAD)))

    # ---- sign-in ----------------------------------------------------------
    lb = c.get("/login").get_data(as_text=True)
    checks += [
        ("credentials are printed, not hidden", BAD in lb and "rahul" in lb),
        ("the two accounts give different verdicts",
         bad_a.claimable != good_a.claimable),
        ("a demo session survives without a stored token",
         c.get(f"/home?s={GOOD}").status_code == 200),
    ]

    print("=" * 70)
    print("  screens, and the four capabilities that are ours")
    bad_n = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        bad_n += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad_n else f'{bad_n} FAILURE(S)'}")
    print("=" * 70)
    return 1 if bad_n else 0


if __name__ == "__main__":
    _s.exit(main())
