# Vested — Build Log

An honest record of how this got made: what we researched, what we rejected, what broke, and what is still open.

---

## 1. Starting point

Documented the hackathon site itself first — three routes (`/`, `/brief`, `/faq`), a 404, and one Google Form. Full transcription lives in the site teardown.

The brief's own copy set the constraints that drove everything after:

> *"Solve the deeper problem, not just the interface. A cleaner screen over the same broken process is not a fix."*

Repeated three times in different words. Combined with **"Honesty"** as an explicit scored criterion — rare in hackathons — this reads as organisers who have seen too many pretty re-skins and too many fake demos.

---

## 2. Idea evolution — two rejections before the answer

### 2.1 Ek Chakkar — pre-submission validation for state certificates

Publish the unwritten rejection rules that clerks and touts use, as versioned citable code, and check applications before submission.

**Rejected.** It is a **linter for a broken process** — it makes the citizen better at being a courier without asking why they are the courier. Its scaling story was manual rule encoding, forever.

### 2.2 Gawaah — corroborated verification, approve-only

Replace one officer's discretionary field visit with corroboration across records the state already holds. Constrained so it could **only auto-approve, never auto-reject** — pre-empting the Robodebt and Dutch childcare failure mode.

Better idea in the abstract, and its approve-only principle survives into the final build. **Rejected on one question: does the main journey actually work?**

Gawaah's entire data layer was imaginary. A judge asks *"where does the electricity data come from?"* and the honest answer is *"an inter-departmental data-sharing agreement that doesn't exist."* That is a proposal with a UI, not a prototype.

### 2.3 The reframe that produced Vested

Pushing for **specificity** — the brief names IRCTC, EPFO and the Income Tax portal — exposed the flaw. Research found:

| Finding | Source |
|---|---|
| **~174 lakh of 796 lakh claims rejected in 2024-25 (~22%)**; EPFO cites sub-1% (office-level, post-auto-settlement) | Business Today |
| Rejection reasons confirmed in Lok Sabha 9 Mar 2026: DOB / exit date / Aadhaar / bank mismatches | MoS Labour, written reply |
| **5+ crore** claims settled FY 2024-25 → ~1.7 crore rejections/year | Tribune / NewsOnAir |
| **₹9,330 crore** in inoperative EPF accounts | Business Today |
| ~₹1.8 lakh crore unclaimed across Indian finance; ₹78,213 cr in bank deposits alone | Business Standard |
| Residual EPFO 3.0 failures concentrate in **DOJ / DOE / overlap** | Kustodian, RTI Wiki |
| ~9.5 crore waitlisted rail passengers unconfirmed over 3 years | Deccan Herald |

IRCTC was rejected despite the scale — waitlist *prediction* is a solved commercial space (ConfirmTkt, Trainman), and three minutes would go on explaining why you are not them.

**The move nobody had made:** Form 26AS contains TDS by employer, month by month, with each employer's TAN. **Income Tax records can prove the EPFO service record wrong** — and the citizen can download both. No data-sharing agreement needed; the citizen is the consent bridge.

---

## 3. Assumptions, resolved by research

Initially flagged as "needs a real file." Most were answerable from published format documentation and specimens:

| # | Assumption | Outcome |
|---|---|---|
| A1 | 26AS Part A has per-deductor TAN with dated transactions | **Confirmed** — two-tier table, and dates are *day*-granular, better than assumed |
| A2 | Passbook has member ID, wage-month rows, DOJ | **Confirmed** |
| A3 | Date of exit is available somewhere | **Resolved unfavourably** — not in the passbook; lives in Service History |
| — | 26AS is text or scan? | **TRACES exports a delimited text file** — vision extraction dropped off the critical path entirely |

---

## 4. Spikes, in order

