"""
Orchestration layer - wires the proven spike modules into one analysis call.

The web layer must contain no reasoning. Everything decided here is decided by
the same code the spikes exercise, so what the demo shows is what the tests
prove.
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


from core.reconcile import (  # noqa: E402
    AssertedService,
    Observation,
    Reconciler,
    assert_no_denial_path,
)
from core.parsers import (  # noqa: E402
    parse_26as,
    parse_passbook,
    parse_service_history,
    verify_26as,
)
from core.gate import (  # noqa: E402
    EvidenceLedger,
    claim_gate,
    render_joint_declaration,
)
from core.orphan import (  # noqa: E402
    Assessment,
    OrphanCandidate,
    assess,
    build_recovery_plan,
    render_trace_request,
)

from app.models import get_backend  # noqa: E402
from app.name_match import compare, worst_pair  # noqa: E402

# The real date, not a pinned one. Every rule that reasons about elapsed time
# depends on it: whether two months have passed since the last contribution,
# how much interest an untraced account has accrued, whether an open exit date
# means "still employed" or "nobody closed it". A hardcoded date silently rots,
# and this one had drifted a year behind the module that renders it.
TODAY = date.today()

PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")


def extract_identity(text_26as: str, parsed_pbs: list[dict], names: dict) -> dict:
    """Who this record belongs to, read from the documents themselves."""
    pan = None
    m = PAN_RE.search(text_26as or "")
    if m:
        pan = m.group(1)
    uan = next((pb.get("uan") for pb in parsed_pbs if pb.get("uan")), None)
    dob = next((pb.get("dob") for pb in parsed_pbs if pb.get("dob")), None)
    # Passbooks from different employers can disagree about a date of birth, and
    # a DOB mismatch is one of the causes of rejection named in the Lok Sabha.
    # Record the disagreement rather than picking a winner.
    dobs = {pb.get("dob") for pb in parsed_pbs if pb.get("dob")}
    name = (names.get("PAN / Form 26AS")
            or next(iter(names.values()), None)
            or "Member")
    return {"name": name, "uan": uan, "pan": pan, "dob": dob,
            "dob_conflict": sorted(d.isoformat() for d in dobs) if len(dobs) > 1 else []}


# ---------------------------------------------------------------------------
# Sample documents - format-accurate, entirely synthetic.
# Starlit appears in Form 26AS but has no passbook and no member ID: the orphan.
# ---------------------------------------------------------------------------

SAMPLE_26AS = """\
Form 26AS
Annual Tax Statement under Section 203AA of the Income Tax Act, 1961

Permanent Account Number (PAN)    AAAPZ1234C
Name of Assessee                  RAHUL KUMAR SINGH

PART A - Details of Tax Deducted at Source

Sr. No.  Name of Deductor                 TAN of Deductor  Total Amount Paid/Credited  Total Tax Deducted  Total TDS Deposited
1        STARLIT RETAIL PRIVATE LIMITED     MUMS45678B       264000.00                   13200.00            13200.00
Sr. No.  Section  Transaction Date  Status of Booking  Date of Booking  Remarks  Amount Paid/Credited  Tax Deducted  TDS Deposited
1        192      31-Aug-2012       F                  15-Oct-2012               24000.00              1200.00       1200.00
2        192      30-Sep-2012       F                  15-Oct-2012               24000.00              1200.00       1200.00
3        192      31-Oct-2012       F                  14-Jan-2013               24000.00              1200.00       1200.00
4        192      30-Nov-2012       F                  14-Jan-2013               24000.00              1200.00       1200.00
5        192      31-Dec-2012       F                  14-Jan-2013               24000.00              1200.00       1200.00
6        192      31-Jan-2013       F                  10-Apr-2013               24000.00              1200.00       1200.00
7        192      28-Feb-2013       F                  10-Apr-2013               24000.00              1200.00       1200.00
8        192      31-Mar-2013       F                  10-Apr-2013               24000.00              1200.00       1200.00
9        192      30-Apr-2013       F                  12-Jul-2013               24000.00              1200.00       1200.00
10       192      31-May-2013       F                  12-Jul-2013               24000.00              1200.00       1200.00
11       192      30-Jun-2013       F                  12-Jul-2013               24000.00              1200.00       1200.00

