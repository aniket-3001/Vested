"""
Corrections a member has started, and what happens to them.

This is the half of the product that was missing. Everything before it
diagnoses: here is the field that is wrong, here is the right value, here is
who can change it. Then the member was handed a letter and left alone.

What this adds is the rest of the arc - submit the correction, have it checked,
see what the record looks like once it is accepted. Three rules govern all of
it, and they are the difference between a working demo and a lie:

  1. We never say a DOCUMENT is verified. We cannot read an appointment letter
     and we certainly cannot tell a genuine one from a file somebody typed this
     morning. What we check is the CORRECTION - whether the date being asked
     for is consistent with the contribution record. That is a real check, and
     it is the same thing EPFO's own validation tests.

  2. Nothing is ever submitted anywhere. No state in here means "EPFO has this".
     The furthest a correction goes is READY - prepared, checked, and waiting
     for the member to file it themselves.

  3. There is no rejected state. A check that fails returns the correction
     asking for one named thing. The approve-only invariant that governs the
     rest of the engine governs this too: we can propose, we can never refuse.

Run:  python app/corrections.py
"""

from __future__ import annotations

import secrets
import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from dataclasses import dataclass, field
from datetime import date

from app.engine import TODAY, analyse, extract_names
from app.history import build_history_text
from core.epfo_rules import ACCEPTED_DATE_EVIDENCE

# EPFO's published outer limit for a correction request. Shown as their target,
# never as a countdown we control.
SLA_DAYS = 20

SUBMITTED = "submitted"
CHECKED = "checked"
READY = "ready"
RETURNED = "returned"

STATE_WORD = {
    SUBMITTED: "Submitted",
    CHECKED: "Checked",
    READY: "Ready to file",
    RETURNED: "Needs one more thing",
}


@dataclass(frozen=True)
class Check:
    """One thing we can actually test about a proposed correction."""
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Correction:
    ref: str
    member_id: str
    employer: str
    field_name: str            # "Date of Exit" / "Date of Joining"
    current: date | None
    proposed: date
    evidence: str
    route: str
    started: date
    checks: list[Check] = field(default_factory=list)

    @property
    def state(self) -> str:
        if not self.checks:
            return SUBMITTED
        if any(not c.ok for c in self.checks):
            return RETURNED
        return READY

    @property
    def state_word(self) -> str:
        return STATE_WORD[self.state]

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.checks)

    @property
    def outstanding(self) -> list[Check]:
        """What still needs doing. Never a refusal - always a named next step."""
        return [c for c in self.checks if not c.ok]

    @property
    def due(self) -> date:
        return date.fromordinal(self.started.toordinal() + SLA_DAYS)


def new_ref() -> str:
    return "JD" + secrets.token_hex(4).upper()


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def check_correction(a, member_id: str, proposed: date,
                     evidence: str) -> list[Check]:
    """
    Test the correction against the record, not the document against reality.

    Every check here is one EPFO's own validation performs. A correction that
    passes all of them is one their system should accept without an employer,
    because the date agrees with contributions they already hold.
    """
    out: list[Check] = []
    asserted = {s.member_id: s for s in (getattr(a, "asserted", []) or [])}
    svc = asserted.get(member_id)
    obs = [o for o in (getattr(a, "observations", []) or [])
           if svc and o.employer_key == svc.employer_key]

    # 1. Is the date supported by contributions EPFO already holds?
    last = max((o.when for o in obs), default=None)
    srcs = len({o.source for o in obs})
    if last is None:
        out.append(Check("Supported by your contribution record", False,
                         "No contribution evidence was found for this account."))
    elif proposed >= last:
        out.append(Check(
            "Supported by your contribution record", True,
            f"{srcs} independent source(s) place you in work to "
            f"{last.strftime('%d-%m-%Y')}."))
    else:
        out.append(Check(
            "Supported by your contribution record", False,
            f"Evidence runs to {last.strftime('%d-%m-%Y')}, after the date you "
            f"entered. Enter {last.strftime('%d-%m-%Y')} or later."))

    # 2. An exit before the joining date is rejected outright.
    if svc and svc.doj:
        ok = proposed >= svc.doj
        out.append(Check(
            "After the recorded joining date", ok,
            f"Joined {svc.doj.strftime('%d-%m-%Y')}." if ok
            else f"This is before the joining date of "
                 f"{svc.doj.strftime('%d-%m-%Y')}."))

    # 3. Would it make two jobs run at once? EPFO refuses overlapping service.
    clash = None
    for other in (getattr(a, "asserted", []) or []):
        if other.member_id == member_id or not other.doj:
            continue
        if other.doj <= proposed and (other.doe is None or other.doe >= proposed):
            clash = other
            break
    out.append(Check(
        "Creates no overlapping service", clash is None,
        "No other employment covers this date." if clash is None
        else f"This date falls inside your service at {clash.member_id}."))

    # 4. Is the paperwork the kind EPFO accepts? This is a check on the NAME of
    #    the document, not on its contents - we cannot read it, and saying
    #    otherwise would be the exact overclaim this product exists to oppose.
    named = evidence in ACCEPTED_DATE_EVIDENCE
    out.append(Check(
        "Supporting document is one EPFO accepts", named,
        f"{evidence} is on EPFO's accepted list for date corrections."
        if named else
        "Choose an appointment letter, attendance register extract, or "
        "relieving letter."))
    return out