| Spike | Question | Result |
|---|---|---|
| **A** | Can we detect claim-blocking contradictions and propose corrections? | 5/5 |
| **B** | Can we link employers across formats without merging different entities? | 22/22 — *mechanism validated, accuracy not* |
| **C** | Do real documents contain the fields we need? | Operator tooling; not yet run on a real file |
| **D** | Does the whole chain work on format-accurate documents? | 11/11 — after finding two real bugs |
| **E** | Can unsupported facts be made structurally unable to reach a signed document? | 5/5 |
| **F** | Can we recover an orphaned account — and stay silent when there is none? | 12/12 |
| **G** | Can we match a person across scripts without merging two people? | 10/10 — after three fixes |

**Spike B's 22/22 is not an accuracy claim.** The corpus was authored by us and the discriminator list tuned against it. What it validates is the *mechanism* — the discriminator penalty demonstrably blocks brand-prefix false merges.

---

## 5. Bugs found by failing tests

Five, all caught by a test failing rather than by review. Three would have actively harmed users.

### 5.1 The proposed correction was never checked for conflict

The overlap check read only the *asserted* timeline. If evidence says "your Acme exit was really 31 March" while Boreal says you joined 20 January, the correction we would draft **creates dual employment** — EPFO rejects it, and we have sent someone to file doomed paperwork with full confidence.

**Fix:** `CORRECTION_CONFLICT` runs the check against the corrected timeline too, and blocks filing.

### 5.2 Settlements misread as wrong exit dates

Full-and-final payouts generate TDS *after* the real exit. Reading that as "your exit date is wrong" would manufacture false disputes at scale — telling people to fight a date that was correct.

**Fix:** `TRAILING_PAYOUT`. The discriminator is clean — **employers don't remit PF on an F&F payout**.

### 5.3 सिंह romanised to "SINH", colliding with Sinha

The anusvara is a nasal whose romanisation depends on what follows; before a velar or ह it is conventionally "ng" — which is *why* सिंह is spelled "Singh."

**Fix:** context-sensitive anusvara. Singh and Sinha stay correctly distinct.

### 5.4 JOSHI and JOSHUA shared a consonant skeleton

Skeleton alone was insufficient.

**Fix:** a vowel-class signature collapsing *lengthening* but not an added *syllable*. `JOSHI→UI`, `JOSHUA→UUA`.

### 5.5 `RAHUL K SINGH` vs `RAHUL SINGH` rejected

An initial standing for a middle name the other document simply omits is ordinary variation — a contradiction only when the other side records a middle name the initial fails to match.

### 5.6 Two honesty bugs, caught late

- **The banner lied.** It read *"all data shown is synthetic"* — untrue the moment someone uploads their own records. Now: *"Nothing you upload is stored, and nothing is submitted anywhere."*
- **The name check caught our own fixtures.** The upload test flagged a mismatch, correctly: 26AS said `SYNTHETIC TEST SUBJECT` while the bank statement said `RAHUL SINGH`. The sample now spells one name four ways.

---

## 6. Integration — a gap worth recording

After building `name_match.py` and `models.py` and reporting the model gap closed, a check showed both modules were **orphaned**: they passed their tests and the running product never called them.

```
engine.py imports:  spike_a, spike_d, spike_e, spike_f
name_match used outside its own spike:  NOWHERE
```

The claim had been true of the *codebase* and false of the *product*. Fixed by wiring both in, which required adding a bank statement as a third evidence source so `classify_narration` sat on the execution path at all.

**Lesson worth keeping:** "built and tested" and "in the product" are different states, and only the second one counts.

---

## 7. What exists now

```
9,493 lines of Python, 7,349 of them across 15 shipping modules
443 checks across 9 suites — all passing
Every page under 6 KB, no JS required, readable without CSS
```

| Capability | State |
|---|---|
| Document ingestion (PDF/TXT/ZIP, passwords) | Built |
| Arithmetic verification | Built |
| Person-name matching across scripts | Built |
| Employer entity resolution | Built |
| Salary credit classification | Built |
| Timeline reconciliation, 7 defect classes | Built |
| Correction routing | Built |
| Evidence-backed generation + claim gate | Built |
| Orphan recovery with silence guard | Built |
| Web interface, upload, sessions | Built |
| Deployment config (Docker/Procfile/gunicorn) | Built |

