# Spec 011: Redaction and pseudonymization

**Status:** Draft. The owner decided Q1–Q17 (§8) and approved the reviews' fixes (§8.1–§8.3).
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

## 2. Decisions

### 2.1 What gets replaced

The owner's decisions Q1–Q8 (§8), from comparing HIPAA Safe Harbor, the i2b2 2014 de-identification categories, Microsoft Presidio's default entities and GDPR Article 9.

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
- IBANs and Cartão de Cidadão numbers, by their shape: a country code and digits, or eight digits, a check digit and two letters and a digit. Both mix letters into the number, so the seven-digit rule alone would leave pieces of them behind.
- Portuguese NIFs, by their check digit, **written like a phone number:** nine digits together or as three groups of three separated by single spaces, so the check digit alone decides between the two. **The check digit is the only thing that decides the type of a nine-digit number starting with 2 or 9:** with a valid check digit it's a NIF, `[ID_n]`, and otherwise the phone rule makes it `[CONTACT_n]`. Either way it's replaced.
- **No other checksum.** An IBAN with a wrong mod-97 or a card number that fails Luhn would still be replaced by its shape or by the seven-digit rule, as `[ID_n]`, so those checks would change nothing a test could observe (review finding 2). Card numbers are caught by the seven-digit rule.
- Portuguese postcodes (`dddd-ddd`). UK and US postcodes are too easy to confuse with ordinary words and numbers, so they're left to the model.
- **Any run of seven or more digits,** allowing spaces or dashes inside, as `[ID_n]`. This catches account and reference numbers no rule names. Ordinary numbers in a journal ("10000 steps", "slept 6 hours") are shorter.
  - **Except dates and year ranges,** which journals often contain and Q2 keeps: a valid calendar date written `yyyy-mm-dd` or `dd-mm-yyyy`, and two years from 1900 to 2099 joined by a dash, optionally with spaces, the second not earlier than the first ("2019-2021", "1990 - 2000"). Anything else that only looks similar, such as "2024-13-45" or "1234-5678", is still `[ID_n]`. **Dates and ranges are matched first, as whole tokens with no digit directly before or after, and a run of digits never extends across one:** in "on 2024-05-03 8 hours" the date is kept and "8" is too short, rather than "2024-05-03 8" being read as one nine-digit run. **This applies to every digit rule,** phone, NIF and postcode as well as the seven-digit catch-all: none of them matches across or inside a date or range. **Phone, NIF and postcode matches are whole tokens,** with no digit or letter directly before or after. So nine digits inside a 16-digit card number or an IBAN never become `[CONTACT_n]`, and neither "2019-202" inside "2019-2021" nor "1234-567" inside "1234-5678" is read as a postcode. A date personal to the person is still the model's job, as `[DATE_n]` (review finding 8).
  - **Numbers grouped in threes stay caught** ("1 500 000 euros" becomes `[ID_n]`). Excluding them would let an account number written "123 456 789" through, so this over-redaction is accepted.

**The local model** finds everything that needs context: names, organizations, places, personal dates, pets, distinctive titles. It tells "Joy" the person from joy the feeling, and "Rosa" the friend from the colour.

**The model only points; code replaces.** The model returns a list of findings, `[{"text": "Ana", "type": "PERSON"}, …]`, and never rewrites the text. Deterministic code makes every replacement. So the model can't quietly change the meaning, drop a sentence or invent content, in line with "LLMs interpret, code computes". The code also checks every finding, as spec 006 checks quotes:

- **A finding not in the text is ignored,** and the rest of the reply is used. Models invent findings, and an invented one has nothing to leak.
- **The types are constrained by the request's JSON schema,** an enum of the nine, which Ollama enforces. A type outside the nine anyway makes the reply malformed (below), so the call fails closed. Dropping the finding instead would let a name the model pointed at, typed `"PERSONS"`, reach the hosted model (review finding 3).
- **Every occurrence is found,** matching whole words, ignoring case and keeping accents distinct, so "Ana" never matches inside "Banana" and "ana" is still Ana.

**A malformed reply fails closed** (review finding 7). A reply is malformed when it isn't valid JSON, or doesn't match the schema: an object with a list of findings, each with a string `text` and one of the nine types. It is *partly invalid* when it matches the schema but some findings aren't in the text: those findings are ignored and the rest are used. Nothing else is tolerated: when unsure, the reply counts as malformed.

