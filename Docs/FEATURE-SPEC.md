# Vested — Feature Specification

**Build What Moves India** · Independent hackathon prototype
Status: engine complete, upload and deployment ready, two external dependencies open (see §9)

---

## 1. Problem

Roughly **one in five** EPF claims is rejected — about **174 lakh of 796 lakh claims in 2024-25** (~22%, down from 29% in 2021-22 but on far higher volume), against **~30 crore UAN accounts**. EPFO cites a **sub-1%** rate, which counts office-level rejections after auto-settlement rather than claims filed.

EPFO 3.0 (January 2026) automated the easy majority — 48% of claims now go in without employer involvement, 44% of transfers are automatic. **The residual failures concentrate in three fields: date of joining, date of exit, and overlapping service.**

The structural problem:

> A member cannot self-correct a wrong date of joining, or an already-wrong exit date. Only the employer can — a company that may have dissolved, ignores the request, or has no reason to help. **A person's own savings are gated on the data hygiene of every employer they have ever had.**

Separately, **₹9,330 crore** sits in inoperative EPF accounts — money belonging to people who changed jobs before UAN linkage and never transferred the balance.

### 1.1 The insight this product is built on

Form 26AS and AIS, on the Income Tax portal, contain **TDS by employer, month by month, with each employer's TAN**. That is an independent, government-held, *citizen-accessible* record of exactly when a person worked where.

**Income Tax records can prove the EPFO service record wrong.**

No inter-departmental data-sharing agreement is required, because **the citizen is the consent bridge** — they download their own records. This is the property that makes the product buildable today rather than hypothetical.

---

## 2. Users

| User | Situation | What they need |
|---|---|---|
| **Rejected claimant** | Filed, was rejected with an opaque reason | To know *which* field is wrong and how to fix it |
| **Blocked transferor** | Auto-transfer fails with "Date of Joining overlaps with previous employer" | The root cause, and a correction the employer will actually act on |
| **Pre-filer** | About to claim, wants to avoid a 20-day rejection cycle | A pre-flight check |
| **Job-changer** | Worked somewhere pre-UAN and forgot | To discover and recover an orphaned account |

**Design assumptions about all of them:** may be on a mobile device, on a slow connection, with limited digital confidence, and anxious because money is involved. Not necessarily comfortable in English.

---

## 3. Feature inventory

### F1 — Document ingestion
Accepts **PDF**, **`.txt`** (the TRACES text export), and **`.zip`** (TRACES delivers the text export zipped). Password field for the DOB-locked Form 26AS.

Documents are identified **by content, not by which upload box was used**. A member who puts all four files in one box gets the same result.

**Privacy guarantee:** nothing is written to disk at any point. Bytes are read into memory, converted, dropped. No filename, content, or derived text is logged.

### F2 — Arithmetic verification
Extracted Form 26AS transaction rows must reconcile to the deductor summary row. Extractions that fail arithmetic are **rejected and retried, never passed downstream**.

*"The model proposes, the checker disposes."*

### F3 — Person-name matching across documents
Resolves the member's name as each document spells it — Aadhaar in Devanagari, PAN in Latin, EPFO abbreviated, bank truncated — and decides whether they are one person.

Reports the **canonical spelling**: the form every other document agrees with, which is what to standardise on. Name mismatch is a leading rejection cause, and the UAN–ABHA linkage auto-rejects mismatches as suspected identity fraud.

### F4 — Employer entity resolution
Links the same employer across a Form 26AS deductor name, an EPF establishment name, and a mangled bank narration — while refusing to merge genuinely different legal entities that share a brand prefix (`Infosys Limited` vs `Infosys BPM Limited`).

### F5 — Salary credit detection
Classifies bank narrations, separating salary credits from interest, rent and transfers, and attributes each to an employer. **A credit that cannot be confidently attributed is dropped rather than guessed.**

### F6 — Timeline reconciliation
The core. Reconciles heterogeneous, multi-granularity evidence against what EPFO asserts, and enumerates contradictions ranked by claim-blocking impact.

Detects seven defect classes:

| Kind | Meaning |
|---|---|
| `MISSING_EXIT` | No exit date recorded; EPFO reads the job as ongoing |
| `EXIT_TOO_EARLY` | Independent evidence of employment after the recorded exit |
| `JOIN_SUSPECT` | Recorded start precedes any evidence of being paid |
| `SERVICE_OVERLAP` | Two employments appear concurrent — why the transfer fails now |
| `CORRECTION_CONFLICT` | The proposed fix would itself be rejected |
| `TRAILING_PAYOUT` | Post-exit TDS that is a settlement, not continued employment |
| `ORPHAN_ACCOUNT` | Employment evidence with no linked member ID |

### F7 — Correction routing
Maps each defect to the pathway that can actually fix it, grounded in published EPFO rules — self-service Mark Exit, Digital Joint Declaration, EPFiGMS grievance, or RTI. **The wrong pathway wastes weeks.**

### F8 — Evidence-backed document generation
Drafts the Joint Declaration, evidence annexure, and trace request. Every factual assertion carries a pointer to the extracted field supporting it.

### F9 — Claim gate
Re-reads the **rendered document**, independently extracts every factual token, and requires each to resolve to a ledger entry in the correct employer scope.

Four blocking conditions: an invented value; a real value attributed to the wrong employer; speculative phrasing in a legal filing; assertions with no annexure.

**The gate does not trust the renderer's account of itself.** It verifies the artifact, not the intent.

