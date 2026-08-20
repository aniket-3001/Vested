"""
SPIKE B - Employer entity resolution across three record formats.

Question this spike answers:
    The same employer appears as a deductor name in Form 26AS, an establishment
    name in the EPF passbook, and a mangled narration string in a bank
    statement. Can we link them reliably - and, more importantly, can we AVOID
    linking genuinely different legal entities that share a brand prefix?

The hard negatives are the point. "Infosys Limited" and "Infosys BPM Limited"
are different establishments with different PF codes. Merging them would
fabricate an overlap and send a member to argue a false case with EPFO.

No real data required. Run:  python core/entity.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

LEGAL_SUFFIXES = {
    "limited", "ltd", "pvt", "private", "llp", "inc", "incorporated",
    "corp", "corporation", "co", "company", "plc",
}

# Noise that banks prepend/append to salary narrations.
BANK_NOISE = {
    "neft", "imps", "rtgs", "cr", "dr", "sal", "salary", "sala", "credit",
    "ach", "upi", "by", "trf", "transfer", "payment", "pymt", "inf", "mmt",
}

# Tokens that look like reference numbers, IFSC codes, dates.
REF_PAT = re.compile(r"^[a-z]{0,4}\d{3,}[a-z0-9]*$")
IFSC_PAT = re.compile(r"^[a-z]{4}0[a-z0-9]{6}$")
MONTH_PAT = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d{0,4}$")

# Well-known contractions. In production this is a learned/curated table; the
# spike only needs enough to prove the mechanism.
ABBREV = {
    "tcs": "tata consultancy services",
    "hcl": "hcl",
    "hdfc": "hdfc",
    "icici": "icici",
    "lt": "larsen toubro",
    "l&t": "larsen toubro",
    "tech": "technologies",
    "techno": "technologies",
    "svcs": "services",
    "ser": "services",
    "serv": "services",
    "sys": "systems",
    "intl": "international",
    "ind": "industries",
    "mfg": "manufacturing",
    "sol": "solutions",
    "soln": "solutions",
    "ent": "enterprises",
}


def normalise(raw: str) -> list[str]:
    s = raw.lower()
    s = re.sub(r"[^a-z0-9&\s]", " ", s)
    tokens = [t for t in s.split() if t]

    out: list[str] = []
    for t in tokens:
        if IFSC_PAT.match(t) or REF_PAT.match(t) or MONTH_PAT.match(t):
            continue
        if t in BANK_NOISE or t in LEGAL_SUFFIXES:
            continue
        expanded = ABBREV.get(t, t)
        out.extend(expanded.split())
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
# Three signals combined:
#   1. token overlap (Jaccard on the token sets)
#   2. ordered-prefix agreement - brand names lead, so a shared head matters
#   3. DISCRIMINATOR PENALTY - tokens present in one and absent in the other
#      that are known entity-splitting words (bpm, enterprises, infosystems...)
#
# Signal 3 is what stops the brand-prefix false merges.

DISCRIMINATORS = {
    "bpm", "bps", "enterprises", "infosystems", "infotech", "retail",
    "finance", "capital", "insurance", "bank", "foundation", "trust",
    "labs", "research", "consulting", "digital", "global", "ventures",
    "healthcare", "power", "energy", "logistics", "realty", "properties",
}


@dataclass
class MatchResult:
    score: float
    linked: bool
    reason: str


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _head_agreement(a: list[str], b: list[str]) -> float:
    """How much of the leading brand portion agrees."""
    n = min(len(a), len(b), 3)
    if n == 0:
        return 0.0
    hits = sum(1 for i in range(n) if a[i] == b[i])
    if hits == n:
        return 1.0
    # Allow fuzzy on the first token only (handles typos/truncation).
    first = SequenceMatcher(None, a[0], b[0]).ratio() if a and b else 0.0
    return max(hits / n, first * 0.8)


def score_pair(x: str, y: str) -> MatchResult:
    ax, ay = normalise(x), normalise(y)
    sx, sy = set(ax), set(ay)

    if not sx or not sy:
        return MatchResult(0.0, False, "empty after normalisation")

    jac = _jaccard(sx, sy)
    head = _head_agreement(ax, ay)

    # Discriminator asymmetry: a splitting token on exactly one side.
    disc_only = (sx ^ sy) & DISCRIMINATORS
    penalty = 0.45 * len(disc_only)

    raw = 0.45 * jac + 0.55 * head
    score = max(0.0, raw - penalty)

    linked = score >= 0.62
    if disc_only and not linked:
        reason = f"blocked by discriminator(s): {sorted(disc_only)}"
    elif linked:
        reason = f"jaccard={jac:.2f} head={head:.2f}"
    else:
        reason = f"below threshold (jaccard={jac:.2f} head={head:.2f})"
    return MatchResult(round(score, 3), linked, reason)


# ---------------------------------------------------------------------------
# Labelled corpus - real-world-shaped variants across the three formats
# ---------------------------------------------------------------------------
# (form_26as_deductor, epf_establishment_or_bank_narration, should_link)

CORPUS: list[tuple[str, str, bool]] = [
    # --- true positives: same entity, three different renderings -------------
    ("TATA CONSULTANCY SERVICES LIMITED", "TATA CONSULTANCY SERVICES LTD", True),
    ("TATA CONSULTANCY SERVICES LIMITED", "NEFT CR-HDFC0000060-TATA CONSULTANCY SER-SALARY", True),
    ("TATA CONSULTANCY SERVICES LIMITED", "TCS LIMITED", True),
    ("INFOSYS LIMITED", "INFOSYS LTD", True),
    ("WIPRO LIMITED", "SAL/WIPRO LIMITED/JUN24", True),
    ("LARSEN & TOUBRO LIMITED", "L&T LTD", True),
    ("HCL TECHNOLOGIES LIMITED", "HCL TECHNOLOGIES LTD", True),
    ("HCL TECHNOLOGIES LIMITED", "IMPS CR HCL TECH LTD SALARY", True),
    ("BOREAL SYSTEMS PRIVATE LIMITED", "BOREAL SYS PVT LTD", True),
    ("GRAMEEN TEXTILES MANUFACTURING CO", "GRAMEEN TEXTILES MFG", True),
    ("STARLIT RETAIL PRIVATE LIMITED", "ACH-STARLIT RETAIL PVT LTD-SAL", True),
    ("ACME TECHNOLOGIES PRIVATE LIMITED", "ACME TECHNO PVT LTD", True),

    # --- hard negatives: shared brand, DIFFERENT legal entity ---------------
    ("INFOSYS LIMITED", "INFOSYS BPM LIMITED", False),
    ("WIPRO LIMITED", "WIPRO ENTERPRISES LIMITED", False),
    ("HCL TECHNOLOGIES LIMITED", "HCL INFOSYSTEMS LIMITED", False),
    ("TATA CONSULTANCY SERVICES LIMITED", "TATA CAPITAL LIMITED", False),
    ("RELIANCE INDUSTRIES LIMITED", "RELIANCE RETAIL LIMITED", False),
    ("ICICI BANK LIMITED", "ICICI SECURITIES LIMITED", False),
    ("BOREAL SYSTEMS PRIVATE LIMITED", "BOREAL LABS PRIVATE LIMITED", False),
    ("ACME TECHNOLOGIES PRIVATE LIMITED", "ACME LOGISTICS PRIVATE LIMITED", False),

    # --- easy negatives -----------------------------------------------------
    ("INFOSYS LIMITED", "TATA CONSULTANCY SERVICES LIMITED", False),
    ("GRAMEEN TEXTILES MANUFACTURING CO", "STARLIT RETAIL PRIVATE LIMITED", False),
]


def main() -> int:
    tp = fp = tn = fn = 0
    errors: list[str] = []

    print(f"{'':4} {'score':>6}  pair")
    print("-" * 88)
    for a, b, expected in CORPUS:
        r = score_pair(a, b)
        ok = (r.linked == expected)
        if expected and r.linked:
            tp += 1
        elif expected and not r.linked:
            fn += 1
        elif not expected and r.linked:
            fp += 1
        else:
            tn += 1

        mark = "ok  " if ok else "MISS"
        if not ok:
            errors.append(f"{a}  <>  {b}  ({r.reason})")
        short_b = b if len(b) <= 42 else b[:39] + "..."
        print(f"{mark} {r.score:>6.3f}  {a[:34]:34} <> {short_b}")

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print("-" * 88)
    print(f"  pairs={total}  TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"  precision={precision:.3f}  recall={recall:.3f}  f1={f1:.3f}")

    if errors:
        print("\n  misclassified:")
        for e in errors:
            print(f"    - {e}")

    # Precision matters far more than recall here: a false merge fabricates an
    # overlap and sends a member to argue a wrong case with EPFO. A missed link
    # only means we ask for one more document.
    print("\n--- spike assertions ---")
    checks = [
        ("precision >= 0.95 (false merges are the dangerous error)", precision >= 0.95),
        ("recall >= 0.80", recall >= 0.80),
        ("zero false merges on hard negatives", fp == 0),
    ]
    failures = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1

    print(f"\nRESULT: {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
