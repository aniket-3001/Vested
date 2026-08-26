"""
Every screen on the site.

House style, and it is not negotiable: labels and values, not sentences. The
real portal explains almost nothing and is perfectly usable; a wall of
reassuring prose is how you make somebody feel their money is complicated. If a
sentence is not doing work, it comes out.

Screens fall into three groups:
  - rebuilt EPFO screens, on synthetic data
  - the four that are ours: timeline, claim check, corrections, why-rejected
  - the sign-in and privacy pages
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

from datetime import date, timedelta

from app.portal import (MENUS, OK, NO, UNKNOWN, alert, bare, card, esc, kv,
                        pill, rs, shell, table)
from app import solver
from core.epfo_rules import AUTO_SETTLE_CEILING, settlement_verdict

from app.engine import TODAY  # one source of truth for "now"


def _who(a) -> tuple[str, str]:
    ident = getattr(a, "identity", {}) or {}
    return (ident.get("name") or "Member", ident.get("uan") or "")


def page(a, token, active, title, body, *, crumb="", heading=None, aside=""):
    m, u = _who(a)
    return shell(title, body, token=token, active=active, member=m, uan=u,
                 crumb=crumb or title, heading=heading, aside=aside)


def _d(d) -> str:
    """A date the way the portal prints it, or the portal's own em-dash."""
    return d.strftime("%d-%m-%Y") if d else "&mdash;"


# ---------------------------------------------------------------------------
# The timeline
# ---------------------------------------------------------------------------

def _runs(dates: list[date]) -> list[tuple[date, date]]:
    """Collapse a set of months into contiguous runs, so gaps stay visible."""
    if not dates:
        return []
    months = sorted({(d.year, d.month) for d in dates})
    runs, start, prev = [], months[0], months[0]
    for y, m in months[1:]:
        ny, nm = (prev[0] + 1, 1) if prev[1] == 12 else (prev[0], prev[1] + 1)
        if (y, m) != (ny, nm):
            runs.append((start, prev))
            start = (y, m)
        prev = (y, m)
    runs.append((start, prev))
    return [(date(a_[0], a_[1], 1), solver._month_end(date(b[0], b[1], 1)))
            for a_, b in runs]


def timeline_chart(r, obs) -> str:
    """
    Four tracks, one per source, over the same axis. Where EPFO's track stops
    short of the others, that gap is the defect - and it needs no caption.
    """
    mine = [o for o in obs if o.employer_key == r.key]
    if not mine:
        return ""
    lo = min([o.when for o in mine] + ([r.asserted_doj] if r.asserted_doj else []))
    hi = max([o.when for o in mine] + ([r.asserted_doe] if r.asserted_doe else []))
    lo, hi = date(lo.year, 1, 1), date(hi.year, 12, 31)
    span = max((hi - lo).days, 1)

    def pos(d):
        return max(0.0, min(100.0, (d - lo).days / span * 100))

    rows = ""
    # EPFO's own assertion first: it is the thing under test.
    if r.asserted_doj:
        end = r.asserted_doe or TODAY
        cls = "epfo"
        left, width = pos(r.asserted_doj), max(pos(end) - pos(r.asserted_doj), 0.7)
        seg = (f'<span class="sg {cls}" style="left:{left:.1f}%;'
               f'width:{width:.1f}%"></span>')
        rows += (f'<div class="tr2"><span class="lb">EPFO record</span>'
                 f'<span class="tk">{seg}</span></div>')

    for src in solver.TRACK_ORDER:
        if src == "EPFO_SERVICE":
            continue
        ds = [o.when for o in mine if o.source == src]
        if not ds:
            continue
        segs = ""
        for s, e in _runs(ds):
            left, width = pos(s), max(pos(e) - pos(s), 0.7)
            # Evidence after the recorded exit is the contradiction itself.
            bad = r.asserted_doe and e > r.asserted_doe
            segs += (f'<span class="sg {"bad" if bad else src.split("_")[0].lower()}"'
                     f' style="left:{left:.1f}%;width:{width:.1f}%"></span>')
        rows += (f'<div class="tr2"><span class="lb">'
                 f'{esc(solver.SOURCE_LABEL[src])}</span>'
                 f'<span class="tk">{segs}</span></div>')

    years = [y for y in range(lo.year, hi.year + 1)]
    axis = "".join(f"<span>{y}</span>" for y in years)
    # Each track is labelled beside itself, so a legend repeating those labels
    # is noise. Red is the only thing the picture does not explain.
    legend = ('<div class="lg"><span><i class="sg bad" style="position:static">'
              "</i>After the date EPFO recorded</span></div>"
              if "sg bad" in rows else "")
    return (f'<div class="tl"><div class="yr"><span class="lb"></span>{axis}</div>'
            f"{rows}{legend}</div>")


VERDICT_WORD = {
    "exit_wrong": ("Exit date is wrong", "no"),
    "exit_missing": ("No exit date recorded", "no"),
    "join_wrong": ("Joining date is wrong", "no"),
    "unlinked": ("Not linked to your UAN", "hm"),
    "agrees": ("Matches the evidence", "ok"),
}


