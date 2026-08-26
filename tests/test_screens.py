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


def _load_un(client, tok):
    """The Analysis behind an unchecked session."""
    from app.server import _load
    return _load(tok)


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
         "not visible" in ck.lower() and "rather than guessing" in ck),
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
        ("and the check page says so", "Does not block settlement" in ck),
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

    # ---- an absent employer means two different things --------------------
    # Found on a real record: with no service history every employer was
    # labelled "Not linked to your UAN" while the transfer page, reading the
    # same record, said "not yet known". One of them was accusing EPFO of
    # losing accounts on no evidence.
    un_recs = solver.reconstruct(_load_un(c, un))
    checks += [
        ("with no service history nothing is called unlinked",
         all(r.verdict != "unlinked" for r in un_recs)),
        ("it is called unchecked instead",
         all(r.verdict == "unchecked" for r in un_recs) if un_recs else True),
        ("and the timeline says so", "Not yet checked" in get("/timeline", un)),
        ("the timeline and the transfer page agree",
         ("Not linked" in get("/timeline", un))
         == ("not linked" in get("/transfer", un))),
        # With a history in hand it is a real signal again.
        ("a genuine orphan is still called unlinked",
         any(r.verdict == "unlinked" for r in solver.reconstruct(bad_a))),
    ]

    # ---- a failing gate with no correction route --------------------------
    # G14 (over the auto-settlement ceiling) has no route, so the plan is
    # empty and the page offered "fix it in 0 days" plus a button to nothing.
    class _NoPlan:
        result = {"contradictions": []}
        orphans = []
    checks.append(("an empty plan reports no duration at all",
                   solver.plan(_NoPlan()).critical_days == 0
                   and not solver.plan(_NoPlan()).steps))
    # "40 days" contains "0 days", so the check needs a boundary.
    checks.append(("and the home page never prints a zero-day estimate",
                   not re.search(r"0 days", get("/home", BAD))))
    checks.append(("a record whose only failure has no route gets no estimate",
                   "Estimated time to fix" not in get("/home", un)))

    # ---- what a missing document costs, said out loud ---------------------
    checks += [
        ("a partial record says which questions went unasked",
         "What we could not check" in get("/home", un)),
        ("and names the document that would answer them",
         "service history" in get("/home", un)),
        ("a complete record is not nagged",
         "What we could not check" not in get("/home", GOOD)),
    ]

    # ---- the planner ------------------------------------------------------
    co = get("/corrections", BAD)
    p = solver.plan(bad_a)
    checks += [
        ("the plan is numbered and ordered", 'class="stp"' in co),
        ("it says how long the whole thing takes", f"{p.critical_days} days" in co),
        ("it warns that order matters", "Order matters" in co),
        ("it names what a blocked step is waiting for", "Blocked until step" in co),
        ("the cost of the wrong order is stated where the warning is",
         f"costs {p.blocked_steps[0].days} days" in co),
        ("timing answers when it ends, not how clever the plan is",
         "All clear by" in co and "days wasted" not in co),
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

    # ---- pages must read fields that exist --------------------------------
    # Three pages read attributes that were never on the object - KycItem.value,
    # Account.entries - so they rendered a literal "&mdash;" or claimed there
    # were no contributions on a record holding fifteen months of them. Nothing
    # failed loudly, which is what made it survive.
    pb = get("/passbook", BAD)
    pbl = get("/passbook-lite", BAD)
    acc = next(x for x in bad_a.accounts if not x.orphan)
    checks += [
        ("contribution rows reach the Account", len(acc.rows) > 0),
        ("the full passbook shows them", "Wage Month" in pb),
        ("with real amounts, not blanks", "&#8377;" in pb),
        ("passbook lite shows five at most",
         pbl.count("<tr>") <= 6),  # header + 5
        ("and it is not empty on a record with contributions",
         "No contributions" not in pbl),
        ("balances are totalled across accounts",
         "Across all accounts" in pb),
        # The defect is visible on this page, so it is named here too.
        ("a contradicted exit date is flagged on the passbook",
         "Contributions continue past this date" in pb),
        ("a clean record is not flagged",
         "Contributions continue past this date" not in get("/passbook", GOOD)),
        ("no page renders a double-escaped entity",
         not any("&amp;mdash;" in get(x, BAD)
                 for x in ("/kyc", "/passbook", "/contact", "/profile"))),
    ]

    # ---- status reads as words, not punctuation --------------------------
    # A tick, a cross and a bare question mark are checklist vocabulary. This
    # is a document about somebody's money.
    checks += [
        ("claim check labels status in words",
         "Action needed" in ck and "Not visible" in ck and "Pass" in ck),
        ("no raw glyphs are used as status", "&#10003;" not in ck
         and "&#10007;" not in ck),
        ("the advisory item is labelled differently from a blocker",
         "Worth doing" in ck),
        ("KYC uses the same vocabulary",
         "Not visible" in get("/kyc", BAD)),
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
        # Submitting now opens a tracked correction rather than printing a
        # reference and forgetting it. A malformed post must still not 500.
        # An orphan reconstruction carries an empty member ID, so an empty
        # mid once matched it and opened a correction against a forgotten
        # account nobody asked to correct.
        ("a submission with no member id is refused cleanly",
         c.post(f"/joint-declaration?s={BAD}",
                data={"key": "x"}).status_code == 400),
        ("an empty member id does not match the orphan",
         c.post(f"/joint-declaration?s={BAD}",
                data={"mid": "", "doc": "Appointment letter"}).status_code == 400),
        ("an unknown member id is refused",
         c.post(f"/joint-declaration?s={BAD}",
                data={"mid": "ZZZZ", "doc": "Appointment letter"}).status_code == 400),
    ]

    # ---- KYC and contact --------------------------------------------------
    ky = get("/kyc", BAD)
    checks += [
        ("KYC does not vouch for what it cannot see",
         "Not visible" in ky and "cannot see your bank KYC" in ky),
        ("and it shows the note rather than an empty dash",
         "&amp;mdash;" not in ky and "character for character" in ky),
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

    # ---- the correction loop ---------------------------------------------
    # The half that was missing: submit, get checked, see what the record looks
    # like if EPFO accepts it. Three things must stay true throughout - we
    # never claim a document was verified, nothing implies EPFO received
    # anything, and no state means rejected.
    from app import corrections as CO

    mid = next(r.member_id for r in solver.reconstruct(bad_a)
               if r.exit_best and r.verdict == "exit_wrong")
    sub = c.post(f"/joint-declaration?s={BAD}",
                 data={"mid": mid, "doc": "Appointment letter"})
    checks.append(("submitting a correction redirects to it",
                   sub.status_code == 303
                   and "/correction/" in sub.headers.get("Location", "")))
    ctok = re.search(r"s=([A-Za-z0-9_-]+)", sub.headers["Location"]).group(1)
    cref = re.search(r"/correction/(\w+)", sub.headers["Location"]).group(1)
    cpage = get(f"/correction/{cref}", ctok)

    checks += [
        ("the correction is checked, not the document",
         "Checked" in cpage and "We cannot read your appointment letter" in cpage),
        ("nothing on it says the document was verified",
         "Verified" not in cpage),
        ("nothing implies EPFO received it",
         "EPFO. We do not submit anything for you." in cpage),
        ("all four checks are shown",
         len(re.findall(r'<ul class="gt">(.*?)</ul>', cpage, re.S)[0]
             .split("<li")) - 1 == 4),
        ("it names where the member files it themselves",
         "Manage &rarr; Joint Declaration" in cpage),
        ("it quotes EPFO's limit as EPFO's", "published limit" in cpage),
        ("a demo account is not mutated by one visitor",
         "Corrections you have started" not in get("/corrections", BAD)),
        ("but the editor's own session carries it",
         "Corrections you have started" in get("/corrections", ctok)),
    ]

    # A document EPFO does not accept is returned, never refused.
    bad_doc = c.post(f"/joint-declaration?s={BAD}",
                     data={"mid": mid, "doc": "Form 26AS"})
    btok = re.search(r"s=([A-Za-z0-9_-]+)", bad_doc.headers["Location"]).group(1)
    bref = re.search(r"/correction/(\w+)", bad_doc.headers["Location"]).group(1)
    bpage = get(f"/correction/{bref}", btok)
    checks += [
        ("an unaccepted document is caught", "One more thing needed" in bpage),
        ("it is returned, never rejected",
         "reject" not in bpage.lower().split("<main>")[-1]),
        ("and it names the accepted documents instead",
         "appointment letter" in bpage.lower()),
        ("an unready correction cannot be previewed",
         "Nothing ready to preview" in get("/outcome", btok)),
    ]

    # The payoff, and it is genuinely recomputed rather than flagged.
    c.post(f"/joint-declaration?s={ctok}",
           data={"mid": next(r.member_id for r in solver.reconstruct(bad_a)
                             if r.verdict == "exit_missing"),
                 "doc": "Relieving letter or final payslip"})
    oc = get("/outcome", ctok)
    checks += [
        ("the preview is labelled a preview", "This is a preview" in oc),
        ("it says nothing was submitted", "Nothing has been submitted" in oc),
        ("it says the result was recomputed, not set",
         "not a flag we set" in oc),
        ("the claim clears", "Claim would settle" in oc),
        ("and it names which checks changed", "G08" in oc and "G09" in oc),
        ("the forms go from blocked to open",
         oc.count(">Blocked<") == 3 and oc.count(">Open<") == 3),
        # Correcting a date must not quietly make the forgotten account vanish.
        ("what the correction does not fix is still surfaced",
         "Still worth doing" in oc),
        ("a clean record has nothing to preview",
         "Nothing ready to preview" in get("/outcome", GOOD)),
        ("an unknown reference does not 500",
         c.get(f"/correction/NOSUCH?s={ctok}").status_code == 200),
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

    # ---- recovering one forgotten account --------------------------------
    # The engine produced a four-step plan and a drafted trace request from the
    # start and nothing rendered either, so the transfer page named money the
    # member had no way to reach.
    tan = next(o.candidate.tan for o in bad_a.orphans
               if o.assessment.verdict == "LIKELY")
    rc = get(f"/recover/{tan}", BAD)
    checks += [
        ("the transfer page links to a recovery page",
         f"/recover/{tan}?s=" in get("/transfer", BAD)),
        ("the recovery page names the establishment code",
         "MHBAN0026403000" in rc),
        ("it gives an ordered plan", 'class="stp"' in rc),
        ("it says which step is blocked and by what", "Needs member ID" in rc),
        ("it drafts the letter", "Regional Provident Fund Commissioner" in rc),
        ("the letter carries its evidence annexure", 'class="ann"' in rc),
        ("it labels the balance a range, with the assumption stated",
         "Range, not a figure" in rc and "basic pay assumed" in rc),
        ("it says who sends the letter", "We do not send it for you" in rc),
        ("the letter is printable", 'class="doc"' in rc),
        ("an unknown account does not 500",
         c.get(f"/recover/NOSUCH?s={BAD}").status_code == 200),
        ("and says so rather than inventing one",
         "No such account" in get("/recover/NOSUCH", BAD)),
    ]

    # ---- Hindi on the findings, as the docs have always claimed -----------
    import re as _re
    def _dev(s):
        return _re.findall(r"[ऀ-ॿ]+", s)
    checks += [
        ("the blocked verdict carries Hindi", bool(_dev(get("/home", BAD)))),
        ("so does the clean one", bool(_dev(get("/home", GOOD)))),
        ("and the unchecked one", bool(_dev(get("/home", un)))),
        ("every timeline finding carries Hindi",
         len(_dev(get("/timeline", BAD))) >= 3),
        ("Hindi is marked for a screen reader", 'lang="hi"' in get("/home", BAD)),
        # Translating navigation would add weight to every page and
        # half-translated chrome reads worse than none.
        ("navigation is left in one language",
         not _dev(get("/home", BAD).split("<main>")[0])),
    ]

    # ---- sign-in must be usable, not merely correct -----------------------
    # The credentials were on the page all along, in a grey card below the
    # form. Technically printed; practically invisible to someone who lands on
    # a login screen and does not scroll.
    lb2 = c.get("/login").get_data(as_text=True)
    checks += [
        ("each account has a button that signs you in",
         lb2.count("Sign in as") == 2),
        ("the credentials are still readable",
         "rahul" in lb2 and "priya" in lb2),
        ("one click actually works",
         c.post("/login", data={"uan": BAD, "password": "rahul"}).status_code
         == 303),
        ("typing them still works too", 'id="password"' in lb2),
        ("and the accounts are described, not just listed",
         "wrong exit date" in lb2),
    ]

    # ---- the two money questions -----------------------------------------
    from core import money as M
    cl = get("/claim", GOOD)
    tenD = get("/claim-10d", BAD)
    checks += [
        ("the claim page answers what you would receive",
         "If you withdrew all of it today" in cl),
        ("it shows the deduction, not just the balance",
         "Tax deducted" in cl),
        ("it explains why that rate applies", "section 192A" in cl),
        ("it says what linking a PAN is worth", "Linking it drops" in cl),
        ("and offers waiting as the alternative", "removes the deduction" in cl),
        ("it is labelled an estimate",
         "EPFO calculates the final figure" in cl),
        ("the pension page gives a figure, not a status",
         "a month" in tenD),
        ("it counts the shortfall in months", "105 months" in tenD),
        ("it shows what full service would pay",
         "Worth at ten years" in tenD),
        ("it offers Form 10C under ten years", "10C" in tenD),
        ("it admits service elsewhere counts too",
         "floor rather than a ceiling" in tenD),
        # The arithmetic itself is owned by core/money.py's self-test; what
        # matters here is that the page shows the number it computed.
        ("the page shows the figure the module computed",
         f"{M.pension_estimate(bad_a.service_months).at_full_service:,.0f}"
         .replace(",", "") in tenD.replace(",", "")),
    ]

    # ---- one action, not a list -------------------------------------------
    hm = get("/home", BAD)
    checks += [
        ("the dashboard names a single next action", "Do this next" in hm),
        ("it prefers what the member can do alone",
         solver.next_step(bad_a).href == "/exit"),
        ("an unchecked record is sent to the one thing that unblocks it",
         solver.next_step(_load_un(c, un)).href == "/history-entry"),
        ("a clean record is given nothing to do",
         solver.next_step(good_a) is None
         and "Do this next" not in get("/home", GOOD)),
    ]

    # ---- the record, on paper ---------------------------------------------
    pr = get("/print", BAD)
    checks += [
        ("the summary carries the member's identity", "Prepared" in pr),
        ("it shows EPFO's record against the evidence",
         "Evidence runs to" in pr),
        ("it lists the corrections being asked for",
         "Corrections requested" in pr),
        ("with the evidence behind each one", "Evidence relied on" in pr),
        ("and the order they must happen in", "after steps 1 and 2" in pr),
        ("it disclaims itself", "Not issued by EPFO" in pr),
        ("it is printable", 'class="doc"' in pr),
        # Written this afternoon and it reintroduced the oldest bug here.
        ("an unchecked record is not told nothing is blocking",
         "Nothing is blocking" not in get("/print", un)),
        ("it says which check could not run",
         "could not run" in get("/print", un)),
        ("a clean record says so plainly",
         "Nothing is blocking" in get("/print", GOOD)),
    ]

    # ---- what a forgotten account has grown into --------------------------
    rc2 = get(f"/recover/{tan}", BAD)
    est = next(o.assessment.estimate for o in bad_a.orphans
               if o.assessment.verdict == "LIKELY")
    checks += [
        ("the recovery page separates contributions from growth",
         "You contributed" in rc2 and "Interest over" in rc2),
        ("interest is the larger part after thirteen years",
         est.interest_low > est.principal_low),
        ("principal and interest reconcile to the total",
         est.principal_low + est.interest_low == est.low),
        ("the years are counted, not asserted", est.years > 1),
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
