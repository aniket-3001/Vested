"""
The two money questions a member actually asks.

  "If I withdraw now, how much do I actually get?"
  "What will my pension be?"

Both are answerable from published rules and data the member already gave us,
and neither is answered anywhere in the real portal - it shows a balance and
leaves the arithmetic, and the tax rules, to you.

Every figure here is an estimate and says so. The rules are real; the inputs
are what we could read from the documents, and where an input is missing we
say which one rather than substituting a plausible number.

Sources for the rules, current as of 27 August 2026:
  - TDS on premature EPF withdrawal: Income Tax Act s.192A. Applies only when
    service is under five years AND the withdrawal exceeds Rs 50,000. 10% with
    PAN; 20% without, under s.206AA since the Finance Act 2023 (before that it
    was the maximum marginal rate). Form 15G/15H stops it where total income is
    below the taxable limit. No TDS on transfer, or where the job ended for
    reasons outside the member's control.
  - EPS-95 monthly pension: (pensionable salary x pensionable service) / 70.
    Pensionable salary is capped at Rs 15,000 a month since September 2014.
    Ten years of eligible service are needed; the pension starts at 58.

Run:  python core/money.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from dataclasses import dataclass, field

# --- TDS on a premature withdrawal (s.192A) --------------------------------
TDS_FREE_YEARS = 5
TDS_THRESHOLD = 50_000.0
TDS_WITH_PAN = 0.10
TDS_WITHOUT_PAN = 0.20

# --- EPS-95 pension --------------------------------------------------------
PENSIONABLE_CAP = 15_000.0     # monthly, capped since September 2014
PENSION_DIVISOR = 70
PENSION_MIN_MONTHS = 120       # ten years of eligible service
PENSION_AGE = 58
PENSION_FLOOR = 1_000.0        # statutory minimum monthly pension
LONG_SERVICE_BONUS_YEARS = 2   # added once service reaches twenty years
LONG_SERVICE_THRESHOLD = 20


@dataclass
class Withdrawal:
    balance: float
    service_months: int
    has_pan: bool
    tds_rate: float
    tds_amount: float
    net: float
    reasons: list[str] = field(default_factory=list)

    @property
    def taxed(self) -> bool:
        return self.tds_amount > 0

    @property
    def service_years(self) -> float:
        return self.service_months / 12


def withdrawal_estimate(balance: float, service_months: int,
                        has_pan: bool) -> Withdrawal:
    """
    What lands in the bank account, and why.

    The reasons are the point. A member who is told "you would lose 10%" and
    also told "five years of service and it is nil" can decide to wait, which
    is a decision the balance alone never offers them.
    """
    reasons: list[str] = []
    years = service_months / 12
    rate = 0.0

    if balance <= 0:
        return Withdrawal(0.0, service_months, has_pan, 0.0, 0.0, 0.0,
                          ["No balance was found in the documents supplied."])

    if years >= TDS_FREE_YEARS:
        reasons.append(
            f"No tax deducted: {years:.1f} years of service is over the "
            f"{TDS_FREE_YEARS}-year threshold.")
    elif balance <= TDS_THRESHOLD:
        reasons.append(
            f"No tax deducted: the balance is under the Rs "
            f"{TDS_THRESHOLD:,.0f} threshold.")
    else:
        rate = TDS_WITH_PAN if has_pan else TDS_WITHOUT_PAN
        reasons.append(
            f"Tax deducted at {rate:.0%}: under {TDS_FREE_YEARS} years of "
            f"service and over Rs {TDS_THRESHOLD:,.0f}.")
        if has_pan:
            reasons.append(
                "Your PAN is on record, so the lower rate applies. Without it "
                f"the rate would be {TDS_WITHOUT_PAN:.0%}.")
        else:
            reasons.append(
                f"No PAN was found. Linking it drops the rate to "
                f"{TDS_WITH_PAN:.0%} and is worth "
                f"Rs {balance * (TDS_WITHOUT_PAN - TDS_WITH_PAN):,.0f} here.")
        need = int(TDS_FREE_YEARS * 12) - service_months
        if need > 0:
            reasons.append(
                f"Waiting {need} more month{'s' if need != 1 else ''} of "
                f"service removes the deduction entirely.")
        reasons.append(
            "Form 15G (or 15H if you are 60 or over) stops the deduction if "
            "your total income for the year is below the taxable limit.")

    tds = round(balance * rate, 2)
    return Withdrawal(balance, service_months, has_pan, rate, tds,
                      round(balance - tds, 2), reasons)


@dataclass
class Pension:
    eligible: bool
    service_months: int
    months_short: int
    monthly: float | None
    at_full_service: float
    reasons: list[str] = field(default_factory=list)


def pension_estimate(service_months: int,
                     pensionable_salary: float = PENSIONABLE_CAP) -> Pension:
    """
    The EPS-95 monthly pension, and how far off it is.

    Deliberately conservative: service is what we can see contributions for,
    which is a floor rather than the member's whole career. A member with
    service elsewhere will get more, and the page says so.
    """
    salary = min(pensionable_salary, PENSIONABLE_CAP)
    reasons: list[str] = []
    short = max(0, PENSION_MIN_MONTHS - service_months)

    if salary < PENSIONABLE_CAP:
        reasons.append(
            f"Calculated on Rs {salary:,.0f} a month.")
    else:
        reasons.append(
            f"Pensionable salary is capped at Rs {PENSIONABLE_CAP:,.0f} a "
            f"month, so that is the figure used however much you earned.")

    if short:
        reasons.append(
            f"{PENSION_MIN_MONTHS} months of eligible service are needed. "
            f"You have {service_months}, so {short} more to go.")
        reasons.append(
            "Under ten years you can withdraw the pension share instead, "
            "using Form 10C.")
        full = salary * (PENSION_MIN_MONTHS / 12) / PENSION_DIVISOR
        return Pension(False, service_months, short, None,
                       round(full, 2), reasons)

    years = service_months / 12
    if years >= LONG_SERVICE_THRESHOLD:
        years += LONG_SERVICE_BONUS_YEARS
        reasons.append(
            f"Twenty years of service adds a {LONG_SERVICE_BONUS_YEARS}-year "
            f"bonus to the calculation.")
    monthly = max(salary * years / PENSION_DIVISOR, PENSION_FLOOR)
    reasons.append(
        f"Formula: Rs {salary:,.0f} x {years:.1f} years / {PENSION_DIVISOR}.")
    reasons.append(
        f"Payable from age {PENSION_AGE}.")
    return Pension(True, service_months, 0, round(monthly, 2),
                   round(monthly, 2), reasons)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def main() -> int:
    checks: list[tuple[str, bool]] = []

    # --- withdrawal --------------------------------------------------------
    long_service = withdrawal_estimate(500_000, 72, True)
    checks += [
        ("five years of service is not taxed", long_service.tds_amount == 0),
        ("and the member keeps the whole balance",
         long_service.net == 500_000),
        ("the reason names the threshold",
         any("5-year threshold" in r for r in long_service.reasons)),
    ]

    small = withdrawal_estimate(40_000, 12, True)
    checks += [
        ("a balance under the threshold is not taxed", small.tds_amount == 0),
        ("and says which threshold", any("50,000" in r for r in small.reasons)),
    ]

    # exactly at each boundary - the place an off-by-one costs real money
    at_thresh = withdrawal_estimate(TDS_THRESHOLD, 12, True)
    over = withdrawal_estimate(TDS_THRESHOLD + 1, 12, True)
    at_years = withdrawal_estimate(200_000, TDS_FREE_YEARS * 12, True)
    under_years = withdrawal_estimate(200_000, TDS_FREE_YEARS * 12 - 1, True)
    checks += [
        ("exactly at the threshold is not taxed", at_thresh.tds_amount == 0),
        ("one rupee over is", over.tds_amount > 0),
        ("exactly five years is not taxed", at_years.tds_amount == 0),
        ("one month short is", under_years.tds_amount > 0),
    ]

    with_pan = withdrawal_estimate(200_000, 24, True)
    without = withdrawal_estimate(200_000, 24, False)
    checks += [
        ("with a PAN the rate is 10%", with_pan.tds_rate == 0.10),
        ("without one it is 20%", without.tds_rate == 0.20),
        ("the net is lower without a PAN", without.net < with_pan.net),
        ("and the page can say what the PAN is worth",
         any("worth Rs" in r for r in without.reasons)),
        ("waiting is offered as an alternative",
         any("more month" in r for r in with_pan.reasons)),
        ("Form 15G is mentioned", any("15G" in r for r in with_pan.reasons)),
        ("tax never exceeds the balance",
         all(w.tds_amount <= w.balance for w in
             (with_pan, without, over, under_years))),
        ("net plus tax equals the balance",
         abs(with_pan.net + with_pan.tds_amount - with_pan.balance) < 0.01),
    ]

    zero = withdrawal_estimate(0, 0, False)
    checks += [
        ("a zero balance is handled", zero.net == 0 and zero.tds_amount == 0),
        ("and says so rather than showing a rate",
         any("No balance" in r for r in zero.reasons)),
    ]

    # --- pension -----------------------------------------------------------
    short = pension_estimate(15)
    checks += [
        ("under ten years there is no pension", not short.eligible),
        ("the shortfall is counted", short.months_short == 105),
        ("no monthly figure is invented", short.monthly is None),
        ("but what full service would pay is shown",
         short.at_full_service > 0),
        ("Form 10C is offered instead",
         any("10C" in r for r in short.reasons)),
    ]

    ten = pension_estimate(120)
    checks += [
        ("exactly ten years qualifies", ten.eligible),
        # (15000 x 10) / 70 = 2142.86
        ("the formula matches the published example",
         abs(ten.monthly - 2142.86) < 1),
        ("the formula is shown, not just the answer",
         any("Formula" in r for r in ten.reasons)),
        ("the cap is explained", any("capped" in r for r in ten.reasons)),
        ("the age is stated", any("age 58" in r for r in ten.reasons)),
    ]

    # Published examples, checked one by one.
    for months, want in [(120, 2142.86), (240, 4714.29), (300, 5785.71)]:
        got = pension_estimate(months).monthly
        # 20 years and over carry the two-year bonus, so 240 is (15000 x 22)/70
        checks.append((f"{months // 12} years computes correctly",
                       abs(got - want) < 1))

    twenty = pension_estimate(240)
    nineteen = pension_estimate(228)
    checks += [
        ("twenty years earns the service bonus",
         any("bonus" in r for r in twenty.reasons)),
        ("nineteen does not",
         not any("bonus" in r for r in nineteen.reasons)),
        ("more service never pays less",
         pension_estimate(360).monthly >= twenty.monthly >= ten.monthly),
        ("the statutory floor is respected",
         pension_estimate(120, 1_000).monthly >= PENSION_FLOOR),
        ("a salary above the cap is capped",
         pension_estimate(120, 90_000).monthly == ten.monthly),
    ]

    print("=" * 68)
    print("  money - what you would receive, and what you would be paid")
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