---

## 8. What is still open

### Decision: built with Codex, ships without a model

These are two separate questions and an earlier draft of this section ran them
together. Splitting them properly:

**Codex wrote most of this code.** It was the build tool for the engine, the
parsers, the views and the test suites. The git history records this as
`Co-Authored-By: Codex` on the commits it authored, which is the same claim made
in the same place a reviewer would look for it.

An earlier version of this section said Codex had been dropped in favour of
other tooling. That was wrong, and it is corrected here rather than quietly
edited out, because a build log that revises its own record without saying so is
worth less than no build log.

**The model backend is still deliberately not enabled at runtime.** That
decision was made after measuring what it would actually do. On a realistic
upload — Latin-script name, no bank statement — it fires **zero API calls** and
the findings are byte-identical. Its only genuine gain is non-Devanagari script
support, which the demo would never show, and the cost is downgrading
`/privacy` from *"nothing leaves this server"* to a qualified claim.

So against *"built with Codex or powered by an OpenAI model"*: the **first
branch is satisfied**, the second is declined on the privacy grounds set out in
FEATURE-SPEC §8.1. `OpenAIBackend` exists as a working extension point and has
never executed.

What declining the runtime model buys: determinism, reproducibility, zero cost,
and a privacy claim that needs no footnote.

### One open dependency

**A real Form 26AS.** Every test to date runs on format-accurate fixtures we wrote — **including the defects they detect**. What is proven: *"given a document containing an error, we find the error."* What is not: *"given a real record, there is an error, and we find it."*

Source it from someone with **two or more past employers** — a single-employer history contains no overlap to find.

### Deferred by choice

- Vision extraction path (`MODEL_VISION` declared, unused)
- Real EPFO establishment register (four entries mocked)
- Shared session store — a privacy decision, not a technical one
- Format variants across older assessment years

---

## 9. Honest self-assessment against the judging criteria

| Criterion | Standing |
|---|---|
| **Problem** | Strong. Documented numbers on a portal the brief names by name |
| **Working build** | Strong. Parsers corrected against real passbooks and a real 26AS; the committed suite runs on synthetic fixtures in the real layout |
| **Usability** | Strong. <6 KB, no JS, plain language, Hindi alongside |
| **Product thinking** | Strong. Approve-only, estimate/fact separation, silence guard |
| **End-to-end** | Strong. Attacks the process, not the interface |
| **Honesty** | Limitations are on-screen and in these documents, not buried. `/privacy` argues against trusting itself |

**The biggest risk flagged from the beginning was that every green test ran on data we authored.** That afternoon happened — see the 21 August entry, where a real 26AS and ten real passbooks found four parser defects that had raised no error and returned plausible nonsense. What remains is narrower but real: the corrected parsers are pinned by synthetic fixtures written in the real layout, because member documents cannot be committed to a public repository. One member's document set is also not a sample. Every layout we have not seen is still untested.

---

## 10. Later work

### 10.1 The portal

The build was reframed from a single-purpose tool into a **reimagined EPFO member
portal** after the organiser described the brief as reimagining public-service
websites and expecting a full proof of concept, not a demo page.

Nine sections, mirroring the real portal's information architecture so a judge
recognises the shape, but each answering the question a member actually has:
Home, Your record, Accounts, Pension, Withdraw, Claim, Track, Profile, Privacy.

### 10.2 The worst bug in the project

Testing with a different person's documents produced:

```
accounts: 0    balance: 0    findings: []
```

**No error.** Employer resolution ran through lookup tables keyed on the
sample's TANs and member IDs, so a real member's documents were silently
skipped — and the product reported a clean record it had never examined.

