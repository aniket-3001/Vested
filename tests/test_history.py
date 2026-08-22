"""
Typing in a service history.

The last gap in this product, and it turned out not to be ours. The UAN portal
shows service history as an on-screen table with NO download button, so members
screenshot it. A screenshot has no rows in it. We could OCR it, but a misread
digit in a date is indistinguishable from the employer error we are hunting -
which makes guessing strictly worse than asking.

So the member types two dates per account, with the member IDs already filled in
from the passbooks we read. The typed dates are turned back into the same
document format the file parser reads, so a typed history travels through
exactly the same code path as an uploaded one and there is no second
implementation to drift.

Most of these tests are about refusing bad input. A date silently coerced the
wrong way round - 03-04 read as 3 April when the member meant 4 March - would
produce a confident, wrong finding against an employer.

Run:  python tests/test_history.py
"""

from __future__ import annotations

import io
import re
import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import app.server as S
from app.engine import SAMPLE_26AS, SAMPLE_PASSBOOKS
from app.manage import build_history_text, read_history_form
from app.server import create_app
from core.parsers import parse_service_history


class Acct:
    def __init__(self, mid, emp):
        self.member_id, self.employer, self.months, self.orphan = mid, emp, 12, False


ACCOUNTS = [Acct("BLBNG00123450000001234", "ACME TECHNOLOGIES PVT LTD"),
            Acct("PNPUN00678900000005678", "BOREAL SYSTEMS PVT LTD")]


def upload(c):
    """A record with 26AS and passbooks but no service history."""
    r = c.post("/analyse", data={
        "f26as": [(io.BytesIO(SAMPLE_26AS.encode()), "26as.txt")],
        "passbook": [(io.BytesIO(p.encode()), f"p{i}.txt")
                     for i, p in enumerate(SAMPLE_PASSBOOKS)]},
        content_type="multipart/form-data")
    return re.search(r"s=([A-Za-z0-9_-]+)", r.headers["Location"]).group(1)