def page_timeline(a, token="sample"):
    recs = solver.reconstruct(a)
    obs = getattr(a, "observations", []) or []
    if not recs:
        return page(a, token, "/timeline", "Service Timeline",
                    alert("<h2>Nothing to draw</h2>"
                          "<p>No employment evidence was found in the documents "
                          "supplied.</p>", "b"))
    body = ""
    for r in recs:
        word, tone = VERDICT_WORD.get(r.verdict, ("Checked", "nu2"))
        rows = [("EPFO records", f"{_d(r.asserted_doj)} to {_d(r.asserted_doe)}"),
                ("Evidence runs to", f"<strong>{_d(r.last_seen)}</strong>"),
                ("Status", pill(word, tone))]
        if r.exit_best and r.verdict in ("exit_wrong", "exit_missing"):
            rows.append(("Date to enter",
                         f'<strong>{_d(r.exit_best)}</strong> '
                         f'{pill(r.confidence + " confidence", "ok" if r.confidence == "High" else "hm")}'))
            rows.append(("Corroborated by", ", ".join(r.source_names)))
        body += card(r.employer,
                     timeline_chart(r, obs) + '<div style="margin-top:14px">'
                     + kv(rows) + "</div>")
    return page(a, token, "/timeline", "Service Timeline", body,
                crumb="View / Service Timeline",
                aside='<span class="sub">Your record against independent evidence</span>')


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

def page_home(a, token="sample"):
    g = solver.gates(a)
    ok, fail, unk = solver.gate_summary(g)
    # A forgotten account is real and worth money, but it does not stop a
    # settlement - EPFO pays out what is linked. Counting it towards "would be
    # rejected" would tell a member their claim is refused when it is not.
    blocking = solver.blocking_failures(g)
    advisory = solver.advisory_failures(g)
    fail = len(blocking)
    p = solver.plan(a)
    m, u = _who(a)
    ident = getattr(a, "identity", {}) or {}

    checked = getattr(a, "dates_checked", False)
    # A real failure outranks an incomplete check. Some defects - a month of
    # tax deducted with no PF deposited against it - are provable from the
    # passbook and 26AS alone, and burying one behind "not yet checked" would
    # hide a finding we actually have.
    caveat = ("" if checked else
              f' <a href="/history-entry?s={esc(token)}">'
              "Your service history has not been checked yet.</a>")
    if fail:
        top = alert(f"<h1>This claim would be rejected</h1>"
                    f"<p>{fail} of {len(g)} checks fail. "
                    f"Estimated time to fix: "
                    f"<strong>{p.critical_days} days</strong>.{caveat}</p>"
                    f'<p><a class="btn" href="/corrections?s={esc(token)}">'
                    f"See the plan</a></p>", "r")
    elif not checked:
        top = alert("<h1>Not yet checked</h1><p>Your service history has not been "
                    "read, so no claim verdict can be given.</p>"
                    f'<p><a class="btn" href="/history-entry?s={esc(token)}">'
                    "Add service history</a></p>", "b")
    else:
        top = alert("<h1>This claim should settle</h1>"
                    f"<p>{ok} of {len(g)} checks pass.</p>"
                    f'<p><a class="btn" href="/claim?s={esc(token)}">'
                    "Go to claim</a></p>", "g")
    if advisory:
        top += alert("<h2>Money left behind</h2><p>"
                     + "; ".join(esc(x.detail or x.name) for x in advisory)
                     + f'. <a href="/transfer?s={esc(token)}">Bring it across'
                     "</a></p>", "a")

    profile = card("Member Profile", kv([
        ("UAN", esc(u) or "&mdash;"),
        ("Name", esc(m)),
        ("Birth Date", _d(ident.get("dob"))),
        ("Total balance", rs(getattr(a, "total_balance", 0.0))),
    ]))

    rows = [("Passed", f'<span style="color:#2f9e44">{ok}</span>'),
            ("Failed", f'<span style="color:#d63b30">{fail}</span>')]
    if advisory:
        rows.append(("Money left behind", str(len(advisory))))
    rows.append(("Not visible to us", str(unk)))
    checks = card("Claim Check", kv(rows)
                  + f'<p style="margin-top:12px"><a href="/check?s={esc(token)}">'
                    f"All {len(g)} checks &rarr;</a></p>")

    links = [("&#128202;", "Service Timeline", "/timeline"),
             ("&#9989;", "Claim Check", "/check"),
             ("&#128296;", "Corrections", "/corrections"),
             ("&#128179;", "Passbook", "/passbook"),
             ("&#128100;", "KYC", "/kyc"),
             ("&#128228;", "Transfer", "/transfer")]
    ql = "".join(f'<a href="{h}?s={esc(token)}"><b>{i}</b>{esc(l)}</a>'
                 for i, l, h in links)

    return page(a, token, "/home", "Home",
                top + f'<div class="grid">{profile}{checks}</div>'
                + card("Quick Links", f'<div class="ql">{ql}</div>'),
                crumb="Home", heading=False)


# ---------------------------------------------------------------------------
# Claim check - the validator twin
# ---------------------------------------------------------------------------

MARK = {"pass": ('<span class="i ok">&#10003;</span>', ""),
        "fail": ('<span class="i no">&#10007;</span>', ""),
        "unknown": ('<span class="i un">?</span>', "")}


def page_check(a, token="sample"):
    g = solver.gates(a)
    ok, fail, unk = solver.gate_summary(g)
    items = ""
    for x in g:
        icon = MARK[x.status][0]
        bits = []
        if x.detail:
            bits.append(esc(x.detail))
        if x.href and x.status == "fail":
            bits.append(f'<a href="{x.href}?s={esc(token)}">fix this</a>')
        if x.status == "fail" and x.advisory:
            bits.append("does not block settlement")
        link = ""

        det = (f'<span class="m">{" &middot; ".join(bits)}</span>'
               if bits else "")
        items += (f"<li>{icon}<span><strong>{esc(x.code)}</strong> "
                  f"{esc(x.name)}{det}</span></li>")
    head = alert(f"<h2>{ok} pass &middot; {fail} fail &middot; {unk} not visible</h2>",
                 "r" if fail else "g")
    note = ('<p class="sub" style="margin-top:12px">Items marked <strong>?</strong> '
            "are held inside EPFO and are not in any document you can download. "
            "We do not guess them.</p>")
    return page(a, token, "/check", "Claim Check",
                head + card("Pre-settlement checks",
                            f'<ul class="gt">{items}</ul>{note}'),
                crumb="Online Services / Claim Check")


