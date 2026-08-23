"""
Ingestion tests - PDF, encrypted PDF, and ZIP.

These exist because the whole upload path was originally exercised only with
.txt files, while PDF is how most people actually receive these documents. The
first run of this suite found two defects:

  1. An encrypted PDF was reported to the user as "damaged". pdfminer raises
     PdfminerException with an EMPTY message for encryption, so matching on the
     message alone silently misclassified the single most common case - Form
     26AS is password protected by default.
  2. A PDF whose text ran off the page extracted losslessly-looking but was
     missing a transaction row. The arithmetic verifier caught it, which is
     exactly its job.

Run:  python tests/test_ingest.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import io
import zipfile

import fitz

import app.engine as E
from app.ingest import IngestError, extract, sort_uploads
from core.parsers import parse_26as, parse_passbook, parse_service_history, verify_26as

# Illustrative only. Day 25 cannot be a month, so the fixture also documents
# that Form 26AS wants DDMMYYYY rather than MMDDYYYY.
PASSWORD = "25121990"


def make_pdf(text: str, password: str | None = None, lines_per_page: int = 46) -> bytes:
    """Lay text out so nothing is clipped - a clipped page is a lossy fixture."""
    doc = fitz.open()
    lines = text.splitlines()
    for i in range(0, len(lines), lines_per_page):
        page = doc.new_page(width=1000, height=620)
        y = 26.0
        for ln in lines[i:i + lines_per_page]:
            page.insert_text((22, y), ln, fontname="cour", fontsize=6.5)
            y += 12.5
    if password:
        return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                           owner_pw=password, user_pw=password)
    return doc.tobytes()


def make_zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def make_scan() -> bytes:
    doc = fitz.open()
    doc.new_page().draw_rect(fitz.Rect(10, 10, 90, 90), fill=(0, 0, 0))
    return doc.tobytes()


def main() -> int:
    checks: list[tuple[str, bool]] = []

    # --- plain PDF, and it must parse LOSSLESSLY -------------------------
    ex = extract("26AS.pdf", make_pdf(E.SAMPLE_26AS))
    ded = parse_26as(ex.text)
    counts = [len(d["transactions"]) for d in ded]
    problems = verify_26as(ded)
    checks += [
        ("PDF 26AS detected as 26as", ex.kind == "26as"),
        ("PDF 26AS: all 3 deductors parsed", len(ded) == 3),
        ("PDF 26AS: no transaction lost", counts == [11, 12, 3]),
        ("PDF 26AS: arithmetic reconciles", not problems),
    ]

    # --- encrypted PDF: the message must be actionable -------------------
    enc = make_pdf(E.SAMPLE_26AS, password=PASSWORD)
    try:
        extract("26AS.pdf", enc)
        no_pw_msg = ""
    except IngestError as e:
        no_pw_msg = str(e)
    try:
        extract("26AS.pdf", enc, "00000000")
        bad_pw_msg = ""
    except IngestError as e:
        bad_pw_msg = str(e)
    ok_pw = extract("26AS.pdf", enc, PASSWORD)
    checks += [
        ("encrypted PDF asks for a password", "password protected" in no_pw_msg),
        ("encrypted PDF is NOT called damaged", "damaged" not in no_pw_msg),
        ("wrong password says so specifically", "did not work" in bad_pw_msg),
        ("correct password opens it", ok_pw.kind == "26as"),
    ]

    # --- ZIP (TRACES delivers the text export zipped) --------------------
    z = extract("26AS.zip", make_zip("26AS.txt", E.SAMPLE_26AS))

    checks += [("ZIP of the text export works", z.kind == "26as")]

    # --- image-only PDF must be refused with guidance --------------------
    try:
        extract("scan.pdf", make_scan())
        scan_msg = ""
    except IngestError as e:
        scan_msg = str(e)
    checks += [
        ("scanned PDF refused", "scan" in scan_msg.lower()),
        ("scan message tells you what to do", "portal" in scan_msg.lower()),
    ]

    # --- every document type classifies from PDF -------------------------
    for label, text, expect in [
        ("passbook", E.SAMPLE_PASSBOOKS[0], "passbook"),
        ("service history", E.SAMPLE_SERVICE_HISTORY, "service_history"),
        ("bank statement", E.SAMPLE_BANK, "bank"),
    ]:
        got = extract(f"{label}.pdf", make_pdf(text)).kind
        checks.append((f"PDF {label} detected", got == expect))

    pb = parse_passbook(extract("pb.pdf", make_pdf(E.SAMPLE_PASSBOOKS[0])).text)
    checks += [
        ("PDF passbook: member ID parsed", bool(pb["member_id"])),
        ("PDF passbook: joining date parsed", pb["doj"] is not None),
        ("PDF passbook: all 12 months parsed", len(pb["months"]) == 12),
    ]
    sh = parse_service_history(extract("sh.pdf", make_pdf(E.SAMPLE_SERVICE_HISTORY)).text)
    checks.append(("PDF service history: both records parsed", len(sh) == 2))

    # --- a full mixed-format upload --------------------------------------
    sorted_up = sort_uploads([
        ("26AS.pdf", make_pdf(E.SAMPLE_26AS)),
        ("pb1.pdf", make_pdf(E.SAMPLE_PASSBOOKS[0])),
        ("pb2.txt", E.SAMPLE_PASSBOOKS[1].encode()),
        ("history.zip", make_zip("h.txt", E.SAMPLE_SERVICE_HISTORY)),
        ("bank.pdf", make_pdf(E.SAMPLE_BANK)),
    ])
    checks += [
        ("mixed PDF/TXT/ZIP upload: nothing missing", sorted_up["missing"] == []),
        ("mixed upload: both passbooks found", len(sorted_up["found"]["passbook"]) == 2),
    ]

    # --- what is genuinely required ---------------------------------------
    # The interface tells people Form 26AS is optional. The code must agree,
    # or we send someone to omit their most sensitive document and then block
    # them for omitting it.
    minimal = sort_uploads([
        ("pb1.txt", E.SAMPLE_PASSBOOKS[0].encode()),
        ("pb2.txt", E.SAMPLE_PASSBOOKS[1].encode()),
        ("sh.txt", E.SAMPLE_SERVICE_HISTORY.encode()),
    ])
    no_pb = sort_uploads([("sh.txt", E.SAMPLE_SERVICE_HISTORY.encode())])
    only_26as = sort_uploads([("26as.txt", E.SAMPLE_26AS.encode())])
    no_sh = sort_uploads([("pb1.txt", E.SAMPLE_PASSBOOKS[0].encode())])
    checks += [
        ("passbook + service history alone is accepted", minimal["missing"] == []),
        ("omitting 26AS is explained, not silently ignored",
         any("Form 26AS" in r for r in minimal["reduced"])),
        ("omitting the bank statement is explained",
         any("bank statement" in r for r in minimal["reduced"])),
        # The gate used to demand passbook AND service history. Real members
        # frequently cannot get either - the EPFO portals are often down - and
        # turning them away with nothing served no one. We now accept whatever
        # arrived and narrow the claims instead.
        ("Form 26AS alone is accepted", only_26as["missing"] == []),
        ("a passbook alone is accepted", no_sh["missing"] == []),
        ("a missing service history is explained",
         any("service history" in r for r in no_sh["reduced"])),
        ("a missing passbook is explained",
         any("PF passbook" in r for r in only_26as["reduced"])),
        # Service history alone carries no accounts and no employers, so there
        # is genuinely nothing to report on.
        ("service history alone is still blocking", no_pb["missing"] != []),
        ("nothing recognisable IS still blocking",
         sort_uploads([("x.txt", b"hello world")])["missing"] != []),
    ]

    # Without the service history there is nothing to test against, so the
    # reconciler orphans every employer - including ones whose passbook we hold.
    # Those findings are unfounded and would send someone chasing trace requests
    # for healthy accounts, so they must be withheld.
    n26 = E.extract_names({"26as": E.SAMPLE_26AS})
    only26 = E.analyse(text_26as=E.SAMPLE_26AS, passbooks=[], service_history="",
                       bank="", names=n26)
    npb = E.extract_names({"26as": E.SAMPLE_26AS, "passbook": E.SAMPLE_PASSBOOKS})
    nohist = E.analyse(text_26as=E.SAMPLE_26AS, passbooks=E.SAMPLE_PASSBOOKS,
                       service_history="", bank="", names=npb)
    kinds26 = [c["kind"] for c in only26.result["contradictions"]]
    kindsnh = [c["kind"] for c in nohist.result["contradictions"]]
    checks += [
        ("one document does not crash the name check", only26.name_check is not None),
        ("26AS alone invents no orphan accounts", "ORPHAN_ACCOUNT" not in kinds26),
        ("no service history invents no orphan accounts",
         "ORPHAN_ACCOUNT" not in kindsnh),
        ("26AS alone still reports where you worked", len(only26.worklist) == 3),
        ("the worklist is in date order",
         [w["first"] for w in only26.worklist]
         == sorted(w["first"] for w in only26.worklist)),
        ("passbook balances survive a missing service history",
         nohist.total_balance > 0 and len(nohist.accounts) == 2),
        # The most dangerous sentence the site could print.
        ("an unchecked record is NOT reported as claimable", not only26.claimable),
        ("an unchecked record says so", only26.checked is False),
        ("a fully checked record is still marked checked", E.analyse().checked),
    ]

    # the engine must actually run on the minimal set
    names = E.extract_names({"passbook": E.SAMPLE_PASSBOOKS})
    a = E.analyse(text_26as="", passbooks=E.SAMPLE_PASSBOOKS,
                  service_history=E.SAMPLE_SERVICE_HISTORY, bank="", names=names)
    kinds = [c["kind"] for c in a.result["contradictions"]]
    checks += [
        ("minimal set still finds a wrong exit date", "EXIT_TOO_EARLY" in kinds),
        ("minimal set still finds a missing exit date", "MISSING_EXIT" in kinds),
        ("minimal set still reports balances", a.total_balance > 0),
        ("minimal set claims no orphans (needs 26AS)", "ORPHAN_ACCOUNT" not in kinds),
    ]

    print("=" * 70)
    print("  ingestion assertions")
    failures = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
    print(f"\n  RESULT: {'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    print("=" * 70)
    return 1 if failures else 0


if __name__ == "__main__":
    _s.exit(main())