Sr. No.  Name of Deductor                 TAN of Deductor  Total Amount Paid/Credited  Total Tax Deducted  Total TDS Deposited
2        ACME TECHNOLOGIES PRIVATE LIMITED  BLRA12345E       780000.00                   46800.00            46800.00
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
3        BOREAL SYSTEMS PRIVATE LIMITED     PNEB67890K       240000.00                   14400.00            14400.00
Sr. No.  Section  Transaction Date  Status of Booking  Date of Booking  Remarks  Amount Paid/Credited  Tax Deducted  TDS Deposited
1        192      31-May-2021       F                  10-Jul-2021               80000.00              4800.00       4800.00
2        192      30-Jun-2021       F                  10-Jul-2021               80000.00              4800.00       4800.00
3        192      31-Jul-2021       F                  05-Sep-2021               80000.00              4800.00       4800.00
"""

SAMPLE_PASSBOOKS = ["""\
EPF Member Passbook

Establishment ID / Name   BLBNG0012345000 / ACME TECHNOLOGIES PVT LTD
Member ID                 BLBNG00123450000001234
Member Name               RAHUL K SINGH
Date of Birth             25-12-1990
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
""", """\
EPF Member Passbook

Establishment ID / Name   PNPUN0067890000 / BOREAL SYSTEMS PVT LTD
Member ID                 PNPUN00678900000005678
Member Name               RAHUL SINGH
Date of Birth             25-12-1990
Date of Joining (EPF)     01-05-2021
UAN                       100999888777

Wage Month    Employee Share    Employer Share    Pension Contribution
May-2021      9600              3350              1250
Jun-2021      9600              3350              1250
Jul-2021      9600              3350              1250
"""]

SAMPLE_SERVICE_HISTORY = """\
Service History

Member ID                     Establishment            Date of Joining   Date of Exit
BLBNG00123450000001234        ACME TECHNOLOGIES PVT LTD  01-04-2020        30-11-2020
PNPUN00678900000005678        BOREAL SYSTEMS PVT LTD     01-05-2021        -
"""

# Bank statement. Narrations are deliberately messy - this is what the model
# classifier is for, and it is the only evidence source with day-level pay dates.
SAMPLE_BANK = """\
Statement of Account
Account Holder   RAHUL SINGH

Date        Narration                                              Amount     Type
30-04-2020  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY APR20     65,000.00  CR
31-05-2020  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY MAY20     65,000.00  CR
30-06-2020  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY JUN20     65,000.00  CR
05-07-2020  INT.CR QUARTERLY INTEREST CREDIT                          412.00  CR
31-12-2020  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY DEC20     65,000.00  CR
31-01-2021  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY JAN21     65,000.00  CR
28-02-2021  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY FEB21     65,000.00  CR
15-03-2021  UPI/P2A/408123456789/RENT                              18,000.00  DR
31-03-2021  NEFT CR-HDFC0000060-ACME TECHNOLOGIES-SALARY MAR21     65,000.00  CR
"""

# Name as each document spells it. This variation is ordinary and is exactly
# what the ABHA linkage auto-rejects as suspected identity fraud.
DOCUMENT_NAMES = {
    "PAN / Form 26AS": "RAHUL KUMAR SINGH",
    "EPFO passbook": "RAHUL K SINGH",
    "Bank statement": "RAHUL SINGH",
    "Aadhaar": "राहुल कुमार सिंह",
}

# Employers are resolved from the uploaded documents, never from a lookup table.
# A 26AS deductor is identified by TAN; an EPF account by establishment code.
# Nothing connects the two except the employer's NAME - which is exactly the
# problem core/entity.py exists to solve.

def _titlecase(name: str) -> str:
    small = {"and", "of", "the"}
    words = []
    for w in name.split():
        lw = w.lower().strip(".,")
        if lw in ("pvt", "pvt.", "private"):
            words.append("Private")
        elif lw in ("ltd", "ltd.", "limited"):
            words.append("Limited")
        elif lw in small:
            words.append(lw)
        elif len(w) <= 3 and w.isupper():
            words.append(w)          # keep acronyms: TCS, HCL, L&T
        else:
            words.append(w.capitalize())
    return " ".join(words)


class EmployerRegistry:
    """
    One entry per real-world employer, assembled from whatever documents were
    supplied. Keys are stable within a session and derived from the evidence,
    so an employer nobody has seen before works exactly like a known one.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, dict] = {}

    def _match(self, name: str) -> str | None:
        from core.entity import score_pair
        best, best_score = None, 0.0
        for key, e in self._by_key.items():
            r = score_pair(name, e["name"])
            if r.linked and r.score > best_score:
                best, best_score = key, r.score
        return best

    def add(self, name: str, *, tan: str | None = None,
            member_id: str | None = None) -> str:
        key = self._match(name)
        if key is None:
            key = (member_id[:15] if member_id else tan or
                   re.sub(r"[^A-Z0-9]", "", name.upper())[:12])
            self._by_key[key] = {"name": name, "tans": set(), "member_ids": set()}
        e = self._by_key[key]
        if tan:
            e["tans"].add(tan)
        if member_id:
            e["member_ids"].add(member_id)
        # Prefer the longest rendering as the display name - it is the least
        # abbreviated, so the most recognisable to the member.
        if len(name) > len(e["name"]):
            e["name"] = name
        return key

    def key_for_tan(self, tan: str) -> str | None:
        for k, e in self._by_key.items():
            if tan in e["tans"]:
                return k
        return None

    def key_for_member_id(self, mid: str) -> str | None:
        for k, e in self._by_key.items():
            if mid in e["member_ids"]:
                return k
        return None

    def display(self, key: str) -> str:
        e = self._by_key.get(key)
        return _titlecase(e["name"]) if e else key

    def has_member_id(self, key: str) -> bool:
        e = self._by_key.get(key)
        return bool(e and e["member_ids"])