# ---------------------------------------------------------------------------
# Corrections - the plan
# ---------------------------------------------------------------------------

ROUTE_WORD = {
    "Self-service (Mark Exit) - member can fix without employer":
        ("You can do this yourself", "/exit"),
    "Digital Joint Declaration - employer must initiate":
        ("Employer must approve", "/joint-declaration"),
    "EPFiGMS grievance, then RTI if unanswered":
        ("Grievance", "/corrections"),
    "Transfer/withdrawal claim against the orphaned member ID":
        ("Transfer request", "/transfer"),
}


def page_corrections(a, token="sample"):
    p = solver.plan(a)
    if not p.steps:
        msg = ("Nothing to correct." if getattr(a, "dates_checked", False)
               else "Your service history has not been read yet.")
        return page(a, token, "/corrections", "Corrections",
                    alert(f"<h2>{msg}</h2>",
                          "g" if getattr(a, "dates_checked", False) else "b"),
                    crumb="Manage / Corrections")

    items = ""
    for s in p.steps:
        word, href = ROUTE_WORD.get(s.route, (s.route, "/corrections"))
        dep = ""
        if s.deps:
            verb = "completes" if len(s.deps) == 1 else "complete"
            dep = (f'<span class="par">Blocked until step '
                   f'{" and ".join(str(d) for d in s.deps)} {verb}</span>')
        items += (f"<li><b>{esc(s.title)}</b>"
                  f'<span class="m">{esc(s.detail)}</span>'
                  f'<span class="m">{esc(word)} &middot; about {s.days} '
                  f'{"day" if s.days == 1 else "days"} '
                  f'&middot; <a href="{href}?s={esc(token)}">open</a></span>'
                  f"{dep}</li>")

    summary = kv([
        ("Steps", str(len(p.steps))),
        ("If done in this order", f"<strong>about {p.critical_days} days</strong>"),
        ("If filed in the wrong order",
         f'<span style="color:#d63b30">{p.wasted_days} days wasted</span>'),
    ])
    warn = ""
    if p.blocked_steps:
        n = p.blocked_steps[0].n
        warn = alert(f"<h2>Order matters</h2><p>Step {n} will be rejected if you "
                     f"file it before the steps above are complete.</p>", "a")
    return page(a, token, "/corrections", "Corrections",
                warn + card("Repair plan", f'<ol class="stp">{items}</ol>')
                + card("Timing", summary, quiet=True),
                crumb="Manage / Corrections")


# ---------------------------------------------------------------------------
# Why was my claim rejected - retro-diagnosis
# ---------------------------------------------------------------------------

def page_why(a, token="sample", claims=None):
    claims = claims or getattr(a, "claim_history", []) or []
    rows = solver.diagnose(a, claims)
    if not rows:
        return page(a, token, "/why-rejected", "Why Was My Claim Rejected",
                    alert("<h2>No rejected claims on this record</h2>", "g"),
                    crumb="Online Services / Why Was My Claim Rejected")
    body = ""
    for r in rows:
        causes = ("".join(f"<li>{esc(c)}</li>" for c in r.causes)
                  if r.causes else "<li>No defect found that predates this claim.</li>")
        conf = pill("Likely cause" if r.confident else "Possible cause",
                    "no" if r.confident else "hm")
        body += card(f"{r.form} · {r.tracking_id}",
                     kv([("Filed", _d(r.filed)),
                         ("EPFO said", pill(r.status, "no")),
                         ("EPFO's reason", "&mdash; none given"),
                         ("Our finding", conf)])
                     + f'<ul style="margin:12px 0 0 18px">{causes}</ul>')
    return page(a, token, "/why-rejected", "Why Was My Claim Rejected",
                alert("<h2>EPFO records a rejection without a reason</h2>"
                      "<p>These are reconstructed from the record as it stood on "
                      "each filing date.</p>", "b") + body,
                crumb="Online Services / Why Was My Claim Rejected")


# ---------------------------------------------------------------------------
# Section landing pages
# ---------------------------------------------------------------------------
# The real portal opens these only on hover, which needs a mouse. Making each
# menu a real page is the one place this rebuild is deliberately better than
# the original.

def page_section(a, token, href):
    label, kids = next(((l, k) for h, l, k in MENUS if h == href), ("", []))
    tiles = "".join(
        f'<a href="{k}?s={esc(token)}"><b>&#9656;</b>{esc(kl)}</a>'
        for k, kl, new in kids)
    return page(a, token, href, label, card(label, f'<div class="ql">{tiles}</div>'),
                crumb=label)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

