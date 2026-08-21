"""
The half of the EPFO member portal we had not built.

Vested began as a checker: it read your record and told you what was wrong with
it. That is the half of the portal marked "View". The real member portal also
has a "Manage" menu - KYC, e-Nomination, Mark Exit, contact details - and an
"Online Services" menu, where corrections and transfers are actually filed.

Reading a record and never offering the action that fixes it stops at the exact
moment of usefulness. These pages close that gap.

Two of them do something the real portal cannot:

  Mark Exit  - EPFO offers the screen but not the date. We compute the date
               from Form 26AS, so we can fill in the answer the member is
               otherwise asked to guess.
  KYC        - the bank-name mismatch that silently fails claims after approval
               is a name-comparison problem, and comparing names across
               documents is something we already do well.
"""

from __future__ import annotations

import re
from datetime import date

from app.views import esc, layout, portal_header, _rs
from core.epfo_rules import (
    ACCEPTED_DATE_EVIDENCE, ATTESTORS, ATTESTED_JD, EVIDENCE_NOTE,
    kyc_ready, kyc_unverified, jd_route,
)

_PILL = {
    "ok": ("money", "Looks right"),
    "risk": ("frozen", "Needs attention"),
    "unknown": ("unknown", "Not visible to us"),
}


def _kyc_items(a):
    """One source of truth, on the analysis itself - see Analysis.kyc_items."""
    return a.kyc_items


# ---------------------------------------------------------------------------

def page_manage(a, token: str = "sample") -> str:
    """The Manage hub - mirrors the real portal's second menu."""
    items = _kyc_items(a)
    at_risk = sum(1 for i in items if i.status != "ok")

    exits = _self_service_exits(a)
    exit_line = (f"{len(exits)} account{'s' if len(exits) != 1 else ''} you can "
                 f"correct yourself, without your employer"
                 if exits else "Nothing here needs your attention")

    ident = getattr(a, "identity", {}) or {}
    n_ids = len([ac for ac in getattr(a, "accounts", []) if not getattr(ac, "orphan", False)])
    uan_line = ("Your passbooks disagree about your date of birth"
                if ident.get("dob_conflict") else
                f"{n_ids} member ID{'s' if n_ids != 1 else ''} under one number")

    hist_line = ("Dates entered - your record has been checked against them"
                 if getattr(a, "history_typed", False) else
                 "Your joining and exit dates, typed from the portal"
                 if not getattr(a, "dates_checked", True) else
                 "The dates EPFO holds, and what they are tested against")

    return layout("Manage", f"""
<h1>Manage your account</h1>
<p class="lede">The things you can change yourself &mdash; and the one thing
most people do not know they can.</p>

<a class="acct" href="/exit?s={esc(token)}">
  <strong>Mark Exit</strong><br>
  <span class="detail">{esc(exit_line)}</span></a>
<a class="acct" href="/kyc?s={esc(token)}">
  <strong>KYC</strong><br>
  <span class="detail">{at_risk} of {len(items)} items need checking before a claim
  can settle automatically</span></a>
<a class="acct" href="/nomination?s={esc(token)}">
  <strong>e-Nomination</strong><br>
  <span class="detail">Who receives this money if you die before you claim it</span></a>
<a class="acct" href="/transfer?s={esc(token)}">
  <strong>Transfer an old account</strong><br>
  <span class="detail">One Member &ndash; One EPF Account, Form 13</span></a>
<a class="acct" href="/uan-card?s={esc(token)}">
  <strong>UAN card</strong><br>
  <span class="detail">{esc(uan_line)}</span></a>
<a class="acct" href="/contact?s={esc(token)}">
  <strong>Contact details</strong><br>
  <span class="detail">The Aadhaar-linked number every digital route depends on</span></a>
<a class="acct" href="/history?s={esc(token)}">
  <strong>Service history</strong><br>
  <span class="detail">{esc(hist_line)}</span></a>

<div class="card">
  <h2>What we changed here, and why</h2>
  <p>EPFO now settles most claims automatically. Employer approval has been
  removed for digital withdrawals and replaced by system checks against your own
  record.</p>
  <p><strong>Automating the decision does not improve the data it is made on.</strong>
  When a clerk approved claims, a wrong date got a phone call. When the decision
  is automated, a wrong date gets a rejection &mdash; faster, and with nobody to
  ask. That is why these screens check before they file.</p>
</div>
""", portal_header(a, token, "/manage"))


