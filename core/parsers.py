"""
SPIKE D - End-to-end: real-shaped documents -> parsed -> verified -> finding.

Question this spike answers:
    Now that the Form 26AS and EPF passbook layouts are confirmed from published
    format documentation and specimens, can we parse documents of that exact
    shape, verify them arithmetically, and drive the reconciler to the correct
    finding - without any real personal data?

Fixtures below reproduce the CONFIRMED column structure:

  Form 26AS Part A, two-tier nested table
    deductor row     : Sr | Name of Deductor | TAN | Total Amount Paid/Credited
                       | Total Tax Deducted | Total TDS Deposited
    transaction rows : Sr | Section | Transaction Date | Status of Booking
                       | Date of Booking | Remarks | Amount Paid/Credited
                       | Tax Deducted | TDS Deposited

  EPF passbook
    header : Establishment ID/Name, Member ID, Name, DOB, DOJ, UAN
    rows   : Wage Month | Employee Share | Employer Share | Pension (EPS)

Run:  python core/parsers.py
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import re
import sys
from datetime import date
from pathlib import Path

from core.reconcile import (  # noqa: E402
    AssertedService,
    Observation,
    Reconciler,
    assert_no_denial_path,
)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


# ===========================================================================
# FIXTURES - format-accurate, fully synthetic
# ===========================================================================

FORM_26AS_TEXT = """\
Form 26AS
Annual Tax Statement under Section 203AA of the Income Tax Act, 1961

Permanent Account Number (PAN)    AAAPZ1234C
Name of Assessee                  SYNTHETIC TEST SUBJECT
Assessment Year                   2021-22

PART A - Details of Tax Deducted at Source

Sr. No.  Name of Deductor                 TAN of Deductor  Total Amount Paid/Credited  Total Tax Deducted  Total TDS Deposited
1        ACME TECHNOLOGIES PRIVATE LIMITED  BLRA12345E       780000.00                   46800.00            46800.00
Sr. No.  Section  Transaction Date  Status of Booking  Date of Booking  Remarks  Amount Paid/Credited  Tax Deducted  TDS Deposited
1        192      30-Apr-2020       F                  15-Jun-2020               65000.00              3900.00       3900.00
2        192      31-May-2020       F                  15-Jun-2020               65000.00              3900.00       3900.00
3        192      30-Jun-2020       F                  14-Sep-2020               65000.00              3900.00       3900.00
4        192      31-Jul-2020       F                  14-Sep-2020               65000.00              3900.00       3900.00
5        192      31-Aug-2020       F                  14-Sep-2020               65000.00              3900.00       3900.00
6        192      30-Sep-2020       F                  12-Dec-2020               65000.00              3900.00       3900.00
7        192      31-Oct-2020       F                  12-Dec-2020               65000.00              3900.00       3900.00
8        192      30-Nov-2020       F                  12-Dec-2020               65000.00              3900.00       3900.00
9        192      31-Dec-2020       F                  10-Mar-2021               65000.00              3900.00       3900.00
10       192      31-Jan-2021       F                  10-Mar-2021               65000.00              3900.00       3900.00
11       192      28-Feb-2021       F                  10-Mar-2021               65000.00              3900.00       3900.00
12       192      31-Mar-2021       F                  05-Jun-2021               65000.00              3900.00       3900.00

Sr. No.  Name of Deductor                 TAN of Deductor  Total Amount Paid/Credited  Total Tax Deducted  Total TDS Deposited
2        BOREAL SYSTEMS PRIVATE LIMITED     PNEB67890K       240000.00                   14400.00            14400.00
Sr. No.  Section  Transaction Date  Status of Booking  Date of Booking  Remarks  Amount Paid/Credited  Tax Deducted  TDS Deposited
1        192      31-May-2021       F                  10-Jul-2021               80000.00              4800.00       4800.00
2        192      30-Jun-2021       F                  10-Jul-2021               80000.00              4800.00       4800.00
3        192      31-Jul-2021       F                  05-Sep-2021               80000.00              4800.00       4800.00
"""

# Same statement with one transaction amount corrupted. The arithmetic verifier
# must reject this: rows no longer sum to the deductor summary row.
FORM_26AS_CORRUPT = FORM_26AS_TEXT.replace(
    "12       192      31-Mar-2021       F                  05-Jun-2021               65000.00              3900.00       3900.00",
    "12       192      31-Mar-2021       F                  05-Jun-2021               95000.00              3900.00       3900.00",
)

PASSBOOK_ACME = """\
EPF Member Passbook