def page_profile(a, token="sample"):
    ident = getattr(a, "identity", {}) or {}
    nc = getattr(a, "name_check", None)
    m, u = _who(a)
    rows = [("UAN", esc(u) or "&mdash;"), ("Name", esc(m)),
            ("Date of Birth", _d(ident.get("dob"))),
            ("PAN", esc(ident.get("pan") or "&mdash;"))]
    body = card("Member Details", kv(rows))
    spellings = getattr(nc, "spellings", None) if nc is not None else None
    if spellings:
        sp = [[esc(k), esc(v)] for k, v in sorted(spellings.items())]
        body += card("Name as each document spells it",
                     table(["Document", "Name"], sp)
                     + '<p class="sub" style="margin-top:10px">Standardise on '
                       f"<strong>{esc(nc.canonical)}</strong>.</p>", quiet=True)
    clash = ident.get("dob_conflict") or []
    if clash:
        body = alert("<h2>Date of birth differs between documents</h2>"
                     f"<p>{' and '.join(esc(str(c)) for c in clash)}</p>", "r") + body
    return page(a, token, "/profile", "Profile", body, crumb="View / Profile")


def page_uan_card(a, token="sample"):
    m, u = _who(a)
    ident = getattr(a, "identity", {}) or {}
    ids = [[f"<code>{esc(x.member_id)}</code>", esc(x.employer)]
           for x in getattr(a, "accounts", []) if not x.orphan]
    return page(a, token, "/uan-card", "UAN Card",
                card("UAN Card", kv([("UAN", esc(u) or "&mdash;"), ("Name", esc(m)),
                                     ("Date of Birth", _d(ident.get("dob"))),
                                     ("KYC", OK if getattr(a, "kyc_ok", False) else NO)]))
                + card("Member IDs under this UAN",
                       table(["Member ID", "Establishment"], ids), quiet=True),
                crumb="View / UAN Card")


def page_passbook_lite(a, token="sample"):
    rows = []
    for acc in getattr(a, "accounts", [])[:1]:
        for e in list(getattr(acc, "entries", []) or [])[-5:]:
            rows.append([esc(getattr(e, "month", "")), rs(getattr(e, "employee", 0)),
                         rs(getattr(e, "employer", 0)), rs(getattr(e, "pension", 0)),
                         f"<code>{esc(acc.member_id)}</code>"])
    body = (table(["Wage Month", "Employee", "Employer", "Pension", "Member ID"], rows)
            if rows else '<p class="sub">No contributions to show.</p>')
    return page(a, token, "/passbook-lite", "Passbook Lite",
                card("Last Five Contributions", body), crumb="View / Passbook Lite")


def page_passbook(a, token="sample"):
    body = ""
    for acc in getattr(a, "accounts", []):
        if acc.orphan:
            continue
        rows = [[esc(getattr(e, "month", "")), rs(getattr(e, "employee", 0)),
                 rs(getattr(e, "employer", 0)), rs(getattr(e, "pension", 0))]
                for e in (getattr(acc, "entries", []) or [])]
        body += card(f"{acc.employer} · {acc.member_id}",
                     kv([("Balance", rs(acc.balance)), ("Pension", rs(acc.pension)),
                         ("Months", str(acc.months))])
                     + (table(["Month", "Employee", "Employer", "Pension"], rows)
                        if rows else ""))
    return page(a, token, "/passbook", "Passbook",
                body or alert("<h2>No passbook loaded</h2>", "b"),
                crumb="View / Passbook")


# ---------------------------------------------------------------------------
# Manage
# ---------------------------------------------------------------------------

def page_kyc(a, token="sample"):
    items = getattr(a, "kyc_items", []) or []
    rows = []
    for i in items:
        badge = {"ok": OK, "risk": NO, "unknown": UNKNOWN}.get(i.status, UNKNOWN)
        rows.append([esc(i.label), esc(getattr(i, "value", "") or "&mdash;"), badge])
    return page(a, token, "/kyc", "KYC",
                card("Currently Active KYC",
                     table(["Document Type", "Name as per Document", "Status"], rows))
                + card("Not visible to us",
                       '<p class="sub">Bank verification and Aadhaar linkage are held '
                       "inside EPFO. We report them as unknown rather than guess.</p>",
                       quiet=True),
                crumb="Manage / KYC")


def page_contact(a, token="sample"):
    return page(a, token, "/contact", "Contact Details",
                card("Aadhaar Linked Mobile Number",
                     kv([("Registered Mobile", "&mdash; " + NO),
                         ("Registered Email", "&mdash; " + NO)]))
                + card("What an unverified number blocks",
                       table(["Service", "Needs OTP"],
                             [["Auto-settlement", "Yes"], ["UPI withdrawal", "Yes"],
                              ["ATM withdrawal", "Yes"], ["Mark Exit", "Yes"]]),
                       quiet=True),
                crumb="Manage / Contact Details")


def page_nomination(a, token="sample"):
    return page(a, token, "/nomination", "E-Nomination",
                alert("<h2>Status not visible</h2><p>Nomination is held inside EPFO "
                      "and is not in any document you can download.</p>", "b"),
                crumb="Manage / E-Nomination")


def page_password(a, token="sample"):
    return page(a, token, "/password", "Change Password",
                card("Change Password",
                     '<div class="fr"><label for="p1">Current password</label>'
                     '<input type="password" id="p1" disabled></div>'
                     '<div class="fr"><label for="p2">New password</label>'
                     '<input type="password" id="p2" disabled></div>'
                     '<p class="sub">Disabled in the prototype.</p>'),
                crumb="Account / Change Password")


# ---------------------------------------------------------------------------
# Online Services
# ---------------------------------------------------------------------------

