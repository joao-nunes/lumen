# Spec 011: Redaction and pseudonymization

**Status:** Draft. The owner decided Q1–Q12 in discussion (§7); Q13–Q17 are open (§8)
**Builds on:** spec 006 (local model, Ollama controls), spec 010 (personal context). Next Milestone 3 slice.

## 1. Goal

`PROJECT.MD` §8 lets a hosted LLM see only Tier 1 data: text the local model has redacted or pseudonymized. Lumen can't produce Tier 1 yet, so no hosted call can be made safely. Every hosted feature in Milestones 4–7 depends on this.

This spec builds a local library that turns Tier 0 text into Tier 1 text and back:

> "Ana criticised my report at Deloitte again, and I couldn't sleep before my session with Dr. Costa on Tuesday."
>
> becomes "[PERSON_1] criticised my report at [ORG_1] again, and I couldn't sleep before my session with Dr. [PERSON_2] on Tuesday."

A reply from a hosted model such as "It sounds like feedback from [PERSON_1] weighs on you" becomes "…feedback from Ana…" before the person sees it. This last step is **re-hydration**.

It also answers the question Milestone 4 depends on: **can a local model find identifiers well enough?** The answer is a measured recall, not a promise.

**What redaction protects, and what it doesn't.** It hides *who* and *where*. It does not hide *what*: "[PERSON_1] criticised me and I couldn't sleep" still describes a mental state, which is why Tier 1 is still treated as sensitive. Redaction is best-effort (`PROJECT.MD` §8); local-only mode is the answer for anyone who wants nothing to leave the machine.

### Non-goals
- **Any hosted-model call, the hosted gateway, and the hosted-call audit log.** These are spec 012 (Q12). This spec ships no API, no screen and no caller.
- **Local-only mode.** It switches off hosted calls, so it belongs with the gateway in spec 012. So does cleaning up the unused `OPENAI_API_KEY`, `MODEL_NAME` and `LOCAL_ONLY_MODE` placeholders in `.env.example`.
- **Embeddings and pgvector.** Their main use is retrieval over journal entries (Milestone 5), and nothing is stored to embed yet.
- **Persisting a pseudonym map,** including for a conversation that survives a restart (§3).
- **Unique events and traits** (Q8), such as "I won the 2024 regional chess title". §2.1 explains.

## 2. Proposed decisions

### 2.1 What gets replaced

The owner's decisions Q1–Q8 (§7), from comparing HIPAA Safe Harbor, the i2b2 2014 de-identification categories, Microsoft Presidio's default entities and GDPR Article 9.

**Replaced**, each with its own placeholder:

| Placeholder | What | Examples |
|---|---|---|
| `[PERSON_n]` | People's names, including first names alone, surnames, nicknames, the person's own name, therapists and doctors | Ana, Sr. Rui, Aninhas, Dr. Costa → Dr. `[PERSON_n]` |
| `[ORG_n]` | Organizations: employers, schools, hospitals, clinics, teams, named shops | Deloitte, Hospital de Santa Maria, Benfica |
| `[ADDRESS_n]` | Street addresses and postcodes | Rua Augusta 12, 1100-053 |
| `[PLACE_n]` | Cities, towns and smaller places (Q1) | Porto, Cascais, Brixton |
| `[CONTACT_n]` | Phone numbers, emails, URLs, social handles, usernames, IP addresses | +351 912 345 678, `@ana.s`, ana@example.com |
| `[ID_n]` | Official and account numbers | NIF, Cartão de Cidadão, SNS number, passport, IBAN, card numbers, car plates |
| `[DATE_n]` | Dates personal to the person (Q2) | "my birthday, 3 May", "our anniversary on the 14th" |
| `[NAME_n]` | Pets and other named things (Q7) | the dog Rex, a band someone plays in |
| `[ROLE_n]` | Distinctive titles that point to one person (Q4) | "the only paediatric surgeon in town" → "the only `[ROLE_1]` in town" |

