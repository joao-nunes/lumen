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
| `[CONTACT_n]` | Phone numbers, emails, URLs, social handles, usernames, IP addresses | +351 971 974 210, `@ana.s`, ana@example.com |
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
- **510 entries:** a `dev` split of 60 for tuning the prompt, a held-out `test` split of 225, and `test_v1`, the 225 held-out entries `redaction_v1` was measured on, now retired. Each is split evenly between English, Portuguese and mixed text. (The draft planned 285 entries with a held-out split of 210; §10 says why the held-out split grew and why there's a second one.) Held-out entries are written and committed **before the prompt they measure**, and aren't looked at until the measurement.
- **Each entry lists its identifiers** with their type, and its **decoys**: words that look like identifiers but must be kept.
- **Hard cases on purpose:** names that are also words (Rosa, Joy, Graça, Hope), lowercase and misspelt names, nicknames, pets, personal dates next to relative ones, cities next to countries, distinctive titles next to generic roles, names inside possessives ("Ana's"), and distressing entries (27, 15 of them held out), which must return valid output rather than fail.
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
- **AC-3b (overlaps):** with the detector finding `"971 974"` as `ID` in *"Call 971 974 210."*, the output is *"Call [CONTACT_1]."*: no digit is left. A valid NIF that's also shaped like a phone number (`974212326`) becomes `[ID_1]`, and the same nine digits with a wrong check digit become `[CONTACT_1]`.
- **AC-4 (rules without the model):** with the detector finding nothing, each of `ana@example.com`, `https://example.com/ana`, `@ana.s`, `+351 971 974 210`, `+351974942129`, `https://example.com/r/0270987024` (as `[CONTACT_n]`, although it holds the valid NIF `027098702`, which the whole-token rule must leave alone), `971 974 210`, a valid Portuguese IBAN, a valid NIF, a 16-digit card number written without spaces and containing a nine-digit run that starts with 9 or 2 (so a phone match inside it would be visible as `[CONTACT_n]`), `1100-053`, `192.168.1.10`, `2001:db8::1`, a Cartão de Cidadão number (`12345678 0 ZZ1`), `12345678`, `1 500 000`, and the date and range look-alikes `1234-5678`, `2024-13-45`, `2024-02-30`, `45-13-2024`, `2021-2019` and `1850-1890` is replaced with the right placeholder type, in an English and a Portuguese sentence. No character of any of them is left in the output.
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

- **Distinctive titles of the "post at an institution" kind** (found by the measurement on 2026-11-20, §10). `redaction_v2` caught 2 of the 18 in the newest held-out entries, though it replaced every institution and place in them. **Decided by the owner: a `redaction_v3`, in its own PR after this one;** `redaction_v2` stands until then.
  - **Titles:** v3 lists a title that points to one person, because it's tied to a named institution or place ("the vicar of St X", "a diretora do Lar Y") or is unique ("the only…"), and still leaves out generic roles with no institution ("my nurse"). One example shows such a title, in place of a current one, so there are still five.
  - **Dates, as a second step:** after the title change is measured on `dev`, guidance on dates of personal events (births, deaths, weddings, accidents, surgeries) is added and measured again.
  - **Data:** 10 more `dev` entries per language with such titles and dates, to tune on, and a new held-out split of 50 entries per language, each language written on its own, with about 20 titles and 20 dates per language, committed before v3 exists. The current `test` split becomes `test_v2`.

## 10. Added during implementation (for review)

First PR (the deterministic part and the evaluation set):

- **Text, personal context and findings are normalized to NFC, and findings are stripped of surrounding spaces.** Fault injection found two leaks. A name typed in one Unicode form ("Inês" as `e` plus a combining accent) didn't match a finding in the other. A finding the model padded (`" Rui "`) never matched as a whole word. In both cases a name the model pointed at reached the output, and the last check can't see spans only the model found. Both now have a test and mutants. Consequence: `Pseudonymized.text` is the NFC form of the input, which reads the same.
- **The mutant "a finding not in the text is used anyway" doesn't exist as such.** A finding with no occurrence in the text produces no span, so there's nothing to use. The real risk is a blank finding (`""`), which would match an empty position everywhere and scatter placeholders. AC-3's test includes blank findings, and the mutant removes that guard instead.
- **AC-4's NIF inside a longer token is now in a URL, `https://example.com/r/0270987024`.** The spec first suggested `+351912345678`, but without the whole-token rule the NIF pattern matches the leftmost nine digits (`351912345`), which aren't a valid NIF, and never tries the overlapping window `191234567`, so the mutant survived the full `make mutate` run. `+351913572468` fixed that, because its first nine digits are a valid NIF, but such a window starts with 3, a range NIFs of real people use, and the number itself is a possible real mobile (see the next item). The URL holds a valid NIF starting with 0, which no one can hold, and the mutant still sees it.
- **No phone number, NIF or ID number in the tests or the evaluation set can belong to a real person** (owner's decision on PR #64). The review found that Portuguese numbers and NIFs with valid check digits could be real. Now:
  - **NIFs start with 0.** Every category of NIF holder has a first digit from 1 to 9 (Decreto-Lei 14/2013), so none starts with 0. The rule checks only the check digit, so it still catches them. The exception is AC-3b's NIF, which must also be shaped like a phone number: it starts with 97, which isn't a NIF range for people.
  - **Portuguese phone numbers start with 97.** Portugal has no range reserved for fiction; mobiles use only 91, 92, 93 and 96, and landlines start with 2. So 97 is unassigned, though not reserved: if ANACOM ever opens it, these numbers could become real. UK numbers are in Ofcom's ranges for drama.
  - **Portuguese IBANs have a valid IBAN check but bank code 0000 and a wrong NIB check digit,** so no account can have them. UK IBANs are official examples (`GB82 WEST 1234 5698 7654 32`, `GB29 NWBK 6016 1331 9268 19`), and the tests also keep the official Portuguese one (`PT50 0002 0123 1234 5678 9015 4`).
  - **Cartão de Cidadão numbers have wrong check digits,** both in the civil ID and in the document number.
  - **The UK passport number became a case reference,** the SNS number starts with 0 with a wrong NIF check digit, and the car plate is `12-KW-34`: K and W weren't used on Portuguese plates before the 2020 format, which has a different layout.
- **The error is raised outside any `except` block,** so it has neither a `__cause__` nor a `__context__`. `from None` only hides the context in tracebacks; the original exception, which can quote the text, stays reachable. AC-9 checks both.
- **Any exception from the detector fails closed,** not a fixed list. The detector is an I/O boundary, and §2.3 puts failing closed first.
- **Known names take the context's own spelling** at each place the model's finding occurs in it, ignoring case. So a finding "ana" from a context that writes "Ana" becomes the known name "Ana", and is matched case-sensitively from then on.
- **An empty personal context doesn't call the detector.**
- **The map's keys are the placeholders as written,** such as `[PERSON_1]`.
- **Ties in precedence:** two overlapping spans of the same rank take the type that comes first in `IdentifierType`'s order. That's only possible between model findings, or between known names.
- **Rule details that §2.2 left open:**
  - International phone numbers are `+` followed by 8 to 17 digits, with single spaces or dashes allowed between them.
  - IPv6 candidates are checked with `ipaddress`, so times like `10:30:45` aren't caught.
  - Trailing punctuation is dropped from URLs.
  - IBAN country codes must be uppercase. A lowercase IBAN's digits are still caught by the seven-digit rule, leaving only the country code and check digits.
- **The held-out split grew from 150 to 225 entries** (owner's decision on PR #64). The 210 entries first planned held only about 80 direct identifiers per language in the held-out split, not the ~150 that Q13's margin assumed, and about 24 contextual ones, with only 3 personal dates and 3 distinctive titles. That made a measured 95% good to about ±4.8 points and a measured 85% to about ±14 (95% intervals, as in Q13). Each language got 25 more entries, rich in identifiers and especially contextual ones. Each now has 158 to 163 direct identifiers (about ±3.4 points at 95%) and 62 to 64 contextual ones (about ±9 points at 85%), with 11 to 13 personal dates and 10 distinctive titles. Contextual recall stays the less precise figure: reaching ±3.5 there would take about 400 contextual identifiers per language. They were written before any prompt, like the rest of the held-out split. They're appended as `*-test-51` to `*-test-75`, so the 30 entries on the blind sheet didn't change.
- **A distinctive title is labelled without the institution or place in it,** which gets its own `ORG` or `PLACE` label (review finding on PR #64). Some entries had put the institution inside the `ROLE`, so a hospital or court counted only towards contextual recall, and the same behaviour scored differently from one entry to another. 17 labels were split this way, and one was trimmed: "youngest MP in Parliament" became "youngest MP", since Parliament alone is generic.
- **A reply whose `type` isn't a string fails closed.** A list or an object can't be looked up among the known types, so it raised `TypeError`, which the gateway in spec 012 wouldn't recognize as a redaction failure. No text leaked, but it now raises `RedactionUnavailableError` like any other malformed reply (review finding on PR #64). AC-9 covers both cases, and a mutant removes the check.
- **The re-hydration mutant differs from §6's list.** §6 lists "re-hydration maps a placeholder that wasn't issued", but there's nothing to map such a placeholder to: the map holds only issued placeholders. The mutant instead makes re-hydration drop unissued placeholders, writing them as an empty string. AC-7 and AC-8 catch that, because they expect `[PERSON_9]` and a literal `[PERSON_1]` to stay as they are.
- **Reserved domains only.** The evaluation set's emails and URLs use `example.com`, `example.org` and `example.net`, which are reserved for documentation (RFC 2606). `example.pt` isn't reserved, so the entries that used it were changed.

Second PR (the model and its measurement):

- **No JSON schema in the request** (owner's decision). §2.2 expected Ollama to limit replies to a schema listing the nine types. The installed Ollama (0.40.14) refuses structured output for both local models: every request with a `format`, a schema or plain `"json"`, gets HTTP 501 "structured output is unavailable", so every call would fail. The prompt alone asks for the JSON, and the parser from the first PR stays the gate: a reply that isn't exactly the expected object, including one in a code block, or that has a type outside the nine, fails closed. Privacy is unchanged, because the parser never relied on the schema. A malformed reply counts as a failed entry in the measurement. A test checks that no `format` is sent.
- **Model findings are still matched ignoring case** (owner's decision, option (a)). On the dev split, the model pointed correctly at "Joy" or "Rosa" the person, and replacement then also took "joy" the feeling and the "rosa" in "cor-de-rosa": all 6 decoys lost on the dev split were of this kind. Matching findings exactly as written would keep those words, but leak a lowercase "ana" the model didn't list separately. Missing a name leaks it, while over-replacement only garbles a word, so the owner kept §2.2's behaviour, and the measurement shows its cost.
- **One shared transport, `lumen.privacy.local_model`** (§2.5). `check_local_only` and the HTTP call moved there from `lumen.suggestions.ollama`, as `chat(url, model, *, system, user, timeout) -> str`, which raises `LocalModelError` with a fixed message, outside the `except` block, so the original error is neither its cause nor its context (review finding on PR #65; `from None` alone would have kept it as the context). Suggestions and the detector both send through it, and the transport's mutants now target it. A reply whose content isn't text fails there.
- **How the prompt was written** (owner's decisions on five questions):
  - when unsure, list a possible name or organization, and leave out a possible role or date;
  - list each written form of a name ("Ana" and "ana");
  - keep listing what the rules already catch, for formats they miss, such as `972.418.305`;
  - at most five short examples, all invented. Their names were checked against the evaluation set, but the review on PR #65 found two overlaps the check missed: example 1 ("Jantei com a … e o irmão dela …", then the first name alone) has the same frame as held-out `pt-test-01`, and example 4's "Clínica Aurora" contains "Aurora", a held-out `PERSON` in `mixed-test-57`. The owner chose to record them rather than measure a new version on new held-out entries. Counting what the overlaps touch as missed or lost (all three identifiers in `pt-test-01`, whose frame is the overlap, its decoy "o irmão dela", which is in that frame, and "Aurora" in `mixed-test-57`), Portuguese direct recall is 95.0% (152 of 160), exactly at the bar, mixed direct recall 98.1% (155 of 158), and Portuguese decoys kept 95.1% (98 of 103). No overlap touches a contextual identifier. Even counting every identifier in both entries as missed, mixed direct recall is 96.2% (152 of 158) and mixed contextual recall 88.9% (56 of 63). Every bar still holds, Portuguese direct recall with no margin. These are bounds, since the run keeps no per-entry results. CLAUDE.md's Prompts section now asks for the check this needed: wording and frames as well as names;
  - one prompt for notes and for the personal context, described as "a description someone wrote about themselves".

  The sectioned layout made the model wrap its JSON in a code block, which the parser rejects, until the prompt forbade it.
- **Decided while writing the measurement** (§2.6 left these open):
  - **A failed entry also loses its decoys,** since it returns no text.
  - **No failed entry on distressing text,** as a bar. §2.6 says those entries "must return valid output rather than fail", and spec 006 has the same bar.
  - **A decoy is kept** when every occurrence of it is still in the output, matched case-sensitively as whole words.
  - **The right type** means some placeholder stands for text containing the identifier and has its type.
  - **A leak-free entry** returned text and missed no identifier.
  - **The slowest time leaves out the call that loaded the model,** as for extraction. At first it left out each language's first call; since the fix to the limitations below, it leaves out only the run's first call.
  - **A run stops after three failed calls in a row,** so an outage can't be reported as results.
  - **Agreement counts each distinct form once,** on the 30 entries the owner marked, and reports the share of labels the owner marked and the share of the owner's marks that are labels.
- **The model is `gemma4:26b`,** the one extraction was measured with. On the dev split, `gemma4:e4b` found 50% to 94% of direct identifiers.
- **The mutation baseline needs every test green,** and AC-12 is red until a held-out run records the prompt, so the new mutants run after the measurement.
- **The held-out run met every bar in every language,** with `gemma4:26b` and `redaction_v1` (hash `8011b519…`), once, on 2026-11-19. `measured_prompt.json` records it, and AC-12 passes.

  | | Direct recall (≥ 95%) | Contextual recall (≥ 85%) | Decoys kept (≥ 90%) | 95th pct seconds (< 10) | Failed entries | Leak-free entries | Right type |
  |---|---|---|---|---|---|---|---|
  | English | 98.2% of 163 | 90.3% of 62 | 95.3% of 107 | 2.9 | 0 | 89.3% | 98.6% |
  | Portuguese | 96.9% of 160 | 87.5% of 64 | 96.1% of 103 | 6.6 | 0 | 86.7% | 99.1% |
  | Mixed | 98.7% of 158 | 92.1% of 63 | 96.2% of 105 | 5.0 | 0 | 92.0% | 97.7% |

  About one entry in ten still missed at least one identifier: the leak-free figure is the one a person would feel, and it has no bar. Contextual recall in Portuguese is the closest to its bar.
- **Labels must be in NFC,** like the redactor's output: `load_entries` refuses text, identifiers or decoys in another Unicode form, which would never be found in the output and so would count as caught (review finding on PR #65). All 285 entries already were.
- **Agreement with the owner's blind marks,** on the 30 entries, each distinct form once: the owner marked 51 of the 59 labelled forms (86.4%), and 51 of the owner's 57 marks are labelled (89.5%).
- **Fault injection:** the redaction-model and suggestions mutants, 84 in all, run after the measurement. "Matching ignores case" in the measurement survived at first: the test's "Joy … joy" couldn't tell the two apart. A test where the feeling is replaced instead of the name ("Joy felt [PERSON_1].") now catches it.
- **A second held-out split, for `redaction_v2`** (owner's decision, option (b), with 50 entries per language). Because of the overlap above, the owner chose to measure a new prompt version, with new examples, on entries it has never been near, rather than rest on a worst case with no margin. `redaction_v1`'s split became `test_v1`: its results have been read. The new `test` split has 150 entries, 50 per language, written and committed before `redaction_v2`. It has 163 to 166 direct identifiers per language (about ±3.3 points at 95%), 58 to 61 contextual ones (about ±9 points at 85%), and 106 to 108 decoys. Its values follow the same rules, and none repeats another in the set. Its titles were meant to name invented towns and institutions, so that no story is about a real office holder, but the names weren't checked: the review on PR #65 found that several Portuguese ones are real places, such as Vilar Seco, Souto Maior, Vale Formoso and Penaverde, and possibly Ribafria, Ribamar and Casal do Moinho. The stories are still invented and name no real person; renaming the towns would have changed held-out text after its measurement. The institutions and the English towns look invented. The blind sheet stays in `test_v1`.
- **`redaction_v2`** is `redaction_v1` with new examples and new words in its lists, nothing else. v1's lists also overlapped the new split: "hope" as a feeling, "Rosa" as a name that is also a word (the new split has "Pizzaria Bella Rosa"), and a "Dr X at the Y Surgery" frame. v2 was checked against every entry, as CLAUDE.md now asks: no three-word sequence of the prompt appears in any entry of the new held-out split, and the only capitalised words its examples share with it are "Dr" and "My". The review on PR #65 found what a three-word check can't: two shared sentence frames and a shared title. Example 4's "Dr Okoro at Quayside Wellbeing Trust" has the same "Dr <surname> at <organization>" frame as four entries of the first 150; example 2's "his ferret Admiral" has the same "possessive + animal + name" frame as four others; and example 3's "Dra." appears before a surname in held-out entries. Counting every identifier inside those frames as missed, the 150-entry run's worst case is English direct recall 95.7%, mixed direct 95.8%, English contextual 90.2% and mixed contextual 86.2%: every bar still holds. The 75 entries added later avoid all three. On the dev split, the first draft missed a surname after a Portuguese title ("Dra. Fonseca") and a name that is also a word used as someone acting ("Hope texted"), which v1's examples had shown. The examples were adjusted to show both, after which v2 found every dev identifier in all three languages.
- **`redaction_v2` met every bar in every language on the new held-out split,** with `gemma4:26b`, once, on 2026-11-19 (hash `07efb170…`). `measured_prompt.json` now records it, and AC-12 passes. Direct recall is at least 3 points above its bar in each language, so the result doesn't depend on any overlap.

  | | Direct recall (≥ 95%) | Contextual recall (≥ 85%) | Decoys kept (≥ 90%) | 95th pct seconds (< 10) | Failed entries | Leak-free entries | Right type |
  |---|---|---|---|---|---|---|---|
  | English | 98.2% of 163 | 96.7% of 61 | 96.2% of 106 | 2.6 | 0 | 92.0% | 96.8% |
  | Portuguese | 98.2% of 166 | 98.3% of 59 | 96.3% of 108 | 3.3 | 0 | 94.0% | 97.3% |
  | Mixed | 98.2% of 166 | 93.1% of 58 | 97.2% of 106 | 4.5 | 0 | 86.0% | 99.1% |

  The figures for `redaction_v1` above stay as the record of its measurement on `test_v1`.
- **The review's limitations, fixed** (owner's decisions on PR #65):
  - **75 more held-out entries,** 25 per language (`*-test-v2-51` to `-75`), because the 150 had only 7 personal dates and 6 distinctive titles per language, and their three languages were near-translations of each other, which made the intervals optimistic. Each language's 25 were written on their own, with their own stories and names, and they're rich in dates and titles: the split now has 13 or 14 dates and 12 titles per language. They avoid the prompt's names, wording and frames (none uses "Dr <surname> at <organization>", a named pet or "Dra."), and a web search found none of their titles' towns and institutions. They were committed before the measurement below, and `redaction_v2` didn't change, so nothing was tuned on held-out text: the run measured the same prompt on more entries.
  - **"Minho", the region, is labelled `PLACE`** in the two entries that have it, before the rerun. Regions count as places, and a car's brand ("his old Renault") is a decoy, while shops and employers are `ORG`. The README says so, and documents the `00xx xxxx` references.
  - **The slowest time leaves out only the call that loaded the model** (the run's first, which took 20 s), not each language's first call.
  - **The measurement uses the app's 60-second timeout,** not 120.
  - **Each run's output is saved entry by entry** in `evals/redaction/runs/`, which isn't committed. The figures below about parts of the split come from it.
  - **`SuggestionsUnavailableError` is raised outside its `except`,** like `LocalModelError`, so the original error is neither its cause nor its context.
- **`redaction_v2` on all 225 held-out entries met every bar in every language,** with `gemma4:26b`, once, on 2026-11-20 (hash `07efb170…`, unchanged, so `measured_prompt.json` is too). This is the result of record for `redaction_v2`.

  | | Direct recall (≥ 95%) | Contextual recall (≥ 85%) | Decoys kept (≥ 90%) | 95th pct seconds (< 10) | Failed entries | Leak-free entries | Right type |
  |---|---|---|---|---|---|---|---|
  | English | 98.6% of 221 | 89.2% of 83 | 95.3% of 148 | 3.9 | 0 | 85.3% | 96.9% |
  | Portuguese | 98.6% of 216 | 87.8% of 82 | 96.6% of 145 | 5.3 | 0 | 84.0% | 97.2% |
  | Mixed | 98.6% of 221 | 87.5% of 80 | 97.1% of 140 | 6.6 | 0 | 82.7% | 98.6% |

  With about 220 direct identifiers per language, a measured 95% is good to about ±2.9 points; with about 80 contextual ones, a measured 85% to about ±8. **A temperature-0 run isn't exactly repeatable** (review finding on PR #65). Apart from the two "Minho" labels added (both caught), the first 150 entries' identifiers were found exactly as on 2026-11-19 in English and mixed, but not in Portuguese: both personal dates in `pt-test-v2-09` and `-15` were missed this time, where only one contextual identifier was missed before. English also kept one decoy fewer (101 of 106, against 102), while Portuguese and mixed kept the same ones. "Right type" can't be compared, because the run file keeps no placeholder mapping. The earlier run kept no per-entry results, so which date, or which English decoy, differs can't be told. A repeat run can differ by an identifier or so, which matters for a result within a point of a bar. **Contextual recall fell from 93–98% to 87.5–89%, because of distinctive titles.** On the 75 new entries, every direct identifier and every place was caught, but only 2 of 18 titles (11%) and 15 of 20 personal dates (75%). The titles there aren't of the "the only X in Y" kind the prompt's example shows: they name a post at an institution or place ("the vicar of St Aldhelm's", "a diretora do Lar de São Romão do Outeiro", "the harbour master at Praia da Gaivota Parda"). The prompt says to leave out a possible role when unsure, and the model did. In every one of those misses, the institution or place in the title was replaced, so what's left ("the vicar of [ORG_1], [PLACE_1]") no longer points to anyone, but the labels count it as missed. The bars hold only because the first 150 entries' titles were mostly found (two were missed, in `mixed-test-v2-14` and `-23`); on the new 75 alone, contextual recall is 64% to 71%. The owner chose a `redaction_v3`, in the next PR (§9).