# ---------------------------------------------------------------------------

def page_kyc(a, token: str = "sample") -> str:
    items = _kyc_items(a)
    rows = ""
    for i in items:
        cls, label = _PILL[i.status]
        rows += f"""<tr>
          <th>{esc(i.label)}</th>
          <td><span class="pill {cls}">{esc(label)}</span></td>
          <td class="detail">{esc(i.note)}</td></tr>"""

    # Three states, as everywhere else in this product. "We found nothing wrong"
    # and "we could not look" are different sentences and must never collapse
    # into the same reassuring one.
    if not kyc_ready(items):
        banner = """
<div class="banner frozen"><h2>Something here would fail the check</h2>
<p>At least one item below is inconsistent across your own documents. EPFO's
check is literal, and this is the kind of thing it stops on.</p></div>"""
    elif kyc_unverified(items):
        banner = """
<div class="banner unknown"><h2>Nothing visible is wrong &mdash; but we cannot see all of it</h2>
<p>What your documents show is consistent. Your bank and Aadhaar KYC live inside
EPFO, and we will not tell you they are fine when we have not seen them.</p></div>"""
    else:
        banner = """
<div class="banner money"><h2>Nothing here is blocking you</h2>
<p>Every item we could see is consistent.</p></div>"""

    return layout("KYC", f"""
<h1>KYC</h1>
<p class="lede">The quiet reason claims fail after they have been approved.</p>
{banner}

<div class="card">
  <h2>What we can and cannot see</h2>
  <table>{rows}</table>
</div>

<div class="card">
  <h2>Why this page exists</h2>
  <p>A bank account name that does not match your UAN and Aadhaar
  <em>exactly</em> is one of the most common causes of an automatic rejection.
  An expanded initial is enough &mdash; <strong>R. K. Singh</strong> and
  <strong>Rahul Kumar Singh</strong> are the same person to you and two different
  people to the check.</p>
  <p>It is also a gate. Without KYC reading <strong>Approved</strong>,
  auto-settlement, UPI withdrawal and ATM withdrawal are all unavailable to you,
  whatever your balance says.</p>
</div>
""", portal_header(a, token, "/manage"))


# ---------------------------------------------------------------------------

def _self_service_exits(a) -> list:
    """Findings the member can fix alone, using EPFO's own Mark Exit screen."""
    if not getattr(a, "checked", False):
        return []
    return [c for c in a.result.get("contradictions", [])
            if "Self-service" in (c.get("correction_route") or "")]


def page_exit(a, token: str = "sample") -> str:
    """
    Mark Exit - the highest-leverage screen in this product.

    EPFO gives members a form and asks for a date. We know the date, because
    Form 26AS records the last month an employer paid you. The portal has the
    action and not the answer; we have the answer and not the action. This page
    hands the member both halves.
    """
    fixes = _self_service_exits(a)

    if not a.checked:
        body = """
<div class="banner unknown"><h2>Not yet known</h2>
<p>Without your service history we cannot tell which accounts are missing an
exit date. Add it and this page will fill itself in.</p></div>"""
    elif not fixes:
        body = """
<div class="banner money"><h2>Nothing to mark</h2>
<p>No account in your record is missing an exit date that you could set
yourself.</p></div>"""
    else:
        rows = ""
        for c in fixes:
            rows += f"""<li><strong>{esc(c['employer'].split(' | ')[0])}</strong><br>
              <span class="detail">{esc(c['proposed_fix'])}</span></li>"""
        body = f"""
<div class="banner calm">
  <h2>You can fix {len(fixes)} of these yourself</h2>
  <p>No employer, no letter, no waiting. EPFO lets you set a missing exit date
  from your own login once two months have passed since the last contribution.</p>
</div>
<div class="card">
  <h2>The dates to enter</h2>
  <ul class="steps">{rows}</ul>
  <p class="detail">We read these from Form 26AS &mdash; the last month each
  employer actually paid you, as recorded by the Income Tax Department.</p>
</div>"""

    return layout("Mark Exit", f"""
<h1>Mark Exit</h1>
<p class="lede">The one correction that needs nobody&rsquo;s permission but yours.</p>
{body}

<div class="card">
  <h2>How to do it on the EPFO portal</h2>
  <ol class="steps">
    <li>Log in to the UAN member portal</li>
    <li>Go to <strong>Manage &rarr; Mark Exit</strong></li>
    <li>Choose the PF account from <strong>Select Employment</strong></li>
    <li>Enter the date of exit and the reason for leaving</li>
    <li>Verify with the OTP sent to your Aadhaar-linked mobile</li>
  </ol>
</div>

<div class="card">
  <h2>Read this before you submit</h2>
  <p><strong>You get one attempt.</strong> Once submitted, the exit date cannot
  be changed again from the portal &mdash; correcting it after that needs a Joint
  Declaration and your employer. Check the date against your final payslip before
  you confirm it.</p>
  <p>This screen only works for an exit date that is <em>missing</em>. A date
  that is already recorded and wrong, a wrong date of joining, or two jobs that
  overlap all still need the employer.</p>
</div>
""", portal_header(a, token, "/manage"))