def page_history(a, token="sample"):
    rows, cls = [], []
    for r in solver.reconstruct(a):
        if r.verdict == "unlinked":
            continue
        word, tone = VERDICT_WORD.get(r.verdict, ("Checked", "nu2"))
        rows.append([f"<code>{esc(r.member_id or '-')}</code>", esc(r.employer),
                     _d(r.asserted_doj), _d(r.asserted_doe), pill(word, tone)])
        cls.append("pri" if len(rows) == 1 else "")
    body = (table(["Member ID", "Establishment", "Date of Joining",
                   "Date of Exit", "Status"], rows, cls)
            if rows else '<p class="sub">No service history on this record.</p>')
    return page(a, token, "/history", "Member Service History",
                card("Member Service History", body),
                crumb="Online Services / Member Service History")


def page_claim(a, token="sample"):
    g = solver.gates(a)
    ok, _all_fail, unk = solver.gate_summary(g)
    fail = len(solver.blocking_failures(g))
    bal = getattr(a, "total_balance", 0.0)
    if fail:
        top = alert("<h2>This claim would be rejected, not settled</h2>"
                    f'<p><a class="btn" href="/corrections?s={esc(token)}">'
                    "See what to fix</a></p>", "r")
    elif not getattr(a, "dates_checked", False):
        top = alert("<h2>Not yet known</h2><p>Service history has not been "
                    "checked.</p>", "b")
    else:
        top = alert("<h2>Eligible for auto-settlement</h2>", "g")
    if not getattr(a, "dates_checked", False):
        open_pill = pill("Not yet known", "nu2")
    else:
        open_pill = pill("Blocked", "no") if fail else pill("Open", "ok")
    forms = table(["Form", "Purpose", "Status"], [
        ["Form 31", "Advance", open_pill],
        ["Form 19", "Final settlement", open_pill],
        ["Form 10C", "Pension withdrawal", open_pill]])
    limits = [("Balance", rs(bal)),
              ("Auto-settlement ceiling", rs(AUTO_SETTLE_CEILING))]
    if not fail and getattr(a, "dates_checked", False):
        limits += [("By UPI", rs(bal * 0.75) + " &mdash; 75%"),
                   ("By ATM", rs(bal * 0.50) + " &mdash; 50%")]
    return page(a, token, "/claim", "Claim (Form 31, 19 & 10C)",
                top + card("Claim forms", forms)
                + card("Limits", kv(limits), quiet=True),
                crumb="Online Services / Claim")


def page_claim_10d(a, token="sample"):
    months = getattr(a, "service_months", 0)
    eligible = getattr(a, "pension_eligible", False)
    return page(a, token, "/claim-10d", "Claim (Form 10-D)",
                card("Monthly pension", kv([
                    ("Eligible service", f"{months} months"),
                    ("Needed", "120 months"),
                    ("Status", pill("Eligible", "ok") if eligible
                     else pill("Not yet eligible", "hm"))])),
                crumb="Online Services / Claim (Form 10-D)")


def page_transfer(a, token="sample"):
    orphans = [o for o in (getattr(a, "orphans", []) or [])
               if getattr(o.assessment, "verdict", "") == "LIKELY"]
    # An empty orphan list means one of two very different things: we looked
    # and found nothing, or we could not look at all. Telling a member their
    # money is all accounted for when we never checked is the failure this
    # product exists to prevent.
    if not getattr(a, "dates_checked", False):
        return page(a, token, "/transfer", "Request for Transfer of Account",
                    alert("<h2>Not yet known</h2><p>Forgotten accounts can only "
                          "be found once your service history has been read.</p>"
                          f'<p><a class="btn" href="/history-entry?s={esc(token)}">'
                          "Add service history</a></p>", "b"),
                    crumb="Online Services / Transfer")
    if not orphans:
        return page(a, token, "/transfer", "Request for Transfer of Account",
                    alert("<h2>Nothing left behind</h2>", "g"),
                    crumb="Online Services / Transfer")
    rows = []
    for o in orphans:
        c = o.candidate
        est = getattr(o.assessment, "estimate", None)
        rows.append([esc(c.employer_name), f"<code>{esc(c.tan)}</code>",
                     f"{_d(c.first_seen)} to {_d(c.last_seen)}",
                     (rs(est.low) + " &ndash; " + rs(est.high)) if est else "&mdash;"])
    return page(a, token, "/transfer", "Request for Transfer of Account",
                alert(f"<h2>{len(rows)} account"
                      f"{'' if len(rows) == 1 else 's'} not linked to your "
                      f"UAN</h2>", "a")
                + card("Form 13 — One Member, One EPF Account",
                       table(["Establishment", "TAN", "Period",
                              "Estimated balance"], rows)),
                crumb="Online Services / Transfer")


def page_track(a, token="sample"):
    return page(a, token, "/track", "Track Claim Status",
                card("Claim Status (Final Settlement, Advances, Withdrawal Benefit)",
                     '<p style="color:#d63b30;font-weight:600">Claim Record Not Found</p>',
                     quiet=True)
                + card("Transfer Claim Status",
                       '<p style="color:#d63b30;font-weight:600">No Claim Details Found</p>',
                       quiet=True),
                crumb="Online Services / Track Claim Status")


def page_track_old(a, token="sample"):
    hist = getattr(a, "claim_history", []) or []
    rows = []
    for c in hist:
        bad = "reject" in c["status"].lower()
        rows.append([f"<code>{esc(c['tracking_id'])}</code>", esc(c["form"]),
                     _d(c["filed"]), _d(c.get("sent") or c["filed"]),
                     pill(c["status"], "no" if bad else "ok")])
    body = (table(["Tracking ID", "Form Type", "Submitted", "Sent to Field Office",
                   "Current Status"], rows) if rows
            else '<p class="sub">No claims filed.</p>')
    if any("reject" in c["status"].lower() for c in hist):
        body += (f'<p style="margin-top:12px"><a href="/why-rejected?s={esc(token)}">'
                 "Why were these rejected? &rarr;</a></p>")
    return page(a, token, "/track-old", "Track Claim Status (OLD)",
                card("Online Claim Status", body),
                crumb="Online Services / Track Claim Status (OLD)")


