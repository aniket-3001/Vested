# Vested — submission write-up

**Check your PF record before you claim.**
Live demo: https://vested-251148844884.asia-south1.run.app

### Sign in — working test credentials

| | UAN | Password | What it shows |
|---|---|---|---|
| **Rahul Kumar Singh** | `100999888777` | `rahul` | Three employers, a wrong exit date, a missing one, and a PF account he does not know exists. |
| **Priya Menon** | `100777666555` | `priya` | One employer, every record agreeing. Proof the checker can say *yes*. |

Both are synthetic. No real person's data appears anywhere. You can also upload
your own Form 26AS or PF passbook — nothing is stored and nothing leaves the server.

---

## The problem

**Roughly one in five EPF claims is rejected.** Of about **796 lakh claims in 2024–25, some 174 lakh were rejected** — a rate of ~22%, down from 29% in 2021–22 but against sharply higher volume.

EPFO cites a **sub-1%** rejection rate. That figure counts office-level rejections after auto-settlement; the ~22% counts every claim filed. **The official number and the member's experience differ by more than twentyfold**, and it is the second number people live in.

Most of them come down to three fields: **date of joining, date of exit, overlapping service.** Usually one wrong date, typed by an employer years ago.

The structural cruelty is this:

> A member can now self-mark a *missing* exit date. But a wrong date of joining, an already-wrong exit date, or overlapping service can still only be corrected by the employer — a company that may have dissolved, ignores the request, or has no reason to help. **A person's savings are gated on the data hygiene of every employer they have ever had.**

That one exception is worth building on rather than glossing over: EPFO offers the *screen* and asks the member for the *date*. Form 26AS is where the date is. So we fill it in.

You find out three weeks after filing. The rejection reason is a code. Nobody tells you which field is wrong, or who can fix it.

Separately, **₹9,330 crore** sits in inoperative EPF accounts — money belonging to people who changed jobs before UAN linkage and never transferred the balance.

## Who it affects

Around 30 crore UAN accounts. The people worst hit are the ones with the most employers and the least leverage: contract workers, people who changed jobs early in their careers, and anyone whose employer has since shut down. They are also least able to spend three weeks discovering that a date is wrong.

## The insight this is built on

Form 26AS, on the Income Tax portal, records **TDS by employer, month by month, with each employer's TAN**. That is an independent, government-held, *citizen-accessible* record of exactly when a person worked where.

**Income Tax records can prove the EPFO service record wrong.**

No inter-departmental data-sharing agreement is needed, because **the citizen is the consent bridge** — they download their own records and bring them. That is what makes this buildable today rather than a policy proposal.

## What we built

The EPFO member portal, rebuilt around one question: **will my claim be rejected, and why?**

The real portal has a *View* menu and a *Manage* menu. We rebuilt both.

**Reading your record**

- **Home** — whether you can claim today, and what is stopping you
- **Your record** — employment history, tested against your own tax documents
- **Accounts** — every PF account in your name, including ones never linked to your UAN
- **Pension** — EPS balance and the ten-year line
- **Withdraw** — the three merged advance categories, checked against your service
- **Claim** — the rejection checks, run before you file rather than three weeks after
- **Track** — how long each step is legally supposed to take
- **Profile** — your name as each document spells it, and which to standardise on

**Doing something about it**

- **Mark Exit** — the highest-leverage screen here. EPFO gives members the form and asks for a date; **we read the date from Form 26AS**, so we can fill in the answer the member is otherwise asked to guess.
- **KYC** — the bank-name mismatch that silently fails claims *after* approval is a name-comparison problem, and comparing names across documents is what this engine already does.
- **e-Nomination** — who receives the money if you die before you claim it.
- **Transfer** — One Member–One EPF Account. We find the forgotten account, then offer the form that recovers it.
- **UAN card** — every member ID under one number, assembled from your own passbooks. It does one thing the official card cannot: **say out loud when two of your accounts disagree about your date of birth** — a named cause of rejection.
- **Service history** — the gap that turned out not to be ours. The UAN portal shows service history as an on-screen table with **no download button**, so members screenshot it. A screenshot has no rows, and OCR guessing at a date is exactly the failure this product exists to catch — a misread digit is indistinguishable from the employer error we are hunting. So we ask: two dates per account, member IDs already filled in from the passbooks. The typed dates are rebuilt into the same document the file parser reads, so they travel the identical code path.
- **Contact details** — thin on its own, and load-bearing: under EPFO 3.0, auto-settlement, UPI, ATM, e-Nomination and Mark Exit are *all* gated on an OTP to the Aadhaar-linked mobile. A dead number silently closes every digital route, and nobody tells you that is why.

