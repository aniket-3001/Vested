# PF Sahi Hai — Low-Level Design

Module-by-module reference. Every signature below exists in the codebase.

---

## 1. Core types

```python
# core/reconcile.py

@dataclass(frozen=True)
class Observation:
    employer_key : str            # post-resolution identity
    when         : date           # point-in-time signal
    source       : str            # EPF_CONTRIB | TDS_26AS | BANK_SALARY | EPF_SERVICE
    note         : str = ""
    amount       : float | None = None   # drives the settlement heuristic

@dataclass(frozen=True)
class AssertedService:            # what EPFO claims — the artifact under test
    employer_key : str
    member_id    : str
    doj          : date
    doe          : date | None    # None => reads as still employed

@dataclass
class Contradiction:
    kind             : str
    employer_key     : str
    severity         : BLOCKING | DEGRADED | OPPORTUNITY
    detail           : str
    evidence         : list[str]
    proposed_fix     : str        # never empty — enforced
    correction_route : str        # never empty — enforced

@dataclass
class SupportWindow:
    employer_key  : str
    earliest      : date
    latest        : date
    sources       : set[str]
    observations  : list[Observation]
    def confidence(self) -> float   # corroboration across distinct sources
```

---

## 2. The solver — `Reconciler`

### 2.1 Formal statement

```
For employer e:
  E(e)  = independent observations, excluding EPF_SERVICE
  W(e)  = [ min t : t ∈ E(e) ,  max t : t ∈ E(e) ]      support window
  A(e)  = [ doj(e) , doe(e) or today ]                  asserted interval
  C(e)  = [ min(doj, min W) , max(doe, max W) ]         corrected interval

  confidence(e) = 1 − ∏ ( 1 − presence(s) )   over distinct sources s
```

### 2.2 Contradiction predicates

| Kind | Predicate | Severity |
|---|---|---|
| `MISSING_EXIT` | `doe = ⊥ ∧ (today − max W) ≥ 2 months` | BLOCKING |
| `EXIT_TOO_EARLY` | `max W > doe ∧ ¬settlement` | BLOCKING if ≥2 sources |
| `JOIN_SUSPECT` | `min W − doj > 1 month` | DEGRADED |
| `SERVICE_OVERLAP` | `∃ e₁,e₂ : A(e₁) ∩ A(e₂) ≠ ∅` | BLOCKING |
| `CORRECTION_CONFLICT` | `∃ e₁,e₂ : C(e₁) ∩ A(e₂) ≠ ∅` ∧ not already overlapping | DEGRADED |
| `TRAILING_PAYOUT` | see §2.3 | DEGRADED |
| `ORPHAN_ACCOUNT` | `E(e) ≠ ∅ ∧ no member_id for e` | OPPORTUNITY |

### 2.3 Settlement heuristic — `_looks_like_settlement`

Full-and-final settlements generate TDS **after** the real exit date. Reading that as "the exit date is wrong" would manufacture false disputes at scale.

The discriminator is provident fund itself: **employers do not remit PF on an F&F payout.**

```python
if any(o.source == "EPF_CONTRIB" for o in after):     return False  # genuinely employed
if len({month_key(o.when) for o in after}) > 2:       return False  # too long for a tail
median = median(prior amounts)
return any(abs(a − median) / median > 0.35 for a in tail)
```

All three conditions must hold. When they do, the engine **explicitly declines to file** on that basis.

### 2.4 Overlap detection — two timelines, two meanings

```python
_check_overlaps(intervals, basis)
```

| `basis` | Question answered |
|---|---|
| `"asserted"` | Why is EPFO refusing *right now*? |
| `"corrected"` | Would our proposed fix be rejected in turn? |

Without the second pass, the system confidently sends members to file paperwork that is doomed before submission. A `CORRECTION_CONFLICT` is suppressed when the same pair already produced a `SERVICE_OVERLAP` — otherwise it is the same defect reported twice.

### 2.5 Enforced invariant

```python
def assert_no_denial_path(result: dict) -> None:
    for c in result["contradictions"]:
        assert c["proposed_fix"]
        assert c["correction_route"]
```

Runs on every scenario. **The engine may propose a correction; it may never deny a claim.**

### 2.6 Correction routing

