"""
PF Sahi Hai - the web layer. Deliberately thin.

Every decision shown to a member is made in engine.py or solver.py, both of
which the test suite exercises directly. Nothing is reasoned about here.

Uploaded documents are held in memory for the length of one session and are
never written to disk. Sessions expire. There is no database.

    Local:       python app/server.py
    Production:  gunicorn "app.server:create_app()"
"""

from __future__ import annotations

import sys as _s
import pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent.parent))

import os
import secrets
import time

from flask import Flask, abort, redirect, request  # noqa: E402

from app import corrections, demo, history, portal, screens  # noqa: E402
from app import solver  # noqa: E402
from app.engine import TODAY, analyse, extract_names  # noqa: E402
from app.ingest import sort_uploads  # noqa: E402

SESSION_TTL = 30 * 60
MAX_CONTENT = 24 * 1024 * 1024

# token -> (expires_at, Analysis). Memory only, by design.
_sessions: dict[str, tuple[float, object]] = {}


def _reap() -> None:
    now = time.time()
    for k in [k for k, (exp, _) in _sessions.items() if exp < now]:
        _sessions.pop(k, None)


def _store(a, docs: dict | None = None, token: str | None = None) -> str:
    _reap()
    token = token or secrets.token_urlsafe(16)
    if docs is not None:
        a.docs = docs
    _sessions[token] = (time.time() + SESSION_TTL, a)
    return token


# The sample analysis is deterministic and holds no personal data, so it is
# computed once and shared.
_sample = None


def _load(token: str):
    # Demo accounts are synthetic and deterministic, so they need no expiry and
    # survive a restart - which matters when a judge opens the link an hour
    # after reading about it.
    global _sample
    if token in demo.ACCOUNTS:
        return demo.build(token)
    if token == "sample":
        if _sample is None:
            _sample = analyse()
            _sample.claim_history = demo.CLAIM_HISTORY.get("100999888777", [])
        return _sample
    _reap()
    entry = _sessions.get(token)
    return entry[1] if entry else None


def _clone_for_edit(a):
    """
    A private copy of a shared demo record.

    Demo accounts are deterministic and shared between visitors, so anything a
    member starts - a correction, a typed service history - has to land in
    their own session rather than mutating what everybody else sees.
    """
    import copy
    fresh = copy.copy(a)
    fresh.corrections = list(getattr(a, "corrections", None) or [])
    return fresh


