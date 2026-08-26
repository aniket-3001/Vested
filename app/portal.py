"""
The portal shell.

Layout, colour and component vocabulary taken from the live EPFO member portal
(unifiedportal-mem.epfindia.gov.in) so that a member who uses the real thing
recognises this one immediately.

Two deliberate departures, both improvements rather than shortcuts:

  - No state emblem and no EPFO logo. Mirroring a government crest on a
    third-party site is a real legal problem, not a styling choice.
  - Menus open as pages, not only as hover dropdowns. The real portal's hover
    menus need a mouse; these work on a phone and from a keyboard. The
    dropdown is layered on top for people who have a pointer.

House style for everything built on this module: labels and values, not
sentences. The real portal explains almost nothing, and a page of prose is how
you tell a member their money is complicated.
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import hashlib
import html

from app.cssmin import minify


def esc(s) -> str:
    return html.escape(str(s))


def rs(n: float) -> str:
    """
    Rupees in Indian digit grouping: 5,00,000 rather than 500,000.

    Last three digits, then pairs. Getting this wrong is the kind of small
    wrongness that tells an Indian reader the page was not built for them.
    No paise - money on this site is never shown to the paisa.
    """
    neg = n < 0
    d = f"{abs(n):.0f}"
    if len(d) > 3:
        head, tail = d[:-3], d[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        d = ",".join(parts + [tail])
    return f"&#8377;{'-' if neg else ''}{d}"


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
# EPFO's six menus, in EPFO's order, with EPFO's labels. Items marked new are
# ours; everything else is a rebuild of a screen that already exists.

MENUS = [
    ("/home", "Home", []),
    ("/view", "View", [
        ("/profile", "Profile", False),
        ("/uan-card", "UAN Card", False),
        ("/passbook-lite", "Passbook Lite", False),
        ("/passbook", "Passbook", False),
        ("/timeline", "Service Timeline", True),
        ("/print", "Record Summary", True),
    ]),
    ("/manage", "Manage", [
        ("/joint-declaration", "Joint Declaration", False),
        ("/contact", "Contact Details", False),
        ("/kyc", "KYC", False),
        ("/nomination", "E-Nomination", False),
        ("/exit", "Mark Exit", False),
        ("/corrections", "Corrections", True),
    ]),
    ("/account", "Account", [
        ("/password", "Change Password", False),
        ("/notifications", "Notifications", True),
    ]),
    ("/services", "Online Services", [
        ("/history", "Member Service History", False),
        ("/claim", "Claim (Form 31, 19 & 10C)", False),
        ("/claim-10d", "Claim (Form 10-D)", False),
        ("/transfer", "Request for Transfer of Account", False),
        ("/track", "Track Claim Status", False),
        ("/track-old", "Track Claim Status (OLD)", False),
        ("/scheme-certificate", "Scheme Certificate Surrender", False),
        ("/check", "Claim Check", True),
        ("/why-rejected", "Why Was My Claim Rejected", True),
    ]),
    ("/pmvbry", "PMVBRY", [
        ("/pmvbry", "Dashboard", False),
        ("/pmvbry-flc", "Financial Literacy Course", False),
        ("/pmvbry-cert", "FLC Certificate", False),
    ]),
]

# Which top-level menu a page belongs to, derived rather than hand-maintained
# so a new page cannot silently fall out of the navigation.
PARENT = {"/home": "/home"}
for _href, _label, _kids in MENUS:
    PARENT.setdefault(_href, _href)
    for _k, _kl, _new in _kids:
        PARENT[_k] = _href


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

CSS = minify("""
:root{
  --teal:#12807f; --teal-d:#0a6261; --teal-l:#e7f2f2;
  --amber:#c07722; --amber-bg:#fdf6dd;
  --red:#d63b30; --red-bg:#fdeceb;
  --green:#2f9e44; --blue:#2b7fd0; --blue-bg:#e8f2fb;
  --ink:#1f2b2b; --mute:#5f7070; --line:#dbe4e4; --bg:#f1f5f5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--teal)}
h1,h2,h3{margin:0;font-weight:600;line-height:1.3}
p{margin:0 0 10px}
p:last-child{margin-bottom:0}

/* prototype strip */
.flag{background:#2b2b2b;color:#fff;font-size:13px;padding:6px 16px;text-align:center}
.flag a{color:#8fd9d8}

/* header */
.hd{background:#fff;border-bottom:3px solid var(--teal);padding:12px 16px;
  display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
.hd .org{font-size:17px;font-weight:700;color:var(--teal);letter-spacing:.2px;
  text-transform:uppercase;margin:0}
.hd .min{font-size:12px;font-weight:600;color:var(--amber);text-transform:uppercase;
  letter-spacing:.3px;margin:2px 0 0}
.hd .rt{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.uan{background:var(--teal-l);border-radius:22px;padding:6px 16px;line-height:1.25}
.uan b{display:block;font-size:14px;color:var(--teal-d)}
.uan span{font-size:12px;color:var(--mute)}
.out{background:var(--red);color:#fff;text-decoration:none;border-radius:4px;
  padding:8px 14px;font-size:14px;font-weight:600}

/* nav */
nav.mn{background:var(--teal)}
nav.mn ul{margin:0 auto;padding:0;list-style:none;display:flex;flex-wrap:wrap;
  max-width:1180px}
nav.mn li{position:relative}
nav.mn a{display:block;color:#fff;text-decoration:none;padding:13px 17px;
  font-size:15px;font-weight:500}
nav.mn > ul > li > a:hover,nav.mn > ul > li:focus-within > a{background:var(--teal-d)}
nav.mn .on > a{background:var(--teal-d);font-weight:600}
nav.mn ul ul{display:none;position:absolute;top:100%;left:0;z-index:20;
  background:#fff;min-width:250px;box-shadow:0 6px 18px rgba(0,0,0,.18);
  border-radius:0 0 4px 4px;flex-direction:column}
nav.mn li:hover > ul,nav.mn li:focus-within > ul{display:flex}
nav.mn ul ul a{color:var(--ink);font-size:13px;text-transform:uppercase;
  letter-spacing:.3px;padding:11px 16px;border-bottom:1px solid var(--line)}
nav.mn ul ul a:hover{background:var(--teal-l);color:var(--teal-d)}
.nu{background:var(--amber);color:#fff;font-size:10px;border-radius:3px;
  padding:1px 5px;margin-left:7px;vertical-align:1px;letter-spacing:.4px}

/* page frame */
.crumb{background:#fff;border-bottom:1px solid var(--line);font-size:14px;
  color:var(--mute);padding:9px 16px}
.crumb a{text-decoration:none}
main{max-width:1180px;margin:0 auto;padding:16px}
.ttl{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;
  justify-content:space-between;border-bottom:2px solid var(--amber);
  padding-bottom:8px;margin-bottom:16px}
.ttl h1{font-size:21px;color:var(--teal-d)}
.sub{color:var(--mute);font-size:14px}

/* card */
.c{background:#fff;border:1px solid var(--line);border-radius:4px;margin-bottom:16px}
.c > h2{background:var(--teal);color:#fff;font-size:15px;font-weight:600;
  padding:11px 14px;border-radius:3px 3px 0 0;display:flex;gap:9px;align-items:center}
.c > h2::before{content:"\\2630";font-size:13px;opacity:.85}
.c.q > h2{background:#eef2f2;color:var(--ink);border-bottom:1px solid var(--line)}
.c.q > h2::before{opacity:.5}
.b{padding:14px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(310px,1fr))}

/* key/value */
.kv{width:100%;border-collapse:collapse}
.kv th{text-align:left;font-weight:400;color:var(--mute);padding:9px 0;
  width:44%;vertical-align:top;font-size:15px}
.kv td{padding:9px 0;font-weight:600;vertical-align:top}
.kv tr + tr th,.kv tr + tr td{border-top:1px solid var(--line)}

/* data table */
.tw{overflow-x:auto}
table.d{width:100%;border-collapse:collapse;font-size:14px;min-width:520px}
table.d th{background:var(--teal);color:#fff;font-weight:600;text-align:left;
  padding:9px 11px;border:1px solid var(--teal-d);white-space:nowrap}
table.d td{padding:9px 11px;border:1px solid var(--line);vertical-align:top}
table.d tbody tr:nth-child(even){background:#fafbfb}
tr.pri > td{background:var(--amber-bg) !important}
tr.sec > th{background:var(--blue);border-color:var(--blue)}

/* status */
.p{display:inline-block;font-size:12px;font-weight:600;border-radius:3px;
  padding:2px 8px;white-space:nowrap}
.p.ok{background:#e6f6ea;color:var(--green)}
.p.no{background:var(--red-bg);color:var(--red)}
.p.hm{background:var(--amber-bg);color:var(--amber)}
.p.nu2{background:#eceff0;color:var(--mute)}

/* banners */
.al{padding:12px 14px;margin-bottom:16px;border-radius:3px;font-size:15px}
.al.r{background:var(--red-bg);border-left:4px solid var(--red)}
.al.b{background:var(--blue-bg);border-left:4px solid var(--blue)}
.al.g{background:#e9f7ed;border-left:4px solid var(--green)}
.al.a{background:var(--amber-bg);border-left:4px solid var(--amber)}
.al h2{font-size:16px;margin-bottom:4px}

/* buttons + forms */
.btn{display:inline-block;background:var(--teal);color:#fff;text-decoration:none;
  border:0;border-radius:4px;padding:10px 18px;font-size:15px;font-weight:600;
  cursor:pointer;font-family:inherit}
.btn:hover{background:var(--teal-d)}
.btn.g{background:var(--green)}
.btn.o{background:#fff;color:var(--teal);border:1px solid var(--teal)}
label{display:block;font-size:14px;color:var(--mute);margin-bottom:4px}
input[type=text],input[type=password],input[type=date],input[type=email],select,textarea{
  width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:4px;
  font:inherit;font-size:15px;background:#fff}
input:disabled{background:#f4f6f6;color:var(--mute)}
.fr{margin-bottom:14px}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
.row > *{flex:1 1 190px}

/* quick links */
.ql{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(155px,1fr))}
.ql a{background:#fff;border:1px solid var(--line);border-radius:4px;padding:16px 12px;
  text-align:center;text-decoration:none;color:var(--ink);font-size:14px;font-weight:500}
.ql a:hover{border-color:var(--teal);background:var(--teal-l)}
.ql b{display:block;font-size:22px;margin-bottom:6px}

/* timeline */
.tl{font-size:13px}
.tl .yr{display:flex;color:var(--mute);font-size:12px;border-bottom:1px solid var(--line);
  margin-bottom:6px;padding-bottom:3px}
.tl .yr span{flex:1;text-align:center}
.tl .tr2{display:flex;align-items:center;gap:10px;margin-bottom:7px}
.tl .lb{width:132px;flex-shrink:0;color:var(--mute);font-size:12px;text-align:right}
.tl .tk{flex:1;position:relative;height:20px;background:#eef1f1;border-radius:3px}
.tl .sg{position:absolute;top:0;height:20px;border-radius:3px}
.tl .sg.epfo{background:#9aa8a8}
.tl .sg.pf{background:var(--teal)}
.tl .sg.tds{background:var(--blue)}
.tl .sg.bank{background:#7bb661}
.tl .sg.bad{background:var(--red)}
.tl .sg.fix{background:repeating-linear-gradient(45deg,var(--green),var(--green) 5px,
  #79c98a 5px,#79c98a 10px)}
.lg{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mute);margin-top:10px}
.lg i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;
  vertical-align:-1px;font-style:normal}

/* plan */
.stp{list-style:none;margin:0;padding:0;counter-reset:s}
.stp li{position:relative;padding:0 0 16px 40px;border-left:2px solid var(--line);
  margin-left:13px}
.stp li:last-child{border-left-color:transparent;padding-bottom:0}
.stp li::before{counter-increment:s;content:counter(s);position:absolute;left:-14px;top:-2px;
  width:26px;height:26px;border-radius:50%;background:var(--teal);color:#fff;
  font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center}
.stp li.done::before{content:"\\2713";background:var(--green)}
.stp b{display:block;margin-bottom:2px}
.stp .m{color:var(--mute);font-size:14px}
.par{background:var(--teal-l);border-radius:3px;padding:3px 9px;font-size:12px;
  color:var(--teal-d);display:inline-block;margin-top:5px}

/* gate list */
.gt{list-style:none;margin:0;padding:0}
.gt li{display:grid;grid-template-columns:1fr auto;gap:4px 14px;
  padding:11px 0 11px 13px;border-bottom:1px solid var(--line);
  font-size:15px;align-items:baseline;border-left:3px solid transparent}
.gt li:last-child{border-bottom:0}
.gt li.ok{border-left-color:var(--green)}
.gt li.no{border-left-color:var(--red)}
.gt li.un{border-left-color:var(--line)}
.gt li.hm{border-left-color:var(--amber)}
.gt .code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12px;color:var(--mute);letter-spacing:.04em;margin-right:8px}
.gt .m{color:var(--mute);font-size:13.5px;grid-column:1/-1;margin:0;
  line-height:1.5}

/* sign-in: one card per test account, each a button that works */
.accts{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  margin-bottom:16px}
.acct{background:var(--paper);border:1px solid var(--line);border-radius:4px;
  padding:18px;display:flex;flex-direction:column;gap:10px;margin:0}
.acct h2{font-size:17px;color:var(--teal-d);margin:0;background:none;padding:0}
.acct h2::before{content:none}
.acct .blurb{font-size:14px;color:var(--mute);margin:0;flex:1}
.cred{display:grid;grid-template-columns:auto 1fr;gap:2px 14px;margin:0;
  background:#f7faf9;border:1px solid var(--line);border-radius:3px;padding:9px 12px}
.cred dt{font-size:12px;color:var(--mute)}
.cred dd{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:14px;font-weight:600;color:var(--ink)}
.acct .btn{text-align:center}

/* Hindi beside English on findings */
.hi{display:block;font-size:14px;color:var(--mute);margin-top:3px;line-height:1.5}

/* a letter meant to be printed and carried to a counter */
.doc{border:1px solid var(--line);border-radius:4px;padding:18px;background:#fff}
.doc h3{font-size:15px;margin-bottom:10px;color:var(--teal-d)}
.doc pre{white-space:pre-wrap;font:inherit;font-size:15px;margin:0;line-height:1.55}
.ann{margin:6px 0 0 18px;padding:0;font-size:14px;color:var(--mute)}
.rz{margin:0 0 0 18px;padding:0}
.rz li{margin-bottom:6px}

/* visually hidden, still read aloud */
.sr{position:absolute;width:1px;height:1px;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap}

/* footer */
footer{background:var(--teal-d);color:#cfe4e4;font-size:13px;padding:13px 16px;
  display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;margin-top:24px}
footer a{color:#fff}
.strip{background:var(--teal);height:8px}

@media (max-width:560px){
  main{padding:12px}
  nav.mn a{padding:11px 13px;font-size:14px}
  nav.mn ul ul{position:static;box-shadow:none;min-width:0}
  .hd{padding:10px 12px}
  .kv th{width:50%}
  .tl .lb{width:78px;font-size:11px}
}
@media print{
  .flag,nav.mn,.crumb,footer,.strip,.out,.ql{display:none !important}
  body{background:#fff;font-size:11pt}
  .c{border-color:#999;page-break-inside:avoid}
  .c > h2{background:#fff;color:#000;border-bottom:1pt solid #000}
  main{max-width:none;padding:0}
  .doc::after{content:"Not an official EPFO document. Independent prototype.";
    display:block;margin-top:14pt;font-size:9pt;color:#444}
}
""")

CSS_HASH = hashlib.sha256(CSS.encode()).hexdigest()[:12]
CSS_URL = f"/s/{CSS_HASH}.css"


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def card(title: str, body: str, quiet: bool = False) -> str:
    return (f'<section class="c{" q" if quiet else ""}">'
            f'<h2>{esc(title)}</h2><div class="b">{body}</div></section>')


def kv(rows: list[tuple[str, str]]) -> str:
    """Label/value pairs. The portal's default way of showing anything."""
    out = "".join(f"<tr><th>{esc(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="kv">{out}</table>'


def table(head: list[str], rows: list[list[str]], classes: list[str] | None = None) -> str:
    h = "".join(f"<th>{esc(c)}</th>" for c in head)
    body = ""
    for i, r in enumerate(rows):
        cls = f' class="{classes[i]}"' if classes and classes[i] else ""
        body += f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    return (f'<div class="tw"><table class="d"><thead><tr>{h}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def pill(text: str, tone: str = "nu2") -> str:
    return f'<span class="p {tone}">{esc(text)}</span>'


OK = pill("Approved", "ok")
NO = pill("Not verified", "no")
UNKNOWN = pill("Not visible to us", "nu2")


# Status shown as a word in a coloured chip, with a thin rule down the left of
# the row carrying the same meaning for anyone who cannot see the colour.
STATUS = {
    "pass": ("Pass", "ok"),
    "fail": ("Action needed", "no"),
    "unknown": ("Not visible", "nu2"),
    "advisory": ("Worth doing", "hm"),
}


def status_chip(kind: str) -> str:
    word, tone = STATUS.get(kind, ("Checked", "nu2"))
    return pill(word, tone)


def alert(body: str, tone: str = "b") -> str:
    return f'<div class="al {tone}">{body}</div>'


NEW_TAG = '<span class="nu">NEW</span>'


def nav(active: str, token: str) -> str:
    """Six menus. Parents are real pages so this works without a pointer."""
    top = PARENT.get(active, active)
    out = ""
    for href, label, kids in MENUS:
        on = " class=\"on\"" if href == top else ""
        sub = ""
        if kids:
            items = ""
            for k, kl, is_new in kids:
                tag = NEW_TAG if is_new else ""
                items += (f'<li><a href="{k}?s={esc(token)}">'
                          f"{esc(kl)}{tag}</a></li>")
            sub = f"<ul>{items}</ul>"
        out += f'<li{on}><a href="{href}?s={esc(token)}">{esc(label)}</a>{sub}</li>'
    return f'<nav class="mn" aria-label="Main"><ul>{out}</ul></nav>'


def shell(title: str, body: str, *, token: str = "sample", active: str = "/home",
          member: str = "", uan: str = "", crumb: str = "",
          heading: str | None = None, aside: str = "") -> str:
    """One page. Every screen on the site goes through here."""
    top = PARENT.get(active, active)
    top_label = next((l for h, l, _ in MENUS if h == top), "Home")
    trail = (f'<a href="/home?s={esc(token)}">Home</a> / {esc(crumb)}'
             if crumb else f'<a href="/home?s={esc(token)}">Home</a> / {esc(top_label)}')
    ident = ""
    if uan or member:
        ident = (f'<div class="uan"><b>UAN: {esc(uan) if uan else "—"}</b>'
                 f'<span>{esc(member)}</span></div>')
    head = f"""<header class="hd">
  <div><p class="org">PF Sahi Hai &mdash; Provident Fund Member Portal</p>
  <p class="min">Independent prototype &middot; not a government service</p></div>
  <div class="rt">{ident}<a class="out" href="/login">Logout</a></div>
</header>{nav(active, token)}<div class="crumb">{trail}</div>"""
    h1 = f'<div class="ttl"><h1>{esc(heading or title)}</h1>{aside}</div>' if heading is not False else ""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} &mdash; PF Sahi Hai</title>
<link rel="stylesheet" href="{CSS_URL}">
</head><body>
<div class="flag"><strong>Independent hackathon prototype.</strong>
Not affiliated with or endorsed by EPFO. Nothing is stored or submitted.
<a href="/privacy?s={esc(token)}">Privacy</a></div>
{head}
<main>{h1}{body}</main>
<footer><span>Build What Moves India &middot; synthetic data only</span>
<span>PF Sahi Hai 2.0</span></footer><div class="strip"></div>
</body></html>"""


def bare(title: str, body: str) -> str:
    """Sign-in and error pages: no member, so no navigation."""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} &mdash; PF Sahi Hai</title>
<link rel="stylesheet" href="{CSS_URL}">
</head><body>
<div class="flag"><strong>Independent hackathon prototype.</strong>
Not affiliated with or endorsed by EPFO. Synthetic data only.</div>
<header class="hd">
  <div><p class="org">PF Sahi Hai &mdash; Provident Fund Member Portal</p>
  <p class="min">Independent prototype &middot; not a government service</p></div>
</header>
<main>{body}</main>
<footer><span>Build What Moves India &middot; synthetic data only</span>
<span>PF Sahi Hai 2.0</span></footer><div class="strip"></div>
</body></html>"""
