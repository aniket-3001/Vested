"""
Server-rendered HTML. No client framework, no web fonts, no build step.

Design constraints, taken from the brief's requirement to design for "mobile
devices, slower connections or limited digital experience":

  - system font stack, so nothing is downloaded before text renders
  - the page is readable and usable with CSS disabled
  - no JavaScript is required for any step of the journey
  - one decision per screen, in plain language
  - large touch targets and high contrast

The independent-prototype banner is mandatory, not decorative: the rules forbid
presenting a build as official or endorsed.
"""

from __future__ import annotations

import hashlib
import html

from app.cssmin import minify
from core.epfo_rules import (
    ACCEPTED_DATE_EVIDENCE, ATTESTORS, CATEGORIES, DELAY_PENALTY_PCT,
    EVIDENCE_NOTE, OUTER_LIMIT_DAYS, TARGET_DAYS, jd_route,
)

CSS = """
:root{
  --paper:#FAF9F6; --card:#FFFFFF; --sunk:#F1EFE9;
  --ink:#1C1B18; --muted:#5C5A54; --line:#DFDCD4;
  --accent:#11605B; --accent-soft:#E3EFED;
  --frozen:#8E3419; --frozen-soft:#F8E8E2;
  --money:#2A6640; --money-soft:#E3F0E7;
  --unknown:#6B5B2E; --unknown-soft:#F4F0E2;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-size:18px; line-height:1.6;
}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 72px}
a{color:var(--accent)}
a:focus-visible,button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

.flag{
  background:var(--sunk); border-bottom:1px solid var(--line);
  font-size:14px; color:var(--muted); padding:9px 0; text-align:center;
}
.flag strong{color:var(--ink)}

header.top{padding:26px 0 20px;border-bottom:1px solid var(--line);margin-bottom:26px}
header.portal{border-bottom:1px solid var(--line);margin-bottom:26px}
.bar{display:flex;justify-content:space-between;align-items:baseline;gap:14px;
  flex-wrap:wrap;padding:22px 0 14px}
.who{margin:0;font-size:15px;color:var(--muted);text-align:right}
.who strong{color:var(--ink);display:block;font-size:16px}
.tabs{display:flex;gap:4px;flex-wrap:wrap;margin:0 0 -1px}
.tabs a{padding:11px 16px;text-decoration:none;color:var(--muted);font-weight:600;
  font-size:16px;border:1px solid transparent;border-bottom:none;
  border-radius:6px 6px 0 0}
.tabs a:hover{color:var(--accent)}
.tabs a.on{background:var(--card);border-color:var(--line);color:var(--accent)}
.tabs a .pip{display:inline-block;min-width:19px;height:19px;line-height:19px;
  border-radius:10px;background:var(--frozen);color:#fff;font-size:12px;
  text-align:center;margin-left:6px;padding:0 5px}

.hero{background:var(--card);border:1px solid var(--line);border-left:5px solid;
  border-radius:6px;padding:26px 28px;margin:0 0 20px}
.hero.no{border-left-color:var(--frozen)}
.hero.yes{border-left-color:var(--money)}
/* Neither answered nor refused: we were not given enough to say. It must not
   borrow the colour of good news or of bad. */
.hero.unknown{border-left-color:var(--unknown);background:var(--unknown-soft)}
.hero.unknown h1{color:var(--unknown)}
.hero .q{margin:0 0 6px;font-size:16px;color:var(--muted);font-weight:600}
/* The verdict is the whole point of the page; it should carry the weight
   of one. clamp() keeps it from overwhelming a narrow phone. */
.hero h1{font-size:clamp(32px,7vw,44px);margin:0 0 10px;line-height:1.1;
  letter-spacing:-.02em;text-wrap:balance}
.hero.no h1{color:var(--frozen)}
.hero.yes h1{color:var(--money)}
.hero p{margin:0;font-size:18px}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:1px;background:var(--line);border:1px solid var(--line);border-radius:6px;
  overflow:hidden;margin:0 0 22px}
.tile{background:var(--card);padding:17px 19px}
.tile dt{font-size:13px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;font-weight:600;margin-bottom:7px}
.tile dd{margin:0;font-size:24px;font-weight:700;line-height:1.15;
  font-variant-numeric:tabular-nums}
.tile dd small{display:block;font-size:13px;font-weight:400;color:var(--muted);
  margin-top:4px;letter-spacing:0}
.tile.alert dd{color:var(--frozen)}
.tile.good dd{color:var(--money)}

/* A status word carries more than a colour does. Anyone who cannot see the
   colour still reads the label. */
.pill{display:inline-block;padding:3px 9px;border-radius:11px;font-size:13px;
  font-weight:600;white-space:nowrap}
.pill.money{background:var(--money-soft);color:var(--money)}
.pill.frozen{background:var(--frozen-soft);color:var(--frozen)}
.pill.unknown{background:var(--unknown-soft);color:var(--unknown)}

.acct{display:block;background:var(--card);border:1px solid var(--line);
  border-radius:6px;padding:17px 20px;margin:0 0 12px;text-decoration:none;color:inherit}
.acct:hover{border-color:var(--accent)}
.acct .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.acct .nm{font-weight:700;font-size:18px;margin:0}
.acct .bal{font-weight:700;font-size:18px;font-variant-numeric:tabular-nums;margin:0}
.acct .meta{margin:6px 0 0;color:var(--muted);font-size:15px}
.acct .warn{color:var(--frozen);font-weight:600}
.acct.orphan{border-left:5px solid var(--money)}
.acct.locked{opacity:.62}
.acct.locked .bal{color:var(--muted)}
.samp{background:var(--accent-soft);border:1px solid var(--accent);
  border-radius:6px;padding:12px 16px;margin:18px 0 0;font-size:16px}
.samp p{margin:0}
.samp a{font-weight:600;white-space:nowrap}
.brand{font-size:21px;font-weight:700;letter-spacing:-.01em;margin:0;color:var(--accent)}
.brand span{color:var(--muted);font-weight:400;font-size:15px;margin-left:9px;letter-spacing:0}

h1{font-size:29px;line-height:1.2;letter-spacing:-.018em;margin:0 0 14px;
  text-wrap:balance}
h2{font-size:21px;line-height:1.3;margin:34px 0 12px;text-wrap:balance}
h3{font-size:17px;margin:22px 0 8px}
p{margin:0 0 14px}
.lede{font-size:20px;color:var(--muted);margin-bottom:24px}

.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:20px 22px;margin:0 0 16px}
.card h2,.card h3{margin-top:0}
.card h2{font-size:17px;margin:0 0 8px}
.card p:last-child{margin-bottom:0}

.banner{border-radius:6px;padding:18px 22px;margin:0 0 22px;border-left:5px solid}
.banner h1,.banner h2{margin:0 0 8px;font-size:22px;line-height:1.25}
.banner p{margin:0}
.banner.frozen{background:var(--frozen-soft);border-color:var(--frozen)}
.banner.frozen h1,.banner.frozen h2{color:var(--frozen)}
.banner.money{background:var(--money-soft);border-color:var(--money)}
.banner.money h1,.banner.money h2{color:var(--money)}
.banner.calm{background:var(--accent-soft);border-color:var(--accent)}
.banner.calm h1,.banner.calm h2{color:var(--accent)}
.banner.unknown{background:var(--unknown-soft);border-color:var(--unknown)}
.banner.unknown h1,.banner.unknown h2{color:var(--unknown)}

.hindi{font-size:16px;color:var(--muted);margin-top:8px}

.steps{list-style:none;padding:0;margin:0 0 22px}
.steps li{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--line);align-items:baseline}
.steps li:last-child{border-bottom:none}
.tick{color:var(--money);font-weight:700;min-width:18px}
.steps .what{font-weight:600}
.steps .detail{color:var(--muted);font-size:16px}

.finding{
  display:block;background:var(--card);border:1px solid var(--line);
  border-left:5px solid var(--frozen); border-radius:6px;
  padding:18px 22px;margin:0 0 14px;text-decoration:none;color:inherit;
}
.finding:hover{border-color:var(--accent);border-left-color:var(--frozen)}
.finding.opportunity{border-left-color:var(--money)}
.finding .who{font-weight:700;font-size:19px;margin:0 0 6px}
.finding .why{margin:0;color:var(--muted)}
.finding .go{color:var(--accent);font-weight:600;margin-top:10px;display:block}

.btn{
  display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
  padding:14px 26px;border-radius:6px;font-size:18px;font-weight:600;
  border:none;cursor:pointer;font-family:inherit;
}
.btn.plain{background:transparent;color:var(--accent);border:2px solid var(--line)}
.btnrow{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}

table{width:100%;border-collapse:collapse;font-size:16px;margin:0 0 18px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
.tw{overflow-x:auto}

.doc{
  background:var(--card);border:1px solid var(--line);border-radius:6px;
  padding:22px;white-space:pre-wrap;font-family:Georgia,"Times New Roman",serif;
  font-size:16px;line-height:1.65;overflow-x:auto;
}
.evidence{list-style:none;padding:0;margin:0}
.evidence li{
  padding:9px 12px;background:var(--sunk);border-radius:4px;margin-bottom:7px;
  font-size:15px;font-family:ui-monospace,Menlo,Consolas,monospace;
  overflow-wrap:anywhere;
}
.gate{
  background:var(--money-soft);border-radius:6px;padding:14px 18px;
  font-size:16px;margin:16px 0;
}
.gate strong{color:var(--money)}

ol.plan{padding-left:0;list-style:none;counter-reset:s;margin:0}
ol.plan li{
  counter-increment:s;position:relative;padding:14px 0 14px 46px;
  border-bottom:1px solid var(--line);
}
ol.plan li:last-child{border-bottom:none}
ol.plan li::before{
  content:counter(s);position:absolute;left:0;top:14px;
  width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;
}
ol.plan .act{font-weight:600;display:block;margin-bottom:3px}
ol.plan .det{color:var(--muted);font-size:16px}
ol.plan .blocked{
  display:inline-block;margin-top:6px;font-size:14px;color:var(--muted);
  background:var(--sunk);padding:3px 9px;border-radius:4px;
}
.back{display:inline-block;margin-bottom:18px;font-size:16px}
.field{margin:0 0 18px}
.field label{display:block;font-weight:600;margin-bottom:6px}
.field .opt{font-weight:400;color:var(--muted);font-size:15px}
.field .req{font-weight:600;color:var(--frozen);font-size:14px;
  text-transform:uppercase;letter-spacing:.05em}
.field input[type=file],.field input[type=password],.field input[type=text]{
  display:block;width:100%;font-family:inherit;font-size:16px;padding:11px 12px;
  border:2px solid var(--line);border-radius:6px;background:var(--paper);color:var(--ink);
}
.field .hint{color:var(--muted);font-size:15px;margin:6px 0 0}
.detail{color:var(--muted);font-size:15px}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
  font-size:14px;color:var(--muted)}
/* This product's whole purpose ends at a printer. The Joint Declaration is
   taken to an EPFO office on paper, signed, and filed. Printing it with
   navigation tabs, a prototype banner and a hero card produces something that
   looks like a web printout rather than a document - so the last step of the
   core feature fails on the one surface that matters.

   Everything that is screen furniture is removed; the letter and its annexure
   are set as a document, in serif, at a readable print size, and kept whole
   across page breaks. */
@media print{
  :root{--paper:#fff;--card:#fff;--line:#999}
  body{background:#fff;color:#000;font-size:11.5pt}
  .wrap{max-width:none;padding:0}
  .flag,.tabs,.who,.back,.samp,.go,header.top,header.portal,
  .hero,.tiles,.banner,.gate,footer,nav{display:none !important}
  h1{font-size:15pt;margin:0 0 10pt}
  h2{font-size:12pt;margin:16pt 0 6pt;page-break-after:avoid}
  .lede,.hindi{display:none}
  .card{border:none;padding:0;margin:0 0 10pt}
  a{color:#000;text-decoration:none}
  .doc{
    border:1px solid #999;border-radius:0;padding:16pt;
    font-family:Georgia,"Times New Roman",serif;font-size:11.5pt;line-height:1.6;
    page-break-inside:avoid;
  }
  .evidence li{background:none;border:none;border-bottom:1px solid #ccc;
    border-radius:0;padding:4pt 0;font-size:10pt}
  /* A filing needs to be identifiable after it leaves the screen. */
  .doc::after{
    content:"Prepared with Vested - an independent prototype. Not an official "
            "EPFO document. Every figure is traceable to the member's own records.";
    display:block;margin-top:14pt;padding-top:8pt;border-top:1px solid #ccc;
    font-family:-apple-system,"Segoe UI",Arial,sans-serif;font-size:8.5pt;color:#444;
  }
}
@media (max-width:560px){
  body{font-size:17px} h1{font-size:25px} .wrap{padding:0 16px 56px}
  .btn{display:block;text-align:center}
}
"""

