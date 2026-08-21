"""
Front-end guarantees.

These test claims that have been made repeatedly in the documentation and were
never actually checked:

  - no JavaScript is required for any step
  - the page is readable with CSS disabled
  - it works on a phone
  - it is usable with a screen reader

A claim in a spec that no test enforces is just a hope.

Run:  python tests/test_frontend.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import html
import io
import re

import app.engine as E
from app.server import create_app


def strip_css(doc: str) -> str:
    return re.sub(r"(?s)<style.*?</style>", "", doc)


def to_text(doc: str) -> str:
    t = strip_css(doc)
    t = re.sub(r"(?i)<(br|/p|/h[1-6]|/li|/a|/div|/tr)[^>]*>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", t)).strip()


def headings(doc: str) -> list[int]:
    return [int(m) for m in re.findall(r"<h([1-6])\b", doc)]


def main() -> int:
    app = create_app()
    c = app.test_client()

    f = lambda n, t: (io.BytesIO(t.encode()), n)
    r = c.post("/analyse", data={
        "mode": "upload",
        "f26as": f("a.txt", E.SAMPLE_26AS),
        "passbook": [f("b.txt", E.SAMPLE_PASSBOOKS[0]), f("c.txt", E.SAMPLE_PASSBOOKS[1])],
        "history": f("d.txt", E.SAMPLE_SERVICE_HISTORY),
        "bank": f("e.txt", E.SAMPLE_BANK),
    }, content_type="multipart/form-data")
    tok = r.headers["Location"].split("s=")[1]

    # Employer keys are derived from the uploaded documents, so discover them
    # rather than hardcoding - hardcoding is what broke this for real users.
    from app.server import _load  # noqa: F401
    an = _load(tok)
    fix_key = next(c["employer"].split(" | ")[0]
                   for c in an.result["contradictions"]
                   if c["kind"] != "ORPHAN_ACCOUNT")
    orphan_key = next(o.candidate.tan for o in an.orphans)
    acct_id = next(x.member_id for x in an.accounts if not x.orphan)

    pages = {
        "/upload": c.get("/upload").data.decode(),
        "/home": c.get(f"/home?s={tok}").data.decode(),
        "/record": c.get(f"/record?s={tok}").data.decode(),
        "/accounts": c.get(f"/accounts?s={tok}").data.decode(),
        "/account": c.get(f"/account/{acct_id}?s={tok}").data.decode(),
        "/claim": c.get(f"/claim?s={tok}").data.decode(),
        "/track": c.get(f"/track?s={tok}").data.decode(),
        "/pension": c.get(f"/pension?s={tok}").data.decode(),
        "/profile": c.get(f"/profile?s={tok}").data.decode(),
        "/withdraw": c.get(f"/withdraw?s={tok}").data.decode(),
        "/privacy": c.get(f"/privacy?s={tok}").data.decode(),
        "/fix": c.get(f"/fix/{fix_key}?s={tok}").data.decode(),
        "/recover": c.get(f"/recover/{orphan_key}?s={tok}").data.decode(),
    }
    checks: list[tuple[str, bool]] = []

    # --- no JavaScript anywhere ------------------------------------------
    for name, doc in pages.items():
        checks.append((f"{name}: zero <script> tags", "<script" not in doc.lower()))
        checks.append((f"{name}: no inline on* handlers",
                       not re.search(r"\son(click|load|change|submit)\s*=", doc, re.I)))

    # --- readable with CSS disabled --------------------------------------
    for name, doc in pages.items():
        txt = to_text(doc)
        checks.append((f"{name}: content survives CSS removal", len(txt) > 400))
    res_txt = to_text(pages["/record"])
    checks += [
        ("/result: verdict appears before findings, unstyled",
         res_txt.find("rejected today") < res_txt.find("recorded the wrong leaving date")),
        ("/result: prototype disclaimer is in the text, not just styling",
         "Independent hackathon prototype" in res_txt),
    ]

    # --- mobile ----------------------------------------------------------
    for name, doc in pages.items():
        checks.append((f"{name}: viewport meta present",
                       'name="viewport"' in doc and "width=device-width" in doc))
    # --- portal navigation is present and marks where you are -----------
    for name in ["/home", "/record", "/accounts", "/pension", "/withdraw",
                 "/claim", "/track", "/profile"]:
        doc = pages[name]
        checks.append((f"{name}: portal nav present", 'class="tabs"' in doc))
        checks.append((f"{name}: current section marked",
                       doc.count('class="tab on"') == 1))
    checks.append(("nav links every section",
                   all(f'href="{h}?' in pages["/home"] for h, _ in
                       [("/home",0),("/record",0),("/accounts",0),("/pension",0),
                        ("/withdraw",0),("/claim",0),("/track",0),("/profile",0)])))
    # the privacy claim must match what the build actually does
    priv = pages["/privacy"]
    an2 = _load(tok)
    checks += [
        ("privacy page reachable from every page",
         all("/privacy" in d for d in pages.values())),
        ("privacy page states the model backend truthfully",
         ("Some text is sent to OpenAI" in priv) == (an2.backend == "openai")),
        ("privacy page says 26AS is optional", "Form 26AS is optional" in priv),
        ("privacy page admits you cannot verify the claim",
         "should be sceptical" in priv or "take our word" in priv),
        ("withdraw page warns about the five-year tax rule",
         "five-year" in pages["/withdraw"] or "five years" in pages["/withdraw"]),
    ]
    checks.append(("upload page reveals the portal sections",
                   "What you get" in pages["/upload"] and "Pension" in pages["/upload"]))
    # The bare URL must land on the sign-in page, which carries working test
    # credentials. Anyone evaluating this has no PF documents of their own, so a
    # form-first landing page hides the entire product behind a submit.
    root = c.get("/")
    login = c.get("/login")
    lb = login.get_data(as_text=True)
    checks += [
        ("/ redirects to sign-in", root.status_code == 302
         and "/login" in root.headers.get("Location", "")),
        ("the sign-in page renders", login.status_code == 200),
        ("working credentials are printed on it",
         "100999888777" in lb and "rahul" in lb),
        ("both test accounts are offered", "100777666555" in lb),
        ("and you can still use your own documents", "/upload" in lb),
        ("a wrong password is refused",
         c.post("/login", data={"uan": "100999888777",
                                "password": "no"}).status_code == 401),
        ("a right password signs you in",
         c.post("/login", data={"uan": "100999888777",
                                "password": "rahul"}).status_code == 303),
    ]
    # The sample banner must appear for the sample record and NOT for a real
    # upload - mislabelling someone's own data as "sample" would be worse than
    # not labelling it at all.
    sample_pages = {n: c.get(f"{n}?s=sample").data.decode()
                    for n in ["/home", "/record", "/accounts", "/pension",
                              "/claim", "/track", "/profile"]}
    checks += [
        ("test account labelled on every sample page",
         all("test account" in d for d in sample_pages.values())),
        ("sample banner links to upload",
         all("/upload" in d for d in sample_pages.values())),
        ("a real upload is NOT labelled as sample",
         not any("You are looking at a sample record" in d
                 for n, d in pages.items() if n != "/upload")),
    ]

    # --- the printer is the last mile ------------------------------------
    # The Joint Declaration is carried to an EPFO counter on paper. Printing it
    # with navigation tabs and a hero card produces a web printout, not a
    # document - the core feature failing on the surface that decides it.
    from app.views import CSS
    pr = CSS[CSS.find("@media print"):] if "@media print" in CSS else ""
    checks += [
        ("a print stylesheet exists", bool(pr)),
        ("printing hides the navigation tabs", ".tabs" in pr),
        ("printing hides the prototype banner strip", ".flag" in pr),
        ("printing keeps the letter itself", ".doc{" in pr),
        ("the letter does not break across pages",
         "page-break-inside:avoid" in pr),
        ("a printed letter still says it is not official",
         "Not an official" in pr),
        ("print sizes are in points, not pixels", "pt" in pr),
    ]

    # --- page weight, measured not asserted ------------------------------
    heaviest = max((len(d), n) for n, d in pages.items())
    mean = sum(len(d) for d in pages.values()) // len(pages)
    checks.append((f"heaviest page under 16 KB ({heaviest[1]} = {heaviest[0]/1024:.1f} KB)",
                   heaviest[0] < 16 * 1024))
    # The stylesheet is served once and cached, so a page is now mostly content.
    # If this regresses it means something started inlining bytes again.
    checks.append((f"mean page under 8 KB ({mean/1024:.1f} KB)", mean < 8 * 1024))

    # --- the stylesheet, served once rather than inlined fifteen times -----
    from app.views import CSS_HASH, CSS_URL
    sheet = c.get(CSS_URL)
    css = sheet.get_data(as_text=True)
    checks += [
        ("stylesheet is served as a cacheable file",
         sheet.status_code == 200 and sheet.mimetype == "text/css"),
        ("it is cached hard, since the URL carries its hash",
         "immutable" in sheet.headers.get("Cache-Control", "")),
        ("a stale hash is not served", c.get("/s/000000000000.css").status_code == 404),
        ("every page links it", all(CSS_URL in d for d in pages.values())),
        ("no page inlines a stylesheet any more",
         not any("<style>" in d for d in pages.values())),
    ]
    checks += [
        ("CSS: has a small-screen breakpoint", "@media (max-width:560px)" in css),
        ("CSS: no fixed px width on containers",
         not re.search(r"\.wrap\{[^}]*[^-]width:\s*\d+px", css)),
        ("CSS: wide content can scroll horizontally", "overflow-x:auto" in css),
        ("CSS: reduced-motion respected or no animation",
         "prefers-reduced-motion" in css or "animation" not in css),
    ]

    # --- screen reader / semantics ---------------------------------------
    start = pages["/upload"]
    inputs = re.findall(r'<input[^>]*id="([^"]+)"', start)
    labels = re.findall(r'<label[^>]*for="([^"]+)"', start)
    checks += [
        ("start: every input has a matching label",
         bool(inputs) and all(i in labels for i in inputs)),
        ("start: form declares multipart encoding",
         'enctype="multipart/form-data"' in start),
        ("start: password field is type=password",
         'id="password"' in start and 'type="password"' in start),
    ]
    for name, doc in pages.items():
        hs = headings(doc)
        no_skip = all(b - a <= 1 for a, b in zip(hs, hs[1:]) if b > a)
        checks += [
            (f"{name}: exactly one <h1>", hs.count(1) == 1),
            (f"{name}: no heading level skipped", no_skip),
            (f"{name}: declares lang", '<html lang="en">' in doc),
            (f"{name}: has a <title>", "<title>" in doc),
        ]

    # --- status is never conveyed by colour alone ------------------------
    checks += [
        ("/result: blocking findings carry words, not just a red bar",
         "rejected today" in res_txt),
        ("/result: ingest steps carry OK/! text markers",
         "OK" in res_txt or "!" in res_txt),
    ]

    print("=" * 72)
    print("  front-end assertions")
    failures = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    _s.exit(main())