**Replacement works on spans of the original text** (review finding 1). Every detector reports spans, start and end positions in the raw text: each rule match, each occurrence of each model finding and each occurrence of each known name. Then:

1. **Overlapping spans are merged into one,** covering both. So "Ana" inside "Ana Silva" becomes part of the one "Ana Silva" span, and a model finding that covers half a phone number can't leave the other half behind.
2. **A merged span takes the type of its highest-precedence part,** in this order: IBAN and Cartão de Cidadão (`ID`), NIF (`ID`), the contact rules (`CONTACT`), postcode (`ADDRESS`), known names, the model's findings, and last the seven-digit catch-all (`ID`). So a valid NIF starting with 2 is `[ID_n]`, not a phone number, and a phone-shaped run of digits inside an IBAN or CC number can't turn it into `[CONTACT_n]`: their letters mean they can't be confused with a phone number, so they come first. A wrong type is a quality problem, not a privacy one (§2.6), but the order makes it deterministic and testable.
3. **Each span is replaced once,** working from the end of the text to the start, so positions never shift. Spans with the same text, ignoring case, get the same placeholder, and **the map keeps the form of the first occurrence**, counting only spans left after merging, so re-hydration writes "Ana" if "Ana" came first, even where the text later says "ana".

**Names in the personal context are always replaced** (Q16). People and places the person mentions in their personal context (spec 010) are the ones most likely to recur, so they're replaced by exact match whether or not the model notices them in a given text. This uses the personal context only on this machine, so spec 010's Q5 still holds: the context never reaches a hosted model.

- **They come from the same detector, run on the personal context** (Q16). The person maintains nothing: no new page, no new table.
- **Only `PERSON`, `ORG`, `PLACE` and `NAME` findings become known names** (review finding 7). They're proper names that recur and mean the same thing wherever they appear. `ADDRESS`, `CONTACT` and `ID` are left out because the rules already catch them by shape in every text. `DATE` and `ROLE` are left out because whether they identify someone depends on the sentence: "3 May" is personal next to "my birthday" and not elsewhere, so an exact match would replace ordinary dates and titles everywhere.
- **Its result is kept in memory, never saved,** in the `Redactor` (§2.5): one entry per owner, holding a SHA-256 hash of the context's text and the names found, so the detector only runs again after the context changes. Every exchange but the first after an edit costs nothing extra. A restart empties it. If the detector fails on the context, the exchange fails closed, as in §2.3.
- **Known names match case-sensitively,** exactly as the context writes them (review finding 5). So "Rosa" the friend is replaced, but "rosa" the colour and "joy" the feeling aren't. A lowercase "rosa" meaning the friend is left to the model, which sees the context.
- **A list the person keeps themselves** is future work, if the measurement shows recurring names being missed.

**A last check runs on the output.** After replacement, the rules and the known names run again over the pseudonymized text. Anything they still find is a bug, and the call fails rather than return the text. It can't see a span that only the model found, because nothing deterministic knows that span; those rely on replacement itself being correct.

### 2.3 If the local model is unavailable: fail closed

The owner chose Q10 (a). If Ollama isn't running, times out, or returns something unusable, redaction raises `RedactionUnavailableError` and returns no text at all. **It never falls back to rules alone**, because rules miss names, and names are what journals are full of. Spec 012's gateway will turn this error into "the hosted call is blocked, and the person is told why".

The error carries no text, as `SuggestionsUnavailableError` does (`from None`), because exceptions can quote the request.

### 2.4 Placeholders and re-hydration

- **Numbering** starts at 1 per type, in order of first appearance.
- **Placeholders already in the text.** If someone writes "[PERSON_1]" themselves, numbering skips 1 for that type. Their literal text then stays literal through re-hydration, because only placeholders Lumen issued are mapped back.
- **Re-hydration** replaces exactly the issued placeholders, such as `[PERSON_1]`. A placeholder Lumen didn't issue, such as `[PERSON_9]` invented by a hosted model, is left as it is. How tolerant re-hydration should be of a hosted model's variations, such as "Person 1" without brackets, depends on real replies, so spec 012 measures and decides it.

### 2.5 Code