# ---------------------------------------------------------------------------
# What the record looks like once the corrections are accepted
# ---------------------------------------------------------------------------

def apply_corrections(a, corrections: list[Correction]):
    """
    Re-run the whole engine with the corrected dates in place.

    Nothing here is faked. The service history is rebuilt with the new dates,
    every parser and the reconciler run again from the original documents, and
    whatever verdict comes out is the verdict. If a correction did not actually
    fix anything, the page will say so.
    """
    ready = {c.member_id: c.proposed for c in corrections if c.state == READY}
    if not ready:
        return None
    docs = getattr(a, "docs", None) or {}
    rows = []
    for s in (getattr(a, "asserted", []) or []):
        doe = ready.get(s.member_id, s.doe)
        rows.append({"member_id": s.member_id, "employer": "",
                     "doj": s.doj.strftime("%d-%m-%Y") if s.doj else "",
                     "doe": doe.strftime("%d-%m-%Y") if doe else None})
    if not rows:
        return None
    try:
        return analyse(
            text_26as=docs.get("26as") or "",
            passbooks=docs.get("passbook") or [],
            service_history=build_history_text(rows),
            bank=docs.get("bank") or "",
            names=extract_names(docs) if docs else None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def main() -> int:
    from app.demo import build
    from app import solver

    checks: list[tuple[str, bool]] = []
    a = build("100999888777")
    recs = {r.member_id: r for r in solver.reconstruct(a) if r.exit_best}
    mid, rec = next(iter(recs.items()))

    good = check_correction(a, mid, rec.exit_best, "Appointment letter")
    checks += [
        ("a well-formed correction passes every check",
         all(c.ok for c in good)),
        ("four things are checked", len(good) == 4),
        ("each check explains itself", all(c.detail for c in good)),
    ]

    c_ok = Correction(new_ref(), mid, "E", "Date of Exit", rec.asserted_doe,
                      rec.exit_best, "Appointment letter", "JD", TODAY, good)
    checks += [
        ("a passing correction is ready to file", c_ok.state == READY),
        ("and says so in words", c_ok.state_word == "Ready to file"),
        ("nothing claims EPFO has it",
         "EPFO" not in c_ok.state_word and "submitted to" not in c_ok.state_word.lower()),
        ("it carries EPFO's published limit, not ours",
         (c_ok.due.toordinal() - TODAY.toordinal()) == SLA_DAYS),
    ]

    # A date earlier than the evidence is the common mistake, and it must be
    # returned with the right value rather than refused.
    early = check_correction(a, mid, date(2019, 1, 1), "Appointment letter")
    c_early = Correction(new_ref(), mid, "E", "Date of Exit", None,
                         date(2019, 1, 1), "Appointment letter", "JD",
                         TODAY, early)
    checks += [
        ("a date before the evidence is caught", any(not c.ok for c in early)),
        ("it is returned, never rejected", c_early.state == RETURNED),
        ("the word 'reject' appears nowhere in the states",
         not any("reject" in w.lower() for w in STATE_WORD.values())),
        ("and it names what to do instead",
         any("or later" in c.detail for c in early if not c.ok)),
    ]

    # A document EPFO does not accept is named as such - but we never claim to
    # have read it.
    wrong_doc = check_correction(a, mid, rec.exit_best, "Form 26AS")
    checks += [
        ("an unaccepted document is caught",
         any(not c.ok for c in wrong_doc)),
        ("no check claims the document itself was verified",
         not any("verified" in c.name.lower() for c in wrong_doc)),
        ("the accepted list is offered instead",
         any("appointment letter" in c.detail.lower()
             for c in wrong_doc if not c.ok)),
    ]

    # The payoff: applying the corrections must genuinely clear the claim.
    fixes = [Correction(new_ref(), m, "E", "Date of Exit", r.asserted_doe,
                        r.exit_best, "Appointment letter", "JD", TODAY,
                        check_correction(a, m, r.exit_best, "Appointment letter"))
             for m, r in recs.items()]
    before = solver.blocking_failures(solver.gates(a))
    after_a = apply_corrections(a, fixes)
    after = solver.blocking_failures(solver.gates(after_a)) if after_a else None
    checks += [
        ("the record is re-analysed, not flagged", after_a is not None),
        ("the blocking failures actually clear",
         after is not None and len(after) == 0 and len(before) > 0),
        ("the engine really re-ran on corrected dates",
         after_a is not None
         and "EXIT_TOO_EARLY" not in [x["kind"] for x in after_a.result["contradictions"]]),
        # Correcting a date must not silently make the forgotten account vanish.
        ("what the correction does not fix is still reported",
         after_a is not None
         and "ORPHAN_ACCOUNT" in [x["kind"] for x in after_a.result["contradictions"]]),
        ("a correction that is not ready changes nothing",
         apply_corrections(a, [c_early]) is None),
        ("no corrections at all changes nothing",
         apply_corrections(a, []) is None),
    ]

    print("=" * 68)
    print("  corrections - checking, returning, and the re-run")
    bad = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        bad += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad else f'{bad} FAILURE(S)'}")
    print("=" * 68)
    return 1 if bad else 0


if __name__ == "__main__":
    _s.exit(main())
