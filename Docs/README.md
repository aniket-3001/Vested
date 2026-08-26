# PF Sahi Hai — Documentation

**Check your PF record before you claim.**

Reconstructs a member's employment history from records they already own, finds the specific contradiction that will freeze their EPF claim, and generates the evidenced correction.

Built for **Build What Moves India**. Independent hackathon prototype — not affiliated with or endorsed by EPFO or any government body.

---

## The documents

| Document | What it covers |
|---|---|
| **[FEATURE-SPEC.md](FEATURE-SPEC.md)** | Problem, users, 11 features, journeys, functional and non-functional requirements, rules compliance, known limitations |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The models-at-edges / solver-at-core thesis, component map, data flow, model integration, four safety guarantees, deployment, architectural limits |
| **[LLD.md](LLD.md)** | Module-by-module reference — type contracts, the solver formalised, name-matching algorithm, claim gate, parsers, test inventory |
| **[BUILD-LOG.md](BUILD-LOG.md)** | How this got made: two rejected ideas and why, research findings, spike results, the five bugs failing tests caught, what is still open |

Operational instructions live in **[`../DEPLOY.md`](../DEPLOY.md)**.

---

## In one paragraph

Roughly one in five EPF claims is rejected — about 174 lakh of 796 lakh claims in 2024-25, against 30 crore accounts. (EPFO cites sub-1%; that counts office-level rejections after auto-settlement, not claims filed.) The residual failures concentrate in three fields: date of joining, date of exit, and overlapping service. A member can now self-mark a *missing* exit date, but an already-wrong date, a wrong date of joining, or an overlap can still only be corrected by the employer — and that employer may have dissolved. **Form 26AS, on the Income Tax portal, records TDS by employer month by month — which means a person's own tax records can prove the EPFO service record wrong.** No data-sharing agreement is required, because the citizen downloads both.

---

## The governing design decision

> **Models at the edges, where language is messy.
> A deterministic solver at the core, where the answer must be auditable.**

The output is a document someone signs and submits to a government office. If it is disputed, they must be able to say *"this inference is wrong, and here is the step where it went wrong."* A model cannot be cross-examined. A weighted constraint system can.

---

## Four guarantees, enforced by code

1. **The system can propose. It can never deny.** `assert_no_denial_path()` fails the build if any contradiction lacks a fix and a route.
2. **Unsupported facts cannot reach a signed document.** The claim gate re-reads the rendered artifact — it does not trust the renderer's account of itself.
3. **Estimates cannot become facts.** `Estimate` is a separate type from `Fact`, enforced at the type level.
4. **Precision over recall on every identity decision.** Merging two people's PF records is catastrophic; a missed link costs one document request.

---

## Running it

```bash
pip install -r requirements.txt
python app/server.py                  # http://127.0.0.1:5000

python app/models.py                  # model backend self-test
python core/reconcile.py    # any spike runs standalone
```

---

## Status

```
9,493 lines of Python · 15 modules · 443 checks across 9 suites — all passing
Every page under 6 KB · no JavaScript required · readable without CSS
```

**Runs local-only by choice.** No model, no API key, no network call. Every
result is deterministic and nothing a member uploads leaves the server. The
trade-offs are recorded in [FEATURE-SPEC §8.1](FEATURE-SPEC.md).

**One thing still gates the claim that this works on real records:** a real
Form 26AS. Every test runs on fixtures we wrote, defects included.
See [BUILD-LOG §9](BUILD-LOG.md).