Establishment ID / Name   BLBNG0012345000 / ACME TECHNOLOGIES PVT LTD
Member ID                 BLBNG00123450000001234
Member Name               SYNTHETIC TEST SUBJECT
Date of Birth             14-08-1992
Date of Joining (EPF)     01-04-2020
UAN                       100999888777

Wage Month    Employee Share    Employer Share    Pension Contribution
Apr-2020      7800              2385              1250
May-2020      7800              2385              1250
Jun-2020      7800              2385              1250
Jul-2020      7800              2385              1250
Aug-2020      7800              2385              1250
Sep-2020      7800              2385              1250
Oct-2020      7800              2385              1250
Nov-2020      7800              2385              1250
Dec-2020      7800              2385              1250
Jan-2021      7800              2385              1250
Feb-2021      7800              2385              1250
Mar-2021      7800              2385              1250
"""

PASSBOOK_BOREAL = """\
EPF Member Passbook

Establishment ID / Name   PNPUN0067890000 / BOREAL SYSTEMS PVT LTD
Member ID                 PNPUN00678900000005678
Member Name               SYNTHETIC TEST SUBJECT
Date of Birth             14-08-1992
Date of Joining (EPF)     01-05-2021
UAN                       100999888777

Wage Month    Employee Share    Employer Share    Pension Contribution
May-2021      9600              3350              1250
Jun-2021      9600              3350              1250
Jul-2021      9600              3350              1250
"""

# What EPFO's Service History page asserts. NOTE: date of exit is NOT in the
# passbook PDF - this is a separate capture. See BRANCH 1 in the build spec.
SERVICE_HISTORY = """\
Service History

Member ID                     Establishment            Date of Joining   Date of Exit
BLBNG00123450000001234        ACME TECHNOLOGIES PVT LTD  01-04-2020        30-11-2020
PNPUN00678900000005678        BOREAL SYSTEMS PVT LTD     01-05-2021        -
"""


# --- Settlement control -----------------------------------------------------
# Exit date here is CORRECT (30-11-2020). The Jan-2021 entry is a full-and-final
# payout: no PF remitted alongside it, and the amount breaks the monthly pattern.
# The engine must NOT conclude the exit date is wrong, or it would send members
# to dispute a date that was right all along.

FORM_26AS_SETTLEMENT = """\
Form 26AS
PART A - Details of Tax Deducted at Source

Sr. No.  Name of Deductor                 TAN of Deductor  Total Amount Paid/Credited  Total Tax Deducted  Total TDS Deposited
1        ACME TECHNOLOGIES PRIVATE LIMITED  BLRA12345E       715000.00                   42900.00            42900.00
Sr. No.  Section  Transaction Date  Status of Booking  Date of Booking  Remarks  Amount Paid/Credited  Tax Deducted  TDS Deposited
1        192      30-Apr-2020       F                  15-Jun-2020               65000.00              3900.00       3900.00
2        192      31-May-2020       F                  15-Jun-2020               65000.00              3900.00       3900.00
3        192      30-Jun-2020       F                  14-Sep-2020               65000.00              3900.00       3900.00
4        192      31-Jul-2020       F                  14-Sep-2020               65000.00              3900.00       3900.00
5        192      31-Aug-2020       F                  14-Sep-2020               65000.00              3900.00       3900.00
6        192      30-Sep-2020       F                  12-Dec-2020               65000.00              3900.00       3900.00
7        192      31-Oct-2020       F                  12-Dec-2020               65000.00              3900.00       3900.00
8        192      30-Nov-2020       F                  12-Dec-2020               65000.00              3900.00       3900.00
9        192      31-Jan-2021       F                  10-Mar-2021               195000.00             11700.00      11700.00
"""

PASSBOOK_SETTLEMENT = """\
EPF Member Passbook