def page_scheme_cert(a, token="sample"):
    return page(a, token, "/scheme-certificate", "Scheme Certificate Surrender",
                alert("<h2>No scheme certificate on this record</h2>", "b"),
                crumb="Online Services / Scheme Certificate Surrender")


# ---------------------------------------------------------------------------
# PMVBRY - present in the real nav, and it refuses you there too
# ---------------------------------------------------------------------------

PMVBRY_PAGES = {"/pmvbry": "Dashboard",
                "/pmvbry-flc": "Financial Literacy Course",
                "/pmvbry-cert": "FLC Certificate"}


def page_pmvbry(a, token="sample", href="/pmvbry"):
    what = PMVBRY_PAGES.get(href, "Dashboard")
    return page(a, token, href, what,
                alert("<h2>Not authorised</h2><p>You are not authorized to access "
                      "this functionality under this PMVBRY PART A scheme.</p>", "r"),
                crumb=f"PMVBRY / {what}")


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------
# Credentials are printed on the page on purpose. Anyone evaluating this has no
# PF documents of their own, and a form-first landing page hides the entire
# product behind a submit button.

def page_login(error: str = ""):
    from app.demo import ACCOUNTS
    rows = []
    for uan, acc in ACCOUNTS.items():
        rows.append([f"<code>{esc(uan)}</code>", f"<code>{esc(acc['password'])}</code>",
                     esc(acc["blurb"])])
    err = alert(f"<h2>{esc(error)}</h2>", "r") if error else ""
    form = ('<form method="post" action="/login">'
            '<div class="row">'
            '<div class="fr"><label for="uan">UAN</label>'
            '<input type="text" id="uan" name="uan" required></div>'
            '<div class="fr"><label for="password">Password</label>'
            '<input type="password" id="password" name="password" required></div>'
            '<div class="fr" style="flex:0 0 auto">'
            '<button class="btn" type="submit">Sign in</button></div>'
            "</div></form>")
    return bare("Sign in",
                '<div class="ttl"><h1>Member Sign In</h1></div>'
                + err + card("Sign in", form)
                + card("Test accounts",
                       table(["UAN", "Password", "Record"], rows), quiet=True)
                + card("Use your own documents",
                       f'<p><a class="btn o" href="/upload">Check your own record</a></p>',
                       quiet=True))


def page_privacy(a=None, token="sample"):
    body = (card("What happens to your documents",
                 kv([("Stored on disk", "Never"),
                     ("Written to a database", "Never"),
                     ("Sent to any government system", "Never"),
                     ("Sent to any model or API", "Never"),
                     ("Held in memory", "30 minutes, then dropped"),
                     ("Logged", "No filename, no content, no extracted text")]))
            + card("How to check",
                   '<p class="sub">You cannot verify this from outside, and you '
                   "should be sceptical of anyone who asks you to take their word "
                   "for it. The source is open and every claim above is enforced "
                   "by a test.</p>", quiet=True))
    if a is None:
        return bare("Privacy", '<div class="ttl"><h1>Privacy</h1></div>' + body)
    return page(a, token, "/privacy", "Privacy", body, crumb="Privacy")


def page_expired():
    return bare("Session expired",
                '<div class="ttl"><h1>Session expired</h1></div>'
                + alert("<h2>Sessions last 30 minutes</h2>"
                        '<p><a class="btn" href="/login">Sign in again</a></p>', "b"))


# ---------------------------------------------------------------------------
# Mark Exit
# ---------------------------------------------------------------------------

def page_exit(a, token="sample"):
    recs = [r for r in solver.reconstruct(a) if r.verdict == "exit_missing"]
    if not getattr(a, "dates_checked", False):
        return page(a, token, "/exit", "Mark Exit",
                    alert("<h2>Not yet known</h2><p>Service history has not been "
                          "read.</p>", "b"), crumb="Manage / Mark Exit")
    if not recs:
        return page(a, token, "/exit", "Mark Exit",
                    alert("<h2>Nothing to mark</h2>", "g"),
                    crumb="Manage / Mark Exit")
    # EPFO refuses a self-marked exit until two months have passed since the
    # last contribution. Offering the screen before then sends somebody to a
    # form that turns them away.
    ready = [r for r in recs if r.self_service_ready]
    waiting = [r for r in recs if not r.self_service_ready]

    rows = [[esc(r.employer), f"<code>{esc(r.member_id)}</code>",
             f"<strong>{_d(r.exit_best)}</strong>",
             pill(r.confidence, "ok" if r.confidence == "High" else "hm"),
             ", ".join(esc(s) for s in r.source_names)] for r in ready]

    head = (alert("<h2>You can do this yourself</h2><p>No employer approval "
                  "needed.</p>", "g") if ready else "")
    dates = (card("Dates to enter",
                  table(["Establishment", "Member ID", "Date of exit",
                         "Confidence", "From"], rows)) if ready else "")

    hold = ""
    if waiting:
        wrows = [[esc(r.employer), _d(r.last_seen),
                  f"<strong>{_d(r.wait_until)}</strong>"] for r in waiting]
        hold = (alert("<h2>Not yet &mdash; two months must pass</h2>"
                      "<p>EPFO reads a recent contribution as a job still "
                      "running.</p>", "a")
                + card("Opens later",
                       table(["Establishment", "Last contribution",
                              "You can mark exit from"], wrows)))

    return page(a, token, "/exit", "Mark Exit",
                head + hold + dates
                + card("Before you submit",
                       kv([("Attempts allowed", "One &mdash; it cannot be changed after"),
                           ("Verified by", "OTP to your Aadhaar-linked mobile"),
                           ("Does not cover",
                            "A date already recorded and wrong, a wrong joining "
                            "date, or overlapping service")]), quiet=True),
                crumb="Manage / Mark Exit")