Fixed with `EmployerRegistry`, which links a 26AS deductor (TAN) to an EPF
account (establishment code) through the employer's *name*, using the entity
matcher. Identity is read from the documents. `tests/test_anyone.py` locks it
down with 18 checks, three asserting no sample identity leaks into a real
person's paperwork.

Two incidental bugs fell out: a PAN regex containing literal backspace
characters (a `` mangled by a non-raw replacement string), and hardcoded UANs
in the portal header.

### 10.3 Other defects found by testing rather than review

- **PDF and ZIP ingestion had never been executed** — only `.txt`. Encrypted
  PDFs were reported to users as "damaged", because pdfminer raises an
  exception with an empty message for encryption. Form 26AS is password
  protected by default, so this was the most common case.
- **Three accessibility failures**: `/record` had no `<h1>` at all; two pages
  skipped `h1 → h3`.
- **The landing page hid the entire portal** behind a form submit. Fixed by
  redirecting `/` into the working product.
- **The privacy banner was inaccurate** — it claimed nothing was stored without
  disclosing that enabling the model backend would send data to a third party.

---

## Entry — the documents people can actually get

A member reported being unable to obtain the two documents the product demanded.
The EPFO passbook portal and the UAN member portal were both down; the only file
they could get hold of was Form 26AS — the one document the gate treated as
optional.

That is the exact inverse of what we had built, and it exposed four defects.

**1. One document crashed the name check.** `worst_pair` returns `None` when
fewer than two documents carry a name. `check_names` subscripted it
unconditionally. The catch-all handler converted the `TypeError` into *"we could
not make sense of the layout"* — blaming the member's document for our bug. This
is the hazard of that handler: it makes crashes look like user error.

**2. Form 26AS alone reported three forgotten accounts that did not exist.**
With no service history there is nothing asserted to link employers to, so the
reconciler orphaned every one of them. Left alone, we would have sent someone
chasing trace requests for perfectly healthy accounts.

**3. Passbook-without-history was worse.** It orphaned the two employers whose
passbooks we were holding. The trigger is the *service history*, not the absence
of a PF record generally.

**4. An unchecked record rendered as "Yes, you can claim."** `claimable` was
`blocking_count == 0`, and with nothing to test against there were no findings.
Absence of evidence rendered as a clean bill of health — the most damaging
sentence the site could print.

### What changed

`ORPHAN_ACCOUNT` findings are withheld whenever the service history is absent,
and `claim_status` becomes `NOT_CHECKED` rather than clean. `Analysis.checked`
now distinguishes *tested and clean* from *never tested*, and `claimable`
requires both. The home page renders three states instead of two.

The gate now blocks only when neither a passbook nor a Form 26AS arrived.
Form 26AS alone yields a **worklist** — where you worked and when, per the
Income Tax Department — which is a genuinely different claim from a finding
about your PF record, and is stated as such.

### The rule this establishes

> Gate on what can be concluded, not on a fixed document set. Narrow the claim
> when evidence is thin; never widen it, and never let thin evidence read as
> good news.

The old design assumed every member could obtain every document on demand. The
portals that serve them are frequently unavailable, which is part of why this
product exists at all — designing as though they were reliable contradicted the
premise.

Coverage: 266 assertions across 11 suites, 21 of them new and specific to
partial evidence.

---

## Entry — first run against real documents

A member supplied ten real EPF passbook PDFs, three password-protected ZIPs and
one scanned PDF. Testing was done locally with structure-only probes: no
document content, name, amount, date, identifier or filename was ever printed,
and nothing was copied out of the folder.

Two things were true before this run that are worth stating plainly. Every
parser test used fixtures we wrote ourselves, in wording we had guessed. And the
member believed they had obtained only Form 26AS — in fact the passbooks were
the files they had, and the 26AS was still locked inside the ZIPs.

### What the real layout does not look like

The live passbook has **no "Wage Month" column header** and no "Employee's
Share" wording. It carries a wage month formatted `Mon-YYYY`, a transaction
date, a `CR` marker, three contribution columns and three running balances. It
is issued **one file per financial year**. It contains a date of birth but
**neither a date of joining nor a date of exit**.