CSS = minify(CSS)

# The stylesheet is ~10 KB and identical on every page. Inlined, a member paying
# for data downloaded it fifteen times over a session; served once and cached,
# they pay for it once and every page after the first is around 6 KB. That is
# the whole reason this product has a weight budget, so the budget should not be
# spent re-sending the same bytes.
#
# The hash in the URL means a redeploy can never serve a stale stylesheet while
# still letting us cache it for a year.
CSS_HASH = hashlib.sha256(CSS.encode()).hexdigest()[:12]
CSS_URL = f"/s/{CSS_HASH}.css"



def esc(s) -> str:
    return html.escape(str(s))


NAV = [("/home", "Home"), ("/record", "Your record"), ("/accounts", "Accounts"),
       ("/pension", "Pension"), ("/withdraw", "Withdraw"), ("/claim", "Claim"),
       ("/manage", "Manage"), ("/track", "Track"), ("/profile", "Profile")]


SAMPLE_NOTE = """
<div class="samp">
  <p><strong>You are signed in to a test account.</strong> The documents behind it
  are synthetic &mdash; no real person&rsquo;s data is shown anywhere.
  <a href="/login">Switch account</a> &middot;
  <a href="/upload">Check your own record &rarr;</a></p>
</div>"""


def _is_demo(token: str) -> bool:
    from app.demo import ACCOUNTS
    return token == "sample" or token in ACCOUNTS


def portal_header(a, token: str, active: str) -> str:
    nc = getattr(a, "name_check", None)
    who = nc.canonical if nc else "Member"
    tabs = ""
    for href, label in NAV:
        pip = ""
        if href == "/record" and a.result["blocking_count"]:
            pip = f'<span class="pip">{a.result["blocking_count"]}</span>'
        on = " on" if href == active else ""
        tabs += f'<a class="tab{on}" href="{href}?s={esc(token)}">{esc(label)}{pip}</a>'
    note = SAMPLE_NOTE if _is_demo(token) else ""
    ident = getattr(a, "identity", {}) or {}
    who = ident.get("name") or who
    uan = ident.get("uan")
    return f"""{note}<header class="portal">
  <div class="bar">
    <p class="brand">Vested <span>your provident fund, checked</span></p>
    <p class="who"><strong>{esc(who)}</strong>{"UAN " + esc(uan) if uan else "UAN not found in your documents"}</p>
  </div>
  <nav class="tabs" aria-label="Sections">{tabs}</nav>
</header>"""


PLAIN_HEADER = """<header class="top">
  <p class="brand">Vested <span>check your PF record before you claim</span></p>
</header>"""


def layout(title: str, body: str, header: str | None = None) -> str:
    head = header if header is not None else PLAIN_HEADER
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} &mdash; Vested</title>
<link rel="stylesheet" href="{CSS_URL}">
</head><body>
<div class="flag">
  <strong>Independent hackathon prototype.</strong>
  Not affiliated with or endorsed by EPFO or any government body.
  Nothing is stored or submitted. <a href="/privacy">What happens to your documents</a>
</div>
<div class="wrap">
{head}
{body}
<footer>
  Built for Build What Moves India. Uses only records you already own.
  Nothing is submitted to any government system.
</footer>
</div></body></html>"""


# ---------------------------------------------------------------------------

def page_login(error: str | None = None) -> str:
    """
    Sign in with a mock account.

    The credentials are printed on the page. Anyone evaluating this has no PF
    documents of their own, and a product they cannot get into is a product that
    does not exist. Behind these passwords there is nothing but synthetic data.
    """
    from app.demo import ACCOUNTS

    rows = ""
    for uan, acct in ACCOUNTS.items():
        rows += f"""<tr>
          <td><strong>{esc(acct['name'])}</strong><br>
            <span class="detail">{esc(acct['blurb'])}</span></td>
          <td><code>{esc(uan)}</code><br><code>{esc(acct['password'])}</code></td>
          <td><a class="btn" href="/home?s={esc(uan)}">Open &rarr;</a></td></tr>"""

    warn = (f'<div class="banner frozen"><h2>{esc(error)}</h2></div>'
            if error else "")

    first = next(iter(ACCOUNTS))
    return layout("Sign in", f"""