- **A new package `lumen.privacy`,** as `PROJECT.MD` §15 planned, with `redaction.py`. Its prompt lives in `src/lumen/privacy/prompts/`, one file per version (Q17, decision record in §4).
- **`IdentifierDetector` is a `Protocol`,** a real seam: the Ollama detector in production, a fake in unit tests. **`detect(text) -> str` returns the model's raw reply,** unparsed. Everything after that is shared deterministic code above the protocol: parsing the JSON, checking it against the schema, dropping findings not in the text, and failing closed on a malformed reply (§2.2). So the first PR tests all of it with a fake that returns raw replies, including `"PERSONS"` and invalid JSON (review finding 1). The rules aren't behind the protocol; they always run.
- **`Redactor(detector)`** is the one entry point, and owns the known-name cache (§2.2). **`Redactor.pseudonymize(text, *, owner, context) -> Pseudonymized`** finds the known names in `context` (from the cache, or by running the detector), detects identifiers in `text`, and returns the Tier 1 text and its map. A failure at either step raises `RedactionUnavailableError`.
  - `owner` is an opaque key chosen by the caller. The library has no idea of users; spec 012's gateway will pass the user's ID. The key only lives in memory and is never logged.
  - The cache holds one entry per owner and is guarded by a lock, because FastAPI runs synchronous work in a thread pool. Lumen is a personal app, so the number of owners is small and the cache isn't bounded further.
- **`rehydrate(reply, pseudonymized) -> str`** maps a reply back.
- **`Pseudonymized` holds the map in memory only,** and has no way to be saved (§3). Its `repr` hides the map and the original text, so neither reaches a log or a traceback by accident.
- **The Ollama detector keeps every control spec 006 set:** `check_local_only` at construction, a loopback address only, no cloud models, `trust_env=False`, no redirects, temperature 0. The HTTP call and these controls move to one shared place in `lumen.privacy` rather than being copied, so a future change can't weaken one copy.
- **A timeout of 60 seconds,** as suggestions use: it leaves room for the model to load on the first call (spec 006 measured 25 seconds). A timeout is a failure, so it fails closed.
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
| **Recall, direct identifiers** (`PERSON`, `ORG`, `ADDRESS`, `CONTACT`, `ID`) | A name or number reaching the hosted model | **At least 95%** |
| **Recall, contextual identifiers** (`PLACE`, `DATE`, `NAME`, `ROLE`) | A place, personal date, pet or distinctive title leaking | **At least 85%** |
| **Decoys kept** | Over-redaction that garbles the text | **At least 90%** |
| **Leak-free entries:** entries with no missed identifier at all | The person's real experience: one miss is a leak | Reported, no bar |
| **Right type,** of caught identifiers | `[PLACE_1]` where `[ORG_1]` belonged | Reported, no bar |
| **Time per text,** 95th percentile, model loaded | Redaction will sit in front of every hosted call | **Under 10 seconds** |

**A failed entry counts as missing all of its identifiers** (review finding 4): a malformed reply, a refusal or a timeout fails closed, so nothing leaks, but the hosted feature is unusable for that text, and dropping it from the figures would hide that. The number of failed entries is also reported.

Every bar applies to each language separately (Q13). Missing any of them, the latency bar included, stops implementation.

**An identifier counts as caught** only when no word of it survives, whatever type it was given (review finding 4). Each word of the identifier must appear in the output no more often than it appears in the entry outside identifiers. So `[PERSON_1] Silva` is a miss, while the "de" of "Hospital de Santa Maria" doesn't count against it if "de" appears elsewhere in the entry. A wrong type is a quality problem, not a privacy one.

**Labelling** (Q14): I write the entries and their labels, and the owner marks the identifiers in 30 held-out entries blind, as in spec 006. The agreement is reported, and shows how fuzzy the line is, especially for distinctive titles (Q4) and personal dates (Q2).

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
- **In code,** `Pseudonymized` lives in memory and has no table, no file and no cache behind it. Saving it would mean writing new code, which a review would see. The known-name cache (§2.2, Q16) is separate: it holds names found in the personal context, never a map, and is also memory only.

**Limitations.**

- **A conversation that survives a restart** would need its map saved, encrypted or under RLS. Conversations arrive in Milestone 4, so that spec decides it.
- **Memories and summaries** that a hosted model writes come back re-hydrated, so they hold real names locally, as Tier 0 should.

**When to revisit.** When a feature needs a hosted model to refer to a placeholder from an earlier exchange, or when conversations need to survive a restart. Either change comes back to the owner as a new decision, with this record as its starting point.

## 4. Decision record: prompts live next to the code that uses them

The owner asked for this decision (Q17) to be documented with the alternatives, because it changes a project-wide convention in `CLAUDE.md`.