**Kept**, because removing them would empty the text of meaning:

- **Relationship words** (Q5): my sister, my boss, my therapist, my ex.
- **Countries** (Q1): Portugal, England.
- **Weekdays and relative dates** (Q2): Tuesday, yesterday, last week.
- **Ages** (Q3): "my 7-year-old".
- **Generic roles** (Q4): manager, nurse, teacher. Only a distinctive title becomes `[ROLE_n]`. The line is fuzzy, so the evaluation set includes both kinds and measures it.
- **Sensitive content** (Q6): health conditions, medication, diagnoses, religion, politics, sexual orientation, ethnicity. They're often what the person is reflecting on. They stay in Tier 1, and local-only mode is the way to keep them home.

**Out of scope: unique events and traits** (Q8), such as a rare award or a well-known accident. No detector catches them reliably, and promising to would be a promise Lumen can't keep. The spec states this as a known limitation rather than a gap.

### 2.2 How identifiers are found: rules plus the local model

The owner chose option D: two detectors, each covering the other's weakness. Both run on the raw text, on this machine, and their findings are combined.

**Rules** find identifiers with a fixed shape. They're deterministic and fully unit-tested, in Portuguese, English and mixed text (Q9):

- Emails, URLs, IPv4 and IPv6 addresses, social handles (`@name`).
- Phone numbers: Portuguese (`+351`, and nine digits starting with 2 or 9), and international ones starting with `+`.
- IBANs (checked with their checksum), card numbers (Luhn), Portuguese NIFs (their check digit), Cartão de Cidadão numbers.
- Portuguese postcodes (`dddd-ddd`). UK and US postcodes are too easy to confuse with ordinary words and numbers, so they're left to the model.
- **Any run of seven or more digits,** allowing spaces or dashes inside, as `[ID_n]`. This catches account and reference numbers no rule names. Ordinary numbers in a journal ("10000 steps", "slept 6 hours") are shorter.

**The local model** finds everything that needs context: names, organizations, places, personal dates, pets, distinctive titles. It tells "Joy" the person from joy the feeling, and "Rosa" the friend from the colour.

**The model only points; code replaces.** The model returns a list of findings, `[{"text": "Ana", "type": "PERSON"}, …]`, and never rewrites the text. Deterministic code makes every replacement. So the model can't quietly change the meaning, drop a sentence or invent content, in line with "LLMs interpret, code computes". The code also checks every finding, as spec 006 checks quotes:

- **A finding not in the text is ignored.** Models invent findings.
- **A type outside the nine is ignored.**
- **Every occurrence is replaced,** matching whole words, ignoring case and keeping accents distinct, so "Ana" never matches inside "Banana" and "ana" is still Ana.
- **Longer findings are replaced first,** so "Ana Silva" isn't left as "[PERSON_1] Silva".

**Names in the personal context are always replaced** (Q16). People and places the person mentions in their personal context (spec 010) are the ones most likely to recur, so they're replaced by exact match whether or not the model notices them in a given text. This uses the personal context only on this machine, so spec 010's Q5 still holds: the context never reaches a hosted model.

**A last check runs on the output.** After replacement, the rules and the known names run again over the pseudonymized text. Anything they still find is a bug, and the call fails rather than return the text.

### 2.3 If the local model is unavailable: fail closed

The owner chose Q10 (a). If Ollama isn't running, times out, or returns something unusable, redaction raises `RedactionUnavailableError` and returns no text at all. **It never falls back to rules alone**, because rules miss names, and names are what journals are full of. Spec 012's gateway will turn this error into "the hosted call is blocked, and the person is told why".

The error carries no text, as `SuggestionsUnavailableError` does (`from None`), because exceptions can quote the request.

### 2.4 Placeholders and re-hydration

