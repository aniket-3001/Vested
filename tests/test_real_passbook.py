"""
The live EPFO passbook layout.

Every parser test before this one used our own fixtures, which used the wording
we had guessed. The first run against real passbooks found four defects, none of
which raised an error:

  1. Member ID and UAN sit MID-LINE in the real format. The parser required them
     to start the line, so both came back empty.
  2. The row scanner took every number after the wage month - including the
     three parts of the transaction date. A row dated 31-08-2023 was read as
     employee=31, employer=8, pension=2023. The balance was nonsense, and it
     looked perfectly plausible.
  3. Amounts carry thousands separators. NUM_RE split "1,23,456" into three.
  4. The passbook is issued one file per FINANCIAL YEAR. Ten uploads were ten
     accounts, splitting one balance across ten rows.

The fixture below is synthetic, in the real layout.

Run:  python tests/test_real_passbook.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from datetime import date

import app.engine as E
from app.ingest import sort_uploads
from core.parsers import parse_26as, parse_passbook, verify_26as

MID_A = "MHBAN00123450000000111"
MID_B = "MHBAN00987650000000222"
UAN = "100999888777"

def year_page(mid, fy, months, closing, extra_id=None):
    head = f"""EPF Passbook - Financial Year {fy}
Member ID {mid}   Establishment Name  ACME TECHNOLOGIES PVT LTD
Account Number {UAN}  UAN {UAN}
Date of Birth 14-08-1992
Wage Month  Transaction Date  Particulars  Employee Employer Pension
Balance Balance Balance"""
    if extra_id:
        head += f"\nTransferred in from {extra_id}"
    rows = "\n".join(
        f"{m}-{fy[:4]} 3{i%2}-0{(i%9)+1}-{fy[:4]} CR Contribution (#ECR) "
        f"1,800 550 1,250 {10000+i*1800:,} {5000+i*550:,} {3000+i*1250:,}"
        for i, m in enumerate(months))
    return f"{head}\n{rows}\nClosing Balance as on 31-03-{int(fy[:4])+1} {closing}"


def main() -> int:
    checks = []

    one = parse_passbook(year_page(MID_A, "2022-23", ["Apr", "May", "Jun"],
                                   "1,20,000 90,000 45,000"))
    checks += [
        ("member ID found mid-line", one["member_id"] == MID_A),
        ("UAN found mid-line", one["uan"] == UAN),
        ("date of birth is NOT read as joining date", one["doj"] is None),
        ("all three rows parsed", len(one["rows"]) == 3),
        # The defect that made a real balance meaningless.
        ("transaction date is not read as money",
         all(r["employee"] == 1800.0 for r in one["rows"])),
        ("employer share correct", all(r["employer"] == 550.0 for r in one["rows"])),
        ("pension share correct", all(r["pension"] == 1250.0 for r in one["rows"])),
        ("thousands separators survive", one["balance"] == 210000.0),
        ("closing balance beats summing contributions", one["balance"] != 7050.0),
        ("pension read from closing balance", one["pension"] == 45000.0),
    ]

    # One account, three financial years, plus a second account.
    pages = [
        year_page(MID_A, "2020-21", ["Apr", "May"], "50,000 40,000 20,000"),
        year_page(MID_A, "2021-22", ["Apr", "May"], "90,000 70,000 35,000"),
        year_page(MID_A, "2022-23", ["Apr", "May"], "1,20,000 90,000 45,000"),
        year_page(MID_B, "2022-23", ["Jun"], "10,000 8,000 4,000", extra_id=MID_A),
    ]
    merged = E.merge_passbooks([parse_passbook(p) for p in pages])
    by_id = {m["member_id"]: m for m in merged}
    checks += [
        ("four files become two accounts", len(merged) == 2),
        ("balances are not multiplied by file count",
         by_id[MID_A]["balance"] == 210000.0),
        ("the latest year wins, not the first", by_id[MID_A]["balance"] != 90000.0),
        ("months accumulate across years", len(by_id[MID_A]["months"]) == 6),
        ("the second account stays separate", by_id[MID_B]["balance"] == 18000.0),
    ]

    a = E.analyse(text_26as="", passbooks=pages, service_history="", bank="",
                  names={"passbook": "RAHUL KUMAR SINGH"})
    kinds = [c["kind"] for c in a.result["contradictions"]]
    checks += [
        ("engine builds accounts from passbooks alone", len(a.accounts) == 2),
        ("balances reach the analysis", a.total_balance == 228000.0),
        ("pension reaches the analysis", a.total_pension == 49000.0),
        ("UAN read from a real-format passbook", a.identity["uan"] == UAN),
        ("no service history means no invented orphans",
         "ORPHAN_ACCOUNT" not in kinds),
        ("an unchecked record is not called claimable", not a.claimable),
        # MID_A is itself an account here, so it is not a dangling reference.
        ("a referenced ID that IS an account is not reported", a.related_ids == []),
    ]

    dangling = E.analyse(
        text_26as="", passbooks=[pages[3]], service_history="", bank="",
        names={"passbook": "RAHUL KUMAR SINGH"})
    checks.append(("a referenced ID with no passbook IS reported",
                   dangling.related_ids == [MID_A]))

    # ---- the TRACES caret-delimited Form 26AS export --------------------
    # Real exports are dominated by section 194A (bank interest). Treating
    # those as salary turns a bank into an employer and then invents a
    # forgotten PF account for it.
    caret = chr(10).join([
        "Form 26AS - Annual Tax Statement",
        "Part A - Details of Tax Deducted at Source",
        "1^ACME TECHNOLOGIES PRIVATE LIMITED^BLRA12345E^^^^^600000.00^30000.00^30000.00",
        "^1^192^30-04-2020^F^15-05-2020^-^300000.00^15000.00^15000.00",
        "^2^192^31-05-2020^F^15-06-2020^-^300000.00^15000.00^15000.00",
        "2^STATE BANK^BLRS99999X^^^^^40000.00^4000.00^4000.00",
        "^1^194A^30-06-2020^F^15-07-2020^-^40000.00^4000.00^4000.00",
        "Part C - Details of Tax Paid (other than TDS)",
        "1^100^0^12000.00^0.00^0.00^0.00^0.00^0.00^12000.00^1234^30-07-2020^567^N",
    ])
    parsed = parse_26as(caret)
    by_tan = {d["tan"]: d for d in parsed}
    checks += [
        ("caret export parses both deductors", len(parsed) == 2),
        ("caret salary rows parsed", len(by_tan["BLRA12345E"]["transactions"]) == 2),
        ("caret interest row parsed", len(by_tan["BLRS99999X"]["transactions"]) == 1),
        ("section kept as text, not int",
         by_tan["BLRS99999X"]["transactions"][0]["section"] == "194A"),
        ("challan minor-head rows are NOT transactions",
         all(t["section"] != "100" for d in parsed for t in d["transactions"])),
        ("caret amounts survive", by_tan["BLRA12345E"]["transactions"][0]["amount_paid"] == 300000.0),
        ("caret export reconciles arithmetically", verify_26as(parsed) == []),
        ("192 counts as salary", E.is_salary_section("192")),
        ("194A does NOT count as salary", not E.is_salary_section("194A")),
        ("integer 192 from our own fixtures still counts", E.is_salary_section(192)),
    ]

    bank_test = E.analyse(text_26as=caret, passbooks=[], service_history="",
                          bank="", names={"26as": "RAHUL KUMAR SINGH"})
    checks += [
        ("a bank paying interest is not an employer",
         all("BANK" not in w["employer"].upper() for w in bank_test.worklist)),
        ("the real employer still appears", len(bank_test.worklist) == 1),
    ]

    # ---- several assessment years of Form 26AS --------------------------
    # 26AS is issued one file per assessment year. sort_uploads kept only the
    # first and reported all of them as "Recognised", so a member with real
    # history lost most of it silently.
    y2 = chr(10).join([
        "Form 26AS - Annual Tax Statement",
        "Part A - Details of Tax Deducted at Source",
        "1^ACME TECHNOLOGIES PVT LTD^BLRA12345E^^^^^600000.00^30000.00^30000.00",
        "^1^192^30-04-2021^F^15-05-2021^-^300000.00^15000.00^15000.00",
        "^2^192^31-05-2021^F^15-06-2021^-^300000.00^15000.00^15000.00",
    ])
    both = sort_uploads([("y1.txt", caret.encode()), ("y2.txt", y2.encode())])
    merged_d = E.merge_deductors(parse_26as(both["found"]["26as"]))
    acme = next(d for d in merged_d if d["tan"] == "BLRA12345E")
    checks += [
        ("both assessment years are kept", both["found"]["26as"].count("Part A") == 2),
        ("one employer, not one per year", len(merged_d) == 2),
        ("every year's entries survive the merge", len(acme["transactions"]) == 4),
        ("merged entries are in date order",
         [t["txn_date"] for t in acme["transactions"]]
         == sorted(t["txn_date"] for t in acme["transactions"])),
        ("the fuller legal name wins",
         acme["name"] == "ACME TECHNOLOGIES PRIVATE LIMITED"),
        ("per-year totals are summed", acme["total_paid"] == 1200000.0),
    ]

    multi = E.analyse(text_26as=both["found"]["26as"], passbooks=[],
                      service_history="", bank="", names={"26as": "RAHUL KUMAR SINGH"})
    checks += [
        ("the employer appears once in the worklist",
         sum(1 for w in multi.worklist if w["tan"] == "BLRA12345E") == 1),
        ("the worklist spans every year supplied",
         next(w for w in multi.worklist if w["tan"] == "BLRA12345E")["months"] == 4),
        ("interest is excluded from the salary count",
         "1 interest or other entries ignored"
         in next(s.detail for s in multi.ingest if s.label == "Form 26AS read")),
    ]

    # ---- every page must survive partial evidence -----------------------
    # /accounts crashed on the real record: a live passbook carries no date of
    # joining, so ac.doj was None and .strftime() threw. The member saw an
    # empty page. Rendering every page is the only way to catch this class.
    import io, re as _re
    from app.server import create_app
    cli = create_app().test_client()
    up = cli.post("/analyse", data={"passbook": [
        (io.BytesIO(p.encode()), f"pb{i}.txt") for i, p in enumerate(pages)]},
        content_type="multipart/form-data")
    tok = _re.search(r"s=([A-Za-z0-9_-]+)", up.headers.get("Location", "")).group(1)
    pages_ok, danger = [], []
    for path in ["/home", "/record", "/accounts", "/pension", "/withdraw",
                 "/claim", "/track", "/profile"]:
        resp = cli.get(f"{path}?s={tok}")
        body = resp.get_data(as_text=True)
        pages_ok.append(resp.status_code == 200 and len(body) > 500)
        if "Nothing is blocking" in body:
            danger.append(path)
    checks += [
        ("every page renders without a service history", all(pages_ok)),
        ("no page claims nothing is blocking an unchecked record", danger == []),
    ]

    print("=" * 70)
    print("  the live EPFO passbook layout")
    bad = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        bad += not ok
    print(f"\n  {len(checks)} checks · RESULT: {'ALL PASS' if not bad else f'{bad} FAILURE(S)'}")
    print("=" * 70)
    return 1 if bad else 0


if __name__ == "__main__":
    _s.exit(main())