def _token() -> str:
    return request.args.get("s", "sample")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT

    # ---- static ----------------------------------------------------------
    @app.get("/s/<name>.css")
    def stylesheet(name: str):
        if name != portal.CSS_HASH:
            abort(404)
        return app.response_class(
            portal.CSS, mimetype="text/css",
            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # ---- sign in ---------------------------------------------------------
    @app.get("/")
    def index():
        return redirect("/login", code=302)

    @app.get("/login")
    def login():
        return screens.page_login()

    @app.post("/login")
    def do_login():
        uan = demo.authenticate(request.form.get("uan", ""),
                                request.form.get("password", ""))
        if uan is None:
            return screens.page_login(
                "That UAN and password do not match."), 401
        return redirect(f"/home?s={uan}", code=303)

    # ---- upload ----------------------------------------------------------
    @app.get("/upload")
    def start():
        return screens.page_upload()

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
            return screens.page_upload("No files selected.")
        sorted_up = sort_uploads(files, request.form.get("password") or None)
        f = sorted_up["found"]
        try:
            a = analyse(
                text_26as=f["26as"] or "",
                passbooks=f["passbook"] or [],
                service_history=f["service_history"] or "",
                bank=f["bank"] or "",
                names=extract_names(f))
            a.reduced = sorted_up.get("reduced", [])
        except Exception:
            # Never surface a stack trace, never log document content.
            return screens.page_upload(
                "Those documents were read, but we could not make sense of "
                "the layout.")
        return redirect(f"/home?s={_store(a, docs=dict(f))}", code=303)

    # ---- session helper --------------------------------------------------
    def _need():
        a = _load(_token())
        return a, (None if a else (screens.page_expired(), 410))

    def simple(path, fn, **kw):
        """Register a GET page that needs a live session."""
        def view(_fn=fn, _kw=kw):
            a, gone = _need()
            return gone or _fn(a, _token(), **_kw)
        view.__name__ = "v" + path.replace("/", "_").replace("-", "_")
        app.add_url_rule(path, view_func=view)

    # ---- section landings ------------------------------------------------
    for _href in ("/view", "/manage", "/account", "/services"):
        def _section(_h=_href):
            a, gone = _need()
            return gone or screens.page_section(a, _token(), _h)
        _section.__name__ = "sec" + _href.replace("/", "_")
        app.add_url_rule(_href, view_func=_section)

    # ---- pages -----------------------------------------------------------
    simple("/home", screens.page_home)
    simple("/profile", screens.page_profile)
    simple("/uan-card", screens.page_uan_card)
    simple("/passbook-lite", screens.page_passbook_lite)
    simple("/passbook", screens.page_passbook)
    simple("/timeline", screens.page_timeline)
    simple("/kyc", screens.page_kyc)
    simple("/contact", screens.page_contact)
    simple("/nomination", screens.page_nomination)
    simple("/exit", screens.page_exit)
    simple("/corrections", screens.page_corrections)
    simple("/password", screens.page_password)
    simple("/notifications", screens.page_notifications)
    simple("/history", screens.page_history)
    simple("/claim", screens.page_claim)
    simple("/claim-10d", screens.page_claim_10d)
    simple("/transfer", screens.page_transfer)
    simple("/track", screens.page_track)
    simple("/track-old", screens.page_track_old)
    simple("/scheme-certificate", screens.page_scheme_cert)
    simple("/check", screens.page_check)
    simple("/why-rejected", screens.page_why)
    simple("/privacy", screens.page_privacy)
    simple("/print", screens.page_print)

    for _p2 in ("/pmvbry", "/pmvbry-flc", "/pmvbry-cert"):
        def _pm(_h=_p2):
            a, gone = _need()
            return gone or screens.page_pmvbry(a, _token(), _h)
        _pm.__name__ = "pm" + _p2.replace("/", "_").replace("-", "_")
        app.add_url_rule(_p2, view_func=_pm)

    @app.get("/recover/<tan>")
    def recover(tan: str):
        a, gone = _need()
        return gone or screens.page_recover(a, _token(), tan)

    # ---- joint declaration ----------------------------------------------
    @app.get("/joint-declaration")
    def jd():
        a, gone = _need()
        return gone or screens.page_joint_declaration(a, _token())

    @app.post("/joint-declaration")
    def jd_post():
        a, gone = _need()
        if gone:
            return gone
        tok = _token()
        mid = (request.form.get("mid") or "").strip()
        evidence = (request.form.get("doc") or "").strip()

        # An orphan reconstruction carries an empty member ID, so an empty mid
        # would match it and silently open a correction against a forgotten
        # account. Require a real one.
        rec = next((r for r in solver.reconstruct(a)
                    if mid and r.member_id == mid and r.exit_best), None)
        if rec is None:
            return screens.page_joint_declaration(a, tok), 400

        # The correction is checked against the record, never the document
        # against reality - see the note at the top of corrections.py.
        c = corrections.Correction(
            ref=corrections.new_ref(), member_id=mid, employer=rec.employer,
            field_name=("Date of Exit" if rec.verdict != "join_wrong"
                        else "Date of Joining"),
            current=(rec.asserted_doe if rec.verdict != "join_wrong"
                     else rec.asserted_doj),
            proposed=rec.exit_best, evidence=evidence,
            route="Digital Joint Declaration", started=TODAY,
            checks=corrections.check_correction(a, mid, rec.exit_best, evidence))

        # Demo accounts are shared, so a correction one visitor starts must not
        # appear for the next. Give them their own session, exactly as typing a
        # service history does.
        if tok == "sample" or tok in demo.ACCOUNTS:
            a = _clone_for_edit(a)
            tok = _store(a, docs=getattr(a, "docs", None))
        held = list(getattr(a, "corrections", None) or [])
        held = [x for x in held if x.member_id != mid] + [c]
        a.corrections = held
        return redirect(f"/correction/{c.ref}?s={tok}", code=303)

    @app.get("/correction/<ref>")
    def correction(ref: str):
        a, gone = _need()
        return gone or screens.page_correction(a, _token(), ref)

    @app.get("/outcome")
    def outcome():
        a, gone = _need()
        return gone or screens.page_outcome(a, _token())

    # ---- typing in the service history ----------------------------------
    @app.get("/history-entry")
    def hist_entry():
        a, gone = _need()
        return gone or screens.page_history_entry(a, _token())

    @app.post("/history-entry")
    def hist_save():
        a, gone = _need()
        if gone:
            return gone
        tok = _token()
        accounts = [ac for ac in a.accounts if not ac.orphan]
        rows, errors = history.read_history_form(request.form, accounts)
        if errors:
            return screens.page_history_entry(a, tok, errors, request.form), 400
        docs = getattr(a, "docs", None) or {}
        try:
            fresh = analyse(
                text_26as=docs.get("26as") or "",
                passbooks=docs.get("passbook") or [],
                service_history=history.build_history_text(rows),
                bank=docs.get("bank") or "",
                names=extract_names(docs) if docs else None)
        except Exception:
            return screens.page_history_entry(
                a, tok, ["Those dates could not be reconciled against your "
                         "documents."], request.form), 400
        fresh.history_typed = True
        fresh.claim_history = getattr(a, "claim_history", [])
        # A demo account is shared, so editing one must not mutate what every
        # other visitor sees. Give the editor their own session instead.
        own = None if (tok == "sample" or tok in demo.ACCOUNTS) else tok
        return redirect(f"/home?s={_store(fresh, docs=docs, token=own)}", code=303)

    # ---- health ----------------------------------------------------------
    # NOTE: /healthz is intercepted upstream on Cloud Run and never reaches the
    # container. /status is the real endpoint.
    @app.get("/status")
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "sessions": len(_sessions)}

    @app.errorhandler(413)
    def too_big(_e):
        return screens.page_upload("Those files are too large."), 413

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
