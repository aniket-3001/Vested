# PF Sahi Hai

**Check your PF record before you claim.**

[![CI and deploy](https://github.com/aniket-3001/pf-sahi-hai/actions/workflows/deploy.yml/badge.svg)](https://github.com/aniket-3001/pf-sahi-hai/actions/workflows/deploy.yml)

**[Live →](https://pf-sahi-hai-251148844884.asia-south1.run.app)**

Reconstructs an EPF member's employment history from records they already own,
finds the specific contradiction that will freeze their claim, and generates an
evidenced correction.

Built for **Build What Moves India**. An independent hackathon prototype — not
affiliated with or endorsed by EPFO or any government body.

---

## The problem

Roughly one in five EPF claims is rejected — about 174 lakh of 796 lakh in
2024-25. (EPFO cites sub-1%, counting office-level rejections after
auto-settlement rather than claims filed.) The residual failures concentrate in
three fields: **date of joining, date of exit, and overlapping service.**

A member can now self-mark a *missing* exit date. But an already-wrong exit date,
a wrong joining date, or an overlap is still correctable only by the employer —
and the employer may be dissolved.

## The insight

**Form 26AS, on the Income Tax portal, records TDS by employer, month by month,
with each employer's TAN.**

Income tax records can prove the EPFO service record wrong. No data-sharing
agreement is required, because the citizen is the consent bridge — they download
both records themselves. That is the property that makes this buildable today
rather than hypothetical.

## The architecture

> Models at the edges, where language is messy.
> A deterministic solver at the core, where the answer must be auditable.

The output is a document a member **signs and submits to a government office**.
If it is disputed, they must be able to say *"this inference is wrong, and here
is the step where it went wrong."*

A model cannot be cross-examined. A weighted constraint system can. So the
boundary is drawn on contestability:

| Layer | May use a model | Why |
|---|---|---|
| Ingestion, normalisation, classification | **Yes** | Language variance, where rules are weak |
| Reconciliation, ranking, routing | **No** | Every step must be arguable |
| Generation | **Yes, behind a gate** | Prose is a language task; facts are not |

## Four guarantees, enforced by code

1. **The system can propose. It can never deny.** `assert_no_denial_path()`
   fails the build if any contradiction lacks a fix route.
2. **Unsupported facts cannot reach a signed document.** The claim gate re-reads
   the rendered artifact rather than trusting the renderer's account of itself.
3. **Estimates cannot become facts.** `Estimate` is a separate type from `Fact`,
   enforced at the type level.
4. **Precision over recall on every identity decision.** Merging two people's PF
   records is catastrophic; a missed link costs one document request.

## Running it

```bash
pip install -r requirements.txt
python app/server.py            # http://127.0.0.1:5000

pip install -r requirements-dev.txt
for f in tests/test_*.py; do python "$f"; done
```

## Status

```
9,493 lines of Python · 15 modules · 443 checks across 9 suites — all passing
Every page under 6 KB · no JavaScript required · readable without CSS
```

**Runs local-only by choice.** No model, no API key, no network call at
inference time. Every result is deterministic, and nothing a member uploads
leaves the server. `OpenAIBackend` is a working extension point that has never
executed.

## Documentation

| Document | What it covers |
|---|---|
| [FEATURE-SPEC](Docs/FEATURE-SPEC.md) | Problem, users, features, journeys, requirements, rules compliance, limitations |
| [ARCHITECTURE](Docs/ARCHITECTURE.md) | The models-at-edges / solver-at-core thesis, component map, safety guarantees |
| [LLD](Docs/LLD.md) | Module-by-module reference — type contracts, the solver, name matching, the gate |
| [BUILD-LOG](Docs/BUILD-LOG.md) | Two rejected ideas, research findings, the bugs failing tests caught, what is still open |
| [DEPLOY](DEPLOY.md) | Local, Docker, Cloud Run, and the CI pipeline |