| Defect | Route | Rationale |
|---|---|---|
| `MISSING_EXIT`, ≥2 months stale | Self-service Mark Exit | Member can fix alone once contributions stop |
| `EXIT_TOO_EARLY` | Digital Joint Declaration | An already-wrong date cannot be self-corrected |
| `JOIN_SUSPECT` | Digital Joint Declaration | DOJ is employer-owned |
| `SERVICE_OVERLAP` | Joint Declaration on the wrong boundary | Fix the cause, not the symptom |
| `CORRECTION_CONFLICT` | Grievance | Needs resolving before anything is filed |
| `ORPHAN_ACCOUNT` | Transfer claim | Recovery, not correction |

---

## 3. Person-name matching — `app/name_match.py`

**Division of labour: the model normalises, the algorithm decides.**

### 3.1 Signature construction

```python
_strip_vowels_to_skeleton(word) -> str    # consonant skeleton
_vowel_signature(word)          -> str    # vowel-class sequence
_signature(word)                -> "SKELETON|VOWELCLASSES"
```

Indian name spelling varies enormously in **vowels** and barely at all in **consonant skeleton**.

```
RAHUL   → RHL|AU        SINGH   → SNGH|I
RAHOOL  → RHL|AU        SINHA   → SNH|IA
RAAHUL  → RHL|AU        IYER    → YR|II
```

Aspirate digraphs (`GH`, `SH`, `TH`, `CHH`, `KSH`…) are **single consonant units** — this is what separates `SINGH` (S-N-GH) from `SINHA` (S-N-H).

Equivalences applied first: `W→V`, `F→PH`, `Z→J`, `X→KS`, `Q→K`.

The vowel signature collapses **lengthening** (`OO→O`) and maps classes (`E/I→I`, `O/U→U`) but preserves **count** — which separates `JOSHI` (`UI`) from `JOSHUA` (`UUA`), where the consonant skeleton alone is identical.

### 3.2 Decision sequence — `compare()`

1. Normalise both: transliterate, uppercase, strip honorifics (`SHRI`, `SMT`, `KUM`, `DR`, `LATE`…)
2. Split into full words vs single-letter initials
3. **Given name** — first full word must match by signature, allowing a leading expanded initial
4. **Surname — strict.** Signature mismatch is an immediate reject. This is where false positives are dangerous
5. **Middle names** — conflicting middles on both sides reject; a middle present on one side only is normal variation
6. **Initials** — a contradiction only when the *other* document records a middle name the initial fails to match. An initial standing for a component the other document simply omits (`RAHUL K SINGH` vs `RAHUL SINGH`) is ordinary

Confidence: `0.99` exact · `0.85` spelling variance · `0.75` with a dropped component.

```python
worst_pair(names: dict[str, str]) -> (key_a, key_b, NameMatch)
```
Compares every document against every other and returns the **weakest link** — the pair EPFO or ABHA will reject on.

### 3.3 Devanagari transliteration

Context-sensitive anusvara handling, which is load-bearing:

```python
if nxt in ("क","ख","ग","घ","ह"):  out.append("ng")   # सिंह → singh
elif nxt in ("प","फ","ब","भ","म"): out.append("m")
else:                              out.append("n")
```

Getting this wrong makes `Singh` and `Sinha` collide. Schwa deletion trims the trailing inherent vowel on words longer than three characters.

---

## 4. Employer entity resolution — `core/entity.py`

```python
score_pair(x, y) -> MatchResult(score, linked, reason)
score  = 0.45·jaccard + 0.55·head_agreement − 0.45·|discriminator_asymmetry|
linked = score ≥ 0.62
```

Normalisation strips legal suffixes (`LTD`, `PVT`, `LLP`), bank noise (`NEFT`, `IMPS`, `SAL`), IFSC codes, reference numbers and month tokens, then expands known contractions (`TCS`, `L&T`, `SER→SERVICES`).

**The discriminator penalty is the load-bearing part.** Tokens like `BPM`, `ENTERPRISES`, `INFOSYSTEMS`, `CAPITAL`, `RETAIL` split legal entities that share a brand:

```
TATA CONSULTANCY SERVICES LIMITED ↔ NEFT CR-...-TATA CONSULTANCY SER-SALARY   1.000  linked
INFOSYS LIMITED                   ↔ INFOSYS BPM LIMITED                       0.325  blocked
```

---

## 5. Document parsing — `core/parsers.py`

### 5.1 Form 26AS — two-tier nested table

Confirmed structure: a deductor row carrying `Name of Deductor | TAN | Total Amount Paid/Credited | Total Tax Deducted | Total TDS Deposited`, followed by transaction rows carrying `Section | Transaction Date | Status of Booking | Date of Booking | Amount Paid/Credited | Tax Deducted | TDS Deposited`.