<h1>Your provident fund, checked before you claim it.</h1>
<p class="lede">One in five PF claims is rejected, usually over one wrong date
typed by an employer years ago. This finds it first &mdash; using your own income
tax records as proof.</p>
{warn}

<div class="card">
  <h2>Sign in</h2>
  <form method="post" action="/login">
    <div class="field">
      <label for="uan">UAN</label>
      <input id="uan" name="uan" type="text" value="{esc(first)}" autocomplete="off">
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input id="password" name="password" type="password"
             value="{esc(ACCOUNTS[first]['password'])}">
    </div>
    <button class="btn" type="submit">Sign in</button>
  </form>
</div>

<div class="card">
  <h2>Test accounts</h2>
  <table>{rows}</table>
  <p class="detail">Both are synthetic. No real person&rsquo;s data appears
  anywhere in this prototype.</p>
</div>

<div class="card">
  <h2>Or check your own record</h2>
  <p>If you have your Form 26AS or PF passbook to hand, you can run the same
  checks against your own documents. Nothing is stored, and nothing is sent
  anywhere.</p>
  <p><a href="/upload">Use my own documents &rarr;</a></p>
</div>
""")


def page_start() -> str:
    return layout("Check your record", """
<h1>One in five PF claims still gets rejected.<br>Find out why before you file.</h1>
<p class="lede">Most rejections come down to one wrong date typed by an employer years ago.
Your own tax records can prove what actually happened.</p>

<div class="card">
  <h2>What you need</h2>
  <table>
    <tr><th>Document</th><th>Where to get it</th></tr>
    <tr><td><strong>Form 26AS</strong></td><td>Income Tax portal &rarr; View Form 26AS &rarr; TRACES</td></tr>
    <tr><td><strong>PF passbook</strong></td><td>passbook.epfindia.gov.in</td></tr>
    <tr><td><strong>Service history</strong></td><td>UAN member portal &rarr; View &rarr; Service History</td></tr>
  </table>
  <p style="color:var(--muted);font-size:16px">
    <strong>Start with whatever you actually have.</strong> Any one of these gets
    you an answer &mdash; a narrower one, and we will say exactly how narrow.
    The EPFO portals are often down; that should not stop you finding out
    something. Everything is read and discarded; nothing is written to disk.
    <a href="/privacy">Exactly what happens to them &rarr;</a>
  </p>
  <p style="color:var(--muted);font-size:16px">
    The <strong>service history</strong> is the one that unlocks the date checks,
    because it is what your evidence gets tested against. Without it we report
    where you worked, but no findings about your dates &mdash; we will not guess.
  </p>
</div>

<form method="post" action="/analyse" enctype="multipart/form-data">
  <div class="card">
    <h2>Upload your documents</h2>
    <p style="color:var(--muted);font-size:16px">
      PDF, or the text file TRACES gives you. ZIP is fine too. We work out which
      document is which, so it does not matter which box you use.
    </p>
    <div class="field">
      <label for="f26as">Form 26AS <span class="opt">finds forgotten accounts</span></label>
      <input type="file" id="f26as" name="f26as" accept=".pdf,.txt,.zip">
    </div>
    <div class="field">
      <label for="passbook">PF passbook <span class="opt">balances and contributions</span> &mdash; one file per account</label>
      <input type="file" id="passbook" name="passbook" accept=".pdf,.txt" multiple>
    </div>
    <div class="field">
      <label for="history">Service history <span class="req">unlocks the date checks</span></label>
      <input type="file" id="history" name="history" accept=".pdf,.txt">
    </div>
    <div class="field">
      <label for="bank">Bank statement <span class="opt">exact pay dates</span></label>
      <input type="file" id="bank" name="bank" accept=".pdf,.txt">
    </div>
    <div class="field">
      <label for="password">PDF password <span class="opt">if asked for</span></label>
      <input type="password" id="password" name="password" placeholder="DDMMYYYY"
             autocomplete="off" inputmode="numeric">
      <p class="hint">Form 26AS is usually locked with your date of birth,
      written as day-month-year with no gaps.</p>
    </div>
    <div class="btnrow">
      <button class="btn" type="submit" name="mode" value="upload">Check my record</button>
    </div>
  </div>
</form>

<form method="post" action="/analyse">
  <div class="btnrow">
    <button class="btn plain" type="submit" name="mode" value="sample">
      Or open a sample record
    </button>
  </div>
</form>

<h2>What you get</h2>
<div class="tw"><table>
  <tr><th>Home</th><td>Whether you can claim your money today, and what is stopping you</td></tr>
  <tr><th>Your record</th><td>Your employment history, checked against your own tax and bank documents</td></tr>
  <tr><th>Accounts</th><td>Every PF account in your name &mdash; including ones never linked to your UAN</td></tr>
  <tr><th>Pension</th><td>Your EPS balance and whether you have crossed the ten-year line</td></tr>
  <tr><th>Claim</th><td>The rejection checks, run before you file instead of three weeks after</td></tr>
  <tr><th>Track</th><td>How long each step is legally supposed to take</td></tr>
  <tr><th>Profile</th><td>Your name as each document spells it, and which version to use</td></tr>
</table></div>
""")


def page_upload_problem(report: list, missing: list, message: str | None) -> str:
    rows = ""
    for r in report:
        state = "Recognised" if r["ok"] else "Not used"
        rows += (f'<tr><td>{esc(r["file"])}</td>'
                 f'<td>{esc(r["kind"] or "&mdash;")}</td>'
                 f'<td>{esc(state)}<br><span class="detail">{esc(r["message"])}</span></td></tr>')
    table = f"""<div class="tw"><table>
<tr><th>File</th><th>Read as</th><th>Result</th></tr>{rows}</table></div>""" if rows else ""

    miss = ""
    if missing:
        items = "".join(f"<li>{esc(m)}</li>" for m in missing)
        miss = f"""
<div class="card">
  <h2>Still needed</h2>
  <ul>{items}</ul>
  <p style="color:var(--muted);font-size:16px">
    Upload each file exactly as the portal gives it to you. Editing, renaming or
    re-saving a document can make it unreadable.
  </p>
</div>"""

    return layout("Something is missing", f"""
<div class="banner frozen">
  <h1>We could not run the check yet</h1>
  <p>{esc(message) if message else 'Some of the documents we need are missing.'}</p>
</div>
{table}
{miss}
<div class="btnrow"><a class="btn" href="/">Try again</a></div>
""")


def page_expired() -> str:
    return layout("Session ended", """
<div class="banner calm">
  <h1>That session has ended</h1>
  <p>Your documents are held only while you are using the page and are never
  saved. Once a session ends, everything from it is gone.</p>
</div>
<p>Upload your documents again to run a fresh check.</p>
<div class="btnrow"><a class="btn" href="/">Start again</a></div>
""")


def _finding_copy(c: dict) -> tuple[str, str, str]:
    """Plain-language rewrite of an engine contradiction. No jargon."""
    emp = c["employer"].replace("_", " ").title()
    k = c["kind"]
    if k == "EXIT_TOO_EARLY":
        return (f"{emp} recorded the wrong leaving date",
                "EPFO thinks you left earlier than you did. Your tax records show "
                "this employer was still paying you months later.",
                "आपके नियोक्ता ने नौकरी छोड़ने की तारीख गलत दर्ज की है।")
    if k == "MISSING_EXIT":
        return (f"{emp} never recorded that you left",
                "EPFO still treats this job as ongoing. Until a leaving date is "
                "recorded, transfers and withdrawals stay blocked.",
                "EPFO के रिकॉर्ड में यह नौकरी अब भी चालू दिखती है।")
    if k == "CONTRIBUTION_GAP":
        return (f"{emp} deducted tax but deposited no PF",
                "For at least one month this employer took tax off your salary and "
                "paid nothing into your provident fund. You were working either "
                "side of it, so this is not a break in service — it is money that "
                "was withheld and never arrived.",
                "इस महीने का पीएफ आपके खाते में जमा ही नहीं हुआ।")
    if k == "SERVICE_OVERLAP":
        return (f"Two jobs look like they overlap",
                "EPFO reads this as working two jobs at once and stops the transfer.",
                "दो नौकरियाँ एक ही समय पर दिख रही हैं।")
    if k == "CORRECTION_CONFLICT":
        return ("A correction here would clash with another job",
                "Filing this as-is would be rejected in turn. It needs sorting out first.",
                "यह सुधार दूसरी नौकरी से टकराएगा।")
    if k == "TRAILING_PAYOUT":
        return (f"{emp} paid you after you left",
                "This looks like a final settlement, not extra months of work. "
                "We are not treating it as a wrong date.",
                "यह अंतिम भुगतान लगता है, गलत तारीख नहीं।")
    if k == "JOIN_SUSPECT":
        return (f"{emp} joining date looks early",
                "The recorded start date is earlier than any record of you being paid.",
                "शुरू होने की तारीख जल्दी लगती है।")
    return (f"{emp}: {k.replace('_', ' ').lower()}", c["detail"][:160], "")


def _nothing_todo(a) -> str:
    """An empty to-do list means two very different things."""
    if not getattr(a, "dates_checked", True):
        extra = (" Your contributions were checked and every month reconciles."
                 if getattr(a, "contributions_checked", False) else "")
        return ('<div class="card"><p>Your dates have not been checked &mdash; '
                'that needs your service history.' + extra + ' Nothing here means '
                'nothing was tested for, not that nothing is wrong.</p></div>')
    return '<div class="card"><p>Nothing is blocking your claim.</p></div>'


def page_result(a, token: str = 'sample') -> str:
    frozen = a.result["claim_status"] == "WILL_BE_REJECTED"
    n = a.result["blocking_count"]

    # Same three states as the home page. "No problems found" is only true if
    # we had something to test against; saying it after checking nothing is
    # the one sentence that could cost someone a rejected claim.
    if not getattr(a, "checked", True):
        banner = """