# ---------------------------------------------------------------------------

@dataclass
class IngestStep:
    label: str
    detail: str
    ok: bool


@dataclass
class OrphanResult:
    candidate: OrphanCandidate
    assessment: Assessment
    plan: list
    document: object | None
    gate_violations: list


@dataclass
class Account:
    """One PF account as the member would recognise it."""
    member_id: str
    employer_key: str
    employer: str
    doj: object
    doe: object
    months: int
    balance: float
    pension: float
    blocking: int          # defects on this account that stop a claim
    orphan: bool = False
    # Month by month, as the passbook prints it. Empty for an orphan, which by
    # definition has no passbook of its own.
    rows: list = field(default_factory=list)


@dataclass
class NameCheck:
    names: dict
    same_person: bool
    confidence: float
    reasons: list
    weakest: tuple
    canonical: str


@dataclass
class Analysis:
    ingest: list[IngestStep] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    orphans: list[OrphanResult] = field(default_factory=list)
    documents: dict = field(default_factory=dict)
    deductors: list = field(default_factory=list)
    name_check: NameCheck | None = None
    backend: str = "offline"
    salary_events: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    reduced: list = field(default_factory=list)
    identity: dict = field(default_factory=lambda: {
        "name": "Member", "uan": None, "pan": None,
        "dob": None, "dob_conflict": []})
    employers: object = None
    # True when Form 26AS arrived without any PF record to test it against.
    timeline_only: bool = False
    # Two different questions, and they have different answers. Dates need
    # EPFO's asserted service history; contributions need only the passbook and
    # Form 26AS, which is what most members can actually obtain.
    dates_checked: bool = False
    contributions_checked: bool = False
    # The documents this was built from, so a service history typed in later can
    # re-reconcile the whole record. Memory only, same lifetime as the session.
    docs: dict | None = None
    # True when the service history was typed by the member rather than read
    # from a file. Changes nothing in the reconciler - it is still EPFO's
    # assertion - but the member should be told which of the two it is.
    history_typed: bool = False
    worklist: list = field(default_factory=list)
    # Raw evidence and EPFO's assertion, retained for the timeline view.
    observations: list = field(default_factory=list)
    asserted: list = field(default_factory=list)
    # Claims already filed. Read only; we never write to it.
    claim_history: list = field(default_factory=list)
    # PF account numbers printed inside a passbook that are not themselves one
    # of the accounts we could read. Reported, never interpreted.
    related_ids: list = field(default_factory=list)

    @property
    def total_balance(self) -> float:
        return sum(a.balance for a in self.accounts if not a.orphan)

    @property
    def total_pension(self) -> float:
        return sum(a.pension for a in self.accounts if not a.orphan)

    @property
    def checked(self) -> bool:
        """
        Did we actually test the record? Absence of findings is not a clean
        bill of health when there was nothing to test against.
        """
        return self.dates_checked

    @property
    def claimable(self) -> bool:
        return self.checked and self.result["blocking_count"] == 0

    @property
    def service_months(self) -> int:
        """Total EPS-eligible service across every linked account."""
        return sum(a.months for a in self.accounts if not a.orphan)

    @property
    def pension_eligible(self) -> bool:
        """EPS-95 needs 10 years of eligible service for a monthly pension."""
        return self.service_months >= 120

    @property
    def forgotten_low(self) -> float:
        return sum(o.assessment.estimate.low for o in self.orphans
                   if o.assessment.estimate)

    @property
    def kyc_items(self) -> list:
        """
        KYC read from the member's own documents.

        Lives here rather than in a page so that the claim page and the KYC page
        cannot drift apart and give the same member two different answers.
        """
        from core.epfo_rules import kyc_review
        nc = self.name_check
        return kyc_review(names=(nc.names if nc else {}),
                          identity=(self.identity or {}),
                          same_person=(nc.same_person if nc else True),
                          weakest=(nc.weakest if nc else None))

    @property
    def kyc_ok(self) -> bool:
        from core.epfo_rules import kyc_ready
        return kyc_ready(self.kyc_items)

    @property
    def settlement(self):
        """What would actually happen if this member filed today."""
        from core.epfo_rules import settlement_verdict
        return settlement_verdict(
            balance=self.total_balance,
            blocking=self.result.get("blocking_count", 0),
            kyc_ready=self.kyc_ok,
            checked=self.checked,
        )

    @property
    def blocking(self) -> list[dict]:
        return [c for c in self.result["contradictions"] if c["severity"] == "BLOCKING"]

    @property
    def other(self) -> list[dict]:
        return [c for c in self.result["contradictions"]
                if c["severity"] != "BLOCKING" and c["kind"] != "ORPHAN_ACCOUNT"]