**Context.** `CLAUDE.md` says prompt wording lives in `src/lumen/suggestions/prompts/`, one file per version, never in code. When it was written, extraction was the only prompt. Redaction adds a second one, in a different package, and Milestone 4 will add more (reflection, conversations). The convention has to say where a prompt goes in general, not where the one prompt is.

What the current convention protects, and any new one must keep:

- **Wording is reviewable on its own,** as a file, not a string inside Python.
- **A version is a new file,** so a measured prompt is never edited in place.
- **A measured prompt is pinned by its hash** (`measured_prompt.json`), and a test fails if it changes without a new measurement.
- **It ships with the package** and is loaded with `importlib.resources`, so it works from an installed wheel, not only from a checkout.

**Options considered.**

| Option | Where the redaction prompt goes | Problem |
|---|---|---|
| **(a) A `prompts/` folder in each package that uses one** | `src/lumen/privacy/prompts/redaction_v1.txt` | One line of `CLAUDE.md` changes |
| (b) Keep the rule literally: every prompt in `suggestions/prompts/` | `src/lumen/suggestions/prompts/redaction_v1.txt` | `lumen.privacy` would load files from `lumen.suggestions` |
| (c) One shared package, `src/lumen/prompts/`, with a folder per feature | `src/lumen/prompts/redaction/v1.txt` | Separates each prompt from the parser and schema that must change with it |
| (d) A top-level `prompts/` folder, outside `src/` | `prompts/redaction_v1.txt` | Not part of the package, so not in the wheel |
| (e) Prompts as constants in code | `redaction.py` | Already ruled out by `CLAUDE.md`: wording hidden among code, versions edited in place |

**Decision: (a).** `CLAUDE.md` will say: *"Prompt wording lives in a `prompts/` folder in the package that uses it (e.g. `src/lumen/suggestions/prompts/`), one file per version, not in code (spec 011 §4). Changing a measured prompt, anchor or starter tag fails a test until it's measured again (`measured_prompt.json` in its evaluation folder, `evals/<name>/`)."*

**Why the others were rejected.**

- **(b) points the dependency the wrong way.** `lumen.privacy` is the lower layer: suggestions, and every hosted feature, will depend on it. Making it read its security-critical prompt out of `lumen.suggestions` couples the privacy layer to a feature, and a change to suggestions' folder could break redaction.
- **(c) splits what changes together.** A prompt, the JSON schema it asks for and the parser that reads the reply change in the same commit (developer guide, "Change a prompt"). A shared prompts package puts them in two places, and invites one feature's prompt to be reused by another without either being measured for it. Its benefit, one place to look, comes almost as well from a single folder name used everywhere.
- **(d) breaks loading.** Files outside `src/lumen/` aren't package data, so `importlib.resources` can't find them in an installed app, and the path would depend on the working directory.
- **(e)** is the practice the rule exists to prevent.

**Why (a).**

- **Cohesion:** the prompt sits next to the code that sends it and parses its reply, so a reviewer sees them together, and the package that owns a prompt owns its measurement.
- **Measurement maps one to one:** `lumen.suggestions` ↔ `evals/extraction/`, `lumen.privacy` ↔ `evals/redaction/`. Each has its own hash and its own test.
- **It's how suggestions already works,** with `files("lumen.suggestions").joinpath("prompts", …)`. Nothing existing moves.
- **Security review:** the redaction prompt decides what leaks. Keeping it inside `lumen.privacy` means a change to it shows up as a change to the privacy package.

**Consequences.**

- `CLAUDE.md` changes in this spec's PR (the owner approved it with Q17).
- The developer guide's "Change a prompt" recipe stays extraction's. The second implementation PR adds the same recipe for redaction, pointing at `evals/redaction/`.
- Each package that adds a prompt also adds its own hash test. That's some repetition, accepted because each prompt is measured against a different evaluation set and bar.

**When to revisit.** If two packages need the same prompt, or prompts need to be edited by someone who doesn't edit code. Either comes back to the owner as a new decision.

## 5. Acceptance criteria

**First PR: the deterministic part** (with a fake detector)

