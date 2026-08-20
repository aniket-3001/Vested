"""
SPIKE E - Claim gate for generated legal documents.

Question this spike answers:
    The system drafts a Joint Declaration that a member signs and submits to
    EPFO. A hallucinated date or amount in that document is not a UX bug - it is
    a false statement to a government office, made under the member's name.

    Can we make unsupported facts STRUCTURALLY unable to survive into a
    generated document, rather than asking a model nicely not to invent them?

Approach:
    Every fact that may appear in output is first admitted to an EvidenceLedger
    with provenance - which document, which row. Rendering emits text plus the
    claims it believes it made. The gate then re-reads the RENDERED TEXT, pulls
    out every factual token independently, and requires each one to resolve to
    a ledger entry scoped to the right employer.

    The gate does not trust the renderer's own account of itself. That is the
    point: it verifies the artifact, not the intent.

Run:  python core/gate.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date


# ---------------------------------------------------------------------------
# Evidence ledger
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fact:
    kind: str          # DATE | AMOUNT | TAN | MEMBER_ID | ORG | UAN
    value: str         # canonical string form
    employer: str | None  # scope; None = member-level fact
    source: str        # provenance, e.g. "26AS:BLRA12345E:txn#12"

    def cite(self) -> str:
        return self.source


class EvidenceLedger:
    """Only facts admitted here may appear in generated output."""

    def __init__(self) -> None:
        self._facts: list[Fact] = []

    def admit(self, kind: str, value: str, source: str, employer: str | None = None) -> Fact:
        f = Fact(kind, value, employer, source)
        self._facts.append(f)
        return f

    def lookup(self, kind: str, value: str, employer: str | None) -> Fact | None:
        for f in self._facts:
            if f.kind != kind or f.value != value:
                continue
            # A member-level fact is valid in any scope. An employer-scoped fact
            # is valid ONLY in its own scope - this is what catches a real date
            # attributed to the wrong employer.
            if f.employer is None or f.employer == employer:
                return f
        return None

    def __len__(self) -> int:
        return len(self._facts)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@dataclass
class RenderedDoc:
    title: str
    body: str
    scope: str                      # employer this document concerns
    annexure: list[str] = field(default_factory=list)


def render_joint_declaration(
    *,
    member_name: str,
    uan: str,
    member_id: str,
    employer_display: str,
    employer_scope: str,
    recorded_doe: date,
    corrected_doe: date,
    supporting: list[Fact],
) -> RenderedDoc:
    body = f"""\
To: The Regional Provident Fund Commissioner

Subject: Joint Declaration for correction of Date of Exit

I, {member_name}, holder of Universal Account Number {uan}, submit that the
Date of Exit recorded against Member ID {member_id} for {employer_display} is
incorrect.

The record currently shows a Date of Exit of {recorded_doe.strftime('%d-%m-%Y')}.
Independent records establish that employment continued beyond that date. I
request that the Date of Exit be corrected to {corrected_doe.strftime('%d-%m-%Y')}.

