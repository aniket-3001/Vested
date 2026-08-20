"""
The EPFO rules a member is actually judged against, as of 2026.

Everything here is deterministic and testable. It exists because EPFO 3.0 moved
the goalposts in a way our earlier pages did not model:

  - auto-settlement now runs to Rs 5,00,000, up from Rs 1,00,000
  - the thirteen withdrawal categories collapsed into three
  - employer approval is gone for digital withdrawals, replaced by automated
    system checks against the member's own record
  - UPI withdrawal up to 75% of balance, ATM up to 50%
  - KYC must read "Approved" or none of the above is available

The last two points are why this module matters more than it looks. When a
human clerk approved claims, a wrong date got a phone call. When the decision
is automated, a wrong date gets a rejection - faster, and with nobody to ask.

Automating a judgement does not improve the data it is made on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Withdrawal categories - EPFO 3.0 merged thirteen into three
# ---------------------------------------------------------------------------

CATEGORIES = [
    ("illness", "Illness and medical emergency",
     "Hospitalisation for you or a dependant. No minimum service period."),
    ("education", "Education and marriage",
     "Your own education, or a child's education or marriage. Needs 7 years of service."),
    ("housing", "Housing",
     "Purchase, construction, or repayment of a home loan. Needs 5 years of service."),
]

AUTO_SETTLE_CEILING = 500_000.0
UPI_SHARE = 0.75
ATM_SHARE = 0.50

# Service standards EPFO publishes. The 3-day figure is the target for claims
# that clear the automated checks; 20 working days is the outer limit, past
# which 12% penal interest is due.
TARGET_DAYS = 3
OUTER_LIMIT_DAYS = 20
DELAY_PENALTY_PCT = 12


@dataclass
class SettlementVerdict:
    """What would actually happen if this member filed today."""
    mode: str                    # auto | manual | blocked
    headline: str
    detail: str
    ceiling_applies: bool = False
    upi_limit: float = 0.0
    atm_limit: float = 0.0
    reasons: list = field(default_factory=list)

    @property
    def good(self) -> bool:
        return self.mode == "auto"


def settlement_verdict(balance: float, blocking: int, kyc_ready: bool,
                       amount: float | None = None,
                       checked: bool = True) -> SettlementVerdict:
    """
    Model the automated gate a claim now passes through.

    Order matters, and the first test is whether we are entitled to an opinion
    at all. Without a service history there is nothing to run the check
    against, and saying "this would go to manual review" would tell a member we
    inspected their record and found it survivable. We did not inspect it.

    After that, a blocking defect outranks everything, because that is the check
    EPFO runs first and the one no amount of correct KYC will rescue.
    """
    want = balance if amount is None else min(amount, balance)
    reasons = []

    if not checked:
        return SettlementVerdict(
            mode="unknown",
            headline="Not yet known",
            detail=(
                "We cannot say how this would be settled, because your service "
                "history is what the automated check reads and it was not "
                "supplied. Nothing found here means nothing was tested."
            ),
            reasons=["No service history to check against"],
        )

    if blocking:
        return SettlementVerdict(
            mode="blocked",
            headline="This would be rejected, not settled",
            detail=(
                f"{blocking} defect{'s' if blocking != 1 else ''} in your service "
                f"record would fail the automated check EPFO runs before it looks "
                f"at anything else. Under the older process a clerk might have "
                f"telephoned you. An automated decision simply says no."
            ),
            reasons=[f"{blocking} unresolved defect(s) in the service record"],
        )

    if not kyc_ready:
        return SettlementVerdict(
            mode="manual",
            headline="This would go to manual review",
            detail=(
                "Auto-settlement, UPI withdrawal and ATM withdrawal all require "
                "your KYC to read Approved. Until it does, the claim is handled "
                "by hand, which is slower and can still fail on a mismatch."
            ),
            reasons=["KYC is not fully approved"],
        )

    if want > AUTO_SETTLE_CEILING:
        return SettlementVerdict(
            mode="manual",
            headline="Above the auto-settlement ceiling",
            detail=(
                f"Auto-settlement covers claims up to Rs {AUTO_SETTLE_CEILING:,.0f}. "
                f"Rs {want:,.0f} is above that, so this goes to an officer. Your "
                f"record is clean, so there is nothing here to fix - it is simply "
                f"a larger claim."
            ),
            ceiling_applies=True,
            reasons=[f"Amount exceeds Rs {AUTO_SETTLE_CEILING:,.0f}"],
        )

    return SettlementVerdict(
        mode="auto",
        headline="This should settle automatically",
        detail=(
            f"Your record passes the checks EPFO runs and the amount is within "
            f"the Rs {AUTO_SETTLE_CEILING:,.0f} auto-settlement ceiling, so the "
            f"target is {TARGET_DAYS} days. One caveat we cannot remove: your "
            f"bank and Aadhaar KYC live inside EPFO and are not visible to us. "
            f"Confirm they read Approved on the portal before you file."
        ),
        upi_limit=round(balance * UPI_SHARE, 2),
        atm_limit=round(balance * ATM_SHARE, 2),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# KYC - the quiet cause of automated rejection
# ---------------------------------------------------------------------------
# A bank account name that does not match the UAN and Aadhaar name exactly is
# one of the most common auto-rejection causes, and one of the least
# understood: an expanded initial is enough to trip it. We already compare
# names across documents, so we can see this coming.

@dataclass
class KycItem:
    label: str
    status: str            # ok | risk | unknown
    note: str


def kyc_review(names: dict, identity: dict, same_person: bool,
               weakest: float | None) -> list[KycItem]:
    """
    Assess KYC readiness from what the member's own documents actually show.

    Deliberately conservative: anything we cannot see is reported as unknown,
    never as fine. A KYC screen that says "all good" because it had nothing to
    look at is the exact failure this whole product exists to prevent.
    """
    items: list[KycItem] = []

    spellings = {v.strip() for v in (names or {}).values() if v and v.strip()}
    if len(spellings) > 1 and not same_person:
        items.append(KycItem(
            "Name", "risk",
            f"Your documents spell your name {len(spellings)} different ways. Your "
            f"bank account name must match your UAN and Aadhaar exactly - even an "
            f"expanded initial is enough to fail the automated check."))
    elif len(spellings) > 1:
        items.append(KycItem(
            "Name", "risk",
            f"{len(spellings)} spellings found. They look like the same person, but "
            f"EPFO's check is literal, not sensible. Standardise on one."))
    elif spellings:
        items.append(KycItem("Name", "ok", "One consistent spelling across your documents."))
    else:
        items.append(KycItem("Name", "unknown", "No document you gave us carries a name."))

    items.append(
        KycItem("UAN", "ok", f"UAN {identity['uan']} read from your passbook.")
        if identity.get("uan") else
        KycItem("UAN", "unknown", "No UAN found in the documents you gave us."))

    items.append(
        KycItem("PAN", "ok", f"PAN ending {identity['pan'][-4:]} found in your tax records.")
        if identity.get("pan") else
        KycItem("PAN", "unknown",
                "No PAN visible. PAN must be linked or withdrawals are taxed at 20% "
                "instead of 10% where TDS applies."))

    items.append(KycItem(
        "Bank account", "unknown",
        "We cannot see your bank KYC from these documents. Check it on the UAN "
        "portal - the account holder name must match your UAN name character for "
        "character, and this is the single most common cause of a claim failing "
        "after approval."))

    items.append(KycItem(
        "Aadhaar", "unknown",
        "We cannot see your Aadhaar link. It must be verified for auto-settlement, "
        "UPI and ATM withdrawal, and your Aadhaar-linked mobile must be active to "
        "receive the OTP."))

    return items


def kyc_ready(items: list[KycItem]) -> bool:
    """
    True when nothing we can see is wrong.

    Deliberately not "everything is verified". Bank and Aadhaar KYC live inside
    EPFO and are never visible to us, so a rule demanding every item be green
    could never be satisfied by any member - which would make auto-settlement
    permanently unreachable and quietly turn an honest caution into a false
    negative.

    So: a risk we can see blocks. Something we cannot see is disclosed as
    unseen, in kyc_review, and does not masquerade as a finding. The verdict
    built on this carries the caveat.
    """
    return not any(i.status == "risk" for i in items)


def kyc_unverified(items: list[KycItem]) -> bool:
    """Is any part of KYC beyond our sight? Almost always yes."""
    return any(i.status == "unknown" for i in items)


# ---------------------------------------------------------------------------
# Corrections where the employer no longer exists
# ---------------------------------------------------------------------------
# The Joint Declaration moved online in 2026 and physical forms are no longer
# accepted for the common corrections. But there is a carve-out, and it happens
# to cover the exact member this product was built for: the one whose employer
# has shut down.

ONLINE_JD = "online"
ATTESTED_JD = "attested"

ATTESTORS = [
    "The manager of the bank branch where your salary account was held",
    "A gazetted officer",
    "A magistrate",
]


def jd_route(employer_closed: bool) -> tuple[str, str]:
    """Which Joint Declaration path applies, and why."""
    if employer_closed:
        return ATTESTED_JD, (
            "Your employer's establishment is closed, so there is nobody to "
            "countersign online. This is the one case where a physical, attested "
            "Joint Declaration is still accepted."
        )
    return ONLINE_JD, (
        "Submit through the UAN member portal under Online Services, with your "
        "supporting documents uploaded. EPFO stopped accepting physical forms for "
        "this correction in 2026."
    )


# ---------------------------------------------------------------------------
# Evidence EPFO actually accepts
# ---------------------------------------------------------------------------
# Stated plainly because getting this wrong would send a member to a counter
# with the wrong paperwork. Form 26AS proves a date is wrong; it is not on
# EPFO's list of accepted evidence for correcting one. Both facts matter.

ACCEPTED_DATE_EVIDENCE = [
    "Appointment letter",
    "Attendance register extract",
    "Relieving letter or final payslip",
]

EVIDENCE_NOTE = (
    "Form 26AS shows that a date is wrong and tells you which employer to "
    "approach. EPFO does not currently list it among the documents it accepts "
    "to correct one, so take it alongside an appointment or relieving letter "
    "rather than instead of them."
)


def mixed_items() -> list[KycItem]:
    """A member whose documents disagree about their own name."""
    return kyc_review({"26as": "RAHUL K SINGH", "passbook": "RAHUL KUMAR SINGH"},
                      {"uan": None, "pan": None}, True, 0.7)


def _self_test() -> int:
    checks = []

    clean = settlement_verdict(180_000, 0, True)
    checks += [
        ("a clean record under the ceiling auto-settles", clean.mode == "auto"),
        ("UPI limit is 75% of balance", clean.upi_limit == 135_000.0),
        ("ATM limit is 50% of balance", clean.atm_limit == 90_000.0),
    ]

    big = settlement_verdict(900_000, 0, True)
    checks += [
        ("above Rs 5L goes to manual review", big.mode == "manual"),
        ("and says so for the right reason", big.ceiling_applies),
    ]

    bad = settlement_verdict(180_000, 2, True)
    checks += [
        ("a blocking defect blocks, whatever the amount", bad.mode == "blocked"),
        # The whole point: the record is checked before the money.
        ("a defect outranks a clean KYC",
         settlement_verdict(180_000, 1, True).mode == "blocked"),
        ("a defect outranks the ceiling too",
         settlement_verdict(9_000_000, 1, True).mode == "blocked"),
    ]

    checks.append(("bad KYC alone means manual, not blocked",
                   settlement_verdict(180_000, 0, False).mode == "manual"))
    checks.append(("amount, not balance, is what the ceiling tests",
                   settlement_verdict(900_000, 0, True, amount=100_000).mode == "auto"))

    # An unchecked record gets no verdict at all. "Manual review" would tell a
    # member we inspected their service record and found it survivable.
    unchecked = settlement_verdict(180_000, 0, True, checked=False)
    checks += [
        ("an unchecked record returns no verdict", unchecked.mode == "unknown"),
        ("and does not read as good news", not unchecked.good),
        ("and says why", "not supplied" in unchecked.detail),
        ("clean KYC cannot manufacture a verdict",
         settlement_verdict(180_000, 0, True, checked=False).mode != "auto"),
        ("no UPI limit is offered on an unchecked record",
         unchecked.upi_limit == 0.0),
    ]

    # KYC review must never say "fine" about something it could not see.
    seen = kyc_review({"26as": "RAHUL KUMAR SINGH", "passbook": "RAHUL KUMAR SINGH"},
                      {"uan": "100999888777", "pan": "ABCDE1234F"}, True, 0.9)
    by = {i.label: i for i in seen}
    checks += [
        ("one spelling reads as ok", by["Name"].status == "ok"),
        ("a UAN we found reads as ok", by["UAN"].status == "ok"),
        ("bank KYC is never assumed good", by["Bank account"].status == "unknown"),
        ("Aadhaar is never assumed good", by["Aadhaar"].status == "unknown"),
        # These two together are the whole distinction: something we cannot see
        # is disclosed as unseen, but it is not treated as a finding against the
        # member. Demanding every item be green would make auto-settlement
        # unreachable for everyone and turn caution into a false negative.
        ("nothing visible is wrong, so the gate opens", kyc_ready(seen)),
        ("but the page still reports KYC as unverified", kyc_unverified(seen)),
        ("a visible risk closes the gate", not kyc_ready(mixed_items())),
    ]

    mixed = mixed_items()
    bym = {i.label: i for i in mixed}
    checks += [
        ("two spellings raise a name risk", bym["Name"].status == "risk"),
        ("a missing UAN is unknown, not ok", bym["UAN"].status == "unknown"),
        ("a missing PAN warns about the 20% TDS rate",
         "20%" in bym["PAN"].note),
    ]

    empty = kyc_review({}, {}, True, None)
    checks.append(("no names at all is unknown, never ok",
                   {i.label: i for i in empty}["Name"].status == "unknown"))

    route_open, why_open = jd_route(False)
    route_shut, why_shut = jd_route(True)
    checks += [
        ("a live employer routes to the online JD", route_open == ONLINE_JD),
        ("and says physical forms stopped in 2026", "2026" in why_open),
        ("a closed establishment routes to an attested JD", route_shut == ATTESTED_JD),
        ("and explains why", "closed" in why_shut),
        ("three attestors are offered", len(ATTESTORS) == 3),
        ("a bank manager is one of them",
         any("bank" in a.lower() for a in ATTESTORS)),
    ]

    checks += [
        ("thirteen categories became three", len(CATEGORIES) == 3),
        ("26AS is not claimed as accepted evidence",
         not any("26AS" in e for e in ACCEPTED_DATE_EVIDENCE)),
        ("but the note explains what it is good for", "26AS" in EVIDENCE_NOTE),
    ]

    print("=" * 66)
    print("  EPFO 3.0 rules")
    bad_n = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        bad_n += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not bad_n else f'{bad_n} FAILURE(S)'}")
    print("=" * 66)
    return 1 if bad_n else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