<div class="banner unknown">
  <h1>We could not check this record</h1>
  <p>Your service history is what every check is measured against, and it was
  not supplied. What was read from your documents is listed below.</p>
</div>"""
    else:
        banner = f"""
<div class="banner {'frozen' if frozen else 'calm'}">
  <h1>{'Your claim would be rejected today' if frozen else 'Nothing is blocking your claim'}</h1>
  <p>{f'We found {n} problem{"s" if n != 1 else ""} in your record that EPFO would stop on.'
      if frozen else 'Your employment record reconciles against your own tax and PF documents.'}</p>
</div>"""

    steps = "".join(
        f'<li><span class="tick">{"OK" if s.ok else "!"}</span>'
        f'<span><span class="what">{esc(s.label)}</span><br>'
        f'<span class="detail">{esc(s.detail)}</span></span></li>'
        for s in a.ingest
    )

    findings = ""
    for c in a.blocking + a.other:
        who, why, hi = _finding_copy(c)
        key = c["employer"].split(" | ")[0]
        findings += f"""
<a class="finding" href="/finding/{esc(key)}?s={esc(token)}">
  <p class="who">{esc(who)}</p>
  <p class="why">{esc(why)}</p>
  {f'<p class="hindi">{esc(hi)}</p>' if hi else ''}
  <span class="go">See the proof and what to do &rarr;</span>
</a>"""

    orphans = ""
    for o in a.orphans:
        if o.assessment.verdict != "LIKELY":
            continue
        est = o.assessment.estimate
        orphans += f"""
<div class="banner money">
  <h2>You have money in an account you forgot</h2>
  <p><strong>{esc(o.candidate.employer_name)}</strong> paid into a PF account for
  {o.candidate.months} months in {o.candidate.first_seen.year}. It was never
  linked to your current UAN.</p>
  <p style="margin-top:10px;font-size:22px;font-weight:700">{esc(est.render() if est else '')}</p>
</div>
<a class="finding opportunity" href="/orphan/{esc(o.candidate.tan)}?s={esc(token)}">
  <p class="who">How to get it back</p>
  <p class="why">Four steps. The first two you can do yourself.</p>
  <span class="go">See the steps &rarr;</span>
</a>"""

    return layout("Your record", f"""
{banner}
<h2>What we read</h2>
<ul class="steps">{steps}</ul>
{_name_card(a)}
<h2>What we found</h2>
{findings}
{orphans}
""", portal_header(a, token, "/record"))


def _name_card(a) -> str:
    nc = getattr(a, "name_check", None)
    if not nc:
        return ""
    rows = "".join(
        f"<tr><td>{esc(src)}</td><td><strong>{esc(spelling)}</strong></td></tr>"
        for src, spelling in nc.names.items()
    )
    if nc.same_person:
        verdict = f"""
<p><strong>All {len(nc.names)} spellings are the same person.</strong>
Your records can safely be matched to each other.</p>
<p style="color:var(--muted);font-size:16px">
{f"Closest call: {esc(nc.weakest[0])} against {esc(nc.weakest[1])} &mdash; " if nc.weakest else ""}
{esc('; '.join(nc.reasons))}.</p>
<p>When a form asks for your name, use
<strong>{esc(nc.canonical)}</strong>. It is the spelling every other document
agrees with. Mismatched names are a leading cause of claim rejection, and the
health-ID linkage rejects them automatically as suspected fraud.</p>"""
    else:
        verdict = f"""
<p><strong>These spellings do not resolve to one person.</strong>
{esc('; '.join(nc.reasons))}.</p>
<p>Fix this before filing anything. Records that cannot be matched to each
other cannot be merged, and a claim filed across them will be rejected.</p>"""
    return f"""
<div class="card">
  <h2>Your name across documents</h2>
  <table>{rows}</table>
  {verdict}
</div>"""


def correction_help(route: str, token: str) -> str:
    """
    How this correction actually gets filed in 2026.

    The Joint Declaration moved online and physical forms stopped being accepted
    for the common corrections - except in one case, which happens to be the
    exact member this product was built for: the one whose employer has shut
    down. Both paths are shown, because we cannot see from a document whether an
    establishment still exists, and guessing would send someone to a counter
    with the wrong paperwork.
    """
    if "Self-service" in route:
        return f"""
<div class="card">
  <h2>You can do this one yourself</h2>
  <p>No employer, no letter, no waiting &mdash; EPFO lets you set a missing exit
  date from your own login.</p>
  <p><a href="/exit?s={esc(token)}">The date to enter, and how &rarr;</a></p>
</div>"""

    if "EPFiGMS" in route:
        return f"""
<div class="card">
  <h2>How this correction is filed</h2>
  <p>This one goes through EPFO&rsquo;s own grievance system rather than a form
  your employer signs.</p>
  <ol class="steps">
    <li>Open <strong>EPFiGMS</strong> and register the grievance against your
      UAN</li>
    <li>Attach the evidence listed below &mdash; a grievance without documents
      is usually closed without action</li>
    <li>Keep the registration number; the statutory limit is 30 days</li>
    <li>If it is closed without a substantive reply, file an RTI asking for the
      action taken. That is a separate 30-day clock, and it is answered by a
      different officer.</li>
  </ol>
</div>
<div class="card">
  <h2>What to attach</h2>
  <ul class="steps">{''.join(f'<li>{esc(x)}</li>' for x in ACCEPTED_DATE_EVIDENCE)}</ul>
  <p class="detail">{esc(EVIDENCE_NOTE)}</p>
</div>"""

    if "orphan" in route.lower() or "Transfer/withdrawal" in route:
        return f"""
<div class="card">
  <h2>How this one is recovered</h2>
  <p>This is not a correction to your current record &mdash; it is a separate
  account with its own member ID, and it has to be brought across.</p>
  <p><a href="/transfer?s={esc(token)}">File the transfer request &rarr;</a></p>
</div>"""

    if "Joint Declaration" not in route:
        return ""

    _, online_why = jd_route(False)
    _, closed_why = jd_route(True)
    who = "".join(f"<li>{esc(x)}</li>" for x in ATTESTORS)
    ev = "".join(f"<li>{esc(x)}</li>" for x in ACCEPTED_DATE_EVIDENCE)
    return f"""
<div class="card">
  <h2>How this correction is filed</h2>
  <p>{esc(online_why)}</p>
  <h3>If that employer has shut down</h3>
  <p>{esc(closed_why)} Any one of these can attest it:</p>
  <ul class="steps">{who}</ul>
  <p class="detail">Attach a letter explaining the closure alongside the form.</p>
</div>
<div class="card">
  <h2>What to take with you</h2>
  <ul class="steps">{ev}</ul>
  <p class="detail">{esc(EVIDENCE_NOTE)}</p>
</div>"""


def page_finding(a, key: str, token: str = 'sample') -> str:
    c = next((x for x in a.result["contradictions"]
              if x["employer"].split(" | ")[0] == key
              and x["kind"] != "ORPHAN_ACCOUNT"), None)
    if c is None:
        return layout("Not found", "<h1>No such finding</h1><p><a href='/'>Start again</a></p>")

    who, why, hi = _finding_copy(c)
    evidence = "".join(f"<li>{esc(e)}</li>" for e in c["evidence"])
    docblock = ""
    d = a.documents.get(key)
    if d:
        v = d["violations"]
        docblock = f"""
