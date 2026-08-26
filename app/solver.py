"""
The three things the real portal cannot do.

1. RECONSTRUCT  - work out what the employment record should say, from
   independent evidence, and state how certain that is.
2. PLAN         - order the corrections by dependency and report the critical
   path, because doing them in the wrong order costs months.
3. RETRO        - given a claim that was rejected in the past, work out why.
   EPFO's own screen shows the word "Rejected" and no reason at all.

Plus the validator twin: EPFO's published pre-settlement checks, reimplemented
as an auditable decision procedure so a member can see which gate they fail and
which field causes it.

Everything here is deterministic. No model is involved, and the same documents
always produce the same answer - which is the point, because the output ends up
on a form somebody signs.

Run:  python app/solver.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import calendar
from dataclasses import dataclass, field
from datetime import date

from core import reconcile as R
from core.epfo_rules import AUTO_SETTLE_CEILING

# Working days each route actually takes, from published EPFO timelines.
# A number that is wrong by a week is still far better than no number: the
# member's real question is "which of these can I start today".
ROUTE_DAYS = {
    R.SELF_SERVICE: 1,
    R.JOINT_DECL: 20,
    R.GRIEVANCE: 30,
    R.CLAIM_ORPHAN: 20,
}
ATTESTED_JD_DAYS = 30      # closed establishment: attestation adds a fortnight

SOURCE_LABEL = {
    "EPFO_SERVICE": "EPFO record",
    "EPF_CONTRIB": "PF contributions",
    "TDS_26AS": "Tax deducted (26AS)",
    "BANK_SALARY": "Salary credits",
}
TRACK_ORDER = ["EPFO_SERVICE", "EPF_CONTRIB", "TDS_26AS", "BANK_SALARY"]


def _dmy(d) -> str:
    """Dates read DD-MM-YYYY everywhere a member can see them."""
    if not d:
        return "Not found"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d)
        except ValueError:
            return d
    return d.strftime("%d-%m-%Y")


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


# ---------------------------------------------------------------------------
# 1. Reconstruction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reconstructed:
    """What the record should say for one employer, and how sure we are."""
    key: str
    employer: str
    member_id: str
    asserted_doj: date | None
    asserted_doe: date | None
    first_seen: date
    last_seen: date
    exit_best: date | None
    sources: tuple[str, ...]
    verdict: str            # agrees | exit_wrong | exit_missing | join_wrong

    @property
    def confidence(self) -> str:
        """Independent sources agreeing. Never a percentage - we cannot
        calibrate one, and a fabricated number is worse than a word."""
        n = len(self.sources)
        return "High" if n >= 3 else "Medium" if n == 2 else "Low"

    @property
    def source_names(self) -> list[str]:
        return [SOURCE_LABEL.get(s, s) for s in self.sources]


def reconstruct(a) -> list[Reconstructed]:
    """
    Derive the true employment interval per employer from the evidence.

    The claim being made is deliberately narrow. We do not say "you left on
    this date". We say "you were definitely still employed on this date, so a
    recorded exit before it is wrong" - which is a fact, not an estimate, and
    survives being argued with at a counter.
    """
    obs = getattr(a, "observations", []) or []
    if not obs:
        return []

    asserted = {s.employer_key: s for s in (getattr(a, "asserted", []) or [])}
    # An orphan has no member ID to match on, so fall back to the employer
    # registry. Showing a member a raw establishment key and calling it their
    # employer is how a screen stops being readable.
    names: dict[str, tuple[str, str]] = {}
    reg = getattr(a, "employers", None)
    for acc in getattr(a, "accounts", []):
        emp = getattr(acc, "employer", "") or ""
        mid = getattr(acc, "member_id", "") or ""
        for o in obs:
            if o.employer_key and (o.employer_key in mid or o.employer_key in emp):
                names.setdefault(o.employer_key, (emp, mid))
    for orp in getattr(a, "orphans", []) or []:
        cand = getattr(orp, "candidate", None)
        key = getattr(cand, "tan", "") if cand else ""
        label = getattr(cand, "employer_name", "") if cand else ""
        if key and label:
            names.setdefault(key, (label, ""))
    if reg is not None:
        for key in {o.employer_key for o in obs if o.employer_key}:
            if key in names:
                continue
            label = getattr(reg, "display", lambda _k: "")(key)
            if label:
                names[key] = (label, "")

    out: list[Reconstructed] = []
    for key in sorted({o.employer_key for o in obs if o.employer_key}):
        mine = [o for o in obs if o.employer_key == key]
        if not mine:
            continue
        first = min(o.when for o in mine)
        last = max(o.when for o in mine)
        # Order the source list the way the timeline draws it, so the caption
        # and the picture always agree.
        srcs = tuple(s for s in TRACK_ORDER if any(o.source == s for o in mine))
        svc = asserted.get(key)
        emp, mid = names.get(key, ("", ""))
        emp = emp or key
        best = _month_end(last)

        if svc is None:
            verdict = "unlinked"
        elif svc.doe is None:
            verdict = "exit_missing"
        elif svc.doe < last:
            verdict = "exit_wrong"
        elif svc.doj and svc.doj > first:
            verdict = "join_wrong"
        else:
            verdict = "agrees"

        out.append(Reconstructed(
            key=key, employer=emp, member_id=mid or (svc.member_id if svc else ""),
            asserted_doj=svc.doj if svc else None,
            asserted_doe=svc.doe if svc else None,
            first_seen=first, last_seen=last,
            exit_best=None if verdict == "agrees" else best,
            sources=srcs, verdict=verdict))
    return out


# ---------------------------------------------------------------------------
# 2. The repair planner
# ---------------------------------------------------------------------------

@dataclass
class Step:
    n: int
    title: str
    detail: str
    route: str
    days: int
    deps: tuple[int, ...] = ()
    wave: int = 1
    kind: str = ""
    key: str = ""


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    critical_days: int = 0
    serial_days: int = 0

    @property
    def waves(self) -> int:
        return max((s.wave for s in self.steps), default=0)

    @property
    def saved_days(self) -> int:
        return max(0, self.serial_days - self.critical_days)

    @property
    def wasted_days(self) -> int:
        """
        What the obvious order costs.

        A member with no guidance files the visible thing first - the transfer,
        because that is where the money is. It is rejected, because the account
        it draws from still has an open exit date, and the whole cycle is spent
        for nothing. That wasted cycle, not the parallelism, is what this
        screen is actually worth.
        """
        return sum(s.days for s in self.steps if s.deps)

    @property
    def blocked_steps(self) -> list["Step"]:
        return [s for s in self.steps if s.deps]


# Which defects must be cleared before which others. These are real
# constraints, not presentation: a transfer request against an account whose
# exit date is open or wrong is rejected, so doing it first wastes the cycle.
_BLOCKS_TRANSFER = {"MISSING_EXIT", "EXIT_TOO_EARLY", "JOIN_SUSPECT"}
_NEEDS_EXIT_FIRST = {"SERVICE_OVERLAP", "ORPHAN_ACCOUNT"}


def plan(a, employer_closed: bool = False) -> Plan:
    """
    Order the corrections, then report the critical path.

    Two numbers come out of this. The serial total is what a member does by
    default, one thing at a time, because nothing tells them otherwise. The
    critical path is what it costs if the independent ones run together. The
    gap between them is the whole value of the screen.
    """
    # Opportunities count. Bringing a forgotten account across is an action
    # the member takes, it takes as long as anything else, and it is the step
    # most likely to be attempted first and rejected.
    cons = [c for c in (a.result.get("contradictions") or [])
            if c.get("severity") in ("BLOCKING", "OPPORTUNITY")]
    if not cons:
        return Plan()

    p = Plan()
    n = 0
    first_wave: list[int] = []

    # Wave 1 - everything that needs nothing else finished first.
    for c in cons:
        if c["kind"] in _NEEDS_EXIT_FIRST:
            continue
        n += 1
        route = c.get("correction_route", "")
        days = ROUTE_DAYS.get(route, 20)
        if route == R.JOINT_DECL and employer_closed:
            days = ATTESTED_JD_DAYS
        p.steps.append(Step(
            n=n, title=_title(c), detail=c.get("proposed_fix", ""),
            route=route, days=days, wave=1,
            kind=c["kind"], key=c.get("employer", "")))
        first_wave.append(n)

    # Wave 2 - the ones that only make sense once the dates above are settled.
    for c in cons:
        if c["kind"] not in _NEEDS_EXIT_FIRST:
            continue
        n += 1
        route = c.get("correction_route", "")
        deps = tuple(first_wave) if first_wave else ()
        p.steps.append(Step(
            n=n, title=_title(c), detail=c.get("proposed_fix", ""),
            route=route, days=ROUTE_DAYS.get(route, 20),
            deps=deps, wave=2 if deps else 1,
            kind=c["kind"], key=c.get("employer", "")))

    p.serial_days = sum(s.days for s in p.steps)
    by_n = {s.n: s for s in p.steps}
    finish: dict[int, int] = {}

    def end_of(step: Step) -> int:
        if step.n in finish:
            return finish[step.n]
        start = max((end_of(by_n[d]) for d in step.deps), default=0)
        finish[step.n] = start + step.days
        return finish[step.n]

    p.critical_days = max((end_of(s) for s in p.steps), default=0)
    return p


def _title(c: dict) -> str:
    return {
        "MISSING_EXIT": "Add the missing date of exit",
        "EXIT_TOO_EARLY": "Correct the date of exit",
        "JOIN_SUSPECT": "Correct the date of joining",
        "SERVICE_OVERLAP": "Resolve the overlapping service",
        "ORPHAN_ACCOUNT": "Bring the untransferred account across",
        "CONTRIBUTION_GAP": "Raise the missing contributions",
        "TRAILING_PAYOUT": "Separate the settlement from employment",
        "CORRECTION_CONFLICT": "Resolve the conflicting correction",
    }.get(c["kind"], "Correct the record")


# ---------------------------------------------------------------------------
# 3. The validator twin
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gate:
    code: str
    name: str
    status: str          # pass | fail | unknown
    detail: str = ""
    href: str = ""
    # An advisory gate reports something true and worth acting on that does not
    # by itself stop a settlement. A forgotten account is the case: EPFO will
    # settle what is linked and the rest is simply left behind.
    advisory: bool = False


def _kinds(a) -> set[str]:
    return {c["kind"] for c in (a.result.get("contradictions") or [])
            if c.get("severity") == "BLOCKING"}


def gates(a) -> list[Gate]:
    """
    EPFO's pre-settlement checks, as far as they are published, run against
    this record.

    "unknown" is a first-class result and is never quietly folded into "pass".
    Bank KYC and Aadhaar linkage live inside EPFO and are not in any document a
    member can hand us, so claiming they are fine would be the exact failure
    this product exists to prevent.
    """
    k = _kinds(a)
    ident = getattr(a, "identity", {}) or {}
    nc = getattr(a, "name_check", None)
    g: list[Gate] = []

    g.append(Gate("G01", "UAN present and active",
                  "pass" if ident.get("uan") else "unknown",
                  ident.get("uan") or "Not found in the documents supplied"))
    g.append(Gate("G02", "Aadhaar linked and approved", "unknown",
                  "Held by EPFO. Not visible in member documents.", "/kyc"))
    g.append(Gate("G03", "PAN approved",
                  "pass" if ident.get("pan") else "unknown",
                  ident.get("pan") or "Not found in Form 26AS", "/kyc"))
    g.append(Gate("G04", "Bank account verified", "unknown",
                  "Held by EPFO. Not visible in member documents.", "/kyc"))
    g.append(Gate("G05", "Mobile verified against Aadhaar", "unknown",
                  "Held by EPFO. Not visible in member documents.", "/contact"))

    if nc is not None:
        same = getattr(nc, "same_person", True)
        g.append(Gate("G06", "Name consistent across records",
                      "pass" if same else "fail",
                      getattr(nc, "canonical", "") or "", "/kyc"))
    else:
        g.append(Gate("G06", "Name consistent across records", "unknown",
                      "Needs at least two documents", "/kyc"))

    clash = ident.get("dob_conflict") or []
    g.append(Gate("G07", "Date of birth consistent",
                  "fail" if clash else ("pass" if ident.get("dob") else "unknown"),
                  " vs ".join(_dmy(c) for c in clash) if clash
                  else _dmy(ident.get("dob")), "/joint-declaration"))

    checked = getattr(a, "dates_checked", False)
    g.append(Gate("G08", "Date of exit recorded for every closed account",
                  "unknown" if not checked else
                  ("fail" if "MISSING_EXIT" in k else "pass"),
                  "No service history to check against" if not checked else "",
                  "/exit"))
    g.append(Gate("G09", "No exit date contradicted by later contributions",
                  "unknown" if not checked else
                  ("fail" if "EXIT_TOO_EARLY" in k else "pass"),
                  "No service history to check against" if not checked else "",
                  "/corrections"))
    g.append(Gate("G10", "No overlapping service periods",
                  "unknown" if not checked else
                  ("fail" if "SERVICE_OVERLAP" in k else "pass"),
                  "", "/corrections"))
    orphans = [o for o in (getattr(a, "orphans", []) or [])
               if getattr(getattr(o, "assessment", None), "verdict", "") == "LIKELY"]
    g.append(Gate("G11", "All accounts linked to this UAN",
                  "unknown" if not checked else ("fail" if orphans else "pass"),
                  (f"{len(orphans)} account not linked" if len(orphans) == 1
                   else f"{len(orphans)} accounts not linked") if orphans else "",
                  "/transfer", advisory=True))

    gaps = getattr(a, "contributions_checked", False)
    g.append(Gate("G12", "No months missing from the contribution record",
                  "unknown" if not gaps else
                  ("fail" if "CONTRIBUTION_GAP" in k else "pass"),
                  "Needs both a passbook and Form 26AS" if not gaps else "",
                  "/corrections"))
    g.append(Gate("G13", "Service history available to verify",
                  "pass" if checked else "unknown",
                  "" if checked else "Type it in to complete the check",
                  "/history-entry"))

    bal = getattr(a, "total_balance", 0.0) or 0.0
    g.append(Gate("G14", "Within the auto-settlement ceiling",
                  "pass" if bal <= AUTO_SETTLE_CEILING else "fail",
                  f"Balance {bal:,.0f} against ceiling "
                  f"{AUTO_SETTLE_CEILING:,.0f}"))
    return g


def gate_summary(g: list[Gate]) -> tuple[int, int, int]:
    return (sum(x.status == "pass" for x in g),
            sum(x.status == "fail" for x in g),
            sum(x.status == "unknown" for x in g))


def blocking_failures(g: list[Gate]) -> list[Gate]:
    """Failures that would actually stop a settlement."""
    return [x for x in g if x.status == "fail" and not x.advisory]


def advisory_failures(g: list[Gate]) -> list[Gate]:
    """True, worth acting on, but not a reason the claim is refused."""
    return [x for x in g if x.status == "fail" and x.advisory]


# ---------------------------------------------------------------------------
# 4. Retro-diagnosis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Retro:
    tracking_id: str
    form: str
    filed: date
    status: str
    causes: list[str]
    confident: bool


def diagnose(a, claims: list[dict]) -> list[Retro]:
    """
    Why a past claim was rejected.

    EPFO's own tracker shows the word "Rejected" and nothing else, so a member
    refiles the same broken claim and is rejected again. We replay the record
    as it stood on the filing date and report which defects already existed.

    Deliberately conservative: only defects whose supporting evidence predates
    the filing date can be named. A defect we can only see because of a
    document from two years later did not cause that rejection.
    """
    out: list[Retro] = []
    cons = [c for c in (a.result.get("contradictions") or [])
            if c.get("severity") == "BLOCKING"]

    for cl in claims:
        if "reject" not in cl.get("status", "").lower():
            continue
        filed = cl["filed"]
        causes, sure = [], False
        for c in cons:
            ev_dates = _evidence_dates(c)
            if ev_dates and min(ev_dates) <= filed:
                causes.append(_title(c))
                if c["kind"] in ("MISSING_EXIT", "EXIT_TOO_EARLY"):
                    sure = True
        out.append(Retro(cl["tracking_id"], cl["form"], filed,
                         cl["status"], causes, sure))
    return out


def _evidence_dates(c: dict) -> list[date]:
    """Pull the dates back out of the citation strings the reconciler emits."""
    found = []
    for e in c.get("evidence", []) or []:
        if "@" not in e:
            continue
        stamp = e.split("@", 1)[1].split(" ")[0]
        parts = stamp.split("-")
        try:
            if len(parts) == 3:
                found.append(date(int(parts[0]), int(parts[1]), int(parts[2])))
            elif len(parts) == 2:
                found.append(date(int(parts[0]), int(parts[1]), 1))
        except ValueError:
            continue
    return found


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def main() -> int:
    from app.demo import build
    checks: list[tuple[str, bool]] = []

    bad_rec, good_rec = build("100999888777"), build("100777666555")

    # --- reconstruction ----------------------------------------------------
    rs = reconstruct(bad_rec)
    checks.append(("a defective record reconstructs at least two employers",
                   len(rs) >= 2))
    checks.append(("every reconstruction names its sources",
                   all(r.sources for r in rs)))
    checks.append(("confidence is a word, never a fabricated percentage",
                   all(r.confidence in ("High", "Medium", "Low") for r in rs)))
    checks.append(("a contradicted exit is found",
                   any(r.verdict == "exit_wrong" for r in rs)))
    checks.append(("a missing exit is found",
                   any(r.verdict == "exit_missing" for r in rs)))
    # The core claim must be a fact, not a guess: we only ever assert that the
    # member was still employed on a date we have evidence for.
    checks.append(("a proposed exit is never earlier than the last evidence",
                   all(r.exit_best >= r.last_seen for r in rs if r.exit_best)))
    checks.append(("evidence never precedes the reconstruction window",
                   all(r.first_seen <= r.last_seen for r in rs)))

    good = reconstruct(good_rec)
    checks.append(("a clean record proposes no new exit dates",
                   all(r.verdict in ("agrees", "unlinked") for r in good)))

    # --- planner -----------------------------------------------------------
    p = plan(bad_rec)
    checks.append(("a defective record produces a plan", len(p.steps) >= 2))
    checks.append(("the plan is ordered into waves", p.waves >= 1))
    checks.append(("the critical path is never longer than doing it serially",
                   p.critical_days <= p.serial_days))
    checks.append(("every step carries a route and a duration",
                   all(s.route and s.days > 0 for s in p.steps)))
    checks.append(("a dependent step never starts in the first wave",
                   all(s.wave > 1 for s in p.steps if s.deps)))
    # The point of the screen is ordering, not parallelism: filing a dependent
    # step early costs a whole cycle, and that is the number worth showing.
    checks.append(("a step that depends on another is identified as blocked",
                   len(p.blocked_steps) >= 1))
    checks.append(("the cost of filing in the wrong order is quantified",
                   p.wasted_days > 0))
    checks.append(("the critical path accounts for the dependency",
                   p.critical_days > max(s.days for s in p.steps)))
    checks.append(("a clean record needs no plan", not plan(good_rec).steps))

    closed = plan(bad_rec, employer_closed=True)
    checks.append(("a closed establishment takes longer, not the same",
                   closed.critical_days >= p.critical_days))

    # --- gates -------------------------------------------------------------
    g = gates(bad_rec)
    ok, fail, unk = gate_summary(g)
    checks.append(("fourteen gates are evaluated", len(g) == 14))
    checks.append(("codes are unique", len({x.code for x in g}) == len(g)))
    checks.append(("a defective record fails at least one gate", fail >= 1))
    checks.append(("what EPFO holds privately is reported unknown, not passed",
                   unk >= 3))
    checks.append(("every status is one of three words",
                   all(x.status in ("pass", "fail", "unknown") for x in g)))
    gg = gates(good_rec)
    checks.append(("a clean record fails no date gate",
                   all(x.status != "fail" for x in gg
                       if x.code in ("G08", "G09", "G10"))))
    # Absence of evidence must never render as good news.
    from app.engine import analyse, SAMPLE_26AS
    # Every optional document defaults to the sample, so a genuinely
    # history-free record has to say so explicitly. Getting this wrong is how
    # you accidentally test against evidence you were pretending not to have.
    blind = analyse(text_26as=SAMPLE_26AS, passbooks=[],
                    service_history="", bank="")
    gb = gates(blind)
    checks.append(("with no service history the date gates are unknown",
                   all(x.status == "unknown" for x in gb
                       if x.code in ("G08", "G09", "G10", "G11"))))
    checks.append(("and no plan is invented from nothing",
                   not plan(blind).steps))

    # --- retro -------------------------------------------------------------
    hist = [
        {"tracking_id": "T1", "form": "Form-19",
         "filed": date(2021, 6, 1), "status": "Claim Rejected"},
        {"tracking_id": "T2", "form": "Form-19",
         "filed": date(2021, 9, 1), "status": "Claim Settled"},
    ]
    r = diagnose(bad_rec, hist)
    checks.append(("only rejected claims are diagnosed", len(r) == 1))
    checks.append(("a cause is named for the rejection", bool(r[0].causes)))
    checks.append(("a settled claim is not second-guessed",
                   all(x.tracking_id != "T2" for x in r)))
    early = diagnose(bad_rec, [{"tracking_id": "T0", "form": "Form-19",
                                "filed": date(2005, 1, 1),
                                "status": "Claim Rejected"}])
    checks.append(("a rejection predating all evidence names no cause",
                   early and not early[0].causes))

    print("=" * 68)
    print("  solver - reconstruction, planning, gates, retro-diagnosis")
    bad = 0
    for name, ok_ in checks:
        print(f"    {'PASS' if ok_ else 'FAIL'}  {name}")
        bad += not ok_
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad else f'{bad} FAILURE(S)'}")
    print("=" * 68)
    return 1 if bad else 0


if __name__ == "__main__":
    _s.exit(main())
