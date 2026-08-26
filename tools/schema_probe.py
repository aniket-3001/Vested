"""
SPIKE C - Document schema probe.  *** YOU RUN THIS, NOT CLAUDE. ***

Question this spike answers - and it is the one that can kill the project:
    Do Form 26AS / AIS and the EPF passbook actually contain the fields the
    reconciliation engine needs?

        Form 26AS  ->  per-deductor TAN + dated TDS transactions
        EPF passbook -> per-member-ID wage-month contributions + date of joining

    If they do not, PF Sahi Hai does not work and we need to know now.

PRIVACY: this script prints STRUCTURE ONLY. No names, no amounts, no PAN, no
UAN, no employer names, no dates. Only: which anchor fields were found, how
many rows parsed, and how many months of coverage. Read the REDACTION NOTES at
the bottom before sharing output. Nothing here needs to leave your machine -
just tell Claude which checks passed.

Usage:
    python tools/schema_probe.py path/to/26AS.pdf --type 26as
    python tools/schema_probe.py path/to/passbook.pdf --type passbook
    python tools/schema_probe.py path/to/file.pdf --type auto --password DDMMYYYY

Form 26AS from TRACES is usually password-protected: your date of birth as
DDMMYYYY. Pass it with --password.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

try:
    import pdfplumber
except ImportError:
    print("need pdfplumber:  pip install pdfplumber")
    sys.exit(2)


# ---------------------------------------------------------------------------
# Anchors we expect to find. Presence/absence is all we report.
# ---------------------------------------------------------------------------

ANCHORS_26AS = {
    "statement header":        r"annual tax statement|form\s*26as|tax credit statement",
    "PART A (TDS on salary)":  r"part\s*[-\s]*a\b",
    "deductor TAN column":     r"\btan\s*of\s*deductor\b|\btan\b",
    "deductor name column":    r"name\s*of\s*deductor",
    "section code (192)":      r"\b192\b|section",
    "transaction date column": r"transaction\s*date|date\s*of\s*(credit|payment)",
    "amount paid/credited":    r"amount\s*paid|amount\s*credited",
    "tax deducted column":     r"tax\s*deducted|tds\s*deposited",
}

ANCHORS_PASSBOOK = {
    "passbook header":        r"member\s*(id|passbook)|epf\s*passbook|passbook",
    "establishment ID":       r"establishment\s*(id|code)",
    "member ID":              r"member\s*id",
    "date of joining":        r"date\s*of\s*joining|doj",
    "date of exit":           r"date\s*of\s*exit|doe",
    "wage month column":      r"wage\s*month|month\s*[-/]?\s*year",
    "employee share":        r"employee\s*share|ee\s*share",
    "employer share":        r"employer\s*share|er\s*share",
    "pension (EPS) column":   r"pension|eps\s*contribution",
}

# Patterns used only to COUNT rows. Captured values are discarded immediately.
TAN_PAT = re.compile(r"\b[A-Z]{4}\d{5}[A-Z]\b")
MEMBER_ID_PAT = re.compile(r"\b[A-Z]{2}[A-Z]{3}\d{7}\d{3}\d{7}\b|\b[A-Z]{5}\d{17}\b")
DATE_PAT = re.compile(r"\b(\d{2})[-/](\d{2})[-/](\d{4})\b")
WAGE_MONTH_PAT = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-\s/]*(\d{2,4})\b",
    re.I,
)
MONEY_PAT = re.compile(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d{2})?\b|\b\d+\.\d{2}\b")


def load_text(path: str, password: str | None) -> tuple[str, int]:
    kwargs = {"password": password} if password else {}
    with pdfplumber.open(path, **kwargs) as pdf:
        pages = len(pdf.pages)
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    return text, pages


def detect_type(text: str) -> str:
    low = text.lower()
    if re.search(r"form\s*26as|annual tax statement|tax credit statement", low):
        return "26as"
    if re.search(r"passbook|member\s*id|establishment", low):
        return "passbook"
    if re.search(r"annual information statement|\bais\b", low):
        return "ais"
    return "unknown"


def check_anchors(text: str, anchors: dict[str, str]) -> list[tuple[str, bool]]:
    low = text.lower()
    return [(label, bool(re.search(pat, low, re.I))) for label, pat in anchors.items()]


def month_span(text: str) -> tuple[int, int]:
    """Distinct wage months seen, and span in months. No actual dates printed."""
    seen: set[tuple[int, int]] = set()
    months = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    for mo, yr in WAGE_MONTH_PAT.findall(text):
        y = int(yr)
        if y < 100:
            y += 2000
        if 1990 <= y <= 2100:
            seen.add((y, months[mo[:3].lower()]))

    for d, m, y in DATE_PAT.findall(text):
        mi, yi = int(m), int(y)
        if 1 <= mi <= 12 and 1990 <= yi <= 2100:
            seen.add((yi, mi))

    if not seen:
        return 0, 0
    lo, hi = min(seen), max(seen)
    span = (hi[0] - lo[0]) * 12 + (hi[1] - lo[1]) + 1
    return len(seen), span


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--type", default="auto", choices=["auto", "26as", "passbook", "ais"])
    ap.add_argument("--password", default=None)
    args = ap.parse_args()

    try:
        text, pages = load_text(args.path, args.password)
    except Exception as e:
        msg = str(e)
        if "password" in msg.lower() or "encrypt" in msg.lower():
            print("FAIL  PDF is encrypted. Retry with --password DDMMYYYY (your date of birth).")
        else:
            print(f"FAIL  could not open: {type(e).__name__}: {msg[:120]}")
        return 2

    if not text.strip():
        print("FAIL  no extractable text - this is a scanned/image PDF.")
        print("      Not fatal: it means the vision-model extraction path is REQUIRED,")
        print("      not optional. Report this back, it changes the architecture.")
        return 1

    doc_type = args.type if args.type != "auto" else detect_type(text)

    print("=" * 66)
    print(f"  doc type detected : {doc_type}")
    print(f"  pages             : {pages}")
    print(f"  extractable text  : yes ({len(text):,} chars)")
    print("=" * 66)

    if doc_type == "26as":
        anchors = ANCHORS_26AS
    elif doc_type == "passbook":
        anchors = ANCHORS_PASSBOOK
    else:
        print("  unknown type - showing both anchor sets")
        anchors = {**ANCHORS_26AS, **ANCHORS_PASSBOOK}

    print("\n  FIELD PRESENCE")
    results = check_anchors(text, anchors)
    for label, found in results:
        print(f"    {'FOUND  ' if found else 'MISSING'}  {label}")

    # Counts only. Values are counted and discarded, never printed.
    tans = Counter(TAN_PAT.findall(text))
    member_ids = Counter(MEMBER_ID_PAT.findall(text))
    n_money = len(MONEY_PAT.findall(text))
    n_months, span = month_span(text)

    print("\n  ROW / CARDINALITY COUNTS  (values discarded, counts only)")
    print(f"    distinct TAN-shaped tokens        : {len(tans)}")
    print(f"    distinct member-ID-shaped tokens  : {len(member_ids)}")
    print(f"    numeric amount-shaped tokens      : {n_money}")
    print(f"    distinct months referenced        : {n_months}")
    print(f"    coverage span (months)            : {span}")

    # ---- verdict ----------------------------------------------------------
    found_labels = {label for label, ok in results if ok}
    print("\n  VERDICT")
    ok = True

    if doc_type == "26as":
        need_tan = len(tans) >= 1
        need_dates = n_months >= 2
        need_amounts = n_money >= 4
        print(f"    {'PASS' if need_tan else 'FAIL'}  at least one deductor TAN present")
        print(f"    {'PASS' if need_dates else 'FAIL'}  dated transactions present (>=2 months)")
        print(f"    {'PASS' if need_amounts else 'FAIL'}  amount columns present")
        ok = need_tan and need_dates and need_amounts
        if ok:
            print("\n    => 26AS CAN anchor employment periods to a deductor. Premise holds.")
        else:
            print("\n    => 26AS premise NOT confirmed on this sample. Report back before building.")

    elif doc_type == "passbook":
        need_member = "member ID" in found_labels or len(member_ids) >= 1
        need_wage = "wage month column" in found_labels or n_months >= 2
        need_doj = "date of joining" in found_labels
        need_doe = "date of exit" in found_labels
        print(f"    {'PASS' if need_member else 'FAIL'}  member ID present")
        print(f"    {'PASS' if need_wage else 'FAIL'}  wage-month contribution rows present")
        print(f"    {'PASS' if need_doj else 'FAIL'}  date of joining present")
        print(f"    {'PASS' if need_doe else 'WARN'}  date of exit present")
        ok = need_member and need_wage and need_doj
        if ok and not need_doe:
            print("\n    => Passbook works for PRESENCE, but exit date is not in the PDF.")
            print("       Means the asserted DOE must come from the Service History page")
            print("       instead. Architecture change - report this back.")
        elif ok:
            print("\n    => Passbook CAN supply presence + boundaries. Premise holds.")
        else:
            print("\n    => Passbook premise NOT confirmed. Report back before building.")

    print("\n" + "=" * 66)
    print("  REDACTION NOTES - what this script did NOT print:")
    print("    your name, PAN, UAN, Aadhaar, employer names, any rupee amount,")
    print("    any specific date, any member ID or TAN value.")
    print("  Safe to paste this output into chat.")
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