# ---------------------------------------------------------------------------
# Joint Declaration - the correction that needs evidence
# ---------------------------------------------------------------------------
# Laid out the way the real portal lays it out: Entity, Available details,
# Changes requested. The difference is that the third column arrives filled in,
# with the evidence that produced it named underneath.

ACCEPTED_DOCS = ["Appointment letter", "Attendance register extract",
                 "Relieving letter or final payslip"]


def page_joint_declaration(a, token="sample", submitted=None):
    recs = [r for r in solver.reconstruct(a)
            if r.verdict in ("exit_wrong", "join_wrong")]
    if not recs:
        return page(a, token, "/joint-declaration", "Joint Declaration",
                    alert("<h2>No correction needed</h2>", "g"),
                    crumb="Manage / Joint Declaration")

    body = ""
    for i, r in enumerate(recs):
        cur = _d(r.asserted_doe) if r.verdict == "exit_wrong" else _d(r.asserted_doj)
        new = _d(r.exit_best)
        field_name = ("Date of Exit" if r.verdict == "exit_wrong"
                      else "Date of Joining")
        rows = [[esc(field_name), cur,
                 f'<strong style="color:#2f9e44">{new}</strong>'],
                ["Member ID", f"<code>{esc(r.member_id)}</code>", "&mdash;"],
                ["Establishment", esc(r.employer), "&mdash;"]]
        opts = "".join(f'<option>{esc(d)}</option>' for d in ACCEPTED_DOCS)
        form = (f'<form method="post" action="/joint-declaration?s={esc(token)}">'
                f'<input type="hidden" name="key" value="{esc(r.key)}">'
                f'<div class="row">'
                f'<div class="fr"><label for="doc{i}">Supporting document</label>'
                f'<select id="doc{i}" name="doc">{opts}</select></div>'
                f'<div class="fr"><label for="f{i}">Upload</label>'
                f'<input type="text" id="f{i}" name="file" '
                f'placeholder="filename.pdf"></div>'
                f'<div class="fr" style="flex:0 0 auto">'
                f'<button class="btn" type="submit">Submit</button></div>'
                f"</div></form>")
        body += card(f"{esc(r.employer)}",
                     table(["Entity", "Available details", "Changes requested"], rows)
                     + '<p class="sub" style="margin:12px 0">Proposed date derived '
                       f"from {esc(', '.join(r.source_names))}. "
                       f"Confidence {esc(r.confidence.lower())}.</p>" + form)

    note = card("What EPFO accepts as evidence",
                table(["Document", "Accepted"],
                      [[esc(d), OK] for d in ACCEPTED_DOCS]
                      + [["Form 26AS", pill("Not on the list", "hm")]])
                + '<p class="sub" style="margin-top:10px">Form 26AS is how we know '
                  "the date is wrong. It is not what EPFO accepts to change it.</p>",
                quiet=True)
    top = ""
    if submitted:
        top = alert(f"<h2>Submitted</h2><p>Reference "
                    f"<code>{esc(submitted)}</code>. "
                    f'<a href="/corrections?s={esc(token)}">Track it</a></p>', "g")
    return page(a, token, "/joint-declaration", "Joint Declaration",
                top + body + note, crumb="Manage / Joint Declaration")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
# Previewed, never sent. Sending real mail would mean holding an address and
# making an outbound call, which is exactly what the privacy page promises we
# do not do.

def page_notifications(a, token="sample", events=None):
    events = events if events is not None else default_events(a)
    if not events:
        return page(a, token, "/notifications", "Notifications",
                    alert("<h2>Nothing to report</h2>", "g"),
                    crumb="Account / Notifications")
    rows = [[_d(e["on"]), esc(e["subject"]), pill(e["kind"], e["tone"])]
            for e in events]
    preview = events[0]
    mail = card("Email preview",
                kv([("To", "the address on your UAN"),
                    ("Subject", esc(preview["subject"])),
                    ("Body", esc(preview["body"]))])
                + '<p class="sub" style="margin-top:10px">Previewed, not sent. '
                  "This prototype makes no outbound connection.</p>", quiet=True)
    return page(a, token, "/notifications", "Notifications",
                card("Alerts", table(["Date", "Subject", "Type"], rows)) + mail,
                crumb="Account / Notifications")


