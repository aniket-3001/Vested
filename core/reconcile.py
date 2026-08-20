"""
SPIKE A - Employment timeline reconciliation core.

Question this spike answers:
    Given noisy, multi-granularity evidence from independent sources, can we
    (a) detect the specific contradictions that block an EPF claim, and
    (b) propose a corrected timeline with the evidence that supports it?

No real data required. Runs on synthetic scenarios that mirror documented
EPFO failure modes.

Deliberately NOT an LLM. The output must be contestable line by line, so the
core is a weighted constraint reconciliation over interval evidence.

Run:  python core/reconcile.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable


# ---------------------------------------------------------------------------
# Source reliability model
# ---------------------------------------------------------------------------
# Each source is trusted differently for two distinct things:
#   presence  - "this person was employed here at this time"
#   boundary  - "this is exactly when employment started/ended"
#
# EPF contribution records are excellent evidence of presence but carry only
# wage-MONTH granularity, so they are weak evidence of an exact boundary.
# The EPFO service record asserts exact boundaries but is precisely the thing
# under test - it is the least trusted, because it is typed by an employer.

SOURCE_MODEL = {
    "EPF_CONTRIB":  {"presence": 0.95, "boundary": 0.35, "granularity": "month"},
    "TDS_26AS":     {"presence": 0.90, "boundary": 0.70, "granularity": "day"},
    "BANK_SALARY":  {"presence": 0.65, "boundary": 0.75, "granularity": "day"},
    "EPF_SERVICE":  {"presence": 0.50, "boundary": 0.30, "granularity": "day"},
}

BLOCKING = "BLOCKING"
DEGRADED = "DEGRADED"
OPPORTUNITY = "OPPORTUNITY"

SEVERITY_RANK = {BLOCKING: 0, DEGRADED: 1, OPPORTUNITY: 2}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Observation:
    """A point-in-time signal that the member was employed by `employer_key`."""
    employer_key: str
    when: date
    source: str
    note: str = ""
    amount: float | None = None  # used to separate salary from settlement payouts

    @property
    def granularity(self) -> str:
        return SOURCE_MODEL[self.source]["granularity"]

    def cite(self) -> str:
        g = "month" if self.granularity == "month" else "day"
        stamp = self.when.strftime("%Y-%m") if g == "month" else self.when.isoformat()
        return f"{self.source}@{stamp}" + (f" ({self.note})" if self.note else "")


@dataclass(frozen=True)
class AssertedService:
    """What EPFO's service history currently claims. The thing under test."""
    employer_key: str
    member_id: str
    doj: date
    doe: date | None  # None => never marked, employment reads as still open


@dataclass
class Contradiction:
    kind: str
    employer_key: str
    severity: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    proposed_fix: str = ""
    correction_route: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "employer": self.employer_key,
            "severity": self.severity,
            "detail": self.detail,
            "evidence": self.evidence,
            "proposed_fix": self.proposed_fix,
            "correction_route": self.correction_route,
        }


@dataclass
class SupportWindow:
    """Independent (non-EPF_SERVICE) evidence envelope for one employer."""
    employer_key: str
    earliest: date
    latest: date
    sources: set[str]
    observations: list[Observation]

    @property
    def independent_source_count(self) -> int:
        return len(self.sources - {"EPF_SERVICE"})

    def confidence(self) -> float:
        """Corroboration across independent sources, not volume within one."""
        indep = self.sources - {"EPF_SERVICE"}
        if not indep:
            return 0.0
        # 1 - product of (1 - presence_reliability) across distinct sources.
        p_miss = 1.0
        for s in indep:
            p_miss *= (1.0 - SOURCE_MODEL[s]["presence"])
        return round(1.0 - p_miss, 4)


# ---------------------------------------------------------------------------
# Correction routing - which EPFO pathway can actually fix each defect
# ---------------------------------------------------------------------------
# Grounded in the documented 2026 rules: a member may self-mark an EXIT once
# two months have passed since the last contribution and the UAN is verified.
# A wrong DATE OF JOINING, or an already-wrong exit date, cannot be self-fixed.