# ---------------------------------------------------------------------------

def page_nomination(a, token: str = "sample") -> str:
    who = (getattr(a, "identity", {}) or {}).get("name") or "you"
    return layout("e-Nomination", f"""
<h1>e-Nomination</h1>
<p class="lede">Who receives this money if you die before you claim it.</p>

<div class="banner unknown">
  <h2>We cannot see whether you have filed one</h2>
  <p>Nomination status lives inside EPFO and is not in any document you gave us.
  If you have never filed one, it is very likely still empty.</p>
</div>

<div class="card">
  <h2>Why this is not a formality</h2>
  <p>Without a valid nomination, your provident fund and the pension under EPS
  do not simply pass to your family. They wait &mdash; for a succession
  certificate, or a legal heir certificate, obtained while the people who need
  the money are grieving.</p>
  <p>The balance shown in this account is
  <strong>{esc(_rs(a.total_balance))}</strong>. That is the amount this one form
  decides the fate of.</p>
</div>

<div class="card">
  <h2>How to file it</h2>
  <ol class="steps">
    <li>Log in to the UAN member portal</li>
    <li><strong>Manage &rarr; E-Nomination</strong></li>
    <li>Confirm your family declaration, then add each nominee with their
      Aadhaar, date of birth and relationship</li>
    <li>Set the share for each &mdash; the total must come to 100%</li>
    <li>e-Sign with Aadhaar OTP</li>
  </ol>
  <p class="detail">It fails most often for a reason nobody warns you about: a
  missing profile photograph or a missing permanent address. Complete your
  profile first and the form will go through.</p>
</div>

<div class="card">
  <h2>What is mocked here</h2>
  <p>This prototype cannot read or file your nomination &mdash; that needs a
  connection to EPFO we do not have and would not claim. The guidance is real;
  the status is not shown because we cannot see it.</p>
</div>
""", portal_header(a, token, "/manage"))


# ---------------------------------------------------------------------------