For each defect found, it drafts the correction — Joint Declaration, evidence annexure, grievance, or transfer request — with every factual assertion pointing back to the document row that supports it, and tells you which of the four routes actually applies.

### Why this matters more under EPFO 3.0

EPFO is mid-rebuild: auto-settlement raised to ₹5 lakh, thirteen withdrawal categories merged into three, UPI and ATM withdrawal, and **employer approval removed** in favour of automated system checks. 2.34 crore advance claims settled automatically in FY 2024-25 — 59% of all advances.

The obvious reading is that EPFO is fixing itself. It is the opposite:

> **EPFO 3.0 automates the decision. It does not fix the data the decision is made on.** Service continuity is an explicit automated gate. Automating a judgement made against a wrong service record does not reduce rejections — it industrialises them, and removes the human you could previously have appealed to.

A pre-flight check is *more* necessary in an auto-settled world, not less. Every claim screen models this gate directly.

## How it works

The architecture has one governing rule:

> **Models at the edges, where language is messy. A deterministic solver at the core, where the answer must be auditable.**

The output is a document that gets signed and handed to a government office. Every inference in it has to be cross-examinable, so the reconciliation core is deterministic by design — a member can contest a specific step, and the same documents always produce the same result.

Three ideas do most of the work:

**Weighted interval reconciliation.** Evidence arrives at different granularities — 26AS is day-exact, the EPF passbook is monthly, a bank statement is transactional. Each source carries a reliability model, and contradictions are ranked by how much they actually block a claim.

**The arithmetic backstop.** Extracted 26AS rows must reconcile to the deductor's stated total within ₹1. Extractions that fail are rejected, never passed downstream. *The parser proposes; the checker disposes.* This caught a real parsing failure on real documents (below).

**The claim gate.** Before any letter is shown, it is re-read as a *rendered artifact* and every factual token must resolve to a ledger entry in the correct employer scope. It blocks invented values, real values attributed to the wrong employer, speculative phrasing in a legal filing, and assertions with no annexure. **The gate does not trust the renderer's account of itself.**

One invariant is enforced in code: **the engine can propose corrections but has no path to deny a claim.** Robodebt and the Dutch childcare benefits scandal both began as automated systems that could refuse people. This one cannot.

## What we changed, and why

**It refuses to guess.** Without a service history there is nothing to test evidence against, so the reconciler would mark every employer an orphan — including ones whose passbook it is holding. Those findings are withheld rather than shown, and the page says what it could not see.

**"No findings" is not "you are fine."** An unchecked record reports *Not yet known*, never *Yes*. Absence of evidence must never render as good news.

**Any one document is enough to start.** The EPFO portals are frequently down. Demanding a fixed set of four documents turns people away with nothing; the app now accepts whatever they could obtain and narrows its claims honestly.

## Tested against real documents

This is the part we would most like scrutinised. The prototype was run against a real member's records — ten EPF passbook PDFs, three TRACES Form 26AS exports, and a scan — using structure-only probes so no personal data was ever displayed.

It found **eleven defects that no synthetic test had caught**, including:

- The TRACES export is `^`-delimited, not tabular. **Zero transactions parsed** — while the employer summary rows loaded fine, so the file looked correct. The arithmetic backstop is what caught it.
- The row scanner read transaction dates as money: a row dated `31-08-2023` became `employee=₹31, employer=₹8, pension=₹2023`, producing a confident and entirely wrong balance.
- A real 26AS is mostly **section 194A — bank interest**, not salary. Every TDS entry was being read as employment, which would have made the member's **bank an employer** and then invented a forgotten PF account for it.
- Form 26AS is issued per assessment year. Only the first file was kept — while all three were reported as "Recognised."
- Five pages returned HTTP 500 on real input, because a live passbook carries no date of joining.