- **Numbering** starts at 1 per type, in order of first appearance.
- **Placeholders already in the text.** If someone writes "[PERSON_1]" themselves, numbering skips 1 for that type. Their literal text then stays literal through re-hydration, because only placeholders Lumen issued are mapped back.
- **Re-hydration** replaces exactly the issued placeholders, such as `[PERSON_1]`. A placeholder Lumen didn't issue, such as `[PERSON_9]` invented by a hosted model, is left as it is. How tolerant re-hydration should be of a hosted model's variations, such as "Person 1" without brackets, depends on real replies, so spec 012 measures and decides it.

### 2.5 Code

- **A new package `lumen.privacy`,** as `PROJECT.MD` §15 planned, with `redaction.py`. Its prompt lives in `src/lumen/privacy/prompts/`, one file per version (Q17).
- **`IdentifierDetector` is a `Protocol`,** a real seam: the Ollama detector in production, a fake in unit tests. The rules aren't behind it; they always run.
- **`pseudonymize(text, known_names, detector) -> Pseudonymized`** returns the Tier 1 text and its map. **`rehydrate(reply, pseudonymized) -> str`** maps a reply back.
- **`Pseudonymized` holds the map in memory only,** and has no way to be saved (§3). Its `repr` hides the map and the original text, so neither reaches a log or a traceback by accident.
- **The Ollama detector keeps every control spec 006 set:** `check_local_only` at construction, a loopback address only, no cloud models, `trust_env=False`, no redirects, temperature 0. The HTTP call and these controls move to one shared place in `lumen.privacy` rather than being copied, so a future change can't weaken one copy.
- **The same `OLLAMA_URL` and `OLLAMA_MODEL`** as suggestions. A separate model setting only becomes worth adding if the measured model misses the bar here and another one passes.
- **Nothing is logged.** There's no route yet, so nothing new reaches `EventLog`.

### 2.6 Measuring it

As for extraction (spec 006 §3), an evaluation set decides whether the local model is good enough, and **implementation stops if no model meets the bar.** The bar is never lowered silently.

**The evaluation set** goes in `evals/redaction/`:

- **Synthetic only, because this repository is public.** No real journal text is ever committed.
- **About 210 entries:** a `dev` split of 60 for tuning the prompt, and a held-out `test` split of 150, split evenly between English, Portuguese and mixed text. The held-out entries are written and committed **before the prompt**, and aren't looked at until the measurement.
- **Each entry lists its identifiers** with their type, and its **decoys**: words that look like identifiers but must be kept.
- **Hard cases on purpose:** names that are also words (Rosa, Joy, Graça, Hope), lowercase and misspelt names, nicknames, pets, personal dates next to relative ones, cities next to countries, distinctive titles next to generic roles, names inside possessives ("Ana's"), and about 10 distressing entries, which must return valid output rather than fail.
- **Decoys** include relationship words, emotions, medication, countries, generic roles, ages and weekdays.

**What's measured, per language** (English, Portuguese, mixed):

| Metric | What it catches | Bar |
|---|---|---|
| **Recall, direct identifiers** (`PERSON`, `ORG`, `ADDRESS`, `CONTACT`, `ID`) | A name or number reaching the hosted model | Q13 |
| **Recall, contextual identifiers** (`PLACE`, `DATE`, `NAME`, `ROLE`) | A place, personal date, pet or distinctive title leaking | Q13 |
| **Decoys kept** | Over-redaction that garbles the text | Q13 |
| **Leak-free entries:** entries with no missed identifier at all | The person's real experience: one miss is a leak | Reported, no bar |
| **Right type,** of caught identifiers | `[PLACE_1]` where `[ORG_1]` belonged | Reported, no bar |
| **Time per text,** 95th percentile, model loaded | Redaction will sit in front of every hosted call | Under 10 seconds |

**An identifier counts as caught** when none of its occurrences is left in the output, whatever type it was given. A wrong type is a quality problem, not a privacy one.

**Rule-shaped identifiers must all be caught** on the evaluation set: a miss there is a bug in the rules, not a model limitation.

