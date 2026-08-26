"""
Front-end guarantees.

These test claims that are made repeatedly in the documentation and would
otherwise never be checked:

  - no JavaScript is required for any step
  - the page is readable with CSS disabled
  - it works on a phone
  - it is usable with a screen reader
  - status is never conveyed by colour alone
  - the pages stay small enough for a slow connection

A claim in a spec that no test enforces is just a hope.

Run:  python tests/test_frontend.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import html
import re

from app.portal import CSS, CSS_HASH, CSS_URL, MENUS
from app.server import create_app

TOK = "100999888777"

# Every screen, including the ones that only exist to complete the rebuild.
PATHS = [
    "/home", "/view", "/manage", "/account", "/services",
    "/profile", "/uan-card", "/passbook-lite", "/passbook", "/timeline",
    "/joint-declaration", "/contact", "/kyc", "/nomination", "/exit",
    "/corrections", "/password", "/notifications",
    "/history", "/history-entry", "/claim", "/claim-10d", "/transfer",
    "/track", "/track-old", "/scheme-certificate", "/check", "/why-rejected",
    "/pmvbry", "/pmvbry-flc", "/pmvbry-cert", "/privacy",
]
PUBLIC = ["/login", "/upload"]


def to_text(doc: str) -> str:
    t = re.sub(r"(?s)<(script|style).*?</\1>", "", doc)
    t = re.sub(r"(?i)<(br|/p|/h[1-6]|/li|/a|/div|/tr|/td)[^>]*>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", t)).strip()


def headings(doc: str) -> list[int]:
    return [int(m) for m in re.findall(r"<h([1-6])\b", doc)]


def main() -> int:
    c = create_app().test_client()
    checks: list[tuple[str, bool]] = []

    pages = {p: c.get(f"{p}?s={TOK}").get_data(as_text=True) for p in PATHS}
    pages.update({p: c.get(p).get_data(as_text=True) for p in PUBLIC})

    # --- no JavaScript anywhere -------------------------------------------
    for name, doc in pages.items():
        checks.append((f"{name}: zero <script> tags", "<script" not in doc.lower()))
        checks.append((f"{name}: no inline on* handlers",
                       not re.search(r"\son(click|load|change|submit)\s*=", doc, re.I)))

    # --- readable with CSS disabled ---------------------------------------
    for name, doc in pages.items():
        checks.append((f"{name}: content survives CSS removal",
                       len(to_text(doc)) > 200))

    # --- mobile ------------------------------------------------------------
    for name, doc in pages.items():
        checks.append((f"{name}: viewport meta present",
                       'name="viewport"' in doc and "width=device-width" in doc))

    # --- semantics ---------------------------------------------------------
    for name, doc in pages.items():
        hs = headings(doc)
        no_skip = all(b - a <= 1 for a, b in zip(hs, hs[1:]) if b > a)
        checks += [
            (f"{name}: exactly one <h1>", hs.count(1) == 1),
            (f"{name}: no heading level skipped", no_skip),
            (f"{name}: declares lang", '<html lang="en">' in doc),
            (f"{name}: has a <title>", "<title>" in doc),
        ]

    # --- every input has a label ------------------------------------------
    for name in ["/upload", "/login", "/history-entry", "/joint-declaration",
                 "/password"]:
        doc = pages[name]
        ids = re.findall(r'<(?:input|select|textarea)[^>]*id="([^"]+)"', doc)
        labels = re.findall(r'<label[^>]*for="([^"]+)"', doc)
        checks.append((f"{name}: every field has a matching label",
                       bool(ids) and all(i in labels for i in ids)))
    checks.append(("upload declares multipart encoding",
                   'enctype="multipart/form-data"' in pages["/upload"]))
    checks.append(("login password field is type=password",
                   'id="password"' in pages["/login"]
                   and 'type="password"' in pages["/login"]))

    # --- navigation --------------------------------------------------------
    for name, doc in pages.items():
        if name in PUBLIC:
            continue
        checks.append((f"{name}: portal nav present", 'class="mn"' in doc))
        # Privacy is reached from the prototype strip, not from a menu, so it
        # correctly highlights nothing. Every page that does live in a menu
        # must highlight exactly one.
        want = 0 if name == "/privacy" else 1
        checks.append((f"{name}: {want} menu(s) marked current",
                       doc.count('<li class="on"') == want))
    home = pages["/home"]
    checks.append(("nav lists all six EPFO menus",
                   all(f'>{label}<' in home for _h, label, _k in MENUS)))
    checks.append(("every menu child is reachable from its landing page",
                   all(any(f'href="{k}?s=' in pages[parent]
                           for k, _l, _n in kids)
                       for parent, _lab, kids in MENUS if kids
                       for _ in [0])))

    # --- the stylesheet, served once rather than inlined thirty times ------
    sheet = c.get(CSS_URL)
    css = sheet.get_data(as_text=True)
    checks += [
        ("stylesheet is served as a cacheable file",
         sheet.status_code == 200 and sheet.mimetype == "text/css"),
        ("it is cached hard, since the URL carries its hash",
         "immutable" in sheet.headers.get("Cache-Control", "")),
        ("a stale hash is not served", c.get("/s/000000000000.css").status_code == 404),
        ("every page links it", all(CSS_URL in d for d in pages.values())),
        ("no page inlines a stylesheet", not any("<style>" in d for d in pages.values())),
        ("the hash matches the served bytes", CSS_HASH in CSS_URL and css == CSS),
        ("CSS: has a small-screen breakpoint", "@media (max-width:560px)" in css),
        ("CSS: wide content can scroll horizontally", "overflow-x:auto" in css),
        ("CSS: no fixed px width on the main container",
         not re.search(r"main\{[^}]*[^-]width:\s*\d+px", css)),
    ]

    # --- the printer is the last mile -------------------------------------
    pr = css[css.find("@media print"):] if "@media print" in css else ""
    checks += [
        ("a print stylesheet exists", bool(pr)),
        ("printing hides the navigation", "nav.mn" in pr),
        ("printing hides the prototype strip", ".flag" in pr),
        ("a printed page still says it is not official", "Not an official" in pr),
        ("print sizes are in points, not pixels", "pt" in pr),
    ]

    # --- page weight, measured not asserted -------------------------------
    heaviest = max((len(d), n) for n, d in pages.items())
    mean = sum(len(d) for d in pages.values()) // len(pages)
    checks += [
        (f"heaviest page under 16 KB ({heaviest[1]} = {heaviest[0]/1024:.1f} KB)",
         heaviest[0] < 16 * 1024),
        (f"mean page under 8 KB ({mean/1024:.1f} KB)", mean < 8 * 1024),
        (f"stylesheet under 12 KB ({len(CSS)/1024:.1f} KB)", len(CSS) < 12 * 1024),
    ]

    # --- sign-in -----------------------------------------------------------
    root = c.get("/")
    lb = pages["/login"]
    checks += [
        ("/ redirects to sign-in", root.status_code == 302
         and "/login" in root.headers.get("Location", "")),
        ("working credentials are printed on it",
         "100999888777" in lb and "rahul" in lb),
        ("both test accounts are offered", "100777666555" in lb),
        ("and you can still use your own documents", "/upload" in lb),
        ("a wrong password is refused",
         c.post("/login", data={"uan": TOK, "password": "no"}).status_code == 401),
        ("a right password signs you in",
         c.post("/login", data={"uan": TOK, "password": "rahul"}).status_code == 303),
    ]

    # --- honesty on every page --------------------------------------------
    for name, doc in pages.items():
        checks.append((f"{name}: declares itself a prototype",
                       "Independent hackathon prototype" in doc))
    priv = pages["/privacy"]
    checks += [
        ("privacy page is linked from every signed-in page",
         all("/privacy" in d for n, d in pages.items() if n not in PUBLIC)),
        ("privacy page admits you cannot verify the claim",
         "sceptical" in priv),
        ("privacy page states nothing is sent to a model", "model" in priv.lower()),
    ]

    # --- status is never conveyed by colour alone -------------------------
    kyc_txt = to_text(pages["/kyc"])
    check_txt = to_text(pages["/check"])
    home_txt = to_text(pages["/home"])
    checks += [
        ("/kyc: statuses carry words, not just colour",
         "Approved" in kyc_txt or "Not Verified" in kyc_txt),
        ("/check: gate results carry a symbol and a code",
         "G01" in check_txt and ("pass" in check_txt.lower()
                                 or "fail" in check_txt.lower()
                                 or "not visible" in check_txt.lower())),
        ("/home: the verdict is a sentence, not a colour",
         "rejected" in home_txt.lower() or "settle" in home_txt.lower()
         or "not yet checked" in home_txt.lower()),
    ]

    # --- an expired session is told so, not shown an empty page -----------
    gone = c.get("/home?s=doesnotexist")
    checks += [
        ("an unknown session returns 410", gone.status_code == 410),
        ("and explains what happened",
         "expired" in gone.get_data(as_text=True).lower()),
    ]

    print("=" * 72)
    print("  front-end assertions")
    failures = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        failures += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    _s.exit(main())