- **AC-1 (replacement):** with the detector finding Ana and Costa as `PERSON` and Deloitte as `ORG`, *"Ana criticised my report at Deloitte again, and I couldn't sleep before my session with Dr. Costa on Tuesday."* becomes exactly *"[PERSON_1] criticised my report at [ORG_1] again, and I couldn't sleep before my session with Dr. [PERSON_2] on Tuesday."*, and the map holds exactly those three pairs.
- **AC-2 (every occurrence, whole words):** *"Ana Silva called. Ana was upset. Bananas for lunch. ana's day was hard."*, with findings "Ana Silva" and "Ana", becomes *"[PERSON_1] called. [PERSON_2] was upset. Bananas for lunch. [PERSON_2]'s day was hard."*: the "Ana" inside "Ana Silva" is merged into the longer span, case is ignored, and "Bananas" is untouched. "Ana Silva" and "Ana" get different placeholders (Q15). The map is exactly `{PERSON_1: "Ana Silva", PERSON_2: "Ana"}`: the form of the first separate occurrence, not the later "ana". (The "Ana" inside "Ana Silva" isn't a separate span once merged, so it never counts as an occurrence.)
- **AC-3 (findings are checked):** a finding not in the text is ignored and the rest of the reply is still used. A reply with a finding typed `"PERSONS"` raises `RedactionUnavailableError`, as in AC-9.
- **AC-3b (overlaps):** with the detector finding `"912 345"` as `ID` in *"Call 912 345 678."*, the output is *"Call [CONTACT_1]."*: no digit is left. A valid NIF starting with 2 becomes `[ID_1]`, and the same nine digits with a wrong check digit become `[CONTACT_1]`.
- **AC-4 (rules without the model):** with the detector finding nothing, each of `ana@example.com`, `https://example.com/ana`, `@ana.s`, `+351 912 345 678`, `+351913572468` (as `[CONTACT_n]`, although its first nine digits are the valid NIF `351913572`, which the whole-token rule must leave alone), `912 345 678`, a valid Portuguese IBAN, a valid NIF, a 16-digit card number written without spaces and containing a nine-digit run that starts with 9 or 2 (so a phone match inside it would be visible as `[CONTACT_n]`), `1100-053`, `192.168.1.10`, `2001:db8::1`, a Cartão de Cidadão number (`12345678 9 ZZ1`), `12345678`, `1 500 000`, and the date and range look-alikes `1234-5678`, `2024-13-45`, `2024-02-30`, `45-13-2024`, `2021-2019` and `1850-1890` is replaced with the right placeholder type, in an English and a Portuguese sentence. No character of any of them is left in the output.
- **AC-5 (decoys under the rules):** *"My sister, 34, works as a nurse in Portugal. Slept 6 hours, walked 10000 steps on Tuesday, took 50 mg of sertraline. From 2019-2021 I lived abroad; on 2024-05-03 8 hours of sleep weren't enough, and again on 03-05-2025."* comes back unchanged with a detector that finds nothing.
- **AC-6 (known names):** with the personal context naming Ana and Rosa, the dog Rex, the employer Deloitte and the city Porto, and a detector that misses all five in the text, *"Ana again. Rosa called; the rosa dress. Walked Rex. Back in Porto, Deloitte phoned."* becomes *"[PERSON_1] again. [PERSON_2] called; the rosa dress. Walked [NAME_1]. Back in [PLACE_1], [ORG_1] phoned."*. Each of the four known-name types is covered.
- **AC-6b (known names are cached):** two calls with the same owner and context run the detector on the context once; after the context changes it runs again, and another owner with the same context gets its own entry. A `DATE` or `ROLE` finding in the context doesn't become a known name.
- **AC-7 (re-hydration):** after AC-1, the reply *"Feedback from [PERSON_1] at [ORG_1] weighs on you; [PERSON_9] isn't mentioned."* becomes *"Feedback from Ana at Deloitte weighs on you; [PERSON_9] isn't mentioned."*.
- **AC-8 (placeholders already in the text):** *"I wrote [PERSON_1] in my notes. Ana called."* becomes *"I wrote [PERSON_1] in my notes. [PERSON_2] called."*, and re-hydrating *"[PERSON_1] and [PERSON_2]"* gives *"[PERSON_1] and Ana"*.
- **AC-9 (fail closed):** when the detector raises, times out, or returns malformed output (§2.2), including a failure on the personal context, `Redactor.pseudonymize` raises `RedactionUnavailableError`, returns no text, and the error's message, `repr` and chained exceptions contain none of the input.
- **AC-10 (nothing leaks through `repr`):** the `repr` and `str` of a `Pseudonymized` contain neither the original text nor any real value from the map.

**Second PR: the model and its measurement**

- **AC-11 (local only):** the Ollama detector refuses a non-loopback URL and a cloud model, sends with `trust_env=False` and without following redirects. The shared transport is the one suggestions use.
- **AC-12 (measured):** `evals/redaction/measured_prompt.json` holds the hash after a held-out run that meets every bar, and a test fails if the prompt then changes.

**Untested by justification**

- **The model's judgement** (names versus words, distinctive titles, personal dates): the evaluation measures it, which is stronger than a few unit tests with a real model.
- **The last check** (§2.2): replacement is deterministic and every detected span is replaced, so no public input makes the check fire; the review found none, and neither did the author. It stays as defence in depth against a future bug in replacement. It's covered by one fault injected by hand: break replacement so it skips a span found by a rule or a known name (such as `ana@example.com`, or the known name Rosa), and see the call fail closed. Skipping a span only the model found isn't a valid version of this fault, because the last check can't see such spans (§2.2). Without an input that can trigger it, a mutant for it could never be killed, so there's none (owner's decision on the PR).
- **That the map is never saved:** there's no table, no file and no cache for it, and `Pseudonymized` has no method to save it. A test can't prove code doesn't exist; a review sees any that's added.

## 6. Mutation check

A new `redaction` group in `make mutate`, because this is security-critical:

- a finding not in the text is used anyway
- matching ignores word boundaries, or is case-sensitive
- one rule is removed (each of: email, phone, IBAN, NIF, Cartão de Cidadão, seven digits)
- the date and year-range exception catches more than valid dates and ranges, or is removed
- the NIF check digit isn't verified, or is verified wrongly
- overlapping spans aren't merged, or merge with the wrong precedence
- a finding with an unknown type is dropped instead of failing closed
- known names match ignoring case
- a known-name type is filtered out (each of `PERSON`, `ORG`, `PLACE`, `NAME`)
- phone, NIF or postcode matches aren't whole tokens (each)
- dates and ranges aren't matched first, so a digit run extends across them
- the known-name cache isn't refreshed when the context changes
- known names aren't applied
- a detector error falls back to rules only
- the error chains the original exception
- re-hydration maps a placeholder that wasn't issued
- numbering doesn't skip a placeholder already in the text
- `repr` shows the map

One-off faults under the project workflow: replacement skipping a span found by a rule or a known name, which the last check must stop; a reply cut off mid-JSON, a very long text, a finding that overlaps another ("Ana" inside "Ana Silva" in the other order), and the same name with and without an accent ("Inês", "Ines").

## 7. Delivery

1. This spec, the `PROJECT.MD` §8 update that records §2–§3, and the `CLAUDE.md` prompt rule (§4).
2. The two PRs of §2.7, each with its tests failing first, fault injection, and an "Added during implementation" section here.

## 8. Decisions

Q1–Q12 were decided by the owner in discussion before the draft, Q13–Q17 on its PR.

| # | Question | Decision |
|---|---|---|
| Q1 | Cities, regions, countries? | **Cities and towns become `[PLACE_n]`; countries are kept.** |
| Q2 | Dates? | **Weekdays and relative dates are kept; dates personal to the person become `[DATE_n]`.** |
| Q3 | Ages? | **Kept.** |
| Q4 | Professions and job titles? | **Generic roles are kept; distinctive titles are replaced.** The line is fuzzy, so the evaluation set includes both and measures it. Distinctive titles become `[ROLE_n]` (proposed in the draft, approved by the owner on its PR). |
| Q5 | Relationship words? | **Always kept.** |
| Q6 | Sensitive content (health, medication, religion, politics, orientation, ethnicity)? | **Kept in Tier 1.** Local-only mode is the opt-out. |
| Q7 | Pets and named things? | **Replaced as `[NAME_n]`.** |
| Q8 | Unique events and traits? | **Out of scope, stated as a known limitation.** |
| — | How are identifiers found? | **Rules plus the local model (option D).** The model only points; code replaces. Names in the personal context are always replaced. Recall is measured. |
| Q9 | Which languages? | **Portuguese, English, and the two mixed.** The rules include Portuguese formats, and the evaluation set has all three. |
| Q10 | If the local model is unavailable? | **Fail closed:** no text is returned, and spec 012's gateway blocks the hosted call. |
| Q11 | How long does a pseudonym map live? | **One exchange, in memory only.** Full record in §3. |
| Q12 | What uses redaction first? | **Nothing yet:** this spec is the library and its measurement; spec 012 adds the hosted gateway and the audit log. |
| Q13 | What are the bars? | **Per language: direct recall at least 95%, contextual recall at least 85%, decoys kept at least 90%, and 10 seconds at the 95th percentile.** The detector times out after 60 seconds. With about 150 direct identifiers per language, a measured 95% is good to about ±3.5 points. |
| Q14 | Who labels the evaluation set? | **I write the entries and labels; the owner marks 30 held-out entries blind,** as in spec 006. |
| Q15 | Do "Ana", "Ana Silva" and "Aninhas" share a placeholder? | **No: each different text gets its own.** Some reflection quality is lost, but two different people can never be merged. Grouping could come later. |
| Q16 | Where do known names come from? | **The same detector, run on the personal context,** with its result kept in memory and refreshed when the context changes (§2.2). A list the person keeps is future work. |
| Q17 | Where do prompts live? | **In a `prompts/` folder in the package that uses them.** `CLAUDE.md` changes. Full record in §4. |

### 8.1 Review findings the owner approved

The `code-reviewer` agent's seven "should fix" findings on the first draft, all approved by the owner:

1. **Overlapping detections:** replacement works on spans of the original text, overlapping spans are merged, and a fixed precedence decides the type (§2.2, AC-3b).
2. **Checks a test couldn't observe:** only the NIF check digit is kept, because it decides between `ID` and `CONTACT`. IBANs are matched by shape, and card numbers by the seven-digit rule (§2.2).
3. **Unknown types:** constrained by the JSON schema; a reply that breaks it fails closed instead of dropping the finding (§2.2, AC-3).
4. **"Caught" means no word survives,** so `[PERSON_1] Silva` is a miss (§2.6).
5. **Known names match case-sensitively,** so "rosa" the colour isn't replaced (§2.2, AC-6).
6. **The latency bar and the detector timeout** are part of Q13 (§2.5, §2.6).
7. **"Malformed" is defined,** separately from "partly invalid", and anything unclear fails closed (§2.2).

### 8.2 Second review's findings the owner approved

The review of the updated draft raised eight more "should fix" findings. The owner approved all eight:

1. **The interface:** `Redactor(detector)` with `pseudonymize(text, *, owner, context)` owns the known-name cache. The detector returns the raw reply, and validating it is shared code above the protocol (§2.5).
2. **Cartão de Cidadão and IPv6** are in AC-4, and CC is in the mutated rules.
3. **IBAN and CC rank first** in the precedence (§2.2).
4. **A failed entry counts as missing all its identifiers** (§2.6).
5. **The map keeps the first occurrence's form,** counting only spans left after merging, and AC-2 checks it.
6. **The `CLAUDE.md` rule and the §4 quote are identical.**
7. **Only `PERSON`, `ORG`, `PLACE` and `NAME` become known names** (§2.2).
8. **Dates and year ranges are excluded from the seven-digit rule;** numbers grouped in threes stay caught (§2.2, AC-5).

### 8.3 Decisions on the later reviews

- **The last check has no acceptance criterion and no mutant.** Replacement is deterministic and every detected span is replaced, so no public input makes the check fire, and a mutant for it could never be killed. The owner chose to keep the check as defence in depth, listed under "untested by justification" (§5) and covered by one fault injected by hand that skips a span found by a rule or a known name. The alternative was making replacement injectable so a test could break it. It was rejected because that seam would exist only for the test.
- **Five more review findings, approved by the owner:**
  - AC-6 covers all four known-name types, with a mutant for each.
  - AC-4 and AC-5 cover `dd-mm-yyyy` dates and invalid calendar dates.
  - Every digit rule stops at a date or range, and phone and NIF matches are whole tokens (§2.2).
  - The hand-injected fault skips a rule or known-name span.
  - This entry records the last-check decision.
- **Deferred to implementation PR 1 by the owner, and done in its first commit:** AC-4 has `+351913572468`, which kills the NIF whole-token mutant (see §10 for why not `+351912345678`); the NIF rule accepts the same grouping as phone numbers; and the card number is written without spaces.
- **Three more, approved by the owner:** postcode matches are whole tokens and stop at dates and ranges, like phone and NIF; §6 has a mutant for all four known-name types; and dropping the whole-token rule for phone, NIF or postcode is a mutant, with AC-4's card number built so it can be caught.

## 9. Open questions

None.

## 10. Added during implementation (for review)

Nothing yet.