SELF_SERVICE = "Self-service (Mark Exit) - member can fix without employer"
JOINT_DECL = "Digital Joint Declaration - employer must initiate"
GRIEVANCE = "EPFiGMS grievance, then RTI if unanswered"
CLAIM_ORPHAN = "Transfer/withdrawal claim against the orphaned member ID"


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _next_month(key: str) -> str:
    """'2020-12' -> '2021-01'. Used to collapse consecutive gaps into one run."""
    y, m = (int(x) for x in key.split("-"))
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------

class Reconciler:
    def __init__(
        self,
        observations: Iterable[Observation],
        asserted: Iterable[AssertedService],
        today: date,
    ) -> None:
        self.observations = list(observations)
        self.asserted = list(asserted)
        self.today = today

    # -- evidence aggregation ------------------------------------------------

    def support_windows(self) -> dict[str, SupportWindow]:
        by_employer: dict[str, list[Observation]] = {}
        for o in self.observations:
            if o.source == "EPF_SERVICE":
                continue
            by_employer.setdefault(o.employer_key, []).append(o)

        windows: dict[str, SupportWindow] = {}
        for emp, obs in by_employer.items():
            obs.sort(key=lambda o: o.when)
            windows[emp] = SupportWindow(
                employer_key=emp,
                earliest=obs[0].when,
                latest=obs[-1].when,
                sources={o.source for o in obs},
                observations=obs,
            )
        return windows

    # -- individual defect detectors ----------------------------------------

    def _check_missing_exit(self, svc: AssertedService, win: SupportWindow | None) -> Contradiction | None:
        if svc.doe is not None:
            return None
        if win is None:
            return None
        stale_months = months_between(win.latest, self.today)
        if stale_months < 2:
            # Still within the window where contributions may simply be ongoing.
            return None
        return Contradiction(
            kind="MISSING_EXIT",
            employer_key=svc.employer_key,
            severity=BLOCKING,
            detail=(
                f"No date of exit recorded for member ID {svc.member_id}. "
                f"Last independent evidence of employment is {month_key(win.latest)}, "
                f"{stale_months} months ago. EPFO reads this employment as still active, "
                f"which blocks both transfer and final settlement."
            ),
            evidence=[o.cite() for o in win.observations[-3:]],
            proposed_fix=f"Set date of exit to end of {month_key(win.latest)} or later.",
            correction_route=SELF_SERVICE if stale_months >= 2 else JOINT_DECL,
        )

    @staticmethod
    def _looks_like_settlement(before: list[Observation], after: list[Observation]) -> bool:
        """
        Full-and-final settlement generates TDS *after* the real exit date, so
        trailing 26AS entries are NOT automatically proof that the exit date is
        wrong. Treating them as proof would generate false corrections at scale.

        Heuristic - a trailing payout is probably a settlement when:
          (a) no EPF contribution accompanies it (employers do not remit PF on
              F&F), and
          (b) it is a short tail, and
          (c) its amount breaks the established monthly salary pattern.
        """
        if any(o.source == "EPF_CONTRIB" for o in after):
            return False  # PF was still being remitted => genuinely employed
        if len({month_key(o.when) for o in after}) > 2:
            return False  # too long to be a settlement tail

        prior = sorted(o.amount for o in before if o.amount is not None)
        tail = [o.amount for o in after if o.amount is not None]
        if not prior or not tail:
            return False
        median = prior[len(prior) // 2]
        if median <= 0:
            return False
        # A payout materially different from the monthly norm reads as F&F.
        return any(abs(a - median) / median > 0.35 for a in tail)

    def _check_exit_too_early(self, svc: AssertedService, win: SupportWindow | None) -> Contradiction | None:
        if svc.doe is None or win is None:
            return None
        if win.latest <= svc.doe:
            return None

        later = [o for o in win.observations if o.when > svc.doe]
        earlier = [o for o in win.observations if o.when <= svc.doe]
        indep_sources = {o.source for o in later}

        if self._looks_like_settlement(earlier, later):
            return Contradiction(
                kind="TRAILING_PAYOUT",
                employer_key=svc.employer_key,
                severity=DEGRADED,
                detail=(
                    f"TDS appears after the recorded exit {svc.doe.isoformat()}, but with no "
                    f"accompanying PF remittance and an amount that breaks the monthly salary "
                    f"pattern. This most likely reflects a full-and-final settlement rather "
                    f"than continued employment. Not treated as proof the exit date is wrong."
                ),
                evidence=[o.cite() for o in later],
                proposed_fix=(
                    "No correction filed on this basis. Confirm with your payslip or F&F "
                    "statement before disputing the exit date."
                ),
                correction_route=GRIEVANCE,
            )

        severity = BLOCKING if len(indep_sources) >= 2 else DEGRADED
        return Contradiction(
            kind="EXIT_TOO_EARLY",
            employer_key=svc.employer_key,
            severity=severity,
            detail=(
                f"Recorded exit {svc.doe.isoformat()}, but {len(later)} independent "
                f"observation(s) from {len(indep_sources)} source(s) place employment "
                f"as late as {month_key(win.latest)}."
            ),
            evidence=[o.cite() for o in later],
            proposed_fix=f"Correct date of exit to end of {month_key(win.latest)}.",
            correction_route=JOINT_DECL,
        )

    def _check_join_too_early(self, svc: AssertedService, win: SupportWindow | None) -> Contradiction | None:
        if win is None:
            return None
        gap = months_between(svc.doj, win.earliest)
        if gap <= 1:
            return None
        return Contradiction(
            kind="JOIN_SUSPECT",
            employer_key=svc.employer_key,
            severity=DEGRADED,
            detail=(
                f"Recorded joining date {svc.doj.isoformat()} precedes the first "
                f"independent evidence ({month_key(win.earliest)}) by {gap} months. "
                f"Commonly caused by HRMS defaulting to the offer-letter date."
            ),
            evidence=[o.cite() for o in win.observations[:3]],
            proposed_fix=f"Verify joining date against {month_key(win.earliest)} evidence.",
            correction_route=JOINT_DECL,
        )

    def _check_overlaps(
        self, intervals: dict[str, tuple[date, date]], basis: str
    ) -> list[Contradiction]:
        """
        Two employments that appear concurrent.

        Run against TWO different timelines, because they mean different things:

        basis='asserted'  - EPFO's current records already overlap. This is why
                            the transfer is failing right now.
        basis='corrected' - our proposed correction WOULD create an overlap. If
                            we filed it, EPFO would reject the correction too.
                            Catching this stops us sending members to file
                            paperwork that is doomed before it is submitted.
        """
        out: list[Contradiction] = []
        items = sorted(intervals.items(), key=lambda kv: kv[1][0])
        for i in range(len(items) - 1):
            a_key, (_, a_end) = items[i]
            b_key, (b_start, _) = items[i + 1]
            if a_end < b_start:
                continue
            days = (a_end - b_start).days + 1

            if basis == "asserted":
                out.append(
                    Contradiction(
                        kind="SERVICE_OVERLAP",
                        employer_key=f"{a_key} | {b_key}",
                        severity=BLOCKING,
                        detail=(
                            f"Service at {a_key} (ends {a_end.isoformat()}) overlaps "
                            f"{b_key} (starts {b_start.isoformat()}) by {days} day(s). "
                            f"EPFO reads this as dual employment and halts auto-transfer "
                            f"with 'Date of Joining overlaps with previous employer'."
                        ),
                        evidence=[f"asserted:{a_key}[..{a_end}]", f"asserted:{b_key}[{b_start}..]"],
                        proposed_fix=(
                            "Resolve by correcting whichever boundary the independent "
                            "evidence contradicts."
                        ),
                        correction_route=JOINT_DECL,
                    )
                )
            else:
                out.append(
                    Contradiction(
                        kind="CORRECTION_CONFLICT",
                        employer_key=f"{a_key} | {b_key}",
                        severity=DEGRADED,
                        detail=(
                            f"The correction implied by the evidence would extend {a_key} to "
                            f"{a_end.isoformat()}, overlapping {b_key} from {b_start.isoformat()} "
                            f"by {days} day(s). Filed as-is, EPFO would reject the correction "
                            f"itself as dual employment. This needs resolving before anything "
                            f"is submitted."
                        ),
                        evidence=[f"corrected:{a_key}[..{a_end}]", f"asserted:{b_key}[{b_start}..]"],
                        proposed_fix=(
                            "Do not file yet. Establish which employment genuinely ended first "
                            "(payslips, relieving letter, or a genuine dual-employment "
                            "declaration) before submitting."
                        ),
                        correction_route=GRIEVANCE,
                    )
                )
        return out

    def _check_orphans(self, windows: dict[str, SupportWindow]) -> list[Contradiction]:
        """Employers with independent evidence but no EPF member ID at all."""
        known = {s.employer_key for s in self.asserted}
        out: list[Contradiction] = []
        for emp, win in windows.items():
            if emp in known:
                continue
            if win.independent_source_count == 0:
                continue
            span = months_between(win.earliest, win.latest) + 1
            out.append(
                Contradiction(
                    kind="ORPHAN_ACCOUNT",
                    employer_key=emp,
                    severity=OPPORTUNITY,
                    detail=(
                        f"Independent evidence of {span} month(s) of employment at {emp} "
                        f"({month_key(win.earliest)} to {month_key(win.latest)}), but no "
                        f"linked EPF member ID. Likely an un-transferred account from "
                        f"before UAN linkage."
                    ),
                    evidence=[o.cite() for o in win.observations[:3]],
                    proposed_fix=f"Trace member ID for {emp} and file a transfer claim.",
                    correction_route=CLAIM_ORPHAN,
                )
            )
        return out

    # -- boundary inference --------------------------------------------------

    def corrected_timeline(self, windows: dict[str, SupportWindow]) -> dict[str, tuple[date, date]]:
        """
        Weighted boundary inference. Where independent evidence extends past an
        asserted boundary, the evidence wins - because the asserted record is the
        least reliable source in the model.
        """
        out: dict[str, tuple[date, date]] = {}
        for svc in self.asserted:
            win = windows.get(svc.employer_key)
            start, end = svc.doj, (svc.doe or self.today)
            if win is not None:
                if win.latest > end:
                    end = win.latest
                if win.earliest < start:
                    start = win.earliest
            out[svc.employer_key] = (start, end)
        return out

    # -- orchestration -------------------------------------------------------

    def _check_contribution_gaps(self) -> list[Contradiction]:
        """
        Months an employer deducted tax but deposited no provident fund.

        This is the one defect class that needs no service history at all, and
        that matters more than it sounds: the service history is the hardest of
        the four documents to obtain, and until now every check we ran depended
        on it. A member who could only get their passbook and their Form 26AS
        got a page that said "not yet known" about everything.

        The comparison is deliberately narrow, because the ways it could be
        wrong are all knowable in advance:

          - Only employers we hold BOTH a passbook and 26AS salary rows for.
            An employer with no passbook may simply not be EPF-covered, which
            is a different finding and not one we can make without the history.
          - Only months strictly INSIDE the passbook's own span. At the edges,
            a missing month is indistinguishable from starting mid-month or a
            final settlement, and March PF is routinely deposited in April.
            Between two contributions there is no such ambiguity: they were
            employed, tax was deducted, and no PF arrived.
          - Consecutive months are reported as one finding, not several, so a
            six-month gap does not become six identical rows.

        What is left is unambiguous. Money was withheld from a payslip and did
        not reach the account.
        """
        by_emp: dict[str, dict[str, set]] = {}
        for o in self.observations:
            if o.source not in ("EPF_CONTRIB", "TDS_26AS"):
                continue
            slot = by_emp.setdefault(o.employer_key, {"pf": set(), "tds": set()})
            slot["pf" if o.source == "EPF_CONTRIB" else "tds"].add(month_key(o.when))

        out: list[Contradiction] = []
        for emp, s in sorted(by_emp.items()):
            pf, tds = s["pf"], s["tds"]
            if not pf or not tds:
                continue
            lo, hi = min(pf), max(pf)
            missing = sorted(m for m in tds if lo < m < hi and m not in pf)
            if not missing:
                continue

            runs: list[list[str]] = []
            for m in missing:
                if runs and _next_month(runs[-1][-1]) == m:
                    runs[-1].append(m)
                else:
                    runs.append([m])

            spans = ", ".join(r[0] if len(r) == 1 else f"{r[0]} to {r[-1]}"
                              for r in runs)
            out.append(Contradiction(
                kind="CONTRIBUTION_GAP",
                employer_key=emp,
                severity=BLOCKING,
                detail=(
                    f"{len(missing)} month{'s' if len(missing) != 1 else ''} "
                    f"({spans}) where the Income Tax Department records this "
                    f"employer deducting tax from your salary, but your PF "
                    f"passbook shows no contribution. You were employed either "
                    f"side of {'these gaps' if len(runs) > 1 else 'this gap'}, "
                    f"so this is not a break in service - it is money that was "
                    f"withheld and did not arrive."
                ),
                evidence=[f"TDS_26AS@{m}" for m in missing[:6]]
                         + [f"EPF_CONTRIB@{lo} (first)", f"EPF_CONTRIB@{hi} (last)"],
                proposed_fix=(
                    f"Ask this employer to deposit and reconcile the missing "
                    f"month{'s' if len(missing) != 1 else ''}: {spans}."
                ),
                correction_route=GRIEVANCE,
            ))
        return out

    def run(self) -> dict:
        windows = self.support_windows()
        contradictions: list[Contradiction] = []

        for svc in self.asserted:
            win = windows.get(svc.employer_key)
            for check in (self._check_missing_exit, self._check_exit_too_early, self._check_join_too_early):
                c = check(svc, win)
                if c is not None:
                    contradictions.append(c)

        asserted_intervals = {
            s.employer_key: (s.doj, s.doe or self.today) for s in self.asserted
        }
        corrected_intervals = self.corrected_timeline(windows)

        contradictions.extend(self._check_overlaps(asserted_intervals, "asserted"))

        # Only report a correction conflict the asserted record did not already
        # have - otherwise it is the same defect reported twice.
        already = {
            c.employer_key for c in contradictions if c.kind == "SERVICE_OVERLAP"
        }
        for c in self._check_overlaps(corrected_intervals, "corrected"):
            if c.employer_key not in already:
                contradictions.append(c)

        contradictions.extend(self._check_orphans(windows))
        # Needs no asserted service history, so it runs whether or not
        # EPFO's record was supplied.
        contradictions.extend(self._check_contribution_gaps())

        contradictions.sort(key=lambda c: SEVERITY_RANK[c.severity])

        blocking = [c for c in contradictions if c.severity == BLOCKING]
        return {
            "claim_status": "WILL_BE_REJECTED" if blocking else "LIKELY_TO_SETTLE",
            "blocking_count": len(blocking),
            "contradictions": [c.to_dict() for c in contradictions],
            "corrected_timeline": {
                k: [v[0].isoformat(), v[1].isoformat()]
                for k, v in self.corrected_timeline(windows).items()
            },
            "evidence_confidence": {
                k: w.confidence() for k, w in windows.items()
            },
        }


# ---------------------------------------------------------------------------
# INVARIANT - the system may propose corrections, never a denial.
# ---------------------------------------------------------------------------

def assert_no_denial_path(result: dict) -> None:
    """
    Structural guarantee carried over from the approve-only design principle:
    every contradiction must carry a proposed fix and a correction route. The
    engine is not permitted to terminate a member's case.
    """
    for c in result["contradictions"]:
        assert c["proposed_fix"], f"{c['kind']} produced no proposed fix"
        assert c["correction_route"], f"{c['kind']} produced no correction route"
        assert c["severity"] in (BLOCKING, DEGRADED, OPPORTUNITY)
    assert result["claim_status"] in ("WILL_BE_REJECTED", "LIKELY_TO_SETTLE")


# ---------------------------------------------------------------------------
# Synthetic scenarios - each mirrors a documented EPFO failure mode
# ---------------------------------------------------------------------------

def _monthly(employer: str, src: str, start: date, count: int, note: str = "") -> list[Observation]:
    obs = []
    y, m = start.year, start.month
    for _ in range(count):
        obs.append(Observation(employer, date(y, m, 1), src, note))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return obs


def scenario_overlap() -> tuple[str, list[Observation], list[AssertedService], date]:
    """The headline case: exit recorded early -> overlap -> transfer frozen."""
    obs: list[Observation] = []
    obs += _monthly("ACME_TECH", "EPF_CONTRIB", date(2017, 6, 1), 34)
    obs += _monthly("ACME_TECH", "TDS_26AS", date(2017, 6, 1), 34, "salary TDS u/s 192")
    obs += [Observation("ACME_TECH", date(2020, 3, 28), "BANK_SALARY", "SAL CR ACME")]
    obs += _monthly("BOREAL_SYS", "EPF_CONTRIB", date(2020, 4, 1), 60)
    obs += _monthly("BOREAL_SYS", "TDS_26AS", date(2020, 4, 1), 60, "salary TDS u/s 192")

    asserted = [
        # Employer typed the exit two months early. Everything downstream breaks.
        AssertedService("ACME_TECH", "MHBAN00123450000001234", date(2017, 6, 12), date(2020, 1, 31)),
        AssertedService("BOREAL_SYS", "KNBNG00456780000005678", date(2020, 1, 20), None),
    ]
    return "Exit recorded early -> service overlap -> auto-transfer frozen", obs, asserted, date(2025, 4, 1)


def scenario_orphan() -> tuple[str, list[Observation], list[AssertedService], date]:
    """Forgotten pre-UAN account, discoverable only from independent records."""
    obs: list[Observation] = []
    obs += _monthly("STARLIT_RETAIL", "TDS_26AS", date(2012, 8, 1), 11, "salary TDS u/s 192")
    obs += _monthly("STARLIT_RETAIL", "BANK_SALARY", date(2012, 8, 1), 11, "SAL CR STARLIT")
    obs += _monthly("BOREAL_SYS", "EPF_CONTRIB", date(2020, 4, 1), 60)
    obs += _monthly("BOREAL_SYS", "TDS_26AS", date(2020, 4, 1), 60)

    asserted = [AssertedService("BOREAL_SYS", "KNBNG00456780000005678", date(2020, 4, 1), None)]
    return "Orphaned pre-UAN account with no linked member ID", obs, asserted, date(2025, 4, 1)


def scenario_clean() -> tuple[str, list[Observation], list[AssertedService], date]:
    """Control. A history that reconciles must produce zero blocking defects."""
    obs: list[Observation] = []
    obs += _monthly("BOREAL_SYS", "EPF_CONTRIB", date(2020, 4, 1), 48)
    obs += _monthly("BOREAL_SYS", "TDS_26AS", date(2020, 4, 1), 48)
    asserted = [AssertedService("BOREAL_SYS", "KNBNG00456780000005678", date(2020, 4, 1), None)]
    return "Clean history (control)", obs, asserted, date(2024, 4, 1)


def scenario_sub_tds() -> tuple[str, list[Observation], list[AssertedService], date]:
    """
    Equity edge case: worker earns below the TDS threshold, so Form 26AS is
    empty. Reconciliation must still work from EPF contributions alone.
    """
    obs: list[Observation] = []
    obs += _monthly("GRAMEEN_TEXTILES", "EPF_CONTRIB", date(2021, 7, 1), 29)
    asserted = [
        AssertedService("GRAMEEN_TEXTILES", "MHTHA00998870000004321", date(2021, 7, 5), None),
    ]
    return "Sub-TDS-threshold worker - no 26AS coverage", obs, asserted, date(2025, 4, 1)


SCENARIOS = [scenario_overlap, scenario_orphan, scenario_clean, scenario_sub_tds]


# ---------------------------------------------------------------------------

def main() -> int:
    results = {}
    failures = 0

    for fn in SCENARIOS:
        title, obs, asserted, today = fn()
        result = Reconciler(obs, asserted, today).run()
        try:
            assert_no_denial_path(result)
        except AssertionError as e:
            print(f"  INVARIANT VIOLATED: {e}")
            failures += 1
        results[fn.__name__] = {"title": title, "result": result}

        print(f"\n=== {title}")
        print(f"    status: {result['claim_status']}  blocking: {result['blocking_count']}")
        for c in result["contradictions"]:
            print(f"    [{c['severity']:11}] {c['kind']:16} {c['employer']}")
            print(f"                  -> {c['proposed_fix']}")
            print(f"                  route: {c['correction_route']}")

    # Assertions that make this a spike rather than a demo.
    checks = [
        ("overlap detected", any(
            c["kind"] == "SERVICE_OVERLAP"
            for c in results["scenario_overlap"]["result"]["contradictions"])),
        ("root cause found", any(
            c["kind"] == "EXIT_TOO_EARLY"
            for c in results["scenario_overlap"]["result"]["contradictions"])),
        ("orphan found", any(
            c["kind"] == "ORPHAN_ACCOUNT"
            for c in results["scenario_orphan"]["result"]["contradictions"])),
        ("control is clean", results["scenario_clean"]["result"]["blocking_count"] == 0),
        ("sub-TDS still works", results["scenario_sub_tds"]["result"]["blocking_count"] > 0),
    ]

    print("\n--- spike assertions ---")
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1

    out = pathlib.Path(__file__).resolve().parent / "reconcile_output.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nfull output -> core/{out.name}")
    print(f"RESULT: {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