A held-out run that meets every bar records the prompt's hash in `evals/redaction/measured_prompt.json`, and a test fails if the prompt changes afterwards, as for extraction.

### 2.7 Delivery: two PRs, with a stop in between

1. **The deterministic part, and the evaluation set.** Rules, replacement, known names, re-hydration and fail-closed, tested with a fake detector. The evaluation set is committed here, so the held-out split exists before any prompt is written.
2. **The Ollama detector, its prompt, `make eval-redaction` and the measurement.** If no model meets the bar, implementation stops and the options go to the owner.

## 3. Decision record: the pseudonym map lives for one exchange, in memory

The owner asked for this decision (Q11) to be documented in full, because it shapes every hosted feature after it.

**Context.** A pseudonym map pairs each placeholder with what it replaced, such as `PERSON_1 → Ana`. It's Tier 0. Re-hydration needs it, so it must exist at least as long as it takes a hosted model to reply. The question is how much longer.

**The fact that decides it.** Hosted LLMs keep no memory between calls. Lumen sends all the context a call needs every time. So pseudonyms only need to be consistent within what one exchange sends, never across exchanges.

**Options considered.**

| Option | Consistency | Cost |
|---|---|---|
| **(a) One exchange, in memory only.** An exchange is one hosted call, or later one multi-turn conversation | Ana is `[PERSON_1]` throughout the exchange; next time she may be `[PERSON_3]` | Nothing new is stored |
| (b) One map per person, saved | Ana is always `[PERSON_1]` | A saved list of everyone in the person's life, and stable pseudonyms the provider can link |

**Decision: (a).**

**Why (b) was rejected.**

- **It would create the most sensitive table in Lumen:** a roster of the people in someone's life, with each one's real name. Even with RLS, a leaked database would expose it, and every new feature would need to reason about it.
- **Stable pseudonyms make the provider's records linkable.** If Ana is `[PERSON_1]` for months, a provider's logs show one person who keeps criticising the user's work, and details from many requests add up to a profile that may identify her. Changing pseudonyms on every exchange keeps each request separate.
- **It buys nothing today.** Nothing sent to a hosted model needs to refer to an earlier exchange's pseudonyms, because each call carries its own context.

**Consequences.**

- **What Lumen saves is always the re-hydrated reply,** which is Tier 0 and stays local. Nothing saved ever contains a placeholder that needs an old map.
- **The same person gets different placeholders in different exchanges.** A feature that sends several texts in one call, such as a weekly review, must pseudonymize them together as one exchange, so Ana is the same placeholder across them.
- **There is nothing to delete, migrate, protect with RLS or include in an export.** The map disappears when the exchange ends.
- **In code,** `Pseudonymized` lives in memory and has no table, no file and no cache behind it. Saving it would mean writing new code, which a review would see.

**Limitations.**

- **A conversation that survives a restart** would need its map saved, encrypted or under RLS. Conversations arrive in Milestone 4, so that spec decides it.
- **Memories and summaries** that a hosted model writes come back re-hydrated, so they hold real names locally, as Tier 0 should.

**When to revisit.** When a feature needs a hosted model to refer to a placeholder from an earlier exchange, or when conversations need to survive a restart. Either change comes back to the owner as a new decision, with this record as its starting point.

## 4. Acceptance criteria

**First PR: the deterministic part** (with a fake detector)