BANK_ROW = __import__("re").compile(
    r"^(\d{2}-\d{2}-\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s+(CR|DR)\s*$")


def parse_bank(text: str) -> list[dict]:
    """Rows only. Whether a row is salary is decided by the model backend."""
    rows = []
    for line in text.splitlines():
        m = BANK_ROW.match(line.strip())
        if not m:
            continue
        d, mm, yy = m.group(1).split("-")
        rows.append({
            "date": date(int(yy), int(mm), int(d)),
            "narration": m.group(2).strip(),
            "amount": float(m.group(3).replace(",", "")),
            "type": m.group(4),
        })
    return rows


def check_names(names: dict, backend) -> NameCheck:
    w = worst_pair(names, backend)
    if w is None:
        # Fewer than two documents carry a name, so there is no pair to
        # disagree. Say that, rather than crashing - a member who could only
        # obtain one document must still get an answer, and a crash here
        # surfaces as "we could not read your file", blaming their document
        # for our defect.
        only = next(iter(names.values()), "")
        return NameCheck(
            names=names,
            same_person=True,
            confidence=0.0,
            reasons=["Only one document carries a name, so there is nothing to "
                     "check it against. Spelling mismatches between documents "
                     "are a common cause of rejection, so this check is worth "
                     "re-running once you have your PF record."],
            weakest=None,
            canonical=only,
        )
    # The canonical spelling is the longest fully-expanded Latin form: it is the
    # one that satisfies every other document, so it is what to standardise on.
    latin = [v for v in names.values() if v.isascii()]
    canonical = max(latin, key=len) if latin else next(iter(names.values()))
    return NameCheck(
        names=names,
        same_person=w[2].same_person,
        confidence=w[2].confidence,
        reasons=w[2].reasons,
        weakest=(w[0], w[1]),
        canonical=canonical,
    )


NAME_FIELDS = [
    r"name\s+of\s+assessee\s{2,}(.+)",
    r"member\s+name\s{2,}(.+)",
    r"account\s+holder\s{2,}(.+)",
]

NAME_LABEL = {
    "26as": "PAN / Form 26AS",
    "passbook": "EPFO passbook",
    "bank": "Bank statement",
}


def extract_names(found: dict) -> dict:
    """Pull the name as each uploaded document spells it."""
    import re as _re
    out: dict[str, str] = {}
    for kind, label in NAME_LABEL.items():
        blobs = found.get(kind) or []
        if isinstance(blobs, str):
            blobs = [blobs]
        for i, blob in enumerate(blobs):
            for pat in NAME_FIELDS:
                m = _re.search(pat, blob, _re.I)
                if m:
                    key = label if i == 0 else f"{label} ({i + 1})"
                    out[key] = m.group(1).strip()
                    break
    return out or DOCUMENT_NAMES


SALARY_SECTIONS = {"192", "192A"}


def is_salary_section(section) -> bool:
    """
    True only for TDS on salary. Anything else in Form 26AS - interest,
    dividend, rent, commission - is income, not evidence of employment.

    Our own fixtures carry section 192 as an integer; a real caret export
    carries it as text, alongside codes like "194A" that int() would reject.
    """
    if section is None:
        return True          # a document with no section column at all
    return str(section).strip().upper() in SALARY_SECTIONS


