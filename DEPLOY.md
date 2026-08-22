# Deploying Vested

The submission needs a **live demo link that works without requesting access**.
Judges do not clone repositories.

## Run it locally

```bash
pip install -r requirements.txt
python app/server.py          # http://127.0.0.1:5000
```

## Turn on the model backend

Without a key the app runs on `OfflineBackend` — deterministic rule tables. It
works, but no OpenAI model is involved, which does not satisfy the hackathon
requirement.

```bash
export OPENAI_API_KEY=sk-...
python app/models.py          # must print "backend: openai" and ALL PASS
```

**Do this before anything else.** `OpenAIBackend` has never made a live call.
The self-test is the only thing that will prove the model id, the strict
JSON-schema call, and the error handling actually work against the real API.
Code that has never executed is not working code.

Optional overrides:

```bash
export VESTED_MODEL=gpt-5     # text + classification
```

## Deploy to Cloud Run (recommended)

Builds remotely via Cloud Build — **no local Docker daemon needed**.

```bash
gcloud config set project YOUR_PROJECT
export OPENAI_API_KEY=sk-...        # optional; omit to run offline
./deploy-cloudrun.sh
```

Region defaults to `asia-south1` (Mumbai). Override with `REGION=` or `SERVICE=`.

The script prints the public URL and curls `/healthz` to confirm it is live.

### Session model — why `--max-instances=1`

Sessions are process-local by design: nothing a member uploads should outlive
their visit, so there is no database and nothing to breach. The cost is that a
session cannot survive being routed to a different process.

Cloud Run autoscales across **instances**, so with default settings a member's
second request can land on an instance that has never seen their upload, and
they get the "session ended" page mid-journey. Two settings prevent that:

- `--max-instances 1` — only ever one instance
- `--session-affinity` — pins a client to it

This is correct for a demo and honest about its ceiling: it serves one instance
worth of traffic. Scaling past that needs either a shared session store — which
means deciding where people's tax documents live, a privacy decision rather than
a technical one — or rendering the whole result as a single stateless page.

## Other hosts

Three ways, all ready. Pick whichever you already have.

**Docker** — the most portable:

```bash
docker build -t vested .
docker run -p 8080:8080 -e OPENAI_API_KEY=sk-... vested
```

**Procfile hosts** (Render, Railway, Fly, Heroku): push the repo. `Procfile` and
`runtime.txt` are in place; set `OPENAI_API_KEY` in the host's environment.

**On Windows, gunicorn will not run** — it needs `fcntl`, which is POSIX-only. Use waitress locally, or the Docker image (Linux):

```bash
pip install waitress
waitress-serve --port=5000 --call app.server:create_app
```

**Anything running gunicorn (Linux/macOS):**

```bash
gunicorn "app.server:create_app()" --bind 0.0.0.0:$PORT --workers 2 --timeout 60
```

`GET /status` returns the live status, which backend is active, and the session
count — use it as the host's health check.

## Before you send the link

- [ ] `python app/models.py` prints **backend: openai**, ALL PASS
- [ ] `/status` reports `"backend": "openai"` on the deployed instance
- [ ] the link opens in a private window with no login
- [ ] the sample record runs end to end
- [ ] a **real** Form 26AS uploads and parses
- [ ] HTTPS is on — people are uploading tax documents

## Operational notes

**Nothing is written to disk.** Uploads are read into memory, converted, and
dropped. Analyses live in a process-local dictionary keyed by a random token and
expire after 30 minutes.

Two consequences worth knowing before you scale it:

- **Sessions do not survive a restart, and do not work across workers.** With
  `--workers 2` a member can be routed to a worker that does not hold their
  session and will see the "session ended" page. For a demo, run
  `--workers 1`; for real use, this needs sticky sessions or a shared store —
  and a shared store means deciding where those documents live, which is a
  privacy decision, not a technical one.
- **Memory is the limit.** Each session holds one parsed analysis. The 30-minute
  expiry bounds it, but there is no cap on concurrent sessions.

## What is deliberately absent

- No database, no object storage, no queue.
- No logging of filenames, document content, or extracted text.
- No analytics.
- No outbound call to any government system. The generated letters are shown to
  the member to file themselves; nothing is submitted anywhere.