<h2>The letter to send</h2>
<div class="gate">
  <strong>{'Checked and clear.' if not v else f'{len(v)} problem(s) found.'}</strong>
  Every date and number in this letter was traced back to one of your documents.
  Nothing in it was invented.
</div>
<div class="doc">{esc(d['doc'].body)}</div>
<h2>Attached evidence</h2>
<ul class="evidence">{''.join(f'<li>{esc(x)}</li>' for x in d['doc'].annexure)}</ul>"""

    return layout(who, f"""
<a class="back" href="/record?s={esc(token)}">&larr; Back to your record</a>
<h1>{esc(who)}</h1>
<p class="lede">{esc(why)}</p>
{f'<p class="hindi">{esc(hi)}</p>' if hi else ''}

<div class="card">
  <h2>What the records show</h2>
  <p>{esc(c['detail'])}</p>
</div>

<h2>The proof</h2>
<ul class="evidence">{evidence}</ul>

<div class="card">
  <h2>What to do</h2>
  <p><strong>{esc(c['proposed_fix'])}</strong></p>
  <p style="color:var(--muted)">Route: {esc(c['correction_route'])}</p>
</div>
{correction_help(c['correction_route'], token)}
{docblock}
""", portal_header(a, token, "/accounts"))


def page_orphan(a, tan: str, token: str = 'sample') -> str:
    o = next((x for x in a.orphans if x.candidate.tan == tan), None)
    if o is None:
        return layout("Not found", "<h1>No such account</h1><p><a href='/'>Start again</a></p>")

    plan = "".join(
        f'<li><span class="act">{esc(s.action)}</span>'
        f'<span class="det">{esc(s.detail)}</span>'
        f'{f"<span class=blocked>Needs first: {esc(s.blocked_by)}</span>" if s.blocked_by else ""}'
        f'</li>'
        for s in o.plan
    )
    reasons = "".join(f"<li>{esc(r)}</li>" for r in o.assessment.reasons)
    doc = ""
    if o.document:
        doc = f"""
<h2>The request to send</h2>
<div class="gate">
  <strong>{'Checked and clear.' if not o.gate_violations else 'Problems found.'}</strong>
  Every detail traced back to your Form 26AS.
</div>
<div class="doc">{esc(o.document.body)}</div>"""

    est = o.assessment.estimate
    return layout("Forgotten account", f"""
<a class="back" href="/record?s={esc(token)}">&larr; Back to your record</a>
<h1>{esc(o.candidate.employer_name)}</h1>
<p class="lede">{o.candidate.months} months of salary in
{o.candidate.first_seen.strftime('%B %Y')} to {o.candidate.last_seen.strftime('%B %Y')},
with no PF account linked to your UAN.</p>

<div class="banner money">
  <h2>{esc(est.render() if est else 'Amount unknown')}</h2>
  <p>This is an estimate, not a balance. PF is calculated on basic pay, and your
  tax record only shows total salary &mdash; so the real figure sits somewhere in
  this range.</p>
</div>

<div class="card">
  <h2>Why we think this account exists</h2>
  <ul>{reasons}</ul>
</div>

<h2>How to get it back</h2>
<ol class="plan">{plan}</ol>
{doc}
""", portal_header(a, token, "/accounts"))


# ---------------------------------------------------------------------------
# Portal pages
# ---------------------------------------------------------------------------

def _rs(n: float) -> str:
    return f"&#8377;{n:,.0f}"


def page_home(a, token: str = "sample") -> str:
    blocking = a.result["blocking_count"]
    claimable = a.claimable
    orphan_n = sum(1 for o in a.orphans if o.assessment.verdict == "LIKELY")

    # Two independent questions, so three states rather than two.
    #
    #   dates          - needs EPFO's asserted service history
    #   contributions  - needs only the passbook and Form 26AS
    #
    # A found defect is a "No" whichever question produced it. But "no defect"
    # is only good news for the questions we actually asked, so an untested axis
    # is always named. "No findings" must never be allowed to read as "you are
    # fine" about something nobody looked at.
    dates_ok = getattr(a, "dates_checked", True)
    contrib_ok = getattr(a, "contributions_checked", False)
    caveat = ("" if dates_ok else
              " Your joining and exit dates were <strong>not</strong> checked &mdash;"
              " that needs your service history, which was not supplied.")

    if blocking:
        hero = f"""
<div class="hero no">
  <p class="q">Can you claim your provident fund today?</p>
  <h1>No</h1>
  <p>{blocking} problem{'s' if blocking != 1 else ''} in EPFO&rsquo;s record would
  stop it. Every one of them is fixable, and none of them are your fault.{caveat}</p>
</div>"""
    elif dates_ok:
        hero = """
<div class="hero yes">
  <p class="q">Can you claim your provident fund today?</p>
  <h1>Yes</h1>
  <p>Your record reconciles against your own tax and bank documents. Nothing is
  blocking a claim.</p>
</div>"""
    else:
        found = ("We did check something: every month an employer deducted tax "
                 "from your salary has a matching provident fund contribution. "
                 "That part is clean. "
                 if contrib_ok else
                 "What we can show you is below: where you worked, and when. "
                 "That is worth having on its own. ")
        hero = f"""
<div class="hero unknown">
  <p class="q">Can you claim your provident fund today?</p>
  <h1>Not yet known</h1>
  <p>{found}Your dates were not checked, because your service history is what
  that check is measured against and it was not supplied.</p>
  <p><a class="btn" href="/history?s={esc(token)}">Type in your dates &rarr;</a></p>
</div>"""

    tiles = f"""
<dl class="tiles">
  <div class="tile"><dt>Your PF balance</dt>
    <dd>{_rs(a.total_balance)}<small>across {len([x for x in a.accounts if not x.orphan])} accounts</small></dd></div>
  <div class="tile"><dt>Pension fund</dt>
    <dd>{_rs(a.total_pension)}<small>separate from PF</small></dd></div>
  <div class="tile {'alert' if blocking else 'good'}"><dt>Blocking problems</dt>
    <dd>{blocking}<small>{'stop a claim today' if blocking else 'nothing in the way'}</small></dd></div>
  <div class="tile {'good' if orphan_n else ''}"><dt>Money you forgot</dt>
    <dd>{_rs(a.forgotten_low) + '+' if orphan_n else '&mdash;'}
      <small>{f'{orphan_n} untraced account' + ('s' if orphan_n != 1 else '') if orphan_n
              else 'no untraced accounts'}</small></dd></div>
</dl>"""

    todo = ""
    for c in (a.blocking + a.other)[:3]:
        who, why, hi = _finding_copy(c)
        key = c["employer"].split(" | ")[0]
        todo += f"""
<a class="finding" href="/fix/{esc(key)}?s={esc(token)}">
  <p class="who">{esc(who)}</p>
  <p class="why">{esc(why)}</p>
  <span class="go">See the proof and what to do &rarr;</span>
</a>"""

    money = ""
    for o in a.orphans:
        if o.assessment.verdict != "LIKELY":
            continue
        money += f"""
<a class="finding opportunity" href="/recover/{esc(o.candidate.tan)}?s={esc(token)}">
  <p class="who">{esc(o.candidate.employer_name)} &mdash; an account you never claimed</p>
  <p class="why">{o.candidate.months} months of contributions in
    {o.candidate.first_seen.year}, never linked to your UAN.
    Roughly {esc(o.assessment.estimate.render() if o.assessment.estimate else '')}.</p>
  <span class="go">How to get it back &rarr;</span>
</a>"""

    work = ""
    if getattr(a, "worklist", None):
        rows = "".join(
            f"<tr><td><strong>{esc(w['employer'].title())}</strong></td>"
            f"<td>{w['first'].strftime('%b %Y') if w['first'] else ''} &ndash; "
            f"{w['last'].strftime('%b %Y') if w['last'] else ''}</td>"
            f"<td>{w['months']} months</td></tr>"
            for w in a.worklist)
        work = f"""
<div class="card">
  <h2>Where you worked, according to the Income Tax Department</h2>
  <p style="color:var(--muted);font-size:16px">Read from your Form 26AS. This is
  an independent record of who paid you and when &mdash; useful precisely because
  it does not come from EPFO. Check each one against your PF record: an employer
  here with no PF account is worth chasing.</p>
  <table>
    <tr><th>Employer</th><th>Paid you</th><th>For</th></tr>
    {rows}
  </table>