def default_events(a) -> list[dict]:
    """What this record would have been told, and when."""
    out = []
    g = solver.gates(a)
    p = solver.plan(a)
    # Count what actually blocks. Counting the advisory gate here would put a
    # different number in the alert than the dashboard shows for the same
    # record.
    blocking = len(solver.blocking_failures(g))
    if blocking:
        noun = "check" if blocking == 1 else "checks"
        out.append({
            "on": TODAY, "kind": "Action needed", "tone": "no",
            "subject": f"{blocking} {noun} would reject your claim",
            "body": (f"{blocking} of {len(g)} pre-settlement {noun} fail. "
                     f"Estimated {p.critical_days} days to clear if done in "
                     f"order.")})
    for r in solver.reconstruct(a):
        if r.verdict == "exit_missing" and r.self_service_ready:
            out.append({
                "on": TODAY, "kind": "You can fix this", "tone": "hm",
                "subject": f"Exit date missing for {r.employer}",
                "body": (f"Mark Exit accepts {_d(r.exit_best)}. "
                         "No employer approval needed.")})
        elif r.verdict == "exit_missing":
            out.append({
                "on": TODAY, "kind": "Wait", "tone": "nu2",
                "subject": f"Exit date missing for {r.employer}",
                "body": (f"Mark Exit opens on {_d(r.wait_until)}, two months "
                         "after the last contribution.")})
    for c in getattr(a, "claim_history", []) or []:
        if "reject" in c["status"].lower():
            out.append({
                "on": c["filed"], "kind": "Rejected", "tone": "no",
                "subject": f"{c['form']} rejected",
                "body": "EPFO gave no reason. See Why Was My Claim Rejected."})
    return out


# ---------------------------------------------------------------------------
# Typing in the service history
# ---------------------------------------------------------------------------
# EPFO shows this as a table on screen with no download button, so most people
# end up with a screenshot. Reading dates out of an image is exactly the guess
# this product exists to avoid, so we ask instead.

def page_history_entry(a, token="sample", errors=None, form=None):
    accounts = [ac for ac in getattr(a, "accounts", []) if not ac.orphan]
    form = form or {}
    err = ""
    if errors:
        err = alert("<h2>Check these dates</h2><ul style='margin:6px 0 0 18px'>"
                    + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul>", "r")
    rows = ""
    for i, ac in enumerate(accounts):
        doj = esc(form.get(f"doj{i}", ""))
        doe = esc(form.get(f"doe{i}", ""))
        rows += (f'<tr><td>{esc(ac.employer)}<br>'
                 f'<code style="font-size:12px">{esc(ac.member_id)}</code>'
                 f'<input type="hidden" name="mid{i}" value="{esc(ac.member_id)}">'
                 f'<input type="hidden" name="emp{i}" value="{esc(ac.employer)}">'
                 f'</td>'
                 f'<td><label class="sr" for="doj{i}">Date of joining</label>'
                 f'<input type="text" id="doj{i}" name="doj{i}" value="{doj}" '
                 f'placeholder="DD-MM-YYYY" required></td>'
                 f'<td><label class="sr" for="doe{i}">Date of exit</label>'
                 f'<input type="text" id="doe{i}" name="doe{i}" value="{doe}" '
                 f'placeholder="DD-MM-YYYY or blank"></td></tr>')
    body = (f'<form method="post" action="/history-entry?s={esc(token)}">'
            f'<input type="hidden" name="n" value="{len(accounts)}">'
            f'<div class="tw"><table class="d"><thead><tr>'
            f"<th>Establishment</th><th>Date of Joining</th><th>Date of Exit</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
            f'<p style="margin-top:14px">'
            f'<button class="btn" type="submit">Check my record</button></p></form>')
    where = card("Where to find it",
                 kv([("Portal", "Online Services &rarr; Member Service History"),
                     ("Copy", "The joining and exit dates for each account"),
                     ("Leave blank", "If no exit date is shown")])
                 + '<p class="sub" style="margin-top:10px">The portal shows this '
                   "as a table with no download button, so most people end up with "
                   "a screenshot. We cannot read dates out of an image without "
                   "guessing, so we ask you instead. These are "
                   "<strong>EPFO&rsquo;s dates</strong>, not ours &mdash; type "
                   "them exactly as shown.</p>", quiet=True)
    return page(a, token, "/history", "Service History",
                err + card("Enter your service history", body) + where,
                crumb="Online Services / Service History")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
# Documents are identified by content, not by which box they were dropped into,
# so the boxes are a convenience rather than a requirement.

def page_upload(error: str = ""):
    err = alert(f"<h2>{esc(error)}</h2>", "r") if error else ""
    fields = [
        ("f26as", "Form 26AS", "Income Tax portal &rarr; TRACES", True),
        ("passbook", "PF passbook", "passbook.epfindia.gov.in", True),
        ("history", "Service history", "Online Services &rarr; Member Service History", False),
        ("bank", "Bank statement", "Salary account", False),
    ]
    rows = ""
    for name, label, where, multi in fields:
        rows += (f'<div class="fr"><label for="{name}">{label} '
                 f'<span class="sub">&middot; {where}</span></label>'
                 f'<input type="file" id="{name}" name="{name}"'
                 f'{" multiple" if multi else ""}></div>')
    form = (f'<form method="post" action="/analyse" '
            f'enctype="multipart/form-data">{rows}'
            f'<div class="fr"><label for="password">Password '
            f'<span class="sub">&middot; Form 26AS is usually locked with your '
            f'date of birth</span></label>'
            f'<input type="password" id="password" name="password"></div>'
            f'<button class="btn" type="submit">Check my record</button>'
            f"</form>")
    return bare("Check your record",
                '<div class="ttl"><h1>Check your record</h1></div>' + err
                + card("Your documents", form)
                + card("Or try a test account",
                       f'<p><a class="btn o" href="/login">Sign in with a test '
                       f"account</a></p>", quiet=True)
                + card("What happens to them",
                       kv([("Stored", "Never"), ("Logged", "Never"),
                           ("Sent anywhere", "Never"),
                           ("Held in memory", "30 minutes")]), quiet=True))
