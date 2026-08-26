"""
Reading a service history the member typed in.

EPFO shows the service history as an on-screen table with no download button,
so a member who wants to give it to us has a screenshot and nothing else.
Reading dates out of an image means guessing, and guessing at a date is the
exact mistake this product exists to catch - so we ask them to type it.

The typed dates are turned back into the same text format the file parser
already reads, so a typed history travels through exactly the same code path as
an uploaded one. There is no second implementation to drift.
"""

from __future__ import annotations

import re
from datetime import date

DMY = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*$")


def build_history_text(rows: list[dict]) -> str:
    """Turn typed dates into the document format the parser already reads."""
    out = ["Service History",
           "Member ID                     Establishment            "
           "Date of Joining   Date of Exit"]
    for r in rows:
        out.append(f"{r['member_id']}        {r.get('employer', '')}        "
                   f"{r['doj']}        {r.get('doe') or '-'}")
    return "\n".join(out)


def read_history_form(form, accounts) -> tuple[list[dict], list[str]]:
    """
    Read the typed service history. Returns (rows, errors).

    Refuses rather than guesses. A date typed 03-04-2020 is ambiguous in exactly
    the way that matters here - it could be March or April - so the field is
    labelled DD-MM-YYYY, and anything that does not parse is rejected with the
    row named rather than silently coerced.
    """
    rows: list[dict] = []
    errors: list[str] = []

    for i, ac in enumerate(accounts):
        doj_raw = (form.get(f"doj{i}") or "").strip()
        doe_raw = (form.get(f"doe{i}") or "").strip()
        if not doj_raw and not doe_raw:
            continue

        who = ac.employer or ac.member_id

        def parse(raw, label):
            m = DMY.match(raw)
            if not m:
                errors.append(f"{who}: {label} should be DD-MM-YYYY, "
                              f"for example 01-04-2020.")
                return None
            d, mo, y = (int(x) for x in m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                errors.append(f"{who}: {label} is not a real date.")
                return None

        if not doj_raw:
            errors.append(f"{who}: a joining date is needed if you enter an "
                          f"exit date.")
            continue

        doj = parse(doj_raw, "the joining date")
        doe = parse(doe_raw, "the exit date") if doe_raw else None
        if doj is None or (doe_raw and doe is None):
            continue
        if doe and doe < doj:
            errors.append(f"{who}: the exit date is before the joining date.")
            continue

        rows.append({"member_id": ac.member_id, "employer": ac.employer,
                     "doj": doj.strftime("%d-%m-%Y"),
                     "doe": doe.strftime("%d-%m-%Y") if doe else None})

    if not rows and not errors:
        errors.append("Nothing was entered. Fill in at least the joining date "
                      "for one account.")
    return rows, errors
