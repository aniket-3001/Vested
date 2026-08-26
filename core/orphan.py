"""
SPIKE F - Orphan account recovery path.

Question this spike answers:
    The solver already detects orphans: an employer in Form 26AS with no linked
    EPF member ID. But detection alone abandons the member - they cannot claim
    an account they cannot name, and not knowing the member ID is precisely why
    it was orphaned.

    Can we turn "you probably have money at X" into a named, ordered, evidenced
    sequence of steps that actually recovers it - and, critically, can we STAY
    SILENT when the money probably is not there?

The guard matters as much as the feature. EPF coverage is not universal:
establishments below the employee threshold need not be covered at all. Telling
someone they have forgotten savings when they do not is a cruel false positive.

Run:  python core/orphan.py
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from core.entity import score_pair  # noqa: E402
from core.gate import (  # noqa: E402
    EvidenceLedger,
    RenderedDoc,
    claim_gate,
)


# ---------------------------------------------------------------------------
# EPF establishment directory (mocked - EPFO publishes a searchable directory)
# ---------------------------------------------------------------------------
# Real member ID = establishment code (15 ch) + member number (7 digits).
# e.g. MHBAN0026403000 + 0001234  ->  MHBAN00264030000001234

@dataclass(frozen=True)
class Establishment:
    name: str
    code: str            # 15-char establishment code
    epf_covered: bool
    coverage_from: date | None


DIRECTORY = [
    Establishment("STARLIT RETAIL PRIVATE LIMITED", "MHBAN0026403000", True, date(2009, 4, 1)),
    Establishment("ACME TECHNOLOGIES PRIVATE LIMITED", "BLBNG0012345000", True, date(2015, 7, 1)),
    Establishment("BOREAL SYSTEMS PRIVATE LIMITED", "PNPUN0067890000", True, date(2018, 1, 1)),
    # Small employer, never EPF-covered. Must NOT generate a recovery promise.
    Establishment("KADAM & SONS TRADERS", "", False, None),
]


def resolve_establishment(employer_name: str) -> Establishment | None:
    """Reuses the Spike B matcher, with its discriminator guard intact."""
    best, best_score = None, 0.0
    for est in DIRECTORY:
        r = score_pair(employer_name, est.name)
        if r.linked and r.score > best_score:
            best, best_score = est, r.score
    return best


# ---------------------------------------------------------------------------
# Estimates - a separate type, because they may NEVER enter a legal filing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Estimate:
    """
    Deliberately not a Fact. Facts are evidence-backed and may be filed with
    EPFO; estimates are inferences shown to the member only. The claim gate
    rejects hedged language in filings, so keeping these apart at the type
    level stops an estimate leaking into a document someone signs.
    """
    low: int
    high: int
    basis: str
    # What was contributed, before interest. Interest has always been part of
    # low/high; keeping the principal beside it lets a page show the growth
    # rather than only the total.
    principal_low: int = 0
    principal_high: int = 0
    years: float = 0.0

    @property
    def interest_low(self) -> int:
        return max(0, self.low - self.principal_low)

    @property
    def interest_high(self) -> int:
        return max(0, self.high - self.principal_high)

    def render(self) -> str:
        return f"Rs {self.low:,} - Rs {self.high:,} (estimated; {self.basis})"


# PF is computed on basic + DA, but Form 26AS reports gross salary for TDS.
# Basic is typically 40-50% of gross, so any estimate from 26AS is a wide band.
BASIC_RATIO_LOW, BASIC_RATIO_HIGH = 0.40, 0.50
EPS_WAGE_CAP = 15000
EPS_RATE = 0.0833
EPF_RATE = 0.12
ANNUAL_INTEREST = 0.0815


def estimate_balance(gross_monthly: float, months: int, years_since_exit: float) -> Estimate:
    """Rough, clearly-banded estimate. Shown to the member, never filed."""
    def parts(ratio: float) -> tuple[float, float]:
        basic = gross_monthly * ratio
        employee = basic * EPF_RATE
        eps = min(basic, EPS_WAGE_CAP) * EPS_RATE
        employer_epf = max(0.0, basic * EPF_RATE - eps)
        monthly = employee + employer_epf
        principal = monthly * months
        # Interest accrues while the account sits inoperative.
        grown = principal * ((1 + ANNUAL_INTEREST) ** max(0.0, years_since_exit))
        return principal, grown

    p_low, c_low = parts(BASIC_RATIO_LOW)
    p_high, c_high = parts(BASIC_RATIO_HIGH)
    return Estimate(
        low=int(round(c_low, -2)),
        high=int(round(c_high, -2)),
        basis="basic pay assumed 40-50% of the gross reported in Form 26AS",
        principal_low=int(round(p_low, -2)),
        principal_high=int(round(p_high, -2)),
        years=round(max(0.0, years_since_exit), 1),
    )


# ---------------------------------------------------------------------------
# Likelihood assessment - the guard
# ---------------------------------------------------------------------------

LIKELY = "LIKELY"
UNCERTAIN = "UNCERTAIN"
UNLIKELY = "UNLIKELY"


@dataclass
class OrphanCandidate:
    employer_name: str
    tan: str
    first_seen: date
    last_seen: date
    months: int
    gross_monthly: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class Assessment:
    verdict: str
    reasons: list[str]
    establishment: Establishment | None
    estimate: Estimate | None


def assess(cand: OrphanCandidate, today: date) -> Assessment:
    reasons: list[str] = []
    est = resolve_establishment(cand.employer_name)

    if est is None:
        return Assessment(
            UNCERTAIN,
            ["Employer could not be matched to the EPF establishment directory. "
             "It may trade under a different registered name."],
            None, None,
        )

    if not est.epf_covered:
        return Assessment(
            UNLIKELY,
            [f"{est.name} is not on the EPF establishment register. Establishments "
             f"below the statutory employee threshold are not required to provide "
             f"EPF, so there is most likely no account to recover.",
             "No claim generated. Nothing is being promised here."],
            est, None,
        )

    if est.coverage_from and cand.first_seen < est.coverage_from:
        reasons.append(
            f"Employment began before this establishment's EPF coverage started "
            f"({est.coverage_from.isoformat()}). Early months may not be covered."
        )

    if cand.months < 3:
        return Assessment(
            UNLIKELY,
            reasons + [f"Only {cand.months} month(s) of employment. Any balance would "
                       f"be very small and may already have been settled."],
            est, None,
        )

    years_since = (today - cand.last_seen).days / 365.25
    estimate = estimate_balance(cand.gross_monthly, cand.months, years_since)
    reasons.append(
        f"{cand.months} months at an EPF-covered establishment with no linked "
        f"member ID in your UAN."
    )
    if years_since > 3:
        reasons.append(
            f"Last contribution about {years_since:.0f} years ago. Accounts with no "
            f"contribution for 36 months are classified inoperative, but the balance "
            f"remains yours and is claimable at any time."
        )
    return Assessment(LIKELY, reasons, est, estimate)


# ---------------------------------------------------------------------------
# Recovery plan
# ---------------------------------------------------------------------------

@dataclass
class Step:
    n: int
    action: str
    detail: str
    blocked_by: str | None = None


def build_recovery_plan(cand: OrphanCandidate, a: Assessment) -> list[Step]:
    if a.verdict == UNLIKELY:
        return []

    steps = [
        Step(1, "Trace the member ID",
             f"File an EPFiGMS request asking the EPFO office holding establishment "
             f"code {a.establishment.code if a.establishment else '(unresolved)'} to "
             f"identify member IDs registered against your PAN for "
             f"{cand.first_seen.strftime('%b %Y')} to {cand.last_seen.strftime('%b %Y')}."),
        Step(2, "Check your own records first",
             "An old payslip, Form 16, or offer letter often carries the PF number "
             "outright. This is faster than waiting on EPFO.",),
        Step(3, "File the transfer claim",
             "Once the member ID is known, file an online transfer request to move "
             "the balance into your current UAN.",
             blocked_by="member ID from step 1 or 2"),
        Step(4, "Escalate if untraceable",
             "If EPFO cannot locate the account, file an RTI with the regional office "
             "for member IDs registered against your PAN and that establishment code.",
             blocked_by="a negative or absent response to step 1"),
    ]
    if a.verdict == UNCERTAIN:
        steps.insert(0, Step(
            0, "Confirm the employer's registered name",
            "The employer could not be matched to the EPF register. Check the "
            "registered legal name on a payslip or Form 16 before filing.",
        ))
        for i, s in enumerate(steps):
            s.n = i
    return steps


# ---------------------------------------------------------------------------
# Generation - runs through the Spike E claim gate
# ---------------------------------------------------------------------------

def render_trace_request(
    *, member_name: str, uan: str, pan: str, cand: OrphanCandidate, est: Establishment
) -> RenderedDoc:
    body = f"""\