def merge_deductors(deductors: list[dict]) -> list[dict]:
    """
    One entry per TAN, across every assessment year supplied.

    Form 26AS comes one file per assessment year, so the same employer appears
    once per year. Left unmerged, the orphan estimate reads only the first
    block it finds - understating months and the monthly average - and the
    same employer is listed several times in the worklist.

    Run this AFTER verify_26as: each block's stated total is per-year, and
    merging first would break the arithmetic check that guards the parse.
    """
    by_tan: dict[str, dict] = {}
    for d in deductors:
        cur = by_tan.get(d["tan"])
        if cur is None:
            by_tan[d["tan"]] = dict(d, transactions=list(d["transactions"]))
            continue
        cur["transactions"].extend(d["transactions"])
        cur["total_paid"] += d["total_paid"]
        cur["total_tds"] += d["total_tds"]
        # Employers rename themselves between years; the longest rendering is
        # the one most likely to be the full legal name.
        if len(d["name"]) > len(cur["name"]):
            cur["name"] = d["name"]
    for d in by_tan.values():
        d["transactions"].sort(key=lambda t: t["txn_date"])
    return list(by_tan.values())


def merge_passbooks(parsed: list[dict]) -> list[dict]:
    """
    Combine per-financial-year passbook pages into one entry per account.

    The closing balance is taken from the most recent year rather than summed:
    each page's closing balance is already cumulative, and it includes interest
    that the contribution column does not. Summing them would multiply the
    member's savings by the number of files they happened to upload.
    """
    by_id: dict[str, list[dict]] = {}
    loose: list[dict] = []
    for pb in parsed:
        mid = pb.get("member_id")
        if mid:
            by_id.setdefault(mid, []).append(pb)
        else:
            loose.append(pb)

    merged: list[dict] = []
    for mid, group in by_id.items():
        group.sort(key=lambda p: max(p["months"]) if p["months"] else date.min)
        latest = group[-1]
        rows = [r for p in group for r in p["rows"]]
        months = sorted({m for p in group for m in p["months"]})
        out = dict(latest)
        out["rows"] = rows
        out["months"] = months
        if latest.get("closing"):
            out["balance"] = (latest["closing"]["employee"]
                              + latest["closing"]["employer"])
            out["pension"] = latest["closing"]["pension"]
        else:
            out["balance"] = sum(r["employee"] + r["employer"] for r in rows)
            out["pension"] = sum(r["pension"] for r in rows)
        out["establishment"] = next(
            (p["establishment"] for p in group if p.get("establishment")), None)
        out["doj"] = next((p["doj"] for p in group if p.get("doj")), None)
        out["other_member_ids"] = sorted(
            {x for p in group for x in p.get("other_member_ids", [])})
        merged.append(out)
    return merged + loose