### Five defects, none of which raised an error

1. **Member ID and UAN sit mid-line.** The parser required them to start the
   line, so both came back empty and every account lookup failed silently.
2. **The row scanner ate the transaction date.** `NUM_RE` was applied to
   everything after the wage month, so a row dated `31-08-2023` was read as
   employee=31, employer=8, pension=2023. The resulting balance was nonsense and
   entirely plausible-looking.
3. **Thousands separators split.** `NUM_RE` read `1,23,456` as three numbers.
4. **Ten files were ten accounts.** Per-year pages were never merged, so one
   member's balance was split across ten rows under ten invented employers.
5. **`Member ID …` lines take the last token.** With the establishment name on
   the same line, the member ID parsed as `LTD`.

Defect 2 is the one that matters most. It produced a confident, wrong number
with no error anywhere — the same class of failure as the hardcoded-employer bug
and the None-reaching-a-parser bug. On this project that pattern has now
appeared three times, and every time it was caught by running real input through
the whole path rather than by reading the code.

### What changed

`AMOUNT_RE` and `REAL_ROW_RE` parse the live row without touching the date.
Header fields are found anywhere on a line. The closing balance is preferred
over summing contributions, because it includes interest. `merge_passbooks()`
groups per-year pages by member ID and takes the most recent year's closing
balance rather than summing. Employers register from a passbook alone, keyed on
the establishment code embedded in the member ID.

A second PF account number printed inside a passbook is now recorded as a
**related account reference** and shown to the member, explicitly uninterpreted:
we do not know whether it is a transfer in, a re-issued number or a second
account, and guessing would be worse than saying so.

`tests/test_real_passbook.py` locks all of this with 23 assertions against a
synthetic fixture in the real layout, so it holds without real data.

### Result on the real record

Three accounts, real balances and pension, one related account reference, and
the correct refusal of four files: three needing a password, one a scan. The
verdict renders as **Not yet known**, because no service history was available
and the record was therefore never tested.

Coverage: 290 assertions across 12 suites.

---

## Entry — the real Form 26AS

The member unzipped the three protected archives, which turned out to be TRACES
caret-delimited text exports covering three assessment years. Testing again used
structure-only probes: every token that was not in a vocabulary fixed in advance
was masked before anything was printed.

Worth recording: the export folders are named `<PAN>-<year>`. A filename alone
can carry an identifier, which is part of why ingestion logs none.

### The export is not the document we built for

TRACES delivers Form 26AS as `^`-delimited records, not the tabular layout our
fixtures imitate:

```
deductor      INT ^ name ^ TAN ^ ... ^ paid ^ tds ^ deposited
transaction   <empty> ^ INT ^ section ^ date ^ status ^ date ^ ... ^ amounts
```

The tabular parser requires a transaction row to START with a digit. A caret row
starts with an empty field, so **not one transaction was read** — while the
deductor summary rows still parsed, so the file looked like it had loaded.
`verify_26as` was what caught it: 4, 4 and 10 arithmetic failures. The
"model proposes, checker disposes" rule earned its place here.

### Six defects

1. **Caret rows parsed as nothing.** Fixed with a dedicated caret path;
   all three files now reconcile with **zero** arithmetic problems.
2. **Interest treated as employment.** The real export is 202 section-194A
   entries against 22 section-192 ones. Every transaction was being read as
   salary, which would have made the member's **bank an employer** and then
   invented a forgotten PF account for it. Only 192/192A now count.
3. **Challan minor-head codes read as sections.** Part C rows carry `100` and
   `300` where a TDS row carries its section, and attached themselves to
   whichever deductor came last.
4. **Only one assessment year was kept.** `sort_uploads` stored the first 26AS
   and discarded the rest — while reporting all three as "Recognised". 26AS is
   exactly the document where more years means more chance of finding a
   forgotten account.
