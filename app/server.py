"""
Vested - web layer.

Deliberately thin. Every decision shown to the user is made in engine.py, which
delegates to the modules the test suite exercises. Nothing is reasoned about here.

Uploaded documents are held in memory for the length of one session and are
never written to disk. Sessions expire; there is no database.

Local:       python app/server.py
Production:  waitress-serve --port=$PORT --call app.server:create_app
             gunicorn "app.server:create_app()"
"""

from __future__ import annotations

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import os
import secrets
import sys
import time
from pathlib import Path


from flask import Flask, abort, redirect, request  # noqa: E402

from app import demo, manage, views
from app.engine import analyse, extract_names  # noqa: E402
from app.ingest import sort_uploads  # noqa: E402

SESSION_TTL = 30 * 60          # seconds
MAX_CONTENT = 24 * 1024 * 1024  # total upload size per request

# token -> (expires_at, Analysis). Memory only, by design: nothing a member
# uploads should outlive their visit, and there is nothing here to breach.
_sessions: dict[str, tuple[float, object]] = {}

# The sample analysis is deterministic and contains no personal data, so it is
# computed once and shared.
_sample = None


def _reap() -> None:
    now = time.time()
    for k in [k for k, (exp, _) in _sessions.items() if exp < now]:
        _sessions.pop(k, None)


def _store(a, docs: dict | None = None, token: str | None = None) -> str:
    """
    Keep the analysis, and the documents it was built from.

    The documents are held so that a member who later types in their service
    history can have the whole record re-reconciled against it, rather than
    being told to upload everything again. Same memory-only lifetime, same
    expiry - nothing is written to disk.
    """
    _reap()
    token = token or secrets.token_urlsafe(16)
    a.docs = docs if docs is not None else getattr(a, "docs", None)
    _sessions[token] = (time.time() + SESSION_TTL, a)
    return token


def _load(token: str | None):
    global _sample
    if not token or token == "sample":
        if _sample is None:
            _sample = analyse()
        return _sample
    # Demo accounts are addressed by UAN rather than a session token. They are
    # synthetic and deterministic, so they need no expiry and survive a restart -
    # which matters when a judge opens a link an hour after reading about it.
    if token in demo.ACCOUNTS:
        return demo.build(token)
    _reap()
    entry = _sessions.get(token)
    if entry is None:
        return None
    return entry[1]