def page_transfer(a, token: str = "sample") -> str:
    """Form 13 - the action that recovers an account we found."""
    orphans = getattr(a, "orphans", []) or []

    if not a.checked:
        found = """
<div class="banner unknown"><h2>Not yet known</h2>
<p>Without your service history we cannot tell a forgotten account from one we
simply have not been shown, so we are not going to guess.</p></div>"""
    elif not orphans:
        found = """
<div class="banner money"><h2>Nothing left behind</h2>
<p>Every employer in your tax records already appears in your PF record.</p></div>"""
    else:
        rows = ""
        for o in orphans:
            nm = getattr(o, "employer_name", None) or getattr(o, "tan", "Unknown employer")
            rows += f"<li><strong>{esc(nm)}</strong></li>"
        found = f"""
<div class="banner calm">
  <h2>{len(orphans)} account{'s' if len(orphans) != 1 else ''} to bring across</h2>
  <p>These employers paid you, according to the Income Tax Department, but do not
  appear in your PF record.</p>
</div>
<div class="card"><h2>Employers to transfer from</h2>
<ul class="steps">{rows}</ul></div>"""

    return layout("Transfer", f"""
<h1>Transfer an old account</h1>
<p class="lede">One Member &ndash; One EPF Account. Form 13.</p>
{found}

<div class="card">
  <h2>How to file it</h2>
  <ol class="steps">
    <li>Log in to the UAN member portal</li>
    <li><strong>Online Services &rarr; One Member &ndash; One EPF Account
      (Transfer Request)</strong></li>
    <li>Verify your present account, then enter the old member ID</li>
    <li>Choose who attests it &mdash; your present or previous employer</li>
    <li>Submit with the OTP, then send the signed PDF to the attesting employer</li>
  </ol>
  <p class="detail">Statutory limit is 20 working days.</p>
</div>

<div class="card">
  <h2>Why this matters more than the balance</h2>
  <p>Money left in an old account is the smaller loss. The larger one is the
  <strong>service</strong>: EPS pension needs ten years of eligible service, and
  years stranded in an unlinked account may not count toward it. Transferring is
  how scattered employment becomes one continuous record.</p>
</div>
""", portal_header(a, token, "/manage"))


# ---------------------------------------------------------------------------

def page_uan_card(a, token: str = "sample") -> str:
    """
    The UAN card, assembled from the member's own documents.

    The real portal hands you a PDF. This builds the same thing out of what your
    passbooks actually say - which means it can do one thing the official card
    cannot: show you every member ID under the UAN side by side, and say so out
    loud when two of them disagree about your date of birth.
    """
    ident = getattr(a, "identity", {}) or {}
    dob = ident.get("dob")
    conflict = ident.get("dob_conflict") or []

    accounts = [ac for ac in getattr(a, "accounts", []) if not getattr(ac, "orphan", False)]
    ids = "".join(
        f"<tr><td><code>{esc(ac.member_id)}</code></td>"
        f"<td>{esc(ac.employer)}</td></tr>"
        for ac in accounts) or "<tr><td colspan=2>No member ID found</td></tr>"

    warn = ""
    if conflict:
        warn = f"""
<div class="banner frozen">
  <h2>Your passbooks disagree about your date of birth</h2>
  <p>Two of your accounts record different dates: {esc(', '.join(conflict))}.
  A date-of-birth mismatch is one of the causes of rejection EPFO names, and it
  cannot be corrected without a Joint Declaration.</p>
</div>"""

    return layout("UAN card", f"""
<h1>Your UAN card</h1>
<p class="lede">Everything EPFO holds under one number, assembled from your own
documents.</p>
{warn}

<div class="doc">
  <table>
    <tr><th>Name</th><td>{esc(ident.get('name') or 'Not found')}</td></tr>
    <tr><th>UAN</th><td><code>{esc(ident.get('uan') or 'Not found')}</code></td></tr>
    <tr><th>Date of birth</th><td>{esc(dob.strftime('%d %B %Y') if dob else 'Not found in your documents')}</td></tr>
    <tr><th>PAN</th><td>{esc(ident.get('pan') or 'Not found')}</td></tr>
  </table>
  <h3>Member IDs under this UAN</h3>
  <table>{ids}</table>
</div>

<div class="card">
  <h2>Why one number matters</h2>
  <p>The UAN is meant to be the thread that ties every job together. It only
  works if every old member ID has actually been linked to it &mdash; and an
  account that was never transferred stays invisible to it, taking its balance
  and its years of service with it.</p>
  <p><a href="/transfer?s={esc(token)}">Bring an old account across &rarr;</a></p>
</div>

<div class="card">
  <h2>What is mocked here</h2>
  <p>The official UAN card is issued by EPFO and carries their seal. This is
  assembled from the documents you gave us, so it is a reference sheet rather
  than a document you can file. Print it if it is useful to carry.</p>
</div>
""", portal_header(a, token, "/manage"))


# ---------------------------------------------------------------------------