5. **One employer counted once per year.** Unmerged blocks made the orphan
   estimate read a single year's months and average, and listed the same
   employer repeatedly.
6. **`/accounts` crashed on the real record.** A live passbook has no date of
   joining, so `doj` was None and `strftime` threw. The member saw an empty
   page.

Defect 2 is the one worth remembering. It is not a parsing bug — the parse was
correct. It is a **domain** bug: the code assumed every TDS entry meant
employment, which is true of our fixtures and false of every real 26AS.

### The three-state rule, applied properly

The earlier entry established that an unchecked record must never read as good
news, and fixed the home page. The real record found the same two-state
assumption still live in `page_result` and in the accounts list. Both now
distinguish *tested and clean* from *never tested*, and a new test renders
**every** page against partial evidence — the only reliable way to catch this.

### Result on the real record

Three assessment years, seven employers after merging, 22 salary entries, three
PF accounts with real balances, one related account reference, **zero false
findings**, and a correct refusal of the one scanned file. The verdict reads
*Not yet known*, because no service history was available.

Coverage: 313 assertions across 12 suites.

---

## Entry — crawling every page instead of inspecting objects

Asked directly whether the whole app worked, the honest answer was that nobody
had checked. Every suite so far built an `Analysis` object and inspected its
fields; none of them asked whether the pages *rendered*.

Crawling every reachable link, on six evidence combinations, found **five**
HTTP 500s that every existing test had missed:

- three account detail pages, and the accounts list, on a live passbook, which
  carries no date of joining - `doj` was None and `.strftime()` threw
- `/record` and `/profile` on a single-document upload, where the name check
  has no second name to compare against and `weakest` is None

Both are failures introduced by earlier *correct* fixes. Allowing partial
evidence created states the pages had never been written to handle, and object
inspection cannot see that. A page that 500s is worse than a wrong number: the
member sees nothing and cannot tell whether their claim is safe.

`tests/test_crawl.py` now follows every internal link on six combinations,
asserting each page returns 200 with real content, never leaks a traceback, and
never tells an unchecked record that nothing is blocking it.

Coverage: 320 assertions across 13 suites.

---

## Entry — the printer is part of the product

Two fixes to how the thing presents itself, one of which was not cosmetic.

**A neutral state that looked broken.** The three-state verdict added earlier
used a bare `<div class="hero">`, but `.hero` sets `border-left:5px solid` with
no colour and `.banner` has no default background. So *Not yet known* — the
state a member with partial documents actually lands on — rendered as an
unstyled box. A regression introduced by a correct fix. There is now a third
semantic colour, deliberately neither the red of a blocked claim nor the green
of a clear one.

**No print stylesheet.** This product exists to produce a Joint Declaration that
someone carries to an EPFO counter, signs, and files. Printing it emitted
navigation tabs, the prototype banner and a hero card — a web printout rather
than a document. The last step of the core feature failed on the one surface
that decides whether it worked.

Printing now strips screen furniture, sets the letter in serif at 11.5pt, keeps
it whole across page breaks, and prints a footer stating that it is an
independent prototype and not an official EPFO document — because that
disclaimer has to survive leaving the browser.

The print rules pushed the heaviest page to 16.4 KB, over the 16 KB budget. The
budget is a real constraint, not decoration, so rather than raise it the
stylesheet is now minified at import (`app/cssmin.py`) while the source keeps
its comments. Heaviest page: 15.1 KB, with print support included.

Coverage: 336 assertions across 14 suites.

## 22 Aug 2026 — the half of the portal that does things

Research into the real EPFO member portal found we had rebuilt its *View* menu
and skipped *Manage* and *Online Services* entirely. Reading a record and never
offering the action that fixes it stops at the exact moment of usefulness.

**Built:** `core/epfo_rules.py` (the 2026 rules, deterministic, 35 checks),
`app/manage.py` (Manage hub, KYC, Mark Exit, e-Nomination, Transfer),
`app/demo.py` (two mock accounts with working sign-in), `tests/test_manage.py`.

