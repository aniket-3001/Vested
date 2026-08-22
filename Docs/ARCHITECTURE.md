# Vested — Architecture

---

## 1. The governing decision

> **Models at the edges, where language is messy.
> A deterministic solver at the core, where the answer must be auditable.**

This is not a stylistic preference. It follows from a legal requirement.

The output of this system is a document a member **signs and submits to a government office**. If EPFO or the member's ex-employer disputes it, the member has to be able to say *"this inference is wrong, and here is the specific step where it went wrong."*

A model cannot be cross-examined. A weighted constraint system can.

So the boundary is drawn on contestability:

| Layer | May use a model | Why |
|---|---|---|
| Ingestion, normalisation, classification | **Yes** | Language variance where rules are weak |
| Reconciliation, ranking, routing | **No** | Every step must be arguable |
| Generation | **Yes, behind a gate** | Prose is a language task; facts are not |

A second constraint keeps this honest: **every model call must have a deterministic fallback.** If one cannot be written, that call is doing reasoning that belongs in the solver. `OfflineBackend` is the enforcement mechanism, not a convenience.

---

## 2. System overview

```
┌── INPUT ────────────────────────────────────────────────┐
│  Form 26AS / AIS     PF passbook(s)                     │
│  Service History     Bank statement (optional)          │
│  PDF · TXT · ZIP — password-protected supported         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌── INGEST (app/ingest.py) ───────────────────────────────┐
│  bytes → text, in memory only, never to disk            │
│  type detected from CONTENT, not upload field           │
└──────────────────────┬──────────────────────────────────┘
                       │
┌── EDGE LAYER — models permitted ────────────────────────┐
│  parse_26as / parse_passbook / parse_service_history    │
│  verify_26as          ← arithmetic backstop             │
│  classify_narration   ← model: salary vs not            │
│  transliterate        ← model: Devanagari → Latin       │
│  score_pair           ← employer entity resolution      │
│  compare              ← person-name matching            │
└──────────────────────┬──────────────────────────────────┘
                       │  Observation[] + AssertedService[]
┌── CORE — NO models, by design ──────────────────────────┐
│  Reconciler.run()                                       │
│    support_windows → contradiction predicates           │
│    → corrected_timeline → severity ranking              │
│    → correction routing                                 │
│  assert_no_denial_path()   ← enforced invariant         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌── OUTPUT — gated ───────────────────────────────────────┐
│  render_joint_declaration / render_trace_request        │
│  claim_gate()  ← re-reads the ARTIFACT, not the intent  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌── PRESENTATION (app/views.py) ──────────────────────────┐
│  server-rendered HTML · no JS · no web fonts · <11 KB   │
│  engine vocabulary never reaches the screen             │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Components

| Module | Lines | Responsibility |
|---|---:|---|
| `app/ingest.py` | 173 | Bytes → text. PDF/TXT/ZIP, passwords, type detection |
| `app/models.py` | 307 | Model backend abstraction, OpenAI + offline, self-test |
| `app/name_match.py` | 237 | Person-name matching across scripts |
| `app/engine.py` | 526 | Orchestration. Contains no reasoning of its own |
| `app/views.py` | 517 | HTML rendering, plain-language translation |
| `app/server.py` | 163 | Routing, ephemeral sessions. 163 lines, no logic |
| `core/reconcile.py` | 611 | **The solver.** Contradiction detection |
| `core/entity.py` | 251 | Employer entity resolution |
| `core/parsers.py` | 444 | Document parsers + arithmetic verifier |
| `core/gate.py` | 297 | Evidence ledger + claim gate |
| `core/orphan.py` | 392 | Orphan assessment + recovery planning |
| `tools/schema_probe.py` | 234 | Privacy-safe probe for real documents |
| `tests/test_names.py` | 170 | Name-matching and model-contract tests |

**Note on layout.** `core/` holds the reasoning modules; `app/` holds ingestion, orchestration and the web layer. Each `core/` module carries its own self-test in `main()`, so `python core/reconcile.py` runs that module's suite. The code that ships is literally the code the tests exercise — there is no parallel "production" copy that can drift.

---

## 4. Data flow

**Evidence model.** Everything reduces to a point-in-time `Observation` that the member was employed by a resolved employer, plus what EPFO *asserts* via `AssertedService`. The asserted record is the artifact under test, and is therefore the **least trusted** source in the model.

| Source | Presence | Boundary | Granularity |
|---|---:|---:|---|
| `EPF_CONTRIB` | 0.95 | 0.35 | month |
| `TDS_26AS` | 0.90 | 0.70 | day |
| `BANK_SALARY` | 0.65 | 0.75 | day |
| `EPF_SERVICE` | 0.50 | 0.30 | day |

Sources are trusted separately for **presence** ("was this person employed here") and **boundary** ("is this exactly when it started or ended"). EPF contributions are excellent presence evidence but carry only wage-month granularity — which is why 26AS matters: the passbook proves someone was *there*; only day-granular evidence can move a *boundary*.

Confidence is **corroboration across distinct sources**, not volume within one:

```
confidence(e) = 1 − ∏ (1 − presence(s))   for each distinct source s
```

Ten payslips from one bank are one source. Three sources agreeing is evidence.

---

## 5. Model integration

Two implementations behind one `Backend` protocol, selected by the presence of `OPENAI_API_KEY`.

| Call | Purpose | Offline fallback |
|---|---|---|
| `transliterate` | Devanagari → Latin name | Rule table with context-sensitive anusvara |
| `classify_narration` | Salary vs interest/rent; employer hint | Keyword + noise-token heuristics |
| `draft` | Prose generation | Returns empty — gate tested adversarially instead |

OpenAI calls use **structured JSON-schema output with `strict: true`**. The model is asked to *normalise*, never to *decide*. It is never asked "are these the same person" or "is this claim valid."

`python app/models.py` exercises every call against its contract — six cases, all passing on the offline backend.

> **Current state: this build runs local-only, by choice.** No key is configured. `OpenAIBackend` is a working extension point that has never executed against the live API; its model id, strict-schema call shape and error handling are unverified.
>
> The gain is that every result is **deterministic and reproducible**, and the privacy claim is absolute rather than qualified: nothing a member uploads leaves the server. The cost is no support for non-Devanagari scripts and no reading of scanned documents. Both are disclosed on `/privacy`.

---

## 6. Safety architecture

Four guarantees, each enforced by code rather than convention.

### 6.1 The system can propose. It can never deny.

`assert_no_denial_path()` runs against every scenario in the suite and fails the build if any contradiction lacks a `proposed_fix` and a `correction_route`.

Automated welfare decisioning has a body count — the Dutch childcare benefits scandal, Robodebt. Both failed the same way: **an algorithm was given the power to deny.** Here the algorithm's only power is to accelerate a correction.

### 6.2 Unsupported facts cannot reach a signed document

The claim gate re-reads the rendered artifact and independently extracts every factual token, requiring each to resolve to a ledger entry **scoped to the correct employer**. A real member ID belonging to a *different* employer is blocked — the failure a naive "does this value exist in our data" check waves through.

### 6.3 Estimates cannot become facts

`Estimate` is a **separate type** from `Fact`, not a subclass. Facts are evidence-backed and may be filed; estimates are inferences shown only to the member. Enforced at the type level, because the gate rejects hedged language in filings and every estimate is inherently hedged.

### 6.4 Precision over recall on every identity decision

Merging two people's provident fund records, or two legal entities, is catastrophic and hard to unwind. Missing a link costs one extra document request. Both matchers are tuned accordingly, and both have zero false positives across their corpora.

---

## 7. Presentation architecture

Server-rendered HTML from plain Python functions. No template engine, no client framework, no build step, no web fonts.

This is a direct response to the brief's requirement to design for *"mobile devices, slower connections or limited digital experience"* — and it is demonstrable on stage by disabling JavaScript.

- Every page **under 11 KB**
- Works with **JS disabled**, readable with **CSS disabled**
- System font stack — nothing downloads before text renders
- **Engine vocabulary never reaches the screen.** `_finding_copy()` is the single translation point

---

## 8. Deployment

```
gunicorn "app.server:create_app()" --bind 0.0.0.0:$PORT --workers 1
```

`Dockerfile` (unprivileged user, healthcheck), `Procfile`, `runtime.txt`, `requirements.txt`, and `DEPLOY.md` are in place. `GET /healthz` reports status, active backend, and session count.

**Session store.** Process-local dict, random token, 30-minute TTL, reaped on access. Memory only, by design: nothing a member uploads should outlive their visit.

---

## 9. Known architectural limits

| Limit | Consequence | Resolution |
|---|---|---|
| Sessions are process-local | A member can hit a worker without their session | `--workers 1` for demo; sticky sessions or a shared store for real use |
| No cap on concurrent sessions | Memory is the bound | TTL limits it; needs an explicit cap |
| Establishment directory is mocked | Orphan resolution covers four employers | Integrate the EPFO establishment register |
| Parsers handle one format generation | Older assessment years may fail | Fixture per format variant |
| No vision path wired | Image-only PDFs rejected | `MODEL_VISION` is declared but unused |

**On the shared-store question:** it is not primarily a technical decision. A shared session store means choosing where people's tax documents live and for how long — a privacy decision that should be made deliberately, not as a side effect of scaling.