</div>"""

    related = ""
    if getattr(a, "related_ids", None):
        ids = "".join(f"<li><code>{esc(x)}</code></li>" for x in a.related_ids)
        related = f"""
<div class="card">
  <h2>Another PF account number appears in your passbook</h2>
  <ul>{ids}</ul>
  <p style="color:var(--muted);font-size:16px">We found this number printed in
  your passbook, but no passbook for it. We do not know what it is &mdash; it
  could be an account that was transferred in, a number that was re-issued, or a
  second account still holding money. <strong>We are not going to guess.</strong>
  It is worth checking on the member portal, because an account nobody looks at
  is how money gets left behind.</p>
</div>"""

    reduced = getattr(a, "reduced", []) or []
    limits = ""
    if reduced:
        items = "".join(f"<li>{esc(x)}</li>" for x in reduced)
        limits = f"""
<div class="card">
  <h2>What this check could not see</h2>
  <ul>{items}</ul>
  <p style="color:var(--muted);font-size:16px">Nothing here is wrong &mdash; it is
  simply narrower than it could be. <a href="/upload">Add the missing documents</a>
  if you want the fuller picture.</p>
</div>"""

    return layout("Home", f"""
{hero}
{tiles}
{work}
{related}
{limits}
<h2>What needs fixing</h2>
{todo or _nothing_todo(a)}
{f'<h2>Money you have not claimed</h2>{money}' if money else ''}
""", portal_header(a, token, "/home"))


def page_accounts(a, token: str = "sample") -> str:
    rows = ""
    for ac in a.accounts:
        if ac.orphan:
            rows += f"""
<a class="acct orphan" href="/recover/{esc(ac.employer_key)}?s={esc(token)}">
  <div class="top"><p class="nm">{esc(ac.employer)}</p><p class="bal">not traced</p></div>
  <p class="meta">{ac.months} months of salary{f" in {ac.doj.year}" if ac.doj else ""} &mdash;
     no PF account linked to your UAN. <span class="warn">Money you have not claimed.</span></p>
</a>"""
        else:
            if ac.blocking:
                state = (f'<span class="warn">{ac.blocking} problem'
                         f'{"s" if ac.blocking != 1 else ""} blocking a claim</span>')
            elif not getattr(a, "checked", True):
                state = "not checked"
            else:
                state = "No problems found"
            exit_txt = ac.doe.strftime("%b %Y") if ac.doe else "no leaving date recorded"
            # A real passbook carries no date of joining - the service history
            # holds it. Without that document this is None, and formatting it
            # crashed the page: the member saw nothing at all.
            join_txt = ac.doj.strftime("%b %Y") if ac.doj else "start date not recorded"
            span = (f"{esc(join_txt)} to {esc(exit_txt)}" if ac.doj
                    else f"{esc(join_txt)}")
            rows += f"""
<a class="acct" href="/account/{esc(ac.member_id)}?s={esc(token)}">
  <div class="top"><p class="nm">{esc(ac.employer)}</p><p class="bal">{_rs(ac.balance)}</p></div>
  <p class="meta">{esc(ac.member_id)} &middot; {span}
     &middot; {ac.months} months &middot; {state}</p>
</a>"""

    return layout("Accounts", f"""
<h1>Your accounts</h1>
<p class="lede">Every provident fund account in your name &mdash; including ones
that were never linked to your UAN.</p>
{rows}
<div class="card">
  <h2>Why an account can go missing</h2>
  <p>Before UAN linked everything together, each employer opened a separate PF
  account for you. If it was never transferred when you changed jobs, the money
  stayed there and stopped appearing anywhere you would think to look.</p>
</div>
""", portal_header(a, token, "/accounts"))


def page_account(a, member_id: str, token: str = "sample") -> str:
    ac = next((x for x in a.accounts if x.member_id == member_id), None)
    if ac is None:
        return layout("Not found", "<h1>No such account</h1>", portal_header(a, token, "/accounts"))
    faults = [c for c in a.result["contradictions"]
              if ac.employer_key in c["employer"].split(" | ")]
    items = ""
    for c in faults:
        who, why, hi = _finding_copy(c)
        items += f"""
<a class="finding" href="/fix/{esc(ac.employer_key)}?s={esc(token)}">
  <p class="who">{esc(who)}</p><p class="why">{esc(why)}</p>
  <span class="go">What to do &rarr;</span></a>"""
    return layout(ac.employer, f"""
<a class="back" href="/accounts?s={esc(token)}">&larr; All accounts</a>
<h1>{esc(ac.employer)}</h1>
<dl class="tiles">
  <div class="tile"><dt>PF balance</dt><dd>{_rs(ac.balance)}</dd></div>
  <div class="tile"><dt>Pension fund</dt><dd>{_rs(ac.pension)}<small>not withdrawable as PF</small></dd></div>
  <div class="tile"><dt>Contributions</dt><dd>{ac.months}<small>months on record</small></dd></div>
</dl>
<div class="card">
  <h2>What EPFO records</h2>
  <table>
    <tr><th>Member ID</th><td>{esc(ac.member_id)}</td></tr>
    <tr><th>Joined</th><td>{ac.doj.strftime('%d %B %Y') if ac.doj
        else 'not recorded &mdash; needs your service history'}</td></tr>
    <tr><th>Left</th><td>{ac.doe.strftime('%d %B %Y') if ac.doe
        else '<strong>no leaving date recorded</strong>'}</td></tr>
  </table>
</div>
{f'<h2>Problems on this account</h2>{items}' if items else
 '<div class="card"><p>No problems found on this account.</p></div>'}
""", portal_header(a, token, "/accounts"))


def page_claim(a, token: str = "sample") -> str:
    """
    The claim journey, inverted.

    EPFO asks you to pick a form, fill it, submit, and find out weeks later
    whether it was ever going to work. This screen runs that check first.
    """
    blocking = a.blocking
    ok = not blocking

    if ok:
        gate = """
<div class="banner money">
  <h2>Your claim should go through</h2>
  <p>We checked your record against your own tax and bank documents and found
  nothing EPFO would stop on.</p>
</div>"""
    else:
        rows = ""
        for c in blocking:
            who, why, hi = _finding_copy(c)
            key = c["employer"].split(" | ")[0]
            rows += f"""<li><strong>{esc(who)}</strong><br>
              <span class="detail">{esc(c['proposed_fix'])}</span><br>
              <a href="/fix/{esc(key)}?s={esc(token)}">Fix this first &rarr;</a></li>"""
        gate = f"""
<div class="banner frozen">
  <h2>Do not file yet</h2>
  <p>{len(blocking)} thing{'s' if len(blocking) != 1 else ''} in EPFO&rsquo;s record
  would cause this claim to be rejected. Filing now most likely means waiting
  three weeks to be told no.</p>
</div>
<div class="card">
  <h2>Clear these first</h2>
  <ul class="steps">{rows}</ul>
</div>"""

    forms = """
<div class="card">
  <h2>Which form you would need</h2>
  <table>
    <tr><th>Form 19</th><td>Final settlement &mdash; withdrawing your PF after leaving</td></tr>
    <tr><th>Form 10C</th><td>Pension withdrawal or a scheme certificate</td></tr>
    <tr><th>Form 10D</th><td>Monthly pension, once you have ten years of service</td></tr>
    <tr><th>Form 31</th><td>Partial advance &mdash; illness, education or marriage, housing</td></tr>
    <tr><th>Form 13</th><td>Transfer &mdash; moving an old account into your current one</td></tr>
  </table>
  <p style="color:var(--muted);font-size:16px">EPFO asks you to choose before it
  tells you whether your record can support the claim. That is the wrong way
  round, so this page checks first.</p>
</div>"""

    # EPFO 3.0 settles most claims with no human involved. That makes the state
    # of the record decisive rather than merely inconvenient: a clerk could have
    # telephoned about a wrong date, an automated check just refuses.
    v = a.settlement
    cls = {"auto": "money", "manual": "unknown",
           "blocked": "frozen", "unknown": "unknown"}[v.mode]
    extra = ""
    if v.mode == "auto":
        extra = f"""
  <table>
    <tr><th>By UPI</th><td>up to {_rs(v.upi_limit)} &mdash; 75% of your balance</td></tr>
    <tr><th>By ATM</th><td>up to {_rs(v.atm_limit)} &mdash; 50% of your balance</td></tr>
  </table>"""
    auto = f"""