def page_contact(a, token: str = "sample") -> str:
    """
    Contact details.

    Thin on its own, and worth a page because of what hangs off it: under EPFO
    3.0 every digital route - auto-settlement, UPI, ATM - is gated on an OTP to
    the Aadhaar-linked mobile. A dead number silently closes all three, and
    nobody tells you that is why.
    """
    ident = getattr(a, "identity", {}) or {}
    return layout("Contact details", f"""
<h1>Contact details</h1>
<p class="lede">The quietest single point of failure in your whole account.</p>

<div class="banner unknown">
  <h2>We cannot see your registered number</h2>
  <p>Your mobile and email live inside EPFO and appear in none of the documents
  you gave us. What we can tell you is what depends on them.</p>
</div>

<div class="card">
  <h2>What breaks if this number is wrong</h2>
  <table>
    <tr><th>Auto-settlement</th><td>Needs an OTP. No OTP, no automatic claim.</td></tr>
    <tr><th>UPI withdrawal</th><td>Needs an OTP.</td></tr>
    <tr><th>ATM withdrawal</th><td>Needs an OTP.</td></tr>
    <tr><th>e-Nomination</th><td>Signed with an Aadhaar OTP.</td></tr>
    <tr><th>Mark Exit</th><td>Confirmed with an Aadhaar OTP.</td></tr>
  </table>
  <p><strong>It must be the number linked to your Aadhaar</strong>, not merely a
  number EPFO has on file. People change phones and leave the old number with
  UIDAI for years without noticing, then find every digital route closed at the
  moment they need money.</p>
</div>

<div class="card">
  <h2>How to change it</h2>
  <ol class="steps">
    <li>Log in to the UAN member portal</li>
    <li><strong>Manage &rarr; Contact Details</strong></li>
    <li>Tick the mobile number or email you want to change</li>
    <li>Enter the new one; an authorisation PIN is sent to it</li>
    <li>Enter the PIN &mdash; it updates immediately</li>
  </ol>
  <p class="detail">If the Aadhaar-linked number itself is dead, fix that at a
  UIDAI centre first. EPFO cannot help with it, and every step above depends on
  it working.</p>
</div>

<div class="card">
  <h2>On file with us</h2>
  <p>Name as your documents spell it:
  <strong>{esc(ident.get('name') or 'not found')}</strong>.
  <a href="/profile?s={esc(token)}">See every spelling &rarr;</a></p>
</div>
""", portal_header(a, token, "/manage"))


DMY = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*$")


def build_history_text(rows: list[dict]) -> str:
    """
    Turn typed dates into the same text the file parser already reads.

    Deliberately produces the document format rather than reconciler objects, so
    a typed history travels through exactly the same code path as an uploaded
    one. There is no second implementation to drift.
    """
    out = ["Service History",
           "Member ID                     Establishment            "
           "Date of Joining   Date of Exit"]
    for r in rows:
        out.append(f"{r['member_id']}        {r.get('employer', '')}        "
                   f"{r['doj']}        {r.get('doe') or '-'}")
    return "\n".join(out)