Establishment ID / Name   BLBNG0012345000 / ACME TECHNOLOGIES PVT LTD
Member ID                 BLBNG00123450000001234
Member Name               SYNTHETIC TEST SUBJECT
Date of Joining (EPF)     01-04-2020
UAN                       100999888777

Wage Month    Employee Share    Employer Share    Pension Contribution
Apr-2020      7800              2385              1250
May-2020      7800              2385              1250
Jun-2020      7800              2385              1250
Jul-2020      7800              2385              1250
Aug-2020      7800              2385              1250
Sep-2020      7800              2385              1250
Oct-2020      7800              2385              1250
Nov-2020      7800              2385              1250
"""

SERVICE_HISTORY_SETTLEMENT = """\
Service History

Member ID                     Establishment            Date of Joining   Date of Exit
BLBNG00123450000001234        ACME TECHNOLOGIES PVT LTD  01-04-2020        30-11-2020
"""


# ===========================================================================
# PARSERS
# ===========================================================================

TAN_RE = re.compile(r"\b([A-Z]{4}\d{5}[A-Z])\b")
DMY_RE = re.compile(r"\b(\d{2})-([A-Za-z]{3})-(\d{4})\b")
NUM_RE = re.compile(r"\b\d+(?:\.\d{2})?\b")
WAGE_MONTH_RE = re.compile(r"^([A-Za-z]{3})-(\d{4})\b")

# An amount as EPFO actually prints it: thousands separators, optional paise.
# NUM_RE splits "1,23,456" into three numbers, so it must never be used on a
# line that carries real money.
AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d{1,2})?")

# The live EPFO passbook row, which is NOT the layout our fixtures use:
#
#   Aug-2023   31-08-2023   CR   <particulars>   ee  er  eps  ee_bal er_bal eps_bal
#
# The transaction date is the hazard. Scanning the rest of the line for numbers
# picks up 31, 08 and 2023 and reads them as rupee amounts - which is exactly
# what the first run against a real passbook did: silently, with no error, and
# a plausible-looking balance.
REAL_ROW_RE = re.compile(
    r"^([A-Za-z]{3})-(\d{4})\s+"
    r"(\d{2}-\d{2}-\d{4})\s+"
    r"(.*?)"
    r"((?:\s+\d[\d,]*(?:\.\d{1,2})?){3,6})\s*$"
)
MEMBER_ID_RE = re.compile(r"\b([A-Z]{5}\d{17}|[A-Z]{5}\d{12})\b")
UAN_ANYWHERE_RE = re.compile(r"\bUAN\b\D{0,15}(\d{12})\b", re.I)
DOJ_LINE_RE = re.compile(r"date\s+of\s+joining", re.I)
# Date of birth is on the live passbook and is one of the mismatches the
# Minister of State for Labour named in the Lok Sabha as a common cause of
# claim rejection. Reading it lets us check it rather than assume it.
DOB_LINE_RE = re.compile(r"date\s+of\s+birth", re.I)
# The live passbook puts the establishment on a shared line, after other fields
# and a pipe: "... | Establishment ID/Name  DLCPM0012345000 / ACME PVT LTD".
# Requiring the line to START with the word - as the first parser did - found
# nothing on any real file, and an employer with no name cannot be matched to
# the same employer in Form 26AS. Same defect class as the mid-line member ID.
EST_ANYWHERE_RE = re.compile(
    r"establishment\s*(?:id\s*/\s*name|name|id)?\s*[:\-]?\s*"
    r"([A-Z]{2,5}\d{7,15})?\s*/?\s*([A-Z][A-Z0-9&.\- ]{2,60})?", re.I)
CLOSING_RE = re.compile(r"closing\s+balance", re.I)


def _amounts(text: str) -> list[float]:
    return [float(m.group(0).replace(",", "")) for m in AMOUNT_RE.finditer(text)]

DDMMYYYY_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")


def _dmy(d: str, mon: str, y: str) -> date:
    return date(int(y), MONTHS[mon.lower()[:3]], int(d))



# TRACES delivers Form 26AS as a caret-delimited text export, a completely
# different shape from the tabular PDF our fixtures imitate:
#
#   deductor     INT ^ name ^ TAN ^ ... ^ paid ^ tds ^ deposited
#   transaction  <empty> ^ INT ^ section ^ date ^ status ^ date ^ ... ^ amounts
#
# The tabular parser requires a row to START with a digit. A caret row starts
# with an empty field, so not one transaction was read from a real export -
# while the deductor totals still parsed, so the file looked like it had
# loaded. Only the arithmetic check caught it.
CARET_MONEY_RE = re.compile(r"^[-+]?[\d,]+\.\d{2}$")
CARET_DMY_RE = re.compile(r"^(\d{2})-(\w{3}|\d{2})-(\d{4})$")


def _caret_date(tok: str):
    m = CARET_DMY_RE.match(tok)
    if not m:
        return None
    d, mid, y = m.group(1), m.group(2), m.group(3)
    mon = int(mid) if mid.isdigit() else MONTHS.get(mid.lower())
    if not mon:
        return None
    try:
        return date(int(y), mon, int(d))
    except ValueError:
        return None


def _parse_26as_caret(text: str) -> list[dict]:
    out: list[dict] = []
    current = None
    for raw in text.splitlines():
        if "^" not in raw:
            continue
        fields = [f.strip() for f in raw.split("^")]
        money = [float(f.replace(",", "")) for f in fields
                 if CARET_MONEY_RE.match(f)]
        tan = next((f for f in fields if TAN_RE.fullmatch(f)), None)

        if tan and len(money) >= 2:
            i = fields.index(tan)
            current = {
                "name": fields[i - 1] if i else "",
                "tan": tan,
                "total_paid": money[-3] if len(money) >= 3 else money[0],
                "total_tds": money[-2] if len(money) >= 3 else money[1],
                "transactions": [],
            }
            out.append(current)
            continue

        when = next((d for d in (_caret_date(f) for f in fields) if d), None)
        sec = fields[2] if len(fields) > 2 else ""
        # Part C of the export lists tax paid other than TDS, whose rows carry
        # a challan MINOR HEAD code - 100 for advance tax, 300 for
        # self-assessment - in the same position a TDS row carries its section.
        # Read as transactions they attach to whichever deductor came last.
        is_tds_section = bool(re.match(r"^19[0-9][A-Z]{0,2}$", sec))
        if current is not None and when and len(money) >= 3 and is_tds_section:
            current["transactions"].append({
                # Kept as text: a real export carries "194A" as well as "192",
                # and int() would throw away the letter that says what it is.
                "section": sec,
                "txn_date": when,
                "amount_paid": money[-3],
                "tax_deducted": money[-2],
                "tds_deposited": money[-1],
            })
    return out


def parse_26as(text: str) -> list[dict]:
    """
    Two-tier parse. A line carrying a TAN opens a new deductor block; lines
    beginning with an integer and containing a dd-Mon-yyyy date are its
    transactions.
    """
    if "^" in text:
        return _parse_26as_caret(text)

    deductors: list[dict] = []
    current: dict | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        low = line.lower()
        if low.lstrip().startswith("sr. no.") or low.startswith("part "):
            continue

        tan_m = TAN_RE.search(line)
        if tan_m:
            # Deductor summary row: name sits between the serial and the TAN.
            head = line[: tan_m.start()].strip()
            name = re.sub(r"^\d+\s+", "", head).strip()
            tail_nums = NUM_RE.findall(line[tan_m.end():])
            current = {
                "name": name,
                "tan": tan_m.group(1),
                "total_paid": float(tail_nums[0]) if tail_nums else 0.0,
                "total_tds": float(tail_nums[1]) if len(tail_nums) > 1 else 0.0,
                "transactions": [],
            }
            deductors.append(current)
            continue

        date_m = DMY_RE.search(line)
        if current is not None and date_m and re.match(r"^\s*\d+\s", line):
            dates = DMY_RE.findall(line)
            nums = [float(n) for n in NUM_RE.findall(DMY_RE.sub(" ", line))]
            # nums: [sr, section, amount_paid, tax_deducted, tds_deposited]
            if len(nums) >= 5:
                current["transactions"].append({
                    "section": int(nums[1]),
                    "txn_date": _dmy(*dates[0]),
                    "amount_paid": nums[-3],
                    "tax_deducted": nums[-2],
                })
    return deductors


def verify_26as(deductors: list[dict], tol: float = 1.0) -> list[str]:
    """Arithmetic backstop: transaction rows must reconcile to the summary row."""
    problems: list[str] = []
    for d in deductors:
        s_paid = sum(t["amount_paid"] for t in d["transactions"])
        s_tds = sum(t["tax_deducted"] for t in d["transactions"])
        if abs(s_paid - d["total_paid"]) > tol:
            problems.append(
                f"{d['tan']}: amount rows sum to {s_paid:.2f}, summary says {d['total_paid']:.2f}"
            )
        if abs(s_tds - d["total_tds"]) > tol:
            problems.append(
                f"{d['tan']}: TDS rows sum to {s_tds:.2f}, summary says {d['total_tds']:.2f}"
            )
    return problems


def parse_passbook(text: str) -> dict:
    out: dict = {"member_id": None, "establishment": None, "doj": None,
             "months": [], "rows": [], "balance": 0.0, "pension": 0.0,
             "uan": None, "name": None, "closing": None, "dob": None,
             "establishment_code": None,
             "other_member_ids": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("member id"):
            # Taking the last token assumes the line holds nothing else. Real
            # passbooks put the establishment name on the same line, which made
            # the member ID come out as "LTD" - and then every account lookup
            # silently failed. Prefer a token that is actually shaped like one.
            m = MEMBER_ID_RE.search(line)
            parts = line.split()
            out["member_id"] = m.group(1) if m else parts[-1]
            if m:
                continue
        if out["establishment"] is None and "establishment" in line.lower():
            m = EST_ANYWHERE_RE.search(line)
            if m and m.group(2):
                name = m.group(2).strip(" -/")
                # A trailing header word is not part of a company name.
                if len(name) >= 3 and not name.lower().startswith("id"):
                    out["establishment"] = name
            if m and m.group(1) and not out.get("establishment_code"):
                out["establishment_code"] = m.group(1)
            continue
        if line.lower().startswith("uan"):
            parts = line.split()
            if parts and parts[-1].isdigit():
                out["uan"] = parts[-1]
            continue
        if line.lower().startswith("member name"):
            out["name"] = line.split(None, 2)[-1].strip()
            continue
        if line.lower().startswith("date of joining"):
            m = DDMMYYYY_RE.search(line)
            if m:
                out["doj"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            continue
        # The live format puts these mid-line, not at the start, so the
        # startswith() rules above never fire on a real passbook.
        for m in MEMBER_ID_RE.finditer(line):
            mid = m.group(1)
            if out["member_id"] is None:
                out["member_id"] = mid
            elif mid != out["member_id"] and mid not in out["other_member_ids"]:
                # A second PF account number printed inside this passbook. We
                # do not know what it means - a transfer in, a re-issued ID, a
                # second account - and guessing would be worse than saying so.
                # It is recorded and handed to the member to check.
                out["other_member_ids"].append(mid)
        if out["uan"] is None:
            m = UAN_ANYWHERE_RE.search(line)
            if m:
                out["uan"] = m.group(1)
        if out["dob"] is None and DOB_LINE_RE.search(line):
            m = DDMMYYYY_RE.search(line)
            if m:
                out["dob"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if out["doj"] is None and DOJ_LINE_RE.search(line):
            m = DDMMYYYY_RE.search(line)
            if m:
                out["doj"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if CLOSING_RE.search(line):
            amts = _amounts(DDMMYYYY_RE.sub(" ", line))
            if len(amts) >= 3:
                # Employee | Employer | Pension. Authoritative, because it
                # includes interest and any transfer out - summing the
                # contribution column alone understates both.
                out["closing"] = {"employee": amts[-3], "employer": amts[-2],
                                  "pension": amts[-1]}

        real = REAL_ROW_RE.match(line)
        if real:
            mon, yr = real.group(1), int(real.group(2))
            when = date(yr, MONTHS[mon.lower()], 1)
            out["months"].append(when)
            amts = _amounts(real.group(5))
            out["rows"].append({
                "month": when,
                "employee": amts[0],
                "employer": amts[1] if len(amts) > 1 else 0.0,
                "pension": amts[2] if len(amts) > 2 else 0.0,
            })
            continue

        wm = WAGE_MONTH_RE.match(line)
        if wm:
            mon, yr = wm.group(1), int(wm.group(2))
            when = date(yr, MONTHS[mon.lower()], 1)
            out["months"].append(when)
            # Employee share | Employer share | Pension (EPS).
            # EPS accrues to the pension fund, NOT the PF balance - a member's
            # passbook total is employee + employer share only. Adding EPS here
            # would overstate what they can actually withdraw.
            nums = [float(n) for n in NUM_RE.findall(line[wm.end():])]
            if len(nums) >= 2:
                out["rows"].append({
                    "month": when,
                    "employee": nums[0],
                    "employer": nums[1],
                    "pension": nums[2] if len(nums) > 2 else 0.0,
                })
    if out.get("closing"):
        out["balance"] = out["closing"]["employee"] + out["closing"]["employer"]
        out["pension"] = out["closing"]["pension"]
    else:
        out["balance"] = sum(r["employee"] + r["employer"] for r in out["rows"])
        out["pension"] = sum(r["pension"] for r in out["rows"])
    return out


def parse_service_history(text: str) -> list[dict]:
    rows: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(("service history", "member id")):
            continue
        if not re.match(r"^[A-Z]{5}\d", line):
            continue
        dates = DDMMYYYY_RE.findall(line)
        if not dates:
            continue
        member_id = line.split()[0]
        doj = date(int(dates[0][2]), int(dates[0][1]), int(dates[0][0]))
        doe = None
        if len(dates) > 1:
            doe = date(int(dates[1][2]), int(dates[1][1]), int(dates[1][0]))
        rows.append({"member_id": member_id, "doj": doj, "doe": doe})
    return rows


# ===========================================================================
# BRIDGE - parsed documents -> reconciler inputs
# ===========================================================================

EMPLOYER_KEY = {
    "BLRA12345E": "ACME_TECH",
    "PNEB67890K": "BOREAL_SYS",
    "BLBNG00123450000001234": "ACME_TECH",
    "PNPUN00678900000005678": "BOREAL_SYS",
}


def build_inputs():
    deductors = parse_26as(FORM_26AS_TEXT)
    pb_acme = parse_passbook(PASSBOOK_ACME)
    pb_boreal = parse_passbook(PASSBOOK_BOREAL)
    history = parse_service_history(SERVICE_HISTORY)

    observations: list[Observation] = []
    for d in deductors:
        key = EMPLOYER_KEY[d["tan"]]
        for t in d["transactions"]:
            observations.append(
                Observation(key, t["txn_date"], "TDS_26AS", f"s{t['section']}",
                            amount=t["amount_paid"])
            )
    for pb in (pb_acme, pb_boreal):
        key = EMPLOYER_KEY[pb["member_id"]]
        for m in pb["months"]:
            observations.append(Observation(key, m, "EPF_CONTRIB"))

    asserted = [
        AssertedService(
            employer_key=EMPLOYER_KEY[h["member_id"]],
            member_id=h["member_id"],
            doj=h["doj"],
            doe=h["doe"],
        )
        for h in history
    ]
    return deductors, (pb_acme, pb_boreal), asserted, observations


# ===========================================================================

def main() -> int:
    failures = 0
    print("=" * 74)
    print("  STAGE 1 - parse Form 26AS")
    deductors = parse_26as(FORM_26AS_TEXT)
    for d in deductors:
        print(f"    {d['tan']}  {d['name'][:38]:38}  {len(d['transactions'])} txns")

    print("\n  STAGE 2 - arithmetic verifier")
    clean = verify_26as(deductors)
    print(f"    clean fixture   : {'PASS (reconciles)' if not clean else clean}")
    corrupt = verify_26as(parse_26as(FORM_26AS_CORRUPT))
    print(f"    corrupt fixture : {'CAUGHT - ' + corrupt[0] if corrupt else 'MISSED'}")

    print("\n  STAGE 3 - parse passbooks + service history")
    _, pbs, asserted, observations = build_inputs()
    for pb in pbs:
        print(f"    {pb['member_id']}  doj={pb['doj']}  {len(pb['months'])} wage months")
    for a in asserted:
        print(f"    asserted  {a.employer_key:12} doj={a.doj}  doe={a.doe}")

    print(f"\n  STAGE 4 - reconcile  ({len(observations)} observations)")
    result = Reconciler(observations, asserted, date(2025, 8, 20)).run()
    assert_no_denial_path(result)
    print(f"    status: {result['claim_status']}  blocking: {result['blocking_count']}")
    for c in result["contradictions"]:
        print(f"    [{c['severity']:11}] {c['kind']:16} {c['employer']}")
        print(f"                  {c['detail'][:96]}")

    kinds = {c["kind"] for c in result["contradictions"]}

    # --- Stage 5: settlement control ---------------------------------------
    print("\n  STAGE 5 - settlement control (exit date is CORRECT here)")
    ded_s = parse_26as(FORM_26AS_SETTLEMENT)
    pb_s = parse_passbook(PASSBOOK_SETTLEMENT)
    hist_s = parse_service_history(SERVICE_HISTORY_SETTLEMENT)
    obs_s = [
        Observation("ACME_TECH", t["txn_date"], "TDS_26AS", "s192", amount=t["amount_paid"])
        for t in ded_s[0]["transactions"]
    ] + [Observation("ACME_TECH", m, "EPF_CONTRIB") for m in pb_s["months"]]
    asserted_s = [
        AssertedService("ACME_TECH", hist_s[0]["member_id"], hist_s[0]["doj"], hist_s[0]["doe"])
    ]
    res_s = Reconciler(obs_s, asserted_s, date(2025, 8, 20)).run()
    assert_no_denial_path(res_s)
    kinds_s = {c["kind"] for c in res_s["contradictions"]}
    for c in res_s["contradictions"]:
        print(f"    [{c['severity']:11}] {c['kind']:18} {c['detail'][:80]}")
    if not res_s["contradictions"]:
        print("    (no contradictions)")

    print("\n" + "-" * 74)
    print("  spike assertions")
    checks = [
        ("26AS: both deductors parsed with TANs", len(deductors) == 2),
        ("26AS: 12 + 3 transactions extracted",
         [len(d["transactions"]) for d in deductors] == [12, 3]),
        ("verifier accepts the clean fixture", not clean),
        ("verifier REJECTS the corrupted fixture", bool(corrupt)),
        ("passbook: DOJ + wage months parsed", all(p["doj"] and p["months"] for p in pbs)),
        ("service history supplies asserted DOE", any(a.doe for a in asserted)),
        ("end-to-end: EXIT_TOO_EARLY found", "EXIT_TOO_EARLY" in kinds),
        ("no false correction-conflict raised", "CORRECTION_CONFLICT" not in kinds),
        ("settlement control: flagged as TRAILING_PAYOUT", "TRAILING_PAYOUT" in kinds_s),
        ("settlement control: does NOT claim exit is wrong", "EXIT_TOO_EARLY" not in kinds_s),
        ("settlement control: nothing blocking", res_s["blocking_count"] == 0),
    ]
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1

    print(f"\n  RESULT: {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    print("=" * 74)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