<div class="card">
  <h2>How this would be settled</h2>
  <div class="banner {cls}">
    <h2>{esc(v.headline)}</h2>
    <p>{esc(v.detail)}</p>
  </div>{extra}
  <p style="color:var(--muted);font-size:16px">Auto-settlement now runs to
  &#8377;5,00,000 and employer approval has been removed for digital withdrawals.
  <strong>Automating the decision does not improve the data it is made on</strong>
  &mdash; which is why this page checks the record first.</p>
</div>"""

    return layout("Claim", f"""
<h1>Claim your provident fund</h1>
<p class="lede">Before anything is filed, the same checks EPFO will run &mdash;
run now, in seconds, instead of in three weeks.</p>
{gate}
{auto}
{forms}
<div class="card">
  <h2>What this page does not do</h2>
  <p>Nothing here is submitted to EPFO. This is an independent prototype with no
  connection to any government system. It prepares the paperwork; you file it.</p>
</div>
""", portal_header(a, token, "/claim"))


# Statutory service standards EPFO publishes for member claims. Used to show a
# member what "delayed" actually means, rather than leaving them guessing.
SERVICE_STANDARDS = [
    ("Claim settlement (Form 19 / 10C / 31)", 20, "working days"),
    ("Transfer request (Form 13)", 20, "working days"),
    ("Grievance on EPFiGMS", 30, "days"),
    ("RTI request", 30, "days"),
]


def page_track(a, token: str = "sample") -> str:
    std = "".join(
        f"<tr><th>{esc(w)}</th><td>{n} {esc(u)}</td></tr>"
        for w, n, u in SERVICE_STANDARDS)

    pending = ""
    for c in a.blocking + a.other:
        who, why, hi = _finding_copy(c)
        key = c["employer"].split(" | ")[0]
        pending += f"""
<a class="finding" href="/fix/{esc(key)}?s={esc(token)}">
  <p class="who">{esc(who)}</p>
  <p class="why">Route: {esc(c['correction_route'])}</p>
  <span class="go">Open the letter &rarr;</span>
</a>"""

    return layout("Track", f"""
<h1>Track</h1>
<p class="lede">Nothing has been filed from here &mdash; this prototype cannot
submit to EPFO. What it can do is tell you how long each step is supposed to
take, so silence stops being ambiguous.</p>

<div class="card">
  <h2>How long each step should take</h2>
  <table>{std}</table>
  <p style="color:var(--muted);font-size:16px">If a step passes its window with
  no response, that is your cue to escalate &mdash; not to wait longer. Most
  people wait because nobody told them what normal looks like.</p>
</div>

{f'<h2>Ready to file</h2>{pending}' if pending else
 '<div class="card"><p>Nothing outstanding.</p></div>'}

<div class="card">
  <h2>If a deadline passes</h2>
  <ol class="body">
    <li>Raise a grievance on EPFiGMS quoting the date you filed.</li>
    <li>If that goes unanswered past its window, file an RTI with the regional
        office asking for the status and the reason for the delay.</li>
    <li>Keep every acknowledgement number. It is the only thing that makes a
        delay provable.</li>
  </ol>
</div>
""", portal_header(a, token, "/track"))


def page_profile(a, token: str = "sample") -> str:
    nc = getattr(a, "name_check", None)
    rows = "".join(
        f"<tr><th>{esc(src)}</th><td><strong>{esc(sp)}</strong></td></tr>"
        for src, sp in (nc.names.items() if nc else {}.items()))

    if nc and nc.same_person:
        verdict = f"""
<div class="banner calm">
  <h2>All {len(nc.names)} spellings are the same person</h2>
  <p>Your records can safely be matched to each other.
  {f"Closest call: {esc(nc.weakest[0])} against {esc(nc.weakest[1])}." if nc.weakest else ""}</p>
</div>
<div class="card">
  <h2>Use this spelling on forms</h2>
  <p style="font-size:24px;font-weight:700;margin:0 0 8px">{esc(nc.canonical)}</p>
  <p>It is the version every other document agrees with. A name that differs
  between records is one of the most common reasons a claim is rejected, and
  the health-ID linkage rejects mismatches automatically as suspected fraud.</p>
</div>"""
    else:
        verdict = """
<div class="banner frozen">
  <h2>Your records do not agree on your name</h2>
  <p>Fix this before filing anything. Records that cannot be matched to each
  other cannot be merged.</p>
</div>"""

    ident = getattr(a, "identity", {}) or {}
    linked = [("UAN", ident.get("uan") or "not found in your documents",
               bool(ident.get("uan"))),
              ("PAN", ident.get("pan") or "not found in Form 26AS",
               bool(ident.get("pan"))),
              ("Aadhaar", "name matched across records", bool(nc and nc.same_person)),
              ("Bank account", "salary credits matched to employers",
               bool(getattr(a, "salary_events", [])))]
    kyc = "".join(
        f'<li><span class="tick">{"OK" if ok else "!"}</span>'
        f'<span><span class="what">{esc(k)}</span><br>'
        f'<span class="detail">{esc(v)}</span></span></li>'
        for k, v, ok in linked)

    return layout("Profile", f"""
<h1>Your profile</h1>
<p class="lede">Your identity as each document spells it &mdash; and whether
those spellings agree.</p>
{verdict}
<div class="card">
  <h2>Name on each document</h2>
  <table>{rows}</table>
</div>
<div class="card">
  <h2>What is linked</h2>
  <ul class="steps">{kyc}</ul>
  <p style="color:var(--muted);font-size:16px">This prototype reads your
  documents only. It cannot change anything held by EPFO &mdash; updating KYC or
  filing a nomination has to be done on the official portal.</p>
</div>
""", portal_header(a, token, "/profile"))


def page_pension(a, token: str = "sample") -> str:
    months = a.service_months
    years, rem = divmod(months, 12)
    eligible = a.pension_eligible
    short = max(0, 120 - months)

    if eligible:
        head = f"""
<div class="banner money">
  <h2>You qualify for a monthly pension</h2>
  <p>{years} years and {rem} months of eligible service &mdash; past the ten-year
  threshold. From 58 you can draw a monthly pension for life.</p>
</div>"""
    else:
        head = f"""
<div class="banner calm">
  <h2>Not yet eligible for a monthly pension</h2>
  <p>{years} years and {rem} months of eligible service. EPS-95 needs
  <strong>ten years</strong>, so you are {short} months short. Until then you can
  withdraw the pension amount instead, using Form 10C.</p>
</div>"""

    return layout("Pension", f"""
<h1>Your pension</h1>
<p class="lede">The 8.33% your employer pays into EPS is not part of your PF
balance, and most people never find that out until they claim.</p>
{head}
<dl class="tiles">
  <div class="tile"><dt>Pension fund</dt><dd>{_rs(a.total_pension)}</dd></div>
  <div class="tile"><dt>Eligible service</dt>
    <dd>{months}<small>months on record</small></dd></div>
  <div class="tile {'good' if eligible else ''}"><dt>Ten-year threshold</dt>
    <dd>{'Met' if eligible else f'{short} to go'}</dd></div>
</dl>
<div class="card">
  <h2>Why this is separate from your PF</h2>
  <p>Your employer pays 12% of your basic pay. Of that, <strong>8.33% goes to the
  pension scheme</strong> (capped at a wage of &#8377;15,000, so &#8377;1,250 a month
  for most people) and only the rest joins your PF balance.</p>
  <p>That is why the pension column in your passbook looks small next to the
  employer column, and why your withdrawable PF is less than the total of
  everything paid in.</p>
</div>
<div class="card">
  <h2>Why your service record matters here</h2>
  <p>Pension eligibility is counted in <strong>months of service</strong>, added up
  across every employer. A missing exit date or an unlinked old account does not
  just block a withdrawal &mdash; it can quietly cost you years of counted service
  and push you under the ten-year line.</p>
  <p><a href="/record?s={esc(token)}">Check your service record &rarr;</a></p>
</div>
""", portal_header(a, token, "/pension"))


def page_privacy(a=None, token: str = "sample") -> str:
    """
    What actually happens to an uploaded document.

    Written to be checkable rather than reassuring: every claim here is one
    someone could verify by reading the source or watching the network.
    """
    backend = getattr(a, "backend", "offline") if a else "offline"
    if backend == "openai":
        model_note = """
<div class="banner frozen">
  <h2>Some text is sent to OpenAI</h2>
  <p>This instance has the model backend switched on. Two small pieces of text
  leave this server and go to OpenAI:</p>
  <ul>
    <li><strong>Your name</strong>, if it is written in a script other than Latin,
    so it can be romanised and compared across documents.</li>
    <li><strong>Individual bank statement descriptions</strong> &mdash; the narration
    line only &mdash; so salary credits can be told apart from interest and rent.</li>
  </ul>
  <p>Your Form 26AS, your passbook, your PAN, your UAN and your balances are
  <strong>never</strong> sent anywhere.</p>