**Mark Exit** is the one that matters. EPFO offers members the screen and asks
for a date; Form 26AS is where the date is. We fill it in.

**EPFO 3.0 modelled.** Auto-settlement to ₹5 lakh, thirteen categories merged to
three, UPI 75% / ATM 50%, employer approval replaced by automated checks. The
argument this produces is the strongest one we have: *automating the decision
does not improve the data it is made on.* A wrong date used to get a phone call;
now it gets a rejection, faster, with nobody to appeal to.

**Defect caught while writing the tests.** `Analysis.settlement` returned "would
go to manual review" on a record with no service history — implying we had
inspected it and found it survivable. Added an explicit `unknown` mode. Same
failure class as the orphan bug: absence of evidence rendering as a verdict.

**Second defect, same session.** `kyc_ready` required every item to be green, but
bank and Aadhaar KYC live inside EPFO and are never visible — so auto-settlement
was unreachable for everyone and the UPI/ATM path was dead code. Split into
`kyc_ready` (nothing visible is wrong) and `kyc_unverified` (something is unseen),
with the caveat carried into the verdict text. Caution had become a false negative.

**Stylesheet externalised.** It was 10.1 KB inlined into every page — 62% of each
response, re-sent fifteen times a session to people the product exists to serve.
Now served once from a content-hashed, immutable URL. **Mean page 13 KB → 4.0 KB;
heaviest 16.3 KB → 5.7 KB.** The weight budget stopped being a fight.

**Corrections to our own claims.** The 13% → 34% rejection figure is stale and the
trend now runs *down* (29% → 22%); replaced with ~1 in 5, and 174 lakh of 796 lakh
in 2024-25. The sub-1% figure EPFO cites counts office-level rejections after
auto-settlement — that twentyfold gap is the better point. The DigiLocker /
Account Aggregator consent rail was an overclaim: the pattern exists, a 26AS pull
over it does not. Joint Declaration is online by default since 2026, physical only
for closed establishments — where it can be attested by a bank manager, gazetted
officer or magistrate, which is our core user's actual answer and was missing.

Form 26AS is **not** on EPFO's accepted-evidence list for date corrections
(attendance register, appointment letter). Stated plainly on the finding pages,
and turned into the one policy ask this POC makes.

**Then the completeness pass.** UAN card and contact details, which sound like
filler and were not. Building the card meant parsing date of birth from the
passbook - which we had never read, despite a DOB mismatch being one of the
rejection causes the Minister of State for Labour named in the Lok Sabha. Two
passbooks can disagree about it, so the card reports the disagreement rather
than picking a winner. Contact details earns its page because every digital
route under EPFO 3.0 hangs off an OTP to the Aadhaar-linked mobile, and a dead
number closes all of them silently.

**467 assertions across 15 suites.** Deployed, revision vested-00019.

## 22 Aug 2026 — closing the engine gap

The reconciliation engine had run on real documents exactly zero times, because
every defect class hung off EPFO's asserted service history — the hardest of the
four documents to obtain. A member with only a passbook and a Form 26AS got a
page that said *not yet known* about everything, which is honest and useless.

**`CONTRIBUTION_GAP`.** Months where 26AS records tax deducted from salary and
the passbook records no deposit, bounded strictly inside the passbook's own span.
No service history required, because nothing is compared against EPFO's claim —
only two records of what actually happened.

Narrow on purpose. Edge months are excluded (March PF lands in April; settlement
TDS trails the last contribution), employers with only one of the two records are
never accused, and consecutive months collapse into one finding. 37 checks, most
of them about the ways it could be wrong: a false accusation against an employer
is worse than a missed one.

**The defect this exposed.** Running it on the real documents returned
`contributions_checked = False`. The cause: **the live passbook prints the
establishment mid-line after a pipe** — `... | Establishment ID/Name <code> /
<NAME>` — and the parser required the line to *start* with the word. Every real
passbook came back with no employer name, so it could never be matched to the
same employer in 26AS, silently disabling the whole check on precisely the files
it was written for. Same defect class as the mid-line member ID and UAN.