- **AC-1 (replacement):** with the detector finding Ana and Costa as `PERSON` and Deloitte as `ORG`, *"Ana criticised my report at Deloitte again, and I couldn't sleep before my session with Dr. Costa on Tuesday."* becomes exactly *"[PERSON_1] criticised my report at [ORG_1] again, and I couldn't sleep before my session with Dr. [PERSON_2] on Tuesday."*, and the map holds exactly those three pairs.
- **AC-2 (every occurrence, whole words):** *"Ana Silva called. ana was upset. Bananas for lunch. Ana's day was hard."*, with findings "Ana Silva" and "Ana", becomes *"[PERSON_1] called. [PERSON_2] was upset. Bananas for lunch. [PERSON_2]'s day was hard."*: the longer finding is replaced first, case is ignored, and "Bananas" is untouched. (How "Ana" and "Ana Silva" should relate is Q15.)
- **AC-3 (findings are checked):** a finding not in the text, and a finding with an unknown type, are both ignored, and the rest of the reply is still used.
- **AC-4 (rules without the model):** with the detector finding nothing, each of `ana@example.com`, `https://example.com/ana`, `@ana.s`, `+351 912 345 678`, `912 345 678`, a valid Portuguese IBAN, a valid NIF, a card number that passes Luhn, `1100-053`, `192.168.1.10` and `12345678` is replaced with the right placeholder type, in an English and a Portuguese sentence. An IBAN or NIF with a wrong check digit is caught only by the seven-digit rule, as `[ID_n]`.
- **AC-5 (decoys under the rules):** *"My sister, 34, works as a nurse in Portugal. Slept 6 hours, walked 10000 steps on Tuesday, took 50 mg of sertraline."* comes back unchanged with a detector that finds nothing.
- **AC-6 (known names):** with the personal context naming Ana and a detector that misses her, *"Ana again."* still becomes *"[PERSON_1] again."*.
- **AC-7 (re-hydration):** after AC-1, the reply *"Feedback from [PERSON_1] at [ORG_1] weighs on you; [PERSON_9] isn't mentioned."* becomes *"Feedback from Ana at Deloitte weighs on you; [PERSON_9] isn't mentioned."*.
- **AC-8 (placeholders already in the text):** *"I wrote [PERSON_1] in my notes. Ana called."* becomes *"I wrote [PERSON_1] in my notes. [PERSON_2] called."*, and re-hydrating *"[PERSON_1] and [PERSON_2]"* gives *"[PERSON_1] and Ana"*.
- **AC-9 (fail closed):** when the detector raises, times out or returns malformed output, `pseudonymize` raises `RedactionUnavailableError`, returns no text, and the error's message, `repr` and chained exceptions contain none of the input.
- **AC-10 (last check):** with a detector fake that makes the replacement leave a rule-shaped identifier behind, the call fails rather than return text. (This guards the last check itself; in normal use it never fires.)
- **AC-11 (nothing leaks through `repr`):** the `repr` and `str` of a `Pseudonymized` contain neither the original text nor any real value from the map.

**Second PR: the model and its measurement**

- **AC-12 (local only):** the Ollama detector refuses a non-loopback URL and a cloud model, sends with `trust_env=False` and without following redirects. The shared transport is the one suggestions use.
- **AC-13 (measured):** `evals/redaction/measured_prompt.json` holds the hash after a held-out run that meets every bar, and a test fails if the prompt then changes.

**Untested by justification**

- **The model's judgement** (names versus words, distinctive titles, personal dates): the evaluation measures it, which is stronger than a few unit tests with a real model.
- **That the map is never saved:** there's no table, no file and no cache for it, and `Pseudonymized` has no method to save it. A test can't prove code doesn't exist; a review sees any that's added.

## 5. Mutation check

A new `redaction` group in `make mutate`, because this is security-critical:

- a finding not in the text is used anyway
- matching ignores word boundaries, or is case-sensitive
- shorter findings are replaced first
- one rule is removed (each of: email, phone, IBAN, NIF, seven digits)
- a check digit isn't verified, or is verified wrongly
- known names aren't applied
- a detector error falls back to rules only
- the error chains the original exception
- the last check is skipped
- re-hydration maps a placeholder that wasn't issued
- numbering doesn't skip a placeholder already in the text
- `repr` shows the map

One-off faults under the project workflow: a reply cut off mid-JSON, a very long text, a finding that overlaps another ("Ana" inside "Ana Silva" in the other order), and the same name with and without an accent ("Inês", "Ines").