</div>"""
    else:
        model_note = """
<div class="banner calm">
  <h2>Nothing leaves this server</h2>
  <p>This instance runs entirely on local rules. No part of any document you
  upload is sent to any third party, including any AI service.</p>
  <p>If the model backend were switched on, two small things would be sent to
  OpenAI &mdash; your name if it is in a non-Latin script, and individual bank
  narration lines. This page would say so, and it would say so before you
  uploaded anything.</p>
</div>"""

    return layout("Privacy", f"""
<h1>What happens to your documents</h1>
<p class="lede">You are being asked to upload tax and provident fund records.
That is a serious thing to ask, so here is exactly what happens to them.</p>

{model_note}

<div class="card">
  <h2>Nothing is written to disk</h2>
  <p>Uploaded files are read into memory, converted to text, and dropped. There
  is no database, no file storage, and no backup. There is nothing here to
  breach because nothing is kept.</p>
</div>

<div class="card">
  <h2>Your session lasts 30 minutes</h2>
  <p>The result of the analysis is held in memory against a random token in your
  address bar, and expires after thirty minutes. Closing the tab or waiting is
  enough &mdash; there is no "delete my data" button because there is nothing to
  delete.</p>
</div>

<div class="card">
  <h2>Nothing is logged</h2>
  <p>Filenames, document contents and extracted text are never written to the
  server log. Errors are reported to you without recording what caused them.</p>
</div>

<div class="card">
  <h2>Nothing is submitted anywhere</h2>
  <p>This prototype has no connection to EPFO or any government system. The
  letters it prepares are shown to you to file yourself. Nothing is sent on your
  behalf.</p>
</div>

<div class="card">
  <h2>What you can safely leave out</h2>
  <p>Only two documents really matter: your <strong>PF passbook</strong> and your
  <strong>service history</strong>. Those alone will find overlapping service and
  missing exit dates.</p>
  <p><strong>Form 26AS is optional.</strong> It makes the evidence much stronger,
  because it can prove <em>when</em> an employer was still paying you &mdash; but it
  is also the most sensitive document you have, since it lists all your income
  and high-value transactions. If you would rather not share it, do not.
  You will still get a useful answer.</p>
  <p>The bank statement is optional too.</p>
</div>

<div class="card">
  <h2>Why you should be sceptical of pages like this</h2>
  <p>Any website can claim it does not store your documents. You cannot verify
  that from the outside, and you should not have to take our word for it.</p>
  <p>The honest answer is that a tool like this should not need an upload at all
  &mdash; it belongs inside EPFO&rsquo;s own portal, where the records already are, or
  running entirely on your own device. This prototype exists to show the idea
  works, not to become the place you send your tax records.</p>
</div>
""", portal_header(a, token, "/privacy") if a else None)


# EPF advance rules. Service thresholds are the stable part; rupee limits move,
# so this shows eligibility and points at the official limit rather than
# quoting a number that may be out of date.
# EPFO 3.0 collapsed thirteen advance types into three. The merge grouped the
# claim reasons; it did not repeal the service thresholds underneath them, so
# both levels are shown - the category you file under, and the rule that
# actually decides whether you qualify.
ADVANCES = [
    ("Illness", 0, "Yours or a family member's",
     "Six months' basic wages, or your own contribution plus interest &mdash; "
     "whichever is lower."),
    ("Unemployment", 0, "Out of work over a month",
     "75% after one month, the rest after two."),
    ("House purchase or construction", 60, "Plot, house, or building one",
     "The largest advance there is, and available once in a working life."),
    ("Home loan repayment", 120, "Paying off a housing loan", ""),
    ("House repair or alteration", 60, "A house you own",
     "Counted from when it was built or bought, not from today."),
    ("Marriage", 84, "Yours, a child's or a sibling's",
     "Up to half of your own contribution."),
    ("Education", 84, "Post-matriculation, for a child",
     "Up to half of your own contribution."),
    ("Before retirement", 0, "Within a year of retiring, from age 54.",
     "Up to 90% of the balance."),
]


def page_withdraw(a, token: str = "sample") -> str:
    months = a.service_months
    years = months / 12
    taxable = years < 5

    if taxable:
        tax = f"""
<div class="banner frozen">
  <h2>Withdrawing now would be taxed</h2>
  <p>You have <strong>{months} months</strong> of service on record &mdash; under the
  five-year mark. Withdraw before five years and the amount becomes taxable, with
  TDS deducted at source on anything above &#8377;50,000.</p>
  <p style="margin-top:10px">Almost nobody is told this before they file. It is
  the single most expensive thing people get wrong about their PF.</p>
</div>
<div class="card">
  <h2>What five years actually means</h2>
  <p>It is <strong>total service across every employer</strong>, not time at your
  current job &mdash; but only for accounts transferred and linked to your UAN.
  An untransferred old account does not count. Neither does service EPFO has no
  record of because an exit date was never filed. That is how a clerical error
  quietly costs you tax.</p>
  <p><a href="/record?s={esc(token)}">Check what service EPFO has recorded &rarr;</a></p>
</div>"""
    else:
        tax = f"""
<div class="banner money">
  <h2>Your withdrawal would not be taxed</h2>
  <p><strong>{months} months</strong> of service on record &mdash; past five years, so
  a withdrawal is exempt and no TDS applies.</p>
</div>"""

    rows = ""
    for name, need, when, detail in ADVANCES:
        ok = months >= need
        if need == 0:
            gate = "No minimum service"
        elif ok:
            gate = f"Needs {need // 12} years &mdash; you have {months // 12}"
        else:
            gate = f"Needs {need // 12} years &mdash; {need - months} months short"
        rows += f"""<tr>
  <th>{esc(name)}<br><span class="detail">{esc(when)}</span></th>
  <td><span class="pill {'money' if ok else 'unknown'}">{
      'Eligible' if ok else 'Not yet'}</span></td>
  <td class="detail">{gate}. {detail}</td></tr>"""

    cats = ", ".join(esc(label.lower()) for _, label, _ in CATEGORIES)

    v = a.settlement
    if v.mode == "auto":
        fast = f"""
<div class="card">
  <h2>How the money would reach you</h2>
  <table>
    <tr><th>By UPI</th><td>up to {_rs(v.upi_limit)} &mdash; 75% of your balance</td></tr>
    <tr><th>By ATM</th><td>up to {_rs(v.atm_limit)} &mdash; 50% of your balance</td></tr>
    <tr><th>Target</th><td>{TARGET_DAYS} days, against a {OUTER_LIMIT_DAYS}-working-day
      outer limit</td></tr>
  </table>
  <p style="color:var(--muted);font-size:16px">Past that limit EPFO owes you
  {DELAY_PENALTY_PCT}% penal interest. Almost nobody claims it, because almost
  nobody is told.</p>
</div>"""
    else:
        fast = f"""
<div class="card">
  <h2>How the money would reach you</h2>
  <p><strong>{esc(v.headline)}</strong> &mdash; UPI and ATM withdrawal are open
  only to claims that clear the automated checks, so those routes are closed to
  you today.</p>
  <p><a href="/claim?s={esc(token)}">What would need to change &rarr;</a></p>
</div>"""

    return layout("Withdraw", f"""
<h1>What you can take out</h1>
<p class="lede">EPFO merged thirteen advance types into three &mdash; {cats} &mdash;
then kept every service threshold underneath them. This checks your record
against each one.</p>
{tax}
{fast}
<dl class="tiles">
  <div class="tile"><dt>Available balance</dt><dd>{_rs(a.total_balance)}</dd></div>
  <div class="tile"><dt>Service on record</dt>
    <dd>{months}<small>months across {len([x for x in a.accounts if not x.orphan])} accounts</small></dd></div>
  <div class="tile {'alert' if taxable else 'good'}"><dt>Five-year mark</dt>
    <dd>{'Not reached' if taxable else 'Reached'}
      <small>{'withdrawal would be taxed' if taxable else 'withdrawal is exempt'}</small></dd></div>
</dl>
<div class="card">
  <h2>Advances, checked against your record</h2>
  <table>{rows}</table>
</div>
<div class="card">
  <h2>Before you rely on this</h2>
  <p>Service thresholds rarely change; the rupee limits do, so we do not quote
  them. Check the current figure on the official portal before you file. This
  prototype has no connection to EPFO and cannot file anything for you.</p>
</div>
""", portal_header(a, token, "/withdraw"))