```python
parse_26as(text)  -> list[{name, tan, total_paid, total_tds, transactions[]}]
verify_26as(deds) -> list[str]     # empty means it reconciles
```

A line containing a TAN (`[A-Z]{4}\d{5}[A-Z]`) opens a deductor block; lines beginning with an integer and containing a `dd-Mon-yyyy` date are its transactions.

**The verifier is the backstop for the whole system.** Transaction rows must sum to the summary row within ₹1.00.

### 5.2 Passbook and Service History

```python
parse_passbook(text)        -> {member_id, establishment, doj, months[]}
parse_service_history(text) -> [{member_id, doj, doe}]
```

**Date of exit is not in the passbook PDF** — it lives in Service History on the UAN portal. This is why ingestion takes three captures, not two.

### 5.3 Bank statement — `app/engine.py`

```python
BANK_ROW = r"^(\d{2}-\d{2}-\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s+(CR|DR)\s*$"
parse_bank(text) -> [{date, narration, amount, type}]
```

Rows only. Whether a row is salary is decided by the model backend, then attributed via `score_pair`. **An unattributable credit is dropped, never guessed.**

---

## 6. Claim gate — `core/gate.py`

```python
@dataclass(frozen=True)
class Fact:
    kind     : DATE | AMOUNT | TAN | MEMBER_ID | ORG | UAN
    value    : str
    employer : str | None       # None = member-level, valid in any scope
    source   : str              # "26AS:BLRA12345E:txn#12"

class EvidenceLedger:
    def admit(kind, value, source, employer=None) -> Fact
    def lookup(kind, value, employer) -> Fact | None
```

Scope rule: a member-level fact is valid anywhere; an employer-scoped fact is valid **only in its own scope**.

```python
claim_gate(doc: RenderedDoc, ledger: EvidenceLedger) -> list[Violation]
```

Independently re-extracts `DATE`, `TAN`, `MEMBER_ID`, `UAN`, `AMOUNT` from the **rendered body** and requires each to resolve. Violations:

| Kind | Trigger |
|---|---|
| `UNSUPPORTED_FACT` | No ledger entry — distinguishes "never seen" from "wrong employer scope" |
| `HEDGED_LANGUAGE` | `I believe`, `approximately N`, `possibly`, `to the best of my memory` |
| `NO_ANNEXURE` | Assertions with no evidence attached |

---

## 7. Orphan recovery — `core/orphan.py`

```python
assess(cand, today) -> Assessment(verdict, reasons, establishment, estimate)
build_recovery_plan(cand, assessment) -> list[Step]
```

### 7.1 Verdict gates, in order

1. Employer unmatched in the register → `UNCERTAIN`, plan starts by confirming the registered name
2. **Not EPF-covered → `UNLIKELY`, no plan, no estimate.** Establishments below the statutory employee threshold need not provide EPF
3. Fewer than 3 months → `UNLIKELY`
4. Otherwise → `LIKELY` with a balance estimate

### 7.2 Balance estimate

```
basic       ∈ [0.40, 0.50] × gross          # 26AS reports gross; PF accrues on basic
employee    = basic × 0.12
eps         = min(basic, 15000) × 0.0833
employer_pf = max(0, basic × 0.12 − eps)
corpus      = (employee + employer_pf) × months × (1.0815 ^ years_since_exit)
```

Returned as an `Estimate` — a **separate type from `Fact`**, so it cannot enter a filing.

### 7.3 Recovery plan

```
1. Trace the member ID          EPFiGMS request against PAN + establishment code
2. Check your own records       payslip / Form 16 often carries the PF number — faster
3. File the transfer claim      blocked_by: member ID from step 1 or 2
4. Escalate if untraceable      blocked_by: negative or absent response to step 1
```

Steps declare what blocks them, so nothing reads as actionable before its prerequisite exists.

---

## 8. Ingestion — `app/ingest.py`

```python
extract(filename, data, password=None) -> Extracted(text, kind, pages)
sort_uploads(items, password=None)     -> {found, report, missing}
```

Dispatch by magic bytes, not extension: `PK` → ZIP, `%PDF-` → PDF, else UTF-8. Type detected from **content**, so upload-field choice is irrelevant.

`IngestError` carries a message written for the person who uploaded the file:

| Condition | Message |
|---|---|
| Encrypted | *"Enter your date of birth as DDMMYYYY in the password box"* |
| No text layer | *"most likely a scan… download the file again directly from the portal"* |
| Over 8 MB | *"Download it again from the portal rather than scanning it"* |
| Unrecognised | *"Upload the file exactly as downloaded, without editing it"* |