## 6. Delivery

1. This spec, and the `PROJECT.MD` §8 update that records §2–§3.
2. The two PRs of §2.7, each with its tests failing first, fault injection, and an "Added during implementation" section here.

## 7. Decisions

Decided by the owner in discussion before this draft.

| # | Question | Decision |
|---|---|---|
| Q1 | Cities, regions, countries? | **Cities and towns become `[PLACE_n]`; countries are kept.** |
| Q2 | Dates? | **Weekdays and relative dates are kept; dates personal to the person become `[DATE_n]`.** |
| Q3 | Ages? | **Kept.** |
| Q4 | Professions and job titles? | **Generic roles are kept; distinctive titles are replaced.** The line is fuzzy, so the evaluation set includes both and measures it. The `[ROLE_n]` placeholder is this draft's proposal. |
| Q5 | Relationship words? | **Always kept.** |
| Q6 | Sensitive content (health, medication, religion, politics, orientation, ethnicity)? | **Kept in Tier 1.** Local-only mode is the opt-out. |
| Q7 | Pets and named things? | **Replaced as `[NAME_n]`.** |
| Q8 | Unique events and traits? | **Out of scope, stated as a known limitation.** |
| — | How are identifiers found? | **Rules plus the local model (option D).** The model only points; code replaces. Names in the personal context are always replaced. Recall is measured. |
| Q9 | Which languages? | **Portuguese, English, and the two mixed.** The rules include Portuguese formats, and the evaluation set has all three. |
| Q10 | If the local model is unavailable? | **Fail closed:** no text is returned, and spec 012's gateway blocks the hosted call. |
| Q11 | How long does a pseudonym map live? | **One exchange, in memory only.** Full record in §3. |
| Q12 | What uses redaction first? | **Nothing yet:** this spec is the library and its measurement; spec 012 adds the hosted gateway and the audit log. |

## 8. Open questions

**Q13. What are the bars?** Proposed, per language, for the owner to approve before the held-out run, as with spec 006:

- **Direct identifiers recall: at least 95%.** These are what identify someone on their own.
- **Contextual identifiers recall: at least 85%.** Places, personal dates, pets and distinctive titles identify less on their own, and are harder to judge.
- **Decoys kept: at least 90%.** Over-redaction costs reflection quality, not privacy.

I haven't measured any model on this, and I found no published figure for local models on mixed Portuguese and English. With about 150 direct identifiers per language, a measured 95% is good to about ±3.5 points. Is 95% enough for something whose failure is a leak, or should direct identifiers aim higher, accepting that the run may stop?

**Q14. Who labels the evaluation set?** Proposed: I write the entries and labels, and the owner marks the identifiers in 30 held-out entries blind, as in spec 006. Agreement shows how fuzzy the line is, especially for distinctive titles (Q4) and personal dates (Q2).

**Q15. Should "Ana", "Ana Silva" and "Aninhas" share a placeholder?** Proposed: **no, each different text gets its own placeholder** in this spec. The hosted model then sees `[PERSON_1]` and `[PERSON_2]` without knowing they're the same person, which costs some reflection quality but can never merge two different people. Grouping could come later, from the model's findings or from the person.

**Q16. Where do known names come from?** Proposed: **the same detector, run on the personal context** in each exchange. It needs no new storage or screen. The alternative is a list of people and places the person maintains themselves: more reliable, but a new page and a new Tier 0 table. That could follow if the measurement shows misses on recurring names.

**Q17. Where do prompts live?** `CLAUDE.md` says prompt wording lives in `src/lumen/suggestions/prompts/`. Proposed: **each package keeps its own `prompts/` folder,** so the redaction prompt goes in `src/lumen/privacy/prompts/`, and `CLAUDE.md` says "in a `prompts/` folder next to the code that uses it, one file per version". Changing `CLAUDE.md` needs the owner's approval.

## 9. Added during implementation (for review)

Nothing yet.