To: The Regional Provident Fund Commissioner

Subject: Request to trace Provident Fund member ID against PAN

I, {member_name}, holder of Universal Account Number {uan} and PAN {pan},
request identification of any Provident Fund member ID registered against my
PAN with the establishment below.

Establishment code: {est.code}
Period of employment: {cand.first_seen.strftime('%d-%m-%Y')} to {cand.last_seen.strftime('%d-%m-%Y')}

Tax deducted at source by this employer over that period is recorded in my
Form 26AS under TAN {cand.tan}. No member ID for this establishment is linked
to my Universal Account Number.

I request that any such account be identified so that the balance may be
transferred to my current account.
"""
    return RenderedDoc(
        title="Request to trace member ID",
        body=body,
        scope=cand.tan,
        annexure=list(cand.evidence),
    )


# ---------------------------------------------------------------------------

def build_ledger(cand: OrphanCandidate, est: Establishment, uan: str, pan: str) -> EvidenceLedger:
    led = EvidenceLedger()
    led.admit("UAN", uan, "passbook:header")
    led.admit("TAN", cand.tan, "26AS:deductor", employer=cand.tan)
    led.admit("DATE", cand.first_seen.strftime("%d-%m-%Y"), "26AS:txn#first", employer=cand.tan)
    led.admit("DATE", cand.last_seen.strftime("%d-%m-%Y"), "26AS:txn#last", employer=cand.tan)
    return led


def main() -> int:
    today = date(2025, 8, 20)
    failures = 0

    # --- Case 1: genuine orphan --------------------------------------------
    starlit = OrphanCandidate(
        employer_name="STARLIT RETAIL PVT LTD",
        tan="MUMS45678B",
        first_seen=date(2012, 8, 31),
        last_seen=date(2013, 6, 30),
        months=11,
        gross_monthly=24000.0,
        evidence=[
            "DATE: 31-08-2012  [26AS:MUMS45678B:txn#1]",
            "DATE: 30-06-2013  [26AS:MUMS45678B:txn#11]",
        ],
    )
    a1 = assess(starlit, today)
    print("=" * 74)
    print("  CASE 1 - forgotten pre-UAN account")
    print(f"    verdict     : {a1.verdict}")
    print(f"    establishment: {a1.establishment.code if a1.establishment else '-'}")
    if a1.estimate:
        print(f"    estimate    : {a1.estimate.render()}")
    for r in a1.reasons:
        print(f"      - {r}")
    plan1 = build_recovery_plan(starlit, a1)
    print("    recovery plan:")
    for s in plan1:
        blocked = f"  (needs: {s.blocked_by})" if s.blocked_by else ""
        print(f"      {s.n}. {s.action}{blocked}")

    doc = render_trace_request(
        member_name="SYNTHETIC TEST SUBJECT", uan="100999888777",
        pan="AAAPZ1234C", cand=starlit, est=a1.establishment,
    )
    led = build_ledger(starlit, a1.establishment, "100999888777", "AAAPZ1234C")
    led.admit("MEMBER_ID", a1.establishment.code, "directory:lookup", employer=starlit.tan)
    violations = claim_gate(doc, led)
    print(f"    claim gate  : {len(violations)} violation(s)"
          f"{'' if not violations else ' -> ' + str(violations[0].token)}")

    # --- Case 2: employer never EPF-covered --------------------------------
    kadam = OrphanCandidate(
        employer_name="KADAM AND SONS TRADERS", tan="PNEK11223C",
        first_seen=date(2014, 5, 31), last_seen=date(2015, 3, 31),
        months=11, gross_monthly=18000.0,
    )
    a2 = assess(kadam, today)
    print("\n  CASE 2 - small employer, never EPF-covered")
    print(f"    verdict: {a2.verdict}")
    for r in a2.reasons:
        print(f"      - {r}")
    plan2 = build_recovery_plan(kadam, a2)
    print(f"    recovery plan: {len(plan2)} steps (correctly silent)")

    # --- Case 3: too short to be worth chasing -----------------------------
    brief = OrphanCandidate(
        employer_name="ACME TECHNOLOGIES PVT LTD", tan="BLRA12345E",
        first_seen=date(2016, 1, 31), last_seen=date(2016, 3, 31),
        months=2, gross_monthly=30000.0,
    )
    a3 = assess(brief, today)
    print("\n  CASE 3 - two-month stint")
    print(f"    verdict: {a3.verdict}  ({a3.reasons[-1][:60]}...)")

    # --- Case 4: unmatched employer name -----------------------------------
    unknown = OrphanCandidate(
        employer_name="ZEPHYR MICROSYSTEMS LLP", tan="DELZ99887A",
        first_seen=date(2011, 4, 30), last_seen=date(2012, 3, 31),
        months=12, gross_monthly=21000.0,
    )
    a4 = assess(unknown, today)
    plan4 = build_recovery_plan(unknown, a4)
    print("\n  CASE 4 - employer not in the register")
    print(f"    verdict: {a4.verdict}  plan starts with: '{plan4[0].action}'" if plan4 else "")

    print("\n" + "-" * 74)
    print("  spike assertions")
    checks = [
        ("genuine orphan assessed LIKELY", a1.verdict == LIKELY),
        ("establishment code resolved", a1.establishment is not None and a1.establishment.code != ""),
        ("balance estimate produced as a range", a1.estimate is not None and a1.estimate.high > a1.estimate.low),
        ("recovery plan has 4 ordered steps", len(plan1) == 4),
        ("later steps declare what blocks them", any(s.blocked_by for s in plan1)),
        ("trace request passes the claim gate", not violations),
        ("non-covered employer -> UNLIKELY", a2.verdict == UNLIKELY),
        ("non-covered employer -> NO plan, no promise", plan2 == []),
        ("non-covered employer -> no balance estimate", a2.estimate is None),
        ("2-month stint -> UNLIKELY", a3.verdict == UNLIKELY),
        ("unmatched name -> UNCERTAIN, not a promise", a4.verdict == UNCERTAIN),
        ("unmatched name -> plan starts by confirming the name",
         bool(plan4) and "registered name" in plan4[0].action.lower()),
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