**Result on the real record:** 2 employers matched across both documents, 9
tax-deducted months inside the contribution span, all 9 with a matching deposit.
Zero gaps — an earned clean verdict on real documents rather than a shrug.

**`checked` split in two.** `dates_checked` and `contributions_checked` are now
separate, and `Analysis.checked` means the dates specifically. A contribution
finding must never be allowed to imply the dates were tested; the home page now
reports a real verdict *and* names the axis nobody looked at.

**504 assertions across 16 suites.** Deployed.


## 22 Aug 2026 — the service history, typed

The last gap, and it turned out not to be ours. Probing the real folder found
14 files: three Form 26AS exports, ten passbooks, and one refused PDF — three
A4 pages, twenty images, **zero text characters**. Screenshots.

Which is not an unusual member. **The UAN portal shows service history as an
on-screen table with no download button.** Everyone screenshots it. So the gap
was never that these documents were odd; it was that we only accepted a file
the portal does not hand out.

OCR was the obvious move and the wrong one. A misread digit in a date is
indistinguishable from the employer error we are hunting, so a confident wrong
finding is strictly worse than asking.

**`/history`.** Two dates per account, member IDs pre-filled from the passbooks
already read. The typed rows are rebuilt into the same text the file parser
consumes, so a typed history travels the identical code path — no second
implementation to drift.

It refuses rather than guesses: ISO order, 31 February, an exit before a
joining date, an exit with no joining date. A row left blank is skipped, not
rejected — half a history beats none. Of 36 checks, most are about bad input.

**Verdict on a history-less record: *Not yet known* → *No*, with EXIT_TOO_EARLY,
MISSING_EXIT and ORPHAN_ACCOUNT.** The orphan is the proof the typed dates
reached the reconciler: it cannot tell a forgotten account from an unseen one
without a service history.

Two things this exposed. Sessions had to start keeping the source documents so
a record can be re-reconciled rather than re-uploaded — memory only, same
expiry. And the shared demo accounts had to fork into a private session on
edit, or one judge typing dates would have changed what every other judge saw.

**540 assertions across 17 suites.** Deployed.

---

## 23 Aug 2026 — the repository history is reconstructed

This project was built without version control. The git history was created
afterwards, in one sitting, by committing the finished tree in dependency order.

That is worth stating here rather than leaving for someone to infer, because the
commit dates do not say it themselves. They are spread across 20–22 August,
which is when the work genuinely happened — the file timestamps agree — but they
were all written on the 23rd. The history is an honest reconstruction of a real
build, not a record kept as it went.

The distinction matters for exactly one reason: a reader is entitled to assume a
commit is a contemporaneous record unless told otherwise. Here it is not. Each
commit's *content* is what was built, its *message* was written with hindsight,
and no commit was ever a checkpoint anyone worked from.

`Co-Authored-By: Codex` on 35 of those commits is accurate — Codex wrote that
code. It was applied retrospectively along with everything else.

## 23 Aug 2026 — a date of birth that was not a fixture

`14-08-1992` appeared in the sample passbooks, in the parser fixtures, in three
test suites, and in the on-screen help explaining that Form 26AS is locked with
your date of birth as DDMMYYYY. One real date, reused as convenient filler and
then shipped.

Nothing about it was load-bearing, which is the point: it survived because it
never caused a failure. Replaced throughout with `25-12-1990`, chosen so the day
cannot be read as a month and the example still teaches the format.

One test failed on the change, and it deserved to. `dob.month == 8` was standing
in for *"the date of birth is still not mistaken for a joining date"* — a check
that passes for any wrong date sharing a month with the right one. It now
asserts the whole date.

**Rule.** A placeholder is a decision, not a leftover. If a real value is easier
to type than an invented one, it will end up in the product.