Every one is now fixed and locked by tests. We think "we showed it real files and here is what broke" is worth more than a demo that has only ever seen data we wrote ourselves.

## What is functional, and what is mocked

### The check that needs no service history

Every defect class we had depended on EPFO's asserted service history — the hardest of the four documents to obtain, and the one most members cannot get when the portal is down. Which meant our answer to those members was *"not yet known"* about everything.

A **contribution gap** needs neither EPFO's claim nor its portal. If the Income Tax Department records an employer deducting tax from your salary in a given month, your own passbook shows nothing deposited that month, and you were demonstrably employed either side of it — then money was withheld from your salary and never arrived. Nothing is being compared to EPFO's assertion about you, only two records of what actually happened.

It is deliberately narrow, because every way it could be wrong is knowable in advance: only employers we hold *both* records for; only months strictly *inside* the passbook's own span, since March PF is routinely deposited in April and a final settlement produces TDS after the last contribution; consecutive months collapsed into one finding rather than six identical ones.

**On the real record this runs and comes back clean** — 2 employers matched across both documents, 9 tax-deducted months inside the contribution span, all 9 with a matching deposit. That is an earned verdict on real documents, not a shrug.

Getting there exposed one more defect, of a class we had already fixed once: **the live passbook prints the establishment mid-line, after a pipe**, so a parser requiring the line to *start* with the word found no employer name on any real file. With no name, a passbook could never be matched to the same employer in Form 26AS — which silently disabled this entire check on exactly the documents it was built for.

**Functional** — document ingestion (PDF, TXT, ZIP, password-protected, with scans refused and explained); Form 26AS parsing in both layouts, with arithmetic verification; EPF passbook parsing including multi-year merging; employer entity resolution; cross-document name matching including Devanagari; timeline reconciliation across seven defect classes; correction routing across all four EPFO pathways; letter generation; the claim gate; the EPFO 3.0 settlement model (auto-settlement ceiling, KYC gate, UPI and ATM limits); KYC review derived from your own documents; Mark Exit dates computed from Form 26AS; two mock accounts with working sign-in; every page.

**Mocked** — e-Nomination status and bank/Aadhaar KYC status live inside EPFO and cannot be read, so those are reported as *not visible to us* rather than guessed; the guidance around them is real. The EPFO establishment directory holds **four entries**. Real establishment lookup is not built, so orphan-account recovery resolves employers against a stub. Balance estimates for orphaned accounts are deliberately a wide labelled range, because PF accrues on basic pay while 26AS reports gross.

**Not built** — submission to EPFO. No API exists, and the rules forbid touching live systems. Letters are handed to the member to file themselves.

## Known limitations

1. **Sub-TDS-threshold earners are invisible to Form 26AS** — often the lowest paid, who need their PF most. The passbook alone still reveals overlaps and gaps; 26AS is an upgrade, not the floor.
2. **The employer remains the gatekeeper** for joining-date and overlap corrections. We make the request trivial and evidenced. We cannot compel anyone to act.
3. **Typed dates are only as good as the typing.** Where a service history is transcribed rather than uploaded, a mistyped date produces a wrong finding. The form refuses anything ambiguous — ISO order, impossible dates, an exit before a joining date — but it cannot catch a plausible wrong date. Contribution checking runs on the real record with no transcription at all.
4. **Scanned documents are rejected**, not read.
5. **Sessions are in memory** and do not survive a restart.

## Privacy

Nothing is written to disk. No database, no accounts, no stored documents. No filename, content, or extracted text is logged. Sessions expire in 30 minutes. Nothing is submitted to any government system, and no data leaves the server — the prototype runs entirely on local deterministic rules.

## Tools

Python and Flask, server-rendered HTML. No JavaScript, no web fonts, no client framework, no build step. The stylesheet is served once from a content-hashed, permanently cacheable URL rather than inlined into every page, so **the mean page is 4.0 KB and the heaviest is 5.7 KB** — and every page is readable with CSS disabled, because the people who need this most are on slow connections and cheap phones. Deployed on Google Cloud Run.

Test coverage: **540 assertions across 17 suites**, including a crawler that renders every reachable page against six different combinations of missing documents, and an invariant that every correction route the reconciler can emit must produce guidance a member can act on — a finding with no path forward is worse than no finding.
