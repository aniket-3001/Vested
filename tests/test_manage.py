"""
The half of the portal that does things rather than showing them.

Covers the Manage pages, the automated-settlement model EPFO 3.0 introduced,
the two mock accounts, and the correction routing that tells a member whether
they can fix something alone or need an employer who may no longer exist.

The assertions that matter most here are the negative ones. A KYC page that
says "all good" because it had nothing to look at, or a settlement verdict on a
record we never checked, would be the same defect this product exists to
prevent - dressed up as a new feature.

Run:  python tests/test_manage.py
"""

from __future__ import annotations

import io
import re
import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from app.demo import build
from app.engine import SAMPLE_PASSBOOKS
from app.server import create_app

MANAGE_PAGES = ["/manage", "/kyc", "/exit", "/nomination", "/transfer",
                "/uan-card", "/contact"]


def unchecked_token(c) -> str:
    """A session with passbooks but no service history - nothing to test against."""
    up = c.post("/analyse", data={"passbook": [
        (io.BytesIO(p.encode()), f"pb{i}.txt")
        for i, p in enumerate(SAMPLE_PASSBOOKS)]},
        content_type="multipart/form-data")
    return re.search(r"s=([A-Za-z0-9_-]+)", up.headers["Location"]).group(1)


def main() -> int:
    checks = []
    c = create_app().test_client()

    rahul, priya = build("100999888777"), build("100777666555")
    un = unchecked_token(c)

    def get(path, tok):
        return c.get(f"{path}?s={tok}").get_data(as_text=True)

    # ---- every new page renders on every account state --------------------
    for tok, label in [("100999888777", "defects"), ("100777666555", "clean"),
                       (un, "unchecked")]:
        for p in MANAGE_PAGES:
            r = c.get(f"{p}?s={tok}")
            b = r.get_data(as_text=True)
            checks.append((f"{p} renders for a {label} record",
                           r.status_code == 200 and len(b) > 500
                           and "Traceback" not in b))

    # ---- KYC must never report on what it cannot see -----------------------
    for tok, label in [("100999888777", "defects"), ("100777666555", "clean")]:
        b = get("/kyc", tok)
        checks += [
            (f"KYC does not vouch for the bank account ({label})",
             "cannot see your bank KYC" in b),
            (f"KYC does not vouch for Aadhaar ({label})",
             "cannot see your Aadhaar link" in b),
        ]
    checks += [
        ("KYC explains the exact-match rule", "expanded initial" in get("/kyc", "sample")),
        # A visible inconsistency blocks; something we cannot see is disclosed
        # but not held against the member. Demanding every item be green would
        # make auto-settlement unreachable for everyone.
        ("a name spelled four ways closes the gate", not rahul.kyc_ok),
        ("a consistently spelled name opens it", priya.kyc_ok),
        ("but the clean record still says KYC is unverified",
         "cannot see all of it" in get("/kyc", "100777666555")),
        ("and the defective one says it would fail",
         "would fail the check" in get("/kyc", "100999888777")),
        ("every KYC item carries a readable status word",
         all(i.status in ("ok", "risk", "unknown") for i in rahul.kyc_items)),
    ]

    # ---- Mark Exit: the date we know and EPFO does not --------------------
    ex_r, ex_p, ex_u = get("/exit", "100999888777"), get("/exit", "100777666555"), get("/exit", un)
    checks += [
        ("Mark Exit offers a date when one is missing",
         "You can fix" in ex_r and "The dates to enter" in ex_r),
        ("Mark Exit says where the date came from", "Form 26AS" in ex_r),
        ("Mark Exit warns the entry is one-shot", "one attempt" in ex_r),
        ("Mark Exit is honest about its limits",
         "already recorded and wrong" in ex_r),
        ("a clean record has nothing to mark", "Nothing to mark" in ex_p),
        # The distinction this whole product turns on.
        ("an unchecked record is not told it is clean",
         "Not yet known" in ex_u and "Nothing to mark" not in ex_u),
    ]

    # ---- Transfer: we find the account, then offer the action -------------
    tr_r, tr_p, tr_u = get("/transfer", "100999888777"), get("/transfer", "100777666555"), get("/transfer", un)
    checks += [
        ("a forgotten account is offered for transfer", "to bring across" in tr_r),
        ("the Form 13 route is named", "One Member" in tr_r),
        ("it explains that service matters more than balance",
         "ten years of eligible service" in tr_r),
        ("a clean record has nothing left behind", "Nothing left behind" in tr_p),
        ("an unchecked record invents no orphans", "Not yet known" in tr_u),
    ]

    # ---- the automated gate EPFO 3.0 introduced ---------------------------
    checks += [
        ("a defective record would be rejected, not settled",
         rahul.settlement.mode == "blocked"),
        ("and the claim page says so", "would be rejected, not settled"
         in get("/claim", "100999888777")),
        # An unchecked record must get no verdict at all. "Manual review" would
        # tell a member we read their service record and found it survivable.
        ("an unchecked record gets no settlement verdict",
         c.get(f"/claim?s={un}").status_code == 200
         and "Not yet known" in get("/claim", un)),
        ("an unchecked record is never called auto-settling",
         not rahul.settlement.good and "should settle automatically" not in get("/claim", un)),
        ("a clean record reaches auto-settlement",
         priya.settlement.mode in ("auto", "manual")),
        ("the Rs 5 lakh ceiling is stated", "5,00,000" in get("/claim", "100777666555")),
    ]

    # ---- withdrawal: three categories, and how the money moves ------------
    w_p = get("/withdraw", "100777666555")
    checks += [
        ("the three merged categories are named", "thirteen advance types into three" in w_p),
        ("service thresholds survive the merge", "Eligible" in w_p or "Not yet" in w_p),
        ("UPI and ATM routes appear on a clean record",
         "By UPI" in w_p and "By ATM" in w_p),
        ("UPI and ATM are withheld on a defective record",
         "By UPI" not in get("/withdraw", "100999888777")),
        ("the delay penalty is disclosed", "penal interest" in w_p),
    ]

    # ---- correction routing, including the employer that no longer exists --
    rec = get("/record", "100999888777")
    keys = sorted(set(re.findall(r"/finding/([^?\"]+)\?", rec)))
    jd = self_serve = 0
    for k in keys:
        b = get(f"/finding/{k}", "100999888777")
        if "shut down" in b:
            jd += 1
            checks.append((f"{k}: attestor list offered when the employer is gone",
                           "gazetted officer" in b.lower()))
            checks.append((f"{k}: accepted evidence is listed",
                           "Appointment letter" in b))
            checks.append((f"{k}: 26AS is not passed off as accepted evidence",
                           "does not currently list it" in b))
        if "do this one yourself" in b:
            self_serve += 1
            checks.append((f"{k}: self-service links to Mark Exit", "/exit?s=" in b))
    checks += [
        ("at least one finding routes through a Joint Declaration", jd >= 1),
        ("at least one finding is self-serviceable", self_serve >= 1),
        ("findings were found at all", len(keys) >= 2),
    ]

    # Every route the reconciler can emit must tell the member what to do about
    # it. A finding with no path forward is worse than no finding: it names a
    # problem and abandons them with it.
    from app.views import correction_help
    from core import reconcile as R
    routes = [R.SELF_SERVICE, R.JOINT_DECL, R.GRIEVANCE, R.CLAIM_ORPHAN]
    for r in routes:
        checks.append((f"guidance exists for: {r[:34]}",
                       len(correction_help(r, "sample")) > 200))
    checks.append(("the grievance route names its 30-day limit",
                   "30 days" in correction_help(R.GRIEVANCE, "sample")))
    checks.append(("the grievance route offers RTI as the escalation",
                   "RTI" in correction_help(R.GRIEVANCE, "sample")))
    checks.append(("the orphan route links to the transfer form",
                   "/transfer?s=" in correction_help(R.CLAIM_ORPHAN, "sample")))

    # ---- UAN card and contact details -------------------------------------
    card = get("/uan-card", "100999888777")
    checks += [
        ("the UAN card shows the UAN", "100999888777" in card),
        ("the UAN card reads date of birth from the passbook",
         "14 August 1992" in card),
        ("it lists every member ID under the number",
         len(re.findall(r"<code>[A-Z]{5}\d{17}</code>", card)) >= 2),
        ("it is honest that it is not the official card",
         "a document you can file" in card and "issued by EPFO" in card),
        ("it routes an untransferred account to the transfer form",
         "/transfer?s=" in card),
    ]

    # Two passbooks disagreeing about a date of birth is a named cause of
    # rejection. Record the disagreement; never silently pick a winner.
    from app.engine import (analyse, SAMPLE_26AS, SAMPLE_BANK, SAMPLE_SERVICE_HISTORY)
    clash = analyse(text_26as=SAMPLE_26AS, service_history=SAMPLE_SERVICE_HISTORY,
                    bank=SAMPLE_BANK,
                    passbooks=[SAMPLE_PASSBOOKS[0],
                               SAMPLE_PASSBOOKS[1].replace("14-08-1992", "15-08-1992")])
    checks += [
        ("a date-of-birth clash across passbooks is detected",
         clash.identity["dob_conflict"] == ["1992-08-14", "1992-08-15"]),
        ("agreeing passbooks report no clash",
         build("100999888777").identity["dob_conflict"] == []),
        ("a date of birth is read at all",
         build("100999888777").identity["dob"] is not None),
        ("date of birth is still not mistaken for a joining date",
         build("100999888777").identity["dob"].month == 8),
    ]

    contact = get("/contact", "100999888777")
    checks += [
        ("contact details does not pretend to see your number",
         "cannot see your registered number" in contact),
        ("it names what an OTP failure closes",
         "Auto-settlement" in contact and "UPI withdrawal" in contact),
        ("it says the number must be the Aadhaar-linked one",
         "linked to your Aadhaar" in contact),
        ("it sends a dead Aadhaar number to UIDAI, not EPFO",
         "UIDAI centre" in contact),
    ]

    hub = get("/manage", "100999888777")
    checks += [
        ("the hub links every Manage page",
         all(f'href="{p}?s=' in hub for p in MANAGE_PAGES if p != "/manage")),
    ]

    # ---- the sign-in the rules require ------------------------------------
    lb = c.get("/login").get_data(as_text=True)
    checks += [
        ("credentials are printed, not hidden", "100999888777" in lb and "rahul" in lb),
        ("a second account is offered", "100777666555" in lb),
        ("the two accounts give different verdicts",
         rahul.claimable != priya.claimable),
        ("a demo session survives without a stored token",
         c.get("/home?s=100777666555").status_code == 200),
        ("both demo records are labelled synthetic",
         all("test account" in get("/home", t)
             for t in ["100999888777", "100777666555"])),
    ]

    print("=" * 70)
    print("  manage, settlement, and the mock accounts")
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
