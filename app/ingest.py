"""
File ingestion - uploaded document to plain text.

Privacy properties, which the interface promises and this module must actually
deliver:

  - nothing is written to disk at any point
  - file bytes are read into memory, converted, and dropped
  - no filename, no content, and no derived text is logged

Accepted: .txt (the TRACES text export), .pdf, and .zip (TRACES delivers the
text export zipped). Form 26AS PDFs and text exports are password-protected
with the member's date of birth as DDMMYYYY.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

MAX_BYTES = 8 * 1024 * 1024


class IngestError(Exception):
    """Carries a message written for the person who uploaded the file."""


@dataclass
class Extracted:
    text: str
    kind: str          # 26as | passbook | service_history | bank | unknown
    pages: int


# A caret-delimited TRACES export, identified by structure rather than wording:
# many carets, a TAN, and a TDS section code. This is a backstop for an export
# whose header text differs from the ones we have seen - without it the file is
# classified "unknown" and silently dropped.
_CARET_26AS = (re.compile(r"\b[A-Z]{4}\d{5}[A-Z]\b"),
               re.compile(r"\^\s*\d+\^19[0-9][A-Z]{0,2}\^", re.M))


def _detect(text: str) -> str:
    low = text.lower()
    if text.count("^") > 20 and all(p.search(text) for p in _CARET_26AS):
        return "26as"
    if re.search(r"form\s*26as|annual tax statement|tax credit statement", low):
        return "26as"
    if re.search(r"service history|date of exit", low) and "wage month" not in low:
        return "service_history"
    if re.search(r"passbook|wage month", low):
        return "passbook"
    if re.search(r"narration|statement of account|closing balance", low):
        return "bank"
    return "unknown"


def _from_pdf(data: bytes, password: str | None) -> tuple[str, int]:
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        raise IngestError("PDF support is unavailable on this server.")

    kwargs = {"password": password} if password else {}
    try:
        with pdfplumber.open(io.BytesIO(data), **kwargs) as pdf:
            pages = len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        # pdfminer raises PdfminerException with an EMPTY message for an
        # encrypted file, so matching on the message alone silently misreports
        # "password needed" as "damaged file" - on Form 26AS, which is password
        # protected by default. Check the container for /Encrypt instead.
        msg = str(e).lower()
        looks_encrypted = (
            b"/Encrypt" in data[:4096] or b"/Encrypt" in data[-4096:]
            or "password" in msg or "encrypt" in msg or "decrypt" in msg
        )
        if looks_encrypted:
            if password:
                raise IngestError(
                    "That password did not work. Form 26AS uses your date of "
                    "birth written as DDMMYYYY - for 14 August 1992 that is "
                    "14081992."
                )
            raise IngestError(
                "This PDF is password protected. Enter your date of birth as "
                "DDMMYYYY in the password box and try again."
            )
        raise IngestError(
            "This PDF could not be opened. It may be damaged, or it may be a "
            "format we do not handle yet."
        )

    if not text.strip():
        raise IngestError(
            "This PDF contains no readable text - it is most likely a scan or a "
            "photograph. Download the file again directly from the portal rather "
            "than scanning a printout."
        )
    return text, pages


def _from_zip(data: bytes, password: str | None) -> tuple[str, int]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise IngestError("This ZIP file could not be opened.")

    pwd = password.encode() if password else None
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        raise IngestError("This ZIP file is empty.")

    for name in names:
        try:
            inner = zf.read(name, pwd=pwd)
        except RuntimeError as e:
            if "password" in str(e).lower():
                raise IngestError(
                    "This ZIP is password protected. Enter your date of birth as "
                    "DDMMYYYY in the password box and try again."
                )
            raise IngestError("This ZIP file could not be read.")
        if name.lower().endswith(".pdf"):
            return _from_pdf(inner, password)
        try:
            return inner.decode("utf-8", errors="replace"), 1
        except Exception:
            continue
    raise IngestError("Nothing readable was found inside this ZIP file.")


def extract(filename: str, data: bytes, password: str | None = None) -> Extracted:
    if not data:
        raise IngestError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise IngestError(
            f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB. "
            f"Download it again from the portal rather than scanning it."
        )

    name = (filename or "").lower()
    if name.endswith(".zip") or data[:2] == b"PK":
        text, pages = _from_zip(data, password)
    elif name.endswith(".pdf") or data[:5] == b"%PDF-":
        text, pages = _from_pdf(data, password)
    else:
        text, pages = data.decode("utf-8", errors="replace"), 1

    if not text.strip():
        raise IngestError("No readable text was found in that file.")
    return Extracted(text=text, kind=_detect(text), pages=pages)


def sort_uploads(items: list[tuple[str, bytes]], password: str | None = None) -> dict:
    """
    Take whatever was uploaded and work out what each file is, rather than
    trusting which box it was dropped into. Returns the pieces the engine needs,
    plus a per-file report for the interface.
    """
    found: dict = {"26as": None, "passbook": [], "service_history": None, "bank": None}
    report: list[dict] = []

    for filename, data in items:
        if not data:
            continue
        try:
            ex = extract(filename, data, password)
        except IngestError as e:
            report.append({"file": filename, "ok": False, "kind": None, "message": str(e)})
            continue
        if ex.kind == "passbook":
            found["passbook"].append(ex.text)
        elif ex.kind == "26as":
            # Form 26AS is issued one file per ASSESSMENT YEAR, so a member with
            # any history has several. Keeping only the first silently threw
            # away most of their record while the report still said
            # "Recognised" - and 26AS is precisely the document where more
            # years means more chance of finding a forgotten account.
            found["26as"] = ((found["26as"] + chr(10) + ex.text)
                             if found["26as"] else ex.text)
        elif ex.kind != "unknown" and found.get(ex.kind) is None:
            found[ex.kind] = ex.text
        report.append({
            "file": filename,
            "ok": ex.kind != "unknown",
            "kind": ex.kind,
            "message": (
                "Recognised" if ex.kind != "unknown" else
                "Could not tell what this document is. Upload the file exactly as "
                "downloaded from the portal, without editing it."
            ),
        })

    # What we can conclude depends on which documents arrived, and the honest
    # answer is different for each combination - so gate on capability rather
    # than demanding a fixed set.
    #
    #   passbook        - the accounts themselves, balances, contributions
    #   service history - what EPFO ASSERTS about joining and leaving dates
    #
    # The service history is what every finding is tested against. Without it
    # the reconciler has nothing to contradict and orphans every employer,
    # including ones whose passbook we are holding, so date findings and
    # forgotten-account findings are both withheld rather than guessed.
    #
    # Form 26AS alone still supports a narrower, real answer: where you worked
    # and when, as the Income Tax Department recorded it. That is a worklist to
    # check your PF record against. Many members cannot obtain the EPFO
    # documents at all - the portals are frequently down - and turning them away
    # with nothing serves no one.
    missing = []
    if not found["passbook"] and not found["26as"]:
        missing.append("either a PF passbook or Form 26AS")

    reduced = []
    if not found["service_history"]:
        reduced.append(
            "Without your service history we cannot check joining and leaving "
            "dates, or tell a forgotten account from one we simply have not been "
            "shown - so no date findings are reported.")
    if not found["passbook"]:
        reduced.append(
            "Without a PF passbook we cannot show balances, contributions or "
            "pension - only where you worked and when.")
    if not found["26as"]:
        reduced.append(
            "Without Form 26AS we cannot find accounts you have forgotten, and "
            "findings rest on your PF record alone rather than being corroborated "
            "by an independent source.")
    if not found["bank"]:
        reduced.append(
            "Without a bank statement we cannot pin down the exact dates you "
            "were paid, only the months.")
    return {"found": found, "report": report, "missing": missing,
            "reduced": reduced}