The evidence relied upon is listed in the annexure to this declaration.
"""
    annexure = [f"{f.kind}: {f.value}  [{f.cite()}]" for f in supporting]
    return RenderedDoc(
        title="Joint Declaration - correction of Date of Exit",
        body=body,
        scope=employer_scope,
        annexure=annexure,
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

# Independently extract factual tokens from the RENDERED text.
TOKEN_PATTERNS = {
    "DATE": re.compile(r"\b(\d{2}-\d{2}-\d{4})\b"),
    "TAN": re.compile(r"\b([A-Z]{4}\d{5}[A-Z])\b"),
    "MEMBER_ID": re.compile(r"\b([A-Z]{5}\d{17})\b"),
    "UAN": re.compile(r"\b(\d{12})\b"),
    "AMOUNT": re.compile(r"(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d{2})?)"),
}

# Phrases that must never appear: hedging or invention in a legal filing.
FORBIDDEN = [
    re.compile(r"\b(approximately|roughly|around|about)\s+\d", re.I),
    re.compile(r"\b(I believe|it seems|possibly|presumably|may have been)\b", re.I),
    re.compile(r"\b(as per my recollection|to the best of my memory)\b", re.I),
]


@dataclass
class Violation:
    kind: str
    token: str
    detail: str


def claim_gate(doc: RenderedDoc, ledger: EvidenceLedger) -> list[Violation]:
    """
    Re-read the rendered artifact and require every factual token to resolve to
    a ledger entry in the correct employer scope. Anything unresolved is a
    hallucinated or misattributed fact and blocks the document.
    """
    violations: list[Violation] = []
    full_text = doc.body + "\n" + "\n".join(doc.annexure)

    for kind, pat in TOKEN_PATTERNS.items():
        for match in pat.findall(doc.body):
            value = match.replace(",", "") if kind == "AMOUNT" else match
            if ledger.lookup(kind, value, doc.scope) is None:
                # Distinguish "never seen" from "seen, but for another employer".
                elsewhere = any(
                    f.kind == kind and f.value == value for f in ledger._facts
                )
                detail = (
                    f"present in ledger but scoped to a different employer"
                    if elsewhere else
                    "no supporting evidence in ledger"
                )
                violations.append(Violation("UNSUPPORTED_FACT", f"{kind}={value}", detail))

    for pat in FORBIDDEN:
        m = pat.search(full_text)
        if m:
            violations.append(
                Violation("HEDGED_LANGUAGE", m.group(0), "speculative phrasing in a legal filing")
            )

    if not doc.annexure:
        violations.append(
            Violation("NO_ANNEXURE", "-", "assertions made with no evidence attached")
        )
    return violations


# ---------------------------------------------------------------------------
# Fixture: a real case, built from Spike D's confirmed evidence shape
# ---------------------------------------------------------------------------

def build_case() -> tuple[EvidenceLedger, dict, list[Fact]]:
    led = EvidenceLedger()

    led.admit("UAN", "100999888777", "passbook:header")
    led.admit("MEMBER_ID", "BLBNG00123450000001234", "passbook:header", employer="ACME_TECH")
    led.admit("TAN", "BLRA12345E", "26AS:deductor#1", employer="ACME_TECH")
    led.admit("DATE", "30-11-2020", "service_history:row#1", employer="ACME_TECH")

    supporting = [
        led.admit("DATE", "31-03-2021", "26AS:BLRA12345E:txn#12", employer="ACME_TECH"),
        led.admit("DATE", "28-02-2021", "26AS:BLRA12345E:txn#11", employer="ACME_TECH"),
        led.admit("DATE", "31-01-2021", "26AS:BLRA12345E:txn#10", employer="ACME_TECH"),
    ]
    # Another employer's fact - must NOT be usable in this document's scope.
    led.admit("MEMBER_ID", "PNPUN00678900000005678", "passbook:header", employer="BOREAL_SYS")

    case = dict(
        member_name="SYNTHETIC TEST SUBJECT",
        uan="100999888777",
        member_id="BLBNG00123450000001234",
        employer_display="ACME TECHNOLOGIES PRIVATE LIMITED",
        employer_scope="ACME_TECH",
        recorded_doe=date(2020, 11, 30),
        corrected_doe=date(2021, 3, 31),
    )
    return led, case, supporting


def main() -> int:
    led, case, supporting = build_case()
    failures = 0

    print("=" * 74)
    print(f"  ledger admitted {len(led)} facts with provenance\n")

    # --- 1. clean document --------------------------------------------------
    doc = render_joint_declaration(supporting=supporting, **case)
    v = claim_gate(doc, led)
    print("  CASE 1 - clean document")
    print(f"    violations: {len(v)}  {'(passes gate)' if not v else v}")
    ok_clean = not v

    # --- 2. hallucinated date ----------------------------------------------
    bad = render_joint_declaration(supporting=supporting, **{**case, "corrected_doe": date(2021, 6, 30)})
    v2 = claim_gate(bad, led)
    print("\n  CASE 2 - date invented by the generator (30-06-2021 never observed)")
    for x in v2:
        print(f"    CAUGHT  {x.kind}: {x.token} - {x.detail}")
    ok_halluc = any(x.token.endswith("30-06-2021") for x in v2)

    # --- 3. misattributed fact ---------------------------------------------
    wrong = render_joint_declaration(
        supporting=supporting, **{**case, "member_id": "PNPUN00678900000005678"}
    )
    v3 = claim_gate(wrong, led)
    print("\n  CASE 3 - real member ID, WRONG employer scope")
    for x in v3:
        print(f"    CAUGHT  {x.kind}: {x.token} - {x.detail}")
    ok_scope = any("different employer" in x.detail for x in v3)

    # --- 4. hedged language -------------------------------------------------
    hedged = render_joint_declaration(supporting=supporting, **case)
    hedged.body = hedged.body.replace(
        "Independent records establish that employment continued beyond that date.",
        "I believe employment continued for approximately 4 more months.",
    )
    v4 = claim_gate(hedged, led)
    print("\n  CASE 4 - speculative phrasing")
    for x in v4:
        print(f"    CAUGHT  {x.kind}: '{x.token}' - {x.detail}")
    ok_hedge = any(x.kind == "HEDGED_LANGUAGE" for x in v4)

    # --- 5. no annexure -----------------------------------------------------
    bare = render_joint_declaration(supporting=[], **case)
    v5 = claim_gate(bare, led)
    ok_annex = any(x.kind == "NO_ANNEXURE" for x in v5)
    print(f"\n  CASE 5 - assertions with no evidence attached: "
          f"{'CAUGHT' if ok_annex else 'MISSED'}")

    print("\n" + "-" * 74)
    print("  spike assertions")
    checks = [
        ("clean document passes the gate", ok_clean),
        ("hallucinated date is blocked", ok_halluc),
        ("real fact in wrong employer scope is blocked", ok_scope),
        ("speculative phrasing is blocked", ok_hedge),
        ("document with no annexure is blocked", ok_annex),
    ]
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1

    print(f"\n  RESULT: {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    print("=" * 74)

    if ok_clean:
        print("\n--- rendered document (gate-approved) ---")
        print(doc.body)
        print("Annexure:")
        for line in doc.annexure:
            print(f"  - {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