### F10 — Orphan account recovery
Resolves the employer to a 15-character establishment code, estimates the balance as a **clearly-labelled range**, and issues an ordered recovery plan: trace the member ID → check payslips first → file the transfer claim → escalate by RTI.

**Silence when there is no money.** EPF coverage is not universal. An employer absent from the EPF register returns `UNLIKELY`, generates **no plan and no estimate**, and says so.

### F11 — Plain-language interface
No engine vocabulary reaches the screen. `EXIT_TOO_EARLY` renders as *"recorded the wrong leaving date."* Findings carry Hindi alongside English.

---

## 4. User journey

```
Start  →  Upload 3–4 documents (or run the sample)
       →  Ingest report: what was read, what reconciled, names matched
       →  Verdict: would this claim be rejected today?
       →  Findings, ranked, in plain language
       →  Per finding: the evidence, the fix, the route, the drafted letter
       →  Orphan accounts: estimate, why we think it exists, how to recover it
```

Every step works **without JavaScript**, and remains readable **without CSS**.

---

## 5. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Identify document type from content, not upload field |
| FR-2 | Reject arithmetically inconsistent extractions |
| FR-3 | Never merge two different people's records |
| FR-4 | Never merge two different legal entities |
| FR-5 | Every contradiction carries a proposed fix and a correction route |
| FR-6 | Never emit a document containing an unsupported fact |
| FR-7 | Never promise money where EPF coverage is absent |
| FR-8 | Never file a correction that would itself be rejected |
| FR-9 | Distinguish settlement payouts from continued employment |
| FR-10 | Report the canonical name spelling to standardise on |

---

## 6. Non-functional requirements

**Bandwidth.** Every page under 6 KB. System font stack — nothing downloaded before text renders. No client framework, no build step.

**Accessibility.** Semantic HTML; usable with CSS disabled; no JavaScript dependency; 18px base type; high contrast; large touch targets; one decision per screen.

**Language.** Plain-language rendering of every engine concept, Hindi alongside English on findings.

**Privacy.** No disk writes. No database. No logging of filenames, content, or extracted text. Sessions in memory, expiring in 30 minutes. No outbound call to any government system.

**Auditability.** Every decision traceable to a named source document and row. The reconciliation core is deterministic *by design*, so a member can contest a specific inference.

---

## 7. Rules compliance

| Rule | How it is met |
|---|---|
| Built with Codex | **Yes.** Codex wrote most of this code; the git history attributes it commit by commit |
| Powered by an OpenAI model | **Deliberately declined at runtime.** The prototype ships local-only and fully deterministic — see §8.1 |
| No live government system contact | Nothing is submitted anywhere; letters are handed to the member to file |
| Mock or synthetic data only | Sample record fully synthetic; uploaded documents never stored |
| No real Aadhaar, PAN, OTPs, payment details | None collected; no identifier is persisted |
| Must not appear official or endorsed | Independent-prototype banner on every page |
| No government logos implying approval | None used |
| Designed for mobile, slow connections, low digital literacy | See §6 |

---

## 8. Explicitly out of scope

### 8.1 No model, by choice

The prototype runs entirely on local rules. `OpenAIBackend` exists as a working
extension point but **no key is configured and it has never executed**.

This is a decision, not an omission, and it buys three things:

- **A privacy claim that is absolute rather than qualified.** Nothing a member
  uploads leaves the server. Not "is not stored" — does not leave.
- **Determinism.** Every result is reproducible from the same documents. Nothing
  depends on a remote service, a model version, or a rate limit.
- **Zero cost and zero latency**, which matters for a page that has to work on a
  slow connection.

What it costs: **scripts other than Devanagari are unsupported** (the offline
transliteration table covers one script), and **scanned or photographed
documents are rejected** rather than read. Both are disclosed on-screen.

The position on the hackathon rules is stated plainly. Of *"built with Codex or
powered by an OpenAI model"*, the **first branch is satisfied and the second is
declined**. Codex wrote most of this code and the git history attributes it
commit by commit; no OpenAI model runs at inference time, which is the trade
made in favour of an unqualified privacy claim.

### 8.2 Other exclusions

- **Submission to EPFO.** No API exists, and the rules forbid touching live systems. Letters are generated for the member to file themselves.
- **Storing anything.** No accounts, no history, no saved documents.
- **Deciding eligibility.** The engine proposes corrections; it never denies a claim.
- **Scanned documents.** Image-only PDFs are rejected with guidance to re-download from the portal.
- **Compelling employer action.** The product makes the request trivial and evidenced. It cannot force anyone to act.

---

## 9. Known limitations

**Stated on-screen and on stage, not buried.**

1. **Form 26AS misses sub-TDS-threshold earners** — often the lowest paid, who need their PF most urgently. Mitigation: the EPF passbook alone still reveals overlaps and gaps; 26AS is a corroboration *upgrade*, not the floor. Verified by test (`core/reconcile.py`, sub-TDS scenario).
2. **The employer remains the gatekeeper** for DOJ and overlap corrections.
3. **The balance estimate is a wide band.** PF accrues on basic pay; 26AS reports gross. Assumption stated on its face.
4. **The establishment directory is mocked** — four entries. Real EPFO establishment lookup is not built.
5. **Sessions do not survive restart or span workers.** Run `--workers 1` for the demo.

### Open dependency

| Item | Status |
|---|---|
| A real Form 26AS | **Not supplied.** Every test runs on format-accurate fixtures written by the team. |

This gates the claim that the system finds defects in *real* records. Everything buildable without it is built and tested.