def analyse(
    text_26as: str = SAMPLE_26AS,
    passbooks: list[str] | None = None,
    service_history: str = SAMPLE_SERVICE_HISTORY,
    bank: str = SAMPLE_BANK,
    names: dict | None = None,
) -> Analysis:
    passbooks = passbooks if passbooks is not None else SAMPLE_PASSBOOKS
    # Optional documents may legitimately be absent; treat missing as empty
    # rather than letting a None reach a parser.
    text_26as = text_26as or ""
    service_history = service_history or ""
    bank = bank or ""
    a = Analysis()
    backend = get_backend()
    a.backend = backend.name

    # --- ingest ------------------------------------------------------------
    deductors = parse_26as(text_26as)
    problems = verify_26as(deductors)
    # Verified per-year first, then collapsed to one entry per employer.
    deductors = merge_deductors(deductors)
    a.deductors = deductors

    # Count what the words actually say: employers who paid SALARY, and salary
    # entries. A real 26AS is mostly bank interest, so counting every deductor
    # and every row would report a number the member cannot recognise.
    salary_n = sum(1 for t in (t for d in deductors for t in d["transactions"])
                   if is_salary_section(t.get("section")))
    employers_n = sum(1 for d in deductors
                      if any(is_salary_section(t.get("section"))
                             for t in d["transactions"]))
    other_n = sum(len(d["transactions"]) for d in deductors) - salary_n
    a.ingest.append(IngestStep(
        "Form 26AS read",
        f"{employers_n} employer{'' if employers_n == 1 else 's'}, "
        f"{salary_n} salary entries"
        + (f" ({other_n} interest or other entries ignored)" if other_n else ""),
        bool(deductors),
    ))
    a.ingest.append(IngestStep(
        "Figures checked",
        "Every employer's entries add up to their stated total"
        if not problems else problems[0],
        not problems,
    ))

    parsed_pbs = [parse_passbook(p) for p in passbooks]
    a.ingest.append(IngestStep(
        "PF passbooks read",
        f"{len(parsed_pbs)} accounts, "
        f"{sum(len(p['months']) for p in parsed_pbs)} months of contributions",
        all(p["member_id"] for p in parsed_pbs),
    ))

    history = parse_service_history(service_history)
    a.ingest.append(IngestStep(
        "EPFO service record read",
        f"{len(history)} employment records as EPFO currently holds them",
        bool(history),
    ))

    # --- bank statement: the model decides what is salary -------------------
    bank_rows = parse_bank(bank)
    salary = []
    for r in bank_rows:
        if r["type"] != "CR":
            continue
        verdict = backend.classify_narration(r["narration"])
        if verdict["is_salary"]:
            salary.append({**r, **verdict})
    a.salary_events = salary
    a.ingest.append(IngestStep(
        "Bank statement read",
        f"{len(salary)} salary credits identified out of {len(bank_rows)} "
        f"transactions, using the {backend.name} classifier",
        bool(salary),
    ))

    # --- name consistency across documents ----------------------------------
    a.name_check = check_names(names or DOCUMENT_NAMES, backend)
    a.ingest.append(IngestStep(
        "Names matched across documents",
        f"{len(a.name_check.names)} spellings resolve to one person"
        if a.name_check.same_person else
        f"spellings do NOT resolve to one person - record linkage unsafe",
        a.name_check.same_person,
    ))

    # --- resolve employers from the documents -------------------------------
    # The live passbook is issued one file per financial year, so ten uploads
    # can be four accounts. Merging on the member ID is what makes the count
    # the member recognises - without it we report ten employers they never
    # had, and split one balance across ten rows.
    parsed_pbs = merge_passbooks(parsed_pbs)

    reg = EmployerRegistry()
    for pb in parsed_pbs:
        if not pb.get("member_id"):
            continue
        # A real passbook does not always print the establishment name in a
        # form we can isolate, but the member ID embeds the establishment code
        # in its first 15 characters. That is enough to keep accounts distinct
        # and correctly grouped; the name is cosmetic, the code is the identity.
        reg.add(pb.get("establishment")
                or f"Establishment {pb['member_id'][:15]}",
                member_id=pb["member_id"])
    for d in deductors:
        reg.add(d["name"], tan=d["tan"])
    a.employers = reg
    a.identity = extract_identity(text_26as, parsed_pbs, names or DOCUMENT_NAMES)

    # --- observations ------------------------------------------------------
    observations: list[Observation] = []
    for d in deductors:
        key = reg.key_for_tan(d["tan"])
        if not key:
            continue
        for t in d["transactions"]:
            # Only section 192 is TDS on SALARY. A real Form 26AS is mostly
            # section 194A - interest paid by banks - and treating that as
            # employment evidence turns the member's bank into an employer,
            # then invents a forgotten PF account for it. On the first real
            # export we saw, interest outnumbered salary nine to one.
            if not is_salary_section(t.get("section")):
                continue
            observations.append(Observation(
                key, t["txn_date"], "TDS_26AS", "salary TDS",
                amount=t["amount_paid"],
            ))
    for pb in parsed_pbs:
        key = reg.key_for_member_id(pb["member_id"])
        if not key:
            continue
        for m in pb["months"]:
            observations.append(Observation(key, m, "EPF_CONTRIB"))

    # Bank salary credits, attributed to an employer via the entity matcher.
    # A credit we cannot confidently attribute is dropped rather than guessed.
    from core.entity import score_pair  # noqa: E402
    for s in salary:
        hint = s.get("employer_hint") or ""
        best, best_score = None, 0.0
        for k in reg._by_key:
            r = score_pair(hint, reg.display(k))
            if r.linked and r.score > best_score:
                best, best_score = k, r.score
        if best is None:
            # Fall back to the raw narration, which carries more tokens.
            for k in reg._by_key:
                r = score_pair(s["narration"], reg.display(k))
                if r.linked and r.score > best_score:
                    best, best_score = k, r.score
        if best:
            observations.append(Observation(
                best, s["date"], "BANK_SALARY", "salary credit",
                amount=s["amount"],
            ))

    asserted = [
        AssertedService(reg.key_for_member_id(h["member_id"]), h["member_id"],
                        h["doj"], h["doe"])
        for h in history if reg.key_for_member_id(h["member_id"])
    ]

    a.result = Reconciler(observations, asserted, TODAY).run()
    # Kept so the timeline view can redraw the evidence without
    # re-reading the documents. Same memory-only lifetime as the rest.
    a.observations = list(observations)
    a.asserted = list(asserted)
    assert_no_denial_path(a.result)

    # An ORPHAN_ACCOUNT finding means "employment evidence with no linked member
    # ID". That conclusion is only available once we have looked at the member
    # IDs. With no passbook and no service history there is no PF record at all,
    # so the reconciler marks EVERY employer orphaned - and we would tell someone
    # they have forgotten accounts they have not forgotten, and send them chasing
    # trace requests for accounts that are perfectly healthy.
    #
    # What Form 26AS alone genuinely supports is narrower: this is where you
    # worked, and these are the months you were paid. That is a worklist to check
    # against your PF record, not a set of findings about it.
    #
    # The trigger is the service history alone. With passbooks but no history we
    # still hold member IDs, yet the reconciler has no asserted service to link
    # them to - so it orphans even the employers whose passbook we are holding.
    a.timeline_only = not parsed_pbs and not history and bool(deductors)
    a.dates_checked = bool(history)
    # A gap check is only meaningful for an employer we hold both records for.
    _pf = {o.employer_key for o in observations if o.source == "EPF_CONTRIB"}
    _tds = {o.employer_key for o in observations if o.source == "TDS_26AS"}
    a.contributions_checked = bool(_pf & _tds)
    if not history:
        a.result["contradictions"] = [
            c for c in a.result["contradictions"] if c["kind"] != "ORPHAN_ACCOUNT"
        ]
        a.result["blocking_count"] = sum(
            1 for c in a.result["contradictions"] if c["severity"] == "BLOCKING")
        a.result["claim_status"] = ("WILL_BE_REJECTED" if a.result["blocking_count"]
                                    else "NOT_CHECKED")
        for ded in deductors:
            # Salary only, for the same reason the observations are filtered:
            # a bank that paid interest is a deductor, not an employer, and
            # listing it under "where you worked" would be simply false.
            sal = [t for t in ded["transactions"]
                   if is_salary_section(t.get("section"))]
            if not sal:
                continue
            months = [t["txn_date"] for t in sal]
            a.worklist.append({
                "employer": ded["name"],
                "tan": ded["tan"],
                "first": min(months) if months else None,
                "last": max(months) if months else None,
                "months": len(sal),
            })
        a.worklist.sort(key=lambda w: w["first"] or date.min)

    # --- documents for correctable defects ---------------------------------
    for c in a.result["contradictions"]:
        if c["kind"] != "EXIT_TOO_EARLY":
            continue
        key = c["employer"]
        svc = next(s for s in asserted if s.employer_key == key)
        corrected = a.result["corrected_timeline"][key][1]
        corrected_date = date.fromisoformat(corrected)

        led = EvidenceLedger()
        led.admit("UAN", (a.identity["uan"] or ""), "passbook:header")
        led.admit("MEMBER_ID", svc.member_id, "passbook:header", employer=key)
        led.admit("DATE", svc.doe.strftime("%d-%m-%Y"), "service_history", employer=key)
        supporting = []
        for o in sorted((o for o in observations
                         if o.employer_key == key and o.source == "TDS_26AS"
                         and o.when > svc.doe),
                        key=lambda o: o.when, reverse=True)[:3]:
            supporting.append(led.admit(
                "DATE", o.when.strftime("%d-%m-%Y"),
                f"26AS:{o.employer_key}:salary entry", employer=key,
            ))
        led.admit("DATE", corrected_date.strftime("%d-%m-%Y"),
                  "reconciliation:corrected boundary", employer=key)

        doc = render_joint_declaration(
            member_name=a.identity["name"], uan=(a.identity["uan"] or ""), member_id=svc.member_id,
            employer_display=reg.display(key).upper(), employer_scope=key,
            recorded_doe=svc.doe, corrected_doe=corrected_date, supporting=supporting,
        )
        a.documents[key] = {"doc": doc, "violations": claim_gate(doc, led)}

    # --- orphans -----------------------------------------------------------
    for c in a.result["contradictions"]:
        if c["kind"] != "ORPHAN_ACCOUNT":
            continue
        key = c["employer"]
        obs = [o for o in observations if o.employer_key == key]
        ded = next((d for d in deductors if reg.key_for_tan(d["tan"]) == key), None)
        if not ded or not obs:
            continue
        # Salary only: averaging in interest or commission would put a number
        # on the page that no payslip could ever match.
        sal_txns = [t for t in ded["transactions"]
                    if is_salary_section(t.get("section"))]
        amounts = [t["amount_paid"] for t in sal_txns] or [0.0]
        cand = OrphanCandidate(
            employer_name=reg.display(key),
            tan=ded["tan"],
            first_seen=min(o.when for o in obs),
            last_seen=max(o.when for o in obs),
            months=len(sal_txns),
            gross_monthly=sum(amounts) / len(amounts),
            evidence=[
                f"Salary entry {t['txn_date'].strftime('%d-%m-%Y')}  "
                f"[Form 26AS, {ded['tan']}]"
                for t in ded["transactions"][:3]
            ],
        )
        asmt = assess(cand, TODAY)
        plan = build_recovery_plan(cand, asmt)
        doc = violations = None
        if asmt.establishment and asmt.verdict == "LIKELY":
            doc = render_trace_request(
                member_name=a.identity["name"], uan=(a.identity["uan"] or ""),
                pan=(a.identity["pan"] or ""), cand=cand, est=asmt.establishment,
            )
            led = EvidenceLedger()
            led.admit("UAN", (a.identity["uan"] or ""), "passbook:header")
            led.admit("TAN", cand.tan, "26AS:deductor", employer=cand.tan)
            led.admit("DATE", cand.first_seen.strftime("%d-%m-%Y"),
                      "26AS:first entry", employer=cand.tan)
            led.admit("DATE", cand.last_seen.strftime("%d-%m-%Y"),
                      "26AS:last entry", employer=cand.tan)
            violations = claim_gate(doc, led)
        a.orphans.append(OrphanResult(cand, asmt, plan, doc, violations or []))

    own = {pb.get("member_id") for pb in parsed_pbs if pb.get("member_id")}
    a.related_ids = sorted({x for pb in parsed_pbs
                            for x in pb.get("other_member_ids", [])} - own)

    # --- accounts, as the member would recognise them -----------------------
    blocking_by_emp: dict[str, int] = {}
    for c in a.result["contradictions"]:
        if c["severity"] != "BLOCKING":
            continue
        for key in c["employer"].split(" | "):
            blocking_by_emp[key] = blocking_by_emp.get(key, 0) + 1

    for pb in parsed_pbs:
        key = reg.key_for_member_id(pb["member_id"])
        if not key:
            continue
        svc = next((s for s in asserted if s.member_id == pb["member_id"]), None)
        a.accounts.append(Account(
            member_id=pb["member_id"],
            employer_key=key,
            employer=reg.display(key),
            doj=svc.doj if svc else pb["doj"],
            doe=svc.doe if svc else None,
            months=len(pb["months"]),
            balance=pb.get("balance", 0.0),
            pension=pb.get("pension", 0.0),
            blocking=blocking_by_emp.get(key, 0),
            rows=list(pb.get("rows") or []),
        ))
    for o in a.orphans:
        if o.assessment.verdict != "LIKELY":
            continue
        a.accounts.append(Account(
            member_id="not yet traced",
            employer_key=o.candidate.tan,
            employer=o.candidate.employer_name,
            doj=o.candidate.first_seen,
            doe=o.candidate.last_seen,
            months=o.candidate.months,
            balance=0.0, pension=0.0, blocking=0, orphan=True,
        ))

    return a


if __name__ == "__main__":
    r = analyse()
    for s in r.ingest:
        print(f"  {'OK ' if s.ok else 'ERR'}  {s.label}: {s.detail}")
    print(f"\n  status: {r.result['claim_status']}  blocking: {r.result['blocking_count']}")
    for c in r.result["contradictions"]:
        print(f"    [{c['severity']:11}] {c['kind']:18} {c['employer']}")
    print(f"\n  documents generated: {len(r.documents)}")
    for k, v in r.documents.items():
        print(f"    {k}: {len(v['violations'])} gate violations")
    print(f"  orphans: {len(r.orphans)}")
    for o in r.orphans:
        est = o.assessment.estimate.render() if o.assessment.estimate else "-"
        print(f"    {o.candidate.employer_name}: {o.assessment.verdict}  {est}")
        print(f"      gate violations: {len(o.gate_violations)}")