def _token() -> str:
    return request.args.get("s", "sample")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT

    @app.get("/s/<name>.css")
    def stylesheet(name: str):
        # Content-hashed URL, so this can be cached hard and still never go
        # stale across a redeploy.
        if name != views.CSS_HASH:
            abort(404)
        return app.response_class(
            views.CSS, mimetype="text/css",
            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/")
    def index():
        return redirect("/login", code=302)

    @app.get("/login")
    def login():
        return views.page_login()

    @app.post("/login")
    def do_login():
        uan = demo.authenticate(request.form.get("uan", ""),
                                request.form.get("password", ""))
        if uan is None:
            return views.page_login("That UAN and password do not match. The "
                                    "working credentials are listed below."), 401
        return redirect(f"/home?s={uan}", code=303)

    @app.get("/upload")
    def start():
        return views.page_start()

    @app.post("/analyse")
    def run():
        if request.form.get("mode") == "sample":
            return redirect("/home?s=sample", code=303)

        files = []
        for key in ("f26as", "passbook", "history", "bank"):
            for fs in request.files.getlist(key):
                if fs and fs.filename:
                    files.append((fs.filename, fs.read()))
        if not files:
            return views.page_upload_problem(
                [], ["Form 26AS", "PF passbook", "service history"],
                "No files were selected.")

        sorted_up = sort_uploads(files, request.form.get("password") or None)
        f = sorted_up["found"]
        if sorted_up["missing"]:
            return views.page_upload_problem(
                sorted_up["report"], sorted_up["missing"], None)

        try:
            a = analyse(
                text_26as=f["26as"] or "",
                passbooks=f["passbook"] or [],
                service_history=f["service_history"] or "",
                bank=f["bank"] or "",
                names=extract_names(f),
            )
            a.reduced = sorted_up.get("reduced", [])
        except Exception:
            # Never surface a stack trace, and never log document content.
            return views.page_upload_problem(
                sorted_up["report"], [],
                "Your documents were read, but we could not make sense of the "
                "layout. This usually means a format we have not seen yet.")
        return redirect(f"/home?s={_store(a, docs=dict(f))}", code=303)

    def _need():
        """Load the session or hand back the expired page."""
        a = _load(_token())
        return a, (None if a else (views.page_expired(), 410))

    @app.get("/home")
    def home():
        a, gone = _need()
        return gone or views.page_home(a, _token())

    @app.get("/record")
    @app.get("/result")            # earlier URL, kept working
    def record():
        a, gone = _need()
        return gone or views.page_result(a, _token())

    @app.get("/accounts")
    def accounts():
        a, gone = _need()
        return gone or views.page_accounts(a, _token())

    @app.get("/account/<member_id>")
    def account(member_id: str):
        a, gone = _need()
        return gone or views.page_account(a, member_id, _token())

    @app.get("/fix/<key>")
    @app.get("/finding/<key>")     # earlier URL, kept working
    def fix(key: str):
        a, gone = _need()
        return gone or views.page_finding(a, key, _token())

    @app.get("/recover/<tan>")
    @app.get("/orphan/<tan>")      # earlier URL, kept working
    def recover(tan: str):
        a, gone = _need()
        return gone or views.page_orphan(a, tan, _token())

    @app.get("/profile")
    def profile():
        a, gone = _need()
        return gone or views.page_profile(a, _token())

    @app.get("/pension")
    def pension():
        a, gone = _need()
        return gone or views.page_pension(a, _token())

    @app.get("/withdraw")
    def withdraw():
        a, gone = _need()
        return gone or views.page_withdraw(a, _token())

    # The half of the member portal that does things rather than showing them.
    @app.get("/manage")
    def manage_hub():
        a, gone = _need()
        return gone or manage.page_manage(a, _token())

    @app.get("/kyc")
    def kyc():
        a, gone = _need()
        return gone or manage.page_kyc(a, _token())

    @app.get("/exit")
    def mark_exit():
        a, gone = _need()
        return gone or manage.page_exit(a, _token())

    @app.get("/nomination")
    def nomination():
        a, gone = _need()
        return gone or manage.page_nomination(a, _token())

    @app.get("/transfer")
    def transfer():
        a, gone = _need()
        return gone or manage.page_transfer(a, _token())

    @app.get("/uan-card")
    def uan_card():
        a, gone = _need()
        return gone or manage.page_uan_card(a, _token())

    @app.get("/contact")
    def contact():
        a, gone = _need()
        return gone or manage.page_contact(a, _token())

    @app.get("/history")
    def history():
        a, gone = _need()
        return gone or manage.page_history(a, _token())

    @app.post("/history")
    def save_history():
        a, gone = _need()
        if gone:
            return gone
        tok = _token()
        accounts = [ac for ac in a.accounts if not ac.orphan]
        rows, errors = manage.read_history_form(request.form, accounts)
        if errors:
            return manage.page_history(a, tok, errors, request.form), 400

        # Re-reconcile the whole record against the dates just typed. The demo
        # accounts are shared and deterministic, so a member editing one must
        # get their own session rather than mutating what everyone else sees.
        docs = getattr(a, "docs", None) or {}
        try:
            fresh = analyse(
                text_26as=docs.get("26as") or "",
                passbooks=docs.get("passbook") or [],
                service_history=manage.build_history_text(rows),
                bank=docs.get("bank") or "",
                names=extract_names(docs) if docs else None,
            )
        except Exception:
            return manage.page_history(
                a, tok, ["Those dates could not be reconciled against your "
                         "documents. Check them and try again."],
                request.form), 400

        fresh.reduced = [r for r in getattr(a, "reduced", [])
                         if "service history" not in r.lower()]
        fresh.history_typed = True
        own = None if (tok == "sample" or tok in demo.ACCOUNTS) else tok
        return redirect(f"/record?s={_store(fresh, docs=docs, token=own)}", code=303)

    @app.get("/privacy")
    def privacy():
        a = _load(_token())
        return views.page_privacy(a, _token())

    @app.get("/claim")
    def claim():
        a, gone = _need()
        return gone or views.page_claim(a, _token())

    @app.get("/track")
    def track():
        a, gone = _need()
        return gone or views.page_track(a, _token())

    # NOTE: /healthz is intercepted upstream on Cloud Run and never reaches the
    # container. /status is the real endpoint; /healthz kept for other hosts.
    @app.get("/status")
    @app.get("/healthz")
    def healthz():
        a = _load("sample")
        return {
            "ok": True,
            "backend": a.backend,
            "status": a.result["claim_status"],
            "blocking": a.result["blocking_count"],
            "sessions": len(_sessions),
        }

    @app.errorhandler(413)
    def too_large(_):
        return views.page_upload_problem(
            [], [], "Those files are too large. Download them again from the "
                    "portal rather than scanning printouts."), 413

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
