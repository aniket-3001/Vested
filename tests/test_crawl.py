"""
Every reachable page, on every evidence combination.

This suite exists because three account pages returned HTTP 500 on the first
real record, and a fourth page returned an empty body. Every one was the same
root cause - a live EPF passbook carries no date of joining, so `doj` was None
and `.strftime()` threw - and every one was invisible to tests that only ever
built an Analysis object and inspected its fields.

A page that 500s is worse than a wrong number: the member sees nothing, and has
no idea whether their claim is safe.

Run:  python tests/test_crawl.py
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import io
import re

import app.engine as E
from app.server import create_app

# Danger phrases: things no page may ever say, whatever it was given.
FORBIDDEN = ["Traceback", "Internal Server Error", "could not make sense of"]


def start(client, files):
    """Upload and return the session token."""
    if not files:
        return "sample"
    resp = client.post("/analyse?s=sample", data={"passbook": [
        (io.BytesIO(t.encode()), f"f{i}.txt") for i, t in enumerate(files)]},
        content_type="multipart/form-data")
    m = re.search(r"s=([A-Za-z0-9_-]+)", resp.headers.get("Location", ""))
    return m.group(1) if m else None


def crawl(client, token):
    """Follow every internal link. Returns (pages_visited, problems)."""
    seen, queue, bad = set(), [f"/home?s={token}"], []
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        r = client.get(url)
        body = r.get_data(as_text=True)
        path = url.split("?")[0]
        if r.status_code != 200:
            bad.append(f"{path} -> HTTP {r.status_code}")
            continue
        if len(body) < 400:
            bad.append(f"{path} -> {len(body)} bytes")
        for phrase in FORBIDDEN:
            if phrase in body:
                bad.append(f"{path} -> says {phrase!r}")
        # An unchecked record must never be reported as clean, on any page.
        if token != "sample" and "Nothing is blocking" in body:
            bad.append(f"{path} -> claims nothing is blocking")
        for href in re.findall(r'href="(/[^"]*)"', body):
            # Stay inside the session under test. The sign-in page links into
            # the demo accounts, and one of those has a deliberately clean
            # record - wandering into it would make this crawl assert things
            # about a different member entirely.
            other = re.search(r"[?&]s=([A-Za-z0-9_-]+)", href)
            if other and other.group(1) != token:
                continue
            if href.split("?")[0] == "/login":
                continue
            if href not in seen:
                queue.append(href)
    return seen, bad


def main() -> int:
    app = create_app()
    checks = []

    combos = [
        ("full sample record", None),
        ("passbooks only", E.SAMPLE_PASSBOOKS),
        ("one passbook only", E.SAMPLE_PASSBOOKS[:1]),
        ("Form 26AS only", [E.SAMPLE_26AS]),
        ("26AS + passbooks, no history",
         [E.SAMPLE_26AS] + list(E.SAMPLE_PASSBOOKS)),
        ("passbooks + history, no 26AS",
         list(E.SAMPLE_PASSBOOKS) + [E.SAMPLE_SERVICE_HISTORY]),
    ]

    for label, files in combos:
        client = app.test_client()
        token = start(client, files)
        if token is None:
            checks.append((f"{label}: upload accepted", False))
            continue
        seen, bad = crawl(client, token)
        checks.append((f"{label}: {len(seen)} pages, none broken", not bad))
        for problem in bad[:4]:
            checks.append((f"    {problem}", False))

    print("=" * 70)
    print("  every reachable page, on every evidence combination")
    failures = 0
    for name, ok in checks:
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        failures += not ok
    print(f"\n  {len(checks)} checks · RESULT: "
          f"{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    print("=" * 70)
    return 1 if failures else 0


if __name__ == "__main__":
    _s.exit(main())