def read_history_form(form, accounts) -> tuple[list[dict], list[str]]:
    """
    Read the typed service history. Returns (rows, errors).

    Refuses rather than guesses. A date typed 03-04-2020 is ambiguous in exactly
    the way that matters here - it could be March or April - so the field is
    labelled DD-MM-YYYY, and anything that does not parse is rejected with the
    row named rather than silently coerced.
    """
    rows: list[dict] = []
    errors: list[str] = []

    for i, ac in enumerate(accounts):
        doj_raw = (form.get(f"doj{i}") or "").strip()
        doe_raw = (form.get(f"doe{i}") or "").strip()
        if not doj_raw and not doe_raw:
            continue

        who = ac.employer or ac.member_id

        def parse(raw, label):
            m = DMY.match(raw)
            if not m:
                errors.append(f"{who}: {label} should be DD-MM-YYYY, "
                              f"for example 01-04-2020.")
                return None
            d, mo, y = (int(x) for x in m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                errors.append(f"{who}: {label} is not a real date.")
                return None

        if not doj_raw:
            errors.append(f"{who}: a joining date is needed if you enter an "
                          f"exit date.")
            continue

        doj = parse(doj_raw, "the joining date")
        doe = parse(doe_raw, "the exit date") if doe_raw else None
        if doj is None or (doe_raw and doe is None):
            continue
        if doe and doe < doj:
            errors.append(f"{who}: the exit date is before the joining date.")
            continue

        rows.append({"member_id": ac.member_id, "employer": ac.employer,
                     "doj": doj.strftime("%d-%m-%Y"),
                     "doe": doe.strftime("%d-%m-%Y") if doe else None})

    if not rows and not errors:
        errors.append("Nothing was entered. Fill in at least the joining date "
                      "for one account.")
    return rows, errors


def page_history(a, token: str = "sample", errors: list | None = None,
                 form=None) -> str:
    """
    Type in your service history.

    The single biggest gap in this product, and it turned out not to be ours:
    the UAN portal shows service history as an on-screen table with no download
    button. Members screenshot it. A scan has no rows in it, and OCR guessing at
    a date is the exact failure this product exists to prevent - a misread digit
    would be indistinguishable from the employer error we are hunting.

    So we ask. Two dates per account, with the member IDs already filled in from
    the passbooks we read. It is still EPFO's assertion, just transcribed, which
    is why nothing downstream changes - only the provenance note.
    """
    accounts = [ac for ac in getattr(a, "accounts", []) if not getattr(ac, "orphan", False)]
    form = form or {}

    if not accounts:
        rows_html = ("<p>We have not read any PF account from your documents "
                     "yet, so there is nothing to attach dates to. Upload a "
                     "passbook first.</p>")
    else:
        rows_html = ""
        for i, ac in enumerate(accounts):
            rows_html += f"""
<div class="card">
  <h3>{esc(ac.employer)}</h3>
  <p class="detail">Member ID <code>{esc(ac.member_id)}</code> &middot;
  {ac.months} month{'s' if ac.months != 1 else ''} of contributions in your passbook</p>
  <div class="field">
    <label for="doj{i}">Date of joining</label>
    <input id="doj{i}" name="doj{i}" type="text" inputmode="numeric"
           placeholder="DD-MM-YYYY" value="{esc(form.get(f'doj{i}', ''))}">
  </div>
  <div class="field">
    <label for="doe{i}">Date of exit <span class="opt">&mdash; leave blank if you still work here</span></label>
    <input id="doe{i}" name="doe{i}" type="text" inputmode="numeric"
           placeholder="DD-MM-YYYY" value="{esc(form.get(f'doe{i}', ''))}">
  </div>
</div>"""

    err = ""
    if errors:
        err = ('<div class="banner frozen"><h2>Check these before continuing</h2><ul>'
               + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></div>")

    typed = ""
    if getattr(a, "history_typed", False):
        typed = """
<div class="banner calm">
  <h2>Your dates are in, and your record has been checked against them</h2>
  <p>Editing below and saving again will re-run every check.</p>
</div>"""

    return layout("Service history", f"""
<h1>Type in your service history</h1>
<p class="lede">The one thing we cannot read from a file &mdash; because EPFO
does not give you one.</p>
{err}{typed}

<div class="card">
  <h2>Where to find it</h2>
  <ol class="steps">
    <li>Log in to the UAN member portal</li>
    <li><strong>View &rarr; Service History</strong></li>
    <li>Copy the joining and exit dates for each account below</li>
  </ol>
  <p class="detail">The portal shows this as a table on screen with no download
  button, which is why most people end up with a screenshot. A screenshot has no
  rows in it that we can read, and guessing at a date from an image is exactly
  the mistake this product exists to catch &mdash; so we ask you instead.</p>
</div>

<form method="post" action="/history?s={esc(token)}">
  {rows_html}
  <button class="btn" type="submit">Check my record against these dates</button>
</form>

<div class="card">
  <h2>What this changes</h2>
  <p>These dates are <strong>EPFO&rsquo;s claim about you</strong>, not ours and
  not yours &mdash; you are transcribing what their portal says. That is the
  whole point: it is the claim being tested. Your own tax and PF records are what
  it gets tested against.</p>
  <p>Nothing is stored. These dates live in memory for this session only, exactly
  like your documents.</p>
</div>
""", portal_header(a, token, "/manage"))


# correction_help lives in views.py so the finding pages can reach it without
# importing this module back the other way.