def main() -> int:
    checks = []
    c = create_app().test_client()

    # ---- the typed dates become a document the existing parser reads -------
    rows, errs = read_history_form(
        {"doj0": "01-04-2020", "doe0": "30-11-2020", "doj1": "01-05-2021"},
        ACCOUNTS)
    text = build_history_text(rows)
    parsed = parse_service_history(text)
    checks += [
        ("two typed rows are accepted", len(rows) == 2 and not errs),
        ("the text round-trips through the file parser", len(parsed) == 2),
        ("member IDs survive", parsed[0]["member_id"] == ACCOUNTS[0].member_id),
        ("the joining date survives", parsed[0]["doj"].isoformat() == "2020-04-01"),
        ("the exit date survives", parsed[0]["doe"].isoformat() == "2020-11-30"),
        ("a blank exit means still employed", parsed[1]["doe"] is None),
    ]

    # ---- refusing, rather than guessing -----------------------------------
    def err(form):
        return read_history_form(form, ACCOUNTS)[1]

    checks += [
        ("an empty form is refused", bool(err({}))),
        ("ISO order is refused rather than reinterpreted",
         "DD-MM-YYYY" in " ".join(err({"doj0": "2020-04-01"}))),
        ("a slashed date is accepted",
         not err({"doj0": "01/04/2020"})),
        ("31 February is refused", "not a real date" in " ".join(
            err({"doj0": "31-02-2020"}))),
        ("an exit before a joining date is refused",
         "before the joining date" in " ".join(
             err({"doj0": "01-04-2020", "doe0": "01-01-2019"}))),
        ("an exit with no joining date is refused",
         "joining date is needed" in " ".join(err({"doe0": "30-11-2020"}))),
        ("the offending row is named, not just the error",
         "ACME" in " ".join(err({"doj0": "bad"}))),
        # A row left entirely blank is not an error - the member may only know
        # some of their dates, and half a history is better than none.
        ("a blank row is skipped, not rejected",
         read_history_form({"doj0": "01-04-2020"}, ACCOUNTS)[1] == []),
        ("and only the filled row is kept",
         len(read_history_form({"doj0": "01-04-2020"}, ACCOUNTS)[0]) == 1),
    ]

    # ---- end to end: the verdict changes ----------------------------------
    tok = upload(c)
    before = c.get(f"/home?s={tok}").get_data(as_text=True)
    form = c.get(f"/history?s={tok}").get_data(as_text=True)
    checks += [
        ("without a history the verdict is not yet known",
         "<h1>Not yet known</h1>" in before),
        ("the home page offers the way out", "/history?s=" in before),
        ("the form has a row per account",
         len(re.findall(r'name="doj\d+"', form)) == 2),
        ("member IDs are filled in already", ACCOUNTS[0].member_id in form),
        ("it explains why we cannot read a screenshot",
         "screenshot" in form),
        ("it is clear these are EPFO's dates, not ours",
         "EPFO&rsquo;s claim about you" in form),
    ]

    posted = c.post(f"/history?s={tok}", data={
        "doj0": "01-04-2020", "doe0": "30-11-2020", "doj1": "01-05-2021"})
    tok2 = re.search(r"s=([A-Za-z0-9_-]+)", posted.headers["Location"]).group(1)
    a2 = S._load(tok2)
    kinds = [x["kind"] for x in a2.result["contradictions"]]
    checks += [
        ("saving redirects to the record", posted.status_code == 303
         and "/record" in posted.headers["Location"]),
        ("the dates are now checked", a2.dates_checked),
        ("the record knows they were typed", a2.history_typed),
        ("a real verdict replaces 'not yet known'",
         "<h1>No</h1>" in c.get(f"/home?s={tok2}").get_data(as_text=True)),
        ("date findings appear", "EXIT_TOO_EARLY" in kinds),
        ("a missing exit is found", "MISSING_EXIT" in kinds),
        # The orphan check needs a service history to distinguish a forgotten
        # account from one we simply were not shown, so this is the clearest
        # proof the typed dates reached the reconciler.
        ("the forgotten account is now found", "ORPHAN_ACCOUNT" in kinds),
        ("the 'no service history' caveat is dropped",
         not any("service history" in r.lower() for r in a2.reduced)),
        ("the documents survived the re-analysis",
         len(a2.accounts) == len(S._load(tok).accounts)),
    ]

    bad = c.post(f"/history?s={tok}", data={"doj0": "nonsense"})
    checks += [
        ("bad input returns the form, not a redirect", bad.status_code == 400),
        ("what was typed is preserved for correction",
         "nonsense" in bad.get_data(as_text=True)),
    ]

    # ---- the shared demo accounts must not be mutated ----------------------
    before_demo = [x["kind"] for x in S._load("100777666555").result["contradictions"]]
    c.post("/history?s=100777666555", data={"doj0": "01-06-2021", "doe0": "31-05-2022"})
    after_demo = [x["kind"] for x in S._load("100777666555").result["contradictions"]]
    checks += [
        ("editing a demo account does not change it for everyone",
         before_demo == after_demo),
        ("the demo account still reads as clean",
         c.get("/home?s=100777666555").get_data(as_text=True).count("<h1>Yes</h1>") == 1),
        ("a demo account can still be edited into a private session",
         c.post("/history?s=100999888777",
                data={"doj0": "01-04-2020"}).status_code == 303),
    ]

    # ---- every page still renders after a typed history --------------------
    ok = []
    for p in ["/home", "/record", "/accounts", "/pension", "/withdraw", "/claim",
              "/manage", "/kyc", "/exit", "/nomination", "/transfer",
              "/uan-card", "/contact", "/history", "/track", "/profile"]:
        r = c.get(f"{p}?s={tok2}")
        b = r.get_data(as_text=True)
        ok.append(r.status_code == 200 and len(b) > 500 and "Traceback" not in b)
    checks.append((f"all {len(ok)} pages render on a typed-history record", all(ok)))

    print("=" * 70)
    print("  typing in a service history")
    bad_n = 0
    for name, good in checks:
        print(f"    {'PASS' if good else 'FAIL'}  {name}")
        bad_n += not good
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad_n else f'{bad_n} FAILURE(S)'}")
    print("=" * 70)
    return 1 if bad_n else 0


if __name__ == "__main__":
    _s.exit(main())