**No filename, content, or derived text is ever logged.**

---

## 9. Model backend — `app/models.py`

```python
class Backend(Protocol):
    name: str
    def available(self) -> bool
    def transliterate(self, text: str) -> str
    def classify_narration(self, narration: str) -> dict
    def draft(self, system: str, user: str) -> str
```

`OpenAIBackend._json_call` uses `response_format={"type":"json_schema", ..., "strict": True}`. Model id from `VESTED_MODEL`, default `gpt-5`.

`selftest(backend) -> int` exercises six cases across both methods. Run via `python app/models.py`.

---

## 9a. Employer resolution — `EmployerRegistry`

Nothing connects a Form 26AS deductor (identified by **TAN**) to an EPF account
(identified by **establishment code**) except the employer's *name*. The registry
resolves them at runtime using `core/entity.score_pair`, so an employer nobody
has seen before behaves exactly like a known one.

```python
reg = EmployerRegistry()
reg.add(passbook["establishment"], member_id=...)   # establishment code key
reg.add(deductor["name"], tan=...)                  # matched into the same entry
reg.key_for_tan(tan) / reg.key_for_member_id(mid) / reg.display(key)
```

Keys prefer the 15-character establishment code, falling back to the TAN. The
display name is the **longest** rendering seen, since it is the least abbreviated
and therefore the most recognisable to the member.

This replaced hardcoded lookup tables. See BUILD-LOG §10.2 for why that mattered.

```python
extract_identity(text_26as, parsed_pbs, names) -> {name, uan, pan}
```
Identity is read from the documents: PAN from Form 26AS, UAN and member name
from the passbook. Nothing about the member is a constant.

---

## 10. Orchestration and web

```python
analyse(text_26as, passbooks, service_history, bank, names) -> Analysis
extract_names(found) -> dict          # "Name of Assessee" / "Member Name" / "Account Holder"
check_names(names, backend) -> NameCheck
```

`Analysis` carries `ingest[]`, `result{}`, `orphans[]`, `documents{}`, `name_check`, `backend`, `salary_events[]`.

`app/server.py` — routes only, **no logic**. An in-memory session dict with a
30-minute TTL reaped on access, and `create_app()` for gunicorn.
`_finding_copy()` in `views.py` is the single point where engine vocabulary
becomes plain language.

### 10.1 Portal routes

| Route | Screen |
|---|---|
| `/` | redirects to `/home?s=sample` — lands people inside the product |
| `/home` | Can you claim today? Balances, blocking problems, forgotten money |
| `/record` | The reconciliation |
| `/accounts`, `/account/<member_id>` | Every PF account, one detail view each |
| `/pension` | EPS balance and the ten-year eligibility line |
| `/withdraw` | Advance eligibility, and the five-year TDS trap |
| `/claim` | Preflight before filing |
| `/track` | Statutory service standards |
| `/profile` | Name across documents, canonical spelling, what is linked |
| `/privacy` | What happens to an uploaded document |
| `/upload` | The upload form |

Earlier URLs (`/result`, `/finding/<key>`, `/orphan/<tan>`) still resolve.

---

## 11. Test inventory

| Suite | Assertions | Covers |
|---|---:|---|
| `core/reconcile` | 5 | Overlap, root cause, orphan, clean control, sub-TDS path |
| `core/entity` | 3 | Entity precision, recall, zero false merges |
| `core/parsers` | 11 | Parsing, arithmetic verifier, end-to-end, settlement control |
| `core/gate` | 5 | Clean pass, invented fact, wrong scope, hedging, no annexure |
| `core/orphan` | 12 | Orphan assessment, plan ordering, three negative cases |
| `tests/test_names` | 10 | 19 name pairs, four-document resolution, backend contract |
| `tests/test_ingest` | 20 | PDF, encrypted PDF, ZIP, scans, mixed-format upload |
| `tests/test_anyone` | 18 | Works for someone who is not the sample; no identity leakage |
| `tests/test_frontend` | 143 | No JS, no-CSS legibility, mobile, headings, labels, nav, privacy claims |
| `app/models` | 6 | Every backend call against its contract |
| **Total** | **233** | |

Plus: pipeline smoke test, upload round-trip, error paths (missing / unrecognised / expired / oversized), and the gunicorn entry point.

`tools/schema_probe.py` is operator tooling, not a test — it reports **structure only** (field presence, row counts, month spans) from a real document, printing no names, amounts, dates or identifiers.
