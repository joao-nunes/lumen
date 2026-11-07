# Spec 006: Free-text check-in with a local model

**Status:** Approved (decisions in §2.1 and §6)
**Builds on:** spec 002 (check-in slice), spec 005 (logging). First slice of Milestone 3.

## 1. Goal

Let someone write how their day went, for example *"slept badly, stressful meeting, ok evening"*, and get suggested scores and tags from a model running on their own machine. They confirm or correct the suggestions on the existing form, and only then is anything saved.

This also answers a question the rest of Milestone 3 depends on: can a local model do this well enough to be useful?

### Non-goals
- **Embeddings, redaction, the hosted-call audit log:** later Milestone 3 slices.
- **Safety classification or a safety gate:** Milestone 4. §2.7 covers the gap until then.
- **Journal entries and storing any free text:** Milestone 5.
- **LangGraph and the Check-in Agent:** this is a plain function for now, so nothing here depends on the orchestration design.
- **Measuring how often real suggestions get corrected:** it needs its own privacy decision.

## 2. Proposed decisions

### 2.1 The owner's decisions

| Decision | Choice |
|---|---|
| Is raw text saved? | **No.** It's used for the suggestion and then discarded |
| Which runtime? | **Ollama** |
| Accuracy bar | **95%, if realistic.** §3 says what that can mean, and Q1 confirms it |
| Installing Ollama | **Done with the owner's permission:** version 0.40.14, with cloud features off, listening on `127.0.0.1` only, and no models downloaded yet |

### 2.2 The flow

1. The Today screen gets a free-text box above the existing form.
2. **Suggest scores** sends the text to the API, which asks the local model.
3. Suggestions fill in the form. Nothing is saved.
4. The person corrects anything and presses the existing save button, which sends only scores and tags.

**Rules for suggestions:**
- **They never overwrite a choice** the person has already made on the form.
- **Anything the text doesn't mention stays blank,** rather than being guessed. The form's required fields still apply.
- **They're marked as suggested** until confirmed, in text and not by colour alone.
- **The structured form works as it does today** without Ollama, so the feature is optional.
- **The model's words are never shown.** Only validated scores and tags come back, so a model can't give advice, even to someone writing about something distressing.

### 2.3 API

```
POST /api/checkins/{local_date}/suggestion
{"text": "slept badly, stressful meeting, ok evening"}

200 {"scores": {"mood": 3, "stress": 4}, "tags": ["poor_sleep"]}
```

- **It needs a session and CSRF token,** like any other write, and writes nothing.
- **Text is 1 to 2,000 characters,** after trimming. Otherwise it's `422 invalid_request`, which doesn't repeat the text.
- **Only the dimensions the form asks that day** can be suggested (`dimensions_for`).
- **Tags come only from a fixed list:** the person's existing tags plus the starter list in `PROJECT.MD` §4.2. The model can't invent one.
- **Any other output is dropped.** Out-of-range scores, unknown dimensions and unlisted tags are removed.
- **Failures give `503 suggestions_unavailable`:** Ollama not running, the model not installed, a timeout (60 seconds), or output that isn't valid. The text box keeps its text, and the form still works.
- **No database transaction stays open during the model call.** Tags are read in a short transaction first, since a call can take many seconds and would otherwise hold a pooled connection.
- **`PUT /api/checkins/{local_date}` gains an optional `mode`,** defaulting to `structured`. The web app sends `free_text` when suggestions were used, using the column that already exists. Confirmed scores are still self-reports, but this keeps open the option of checking later whether suggestions bias them.

### 2.4 Raw text stays on the machine

`PROJECT.MD` §8 makes free-text check-ins Tier 0, which never leave the machine. Ollama needs specific care here, because **its cloud models send prompts to Ollama's servers.**

| Risk | Control |
|---|---|
| `OLLAMA_URL` points at another machine | The app refuses to start unless the host is a loopback address |
| A cloud model is configured | The app refuses to start if `OLLAMA_MODEL` names a cloud model, such as a `-cloud` tag |
| Ollama itself allows cloud models | Setup requires `"disable_ollama_cloud": true` in `~/.ollama/server.json`, which applies however Ollama is started, and the hand check confirms `Ollama cloud disabled: true` in its log. The app can't verify this itself, so the two checks above don't rely on it |
| Ollama writes prompts to its own logs | Ollama's documentation doesn't say. **The hand check tests this with a marker.** If a marker appears at default settings, implementation stops and this comes back to the owner |
| Stored in the database | No table has a column for it |
| In Lumen's log | `EventLog` can't carry it (spec 005), and AC-5 tests it |
| In the browser | React state only: no `localStorage`, no URL, and no retained TanStack mutation (`gcTime: 0`). `autocomplete="off"` applies, and `spellcheck="false"`, because some browsers' enhanced spell check sends text to a remote service |
| Left on screen | The box is cleared after a successful save. **A reload loses a draft,** which follows from not storing it |

Ollama runs natively rather than in Compose, because Docker on a Mac has no GPU access. It's installed with Homebrew's `ollama` formula, which adds no login item and runs only when started, and it writes its log to its own output rather than a file. The CSP doesn't change: the server calls Ollama, not the browser.

### 2.5 Code

- **`SuggestionModel` is a `Protocol`, a real seam:** `suggest(text, dimensions, tags) -> Suggestion`. `OllamaSuggestionModel` uses `POST /api/chat`, with `format` set to a JSON schema, `stream: false` and temperature 0, as Ollama's documentation recommends. The schema is built from the dimensions and tags asked for.
- **Anchors go in the prompt,** using the same descriptions the form shows, so a "2" means the same thing in both places.
- **Everything stays validated after the schema.** A schema enforces shape, not correct values.
- **New settings, documented in `.env.example`:** `OLLAMA_URL` (default `http://127.0.0.1:11434`) and `OLLAMA_MODEL` (no default, set once a model is chosen). With no model set, the endpoint returns `503` and the app still starts.

### 2.6 Delivered in two PRs, with a stop in between

1. **Measure first:** the evaluation set, `make eval-extraction`, `OllamaSuggestionModel`, and a model comparison reported to the owner. **There's no API or screen yet.**
2. **Only if the model meets the bar:** the endpoint and the screen.

This avoids building a screen around a model that isn't good enough.

### 2.7 The safety gap until Milestone 4

Someone may write about a crisis in this box, and Lumen won't detect it. So, with no model involved and regardless of what's typed, this is **always visible next to the box** (Q4):

> Lumen only turns this text into suggested scores. No one reads it, and it can't respond to what you write.
> If you're struggling: SNS 24, 808 24 24 24, option 4 (psychological support, 24 hours).
> In an emergency, call 112.

## 3. What "95% accurate" can mean

**Exact matches on a 1 to 5 score probably won't reach 95%, and that isn't all down to the model.** *"ok evening"* has no single right number: reasonable people could pick 3 or 4. I haven't measured this, and no study I found matches this task. The nearest figure is from a different task, where two people rating text quality on a 5-point scale were within one point of each other 82.7% of the time.

A wrong suggestion also costs little here, because the person sees and corrects it. The expensive errors are the ones they might miss. So the bar focuses on those. The owner approved these numbers after scoring 30 held-out notes blind, and before any model saw the held-out split (Q1):

| Metric | What it catches | Bar | The owner, on the same measure |
|---|---|---|---|
| **Suggested scores within one point** | A clearly wrong suggestion | **At least 95%** | 96.5% |
| **Addressed dimensions it scores at all** | Being useless by leaving everything blank | **At least 75%** | 81% |
| **Left blank,** on dimensions the text doesn't address | Invented scores | **At least 90%** | 94% |
| **Off by three or more,** of addressed dimensions | Reversals, such as high stress scored as calm | **At most 1%** | 1.4% |
| **Time per suggestion** on this machine (M4 Pro, 24 GB), after the model has loaded | Check-ins should take under a minute (`PROJECT.MD` §2.10) | **Under 10 seconds, 95th percentile** | n/a |
| Exact match, of addressed dimensions | Reported for reference | No bar | 56% |
| Tag precision and recall | Reported for reference | No bar yet: set with the owner after the first run | n/a |

The bar applies to each language separately.

**If no model meets the bar, implementation stops and the options go to the owner.** The bar is never lowered silently.

### The evaluation set

- **Synthetic only, because this repository is public.** No real check-in text is ever committed.
- **150 entries:** terse notes, long ones, mixed days, negation (*"not stressed at all"*), stress's reversed scale, nothing relevant at all, and about 10 distressing entries, which must return valid output rather than failing.
- **Split 50 and 100.** Prompts are tuned on the 50 and the result is reported on the 100, which aren't looked at until then. Tuning and reporting on the same entries would inflate the score.
- **100 entries gives roughly 300 labelled scores,** so a measured 95% is good to about 2.5 points either way. The entries aren't fully independent, so that's a rough figure.
- **Who writes the labels matters:** if I write both the text and the labels, the set flatters the model (Q3).
- **Candidates:** two or three models that fit this machine, one around 3 to 5 GB and one around 10 to 18 GB, chosen from Ollama's library when this runs. Published comparisons I found were weak, so this set decides.

## 4. Acceptance criteria

API and screen tests use a fake `SuggestionModel`, since a real model is slow and non-deterministic. The real model is measured separately (§3).

**Evaluation (first PR)**
- **AC-1:** `make eval-extraction MODEL=x` prints the §3 metrics for the chosen split and needs no database. It's not part of CI.
- **AC-2 (client):** against a stub HTTP server, a valid reply gives the expected suggestion. An unreachable server, a `404` (no such model), a timeout, invalid JSON and JSON of the wrong shape each raise one error type, whose message doesn't contain the text.
- **AC-3 (privacy settings):** the app refuses to start with `OLLAMA_URL=http://192.168.1.5:11434`, `http://example.com`, or a cloud `OLLAMA_MODEL`. It starts with `127.0.0.1`, `localhost` and `[::1]`.

**API (second PR)**
- **AC-4:** with the fake returning `{"mood": 3, "stress": 4}` and `["poor_sleep"]`, the endpoint returns exactly that, and the `checkins` table stays empty.
- **AC-5 (no trace):** text with a marker, sent through a success, a `503` and a crash, leaves no marker in the log, in the error responses, or in any table.
- **AC-6 (filtering):** a fake returning a score of 9, a dimension not asked that day, and an unlisted tag has all three removed, while valid values remain.
- **AC-7 (failures):** with the model unavailable: `503 suggestions_unavailable`. Without a session: `401`. Without a CSRF token: `403`. Empty or over 2,000 characters: `422`, with no text in the body.
- **AC-8 (no open transaction):** while the fake is running, `pg_stat_activity` shows no transaction open for the request.
- **AC-9 (isolation):** the fake receives only the calling user's tags.
- **AC-10 (mode):** `PUT` with `mode: "free_text"` stores it, without it stores `structured`, and an unknown value gets `422`.

**Screen (second PR)**
- **AC-11:** suggestions fill blank fields, and a field already chosen keeps its value. Nothing is saved until the save button is pressed.
- **AC-12:** a `503` shows a message, keeps the text, and the form still saves.
- **AC-13:** the save request's body holds no free text, and a successful save clears the box. Nothing is written to `localStorage` or `sessionStorage`.
- **AC-14:** the §2.7 text is visible before anything is typed, and stays visible while a suggestion is loading or has failed.
- **AC-15 (end to end):** in Chromium under the real CSP, with a stub standing in for Ollama: write, suggest, correct a score, save, and see the corrected value on the overview.

**Checked by hand once, with real Ollama**
- With a marker in the text and default settings, the marker isn't in the output of `ollama serve`, or anywhere under `~/.ollama`.
- Ollama's log shows `Ollama cloud disabled: true`, and it binds to `127.0.0.1` only.
- A suggestion still works with the network off, which shows nothing depends on leaving the machine.

**Untested by justification:** Ollama's own handling of `format`, which is its behaviour rather than ours, and the prompt's wording, which the evaluation measures better than any unit test could.

## 5. Mutation check

A new `suggestions` group in `make mutate`:
- Non-loopback URL allowed, and cloud model allowed
- Unlisted tag, out-of-range score or unasked dimension passed through
- Suggestion saved by the endpoint
- CSRF or session check removed
- Text included in the `503` body or the client's error
- Transaction held open during the model call
- All users' tags passed to the model
- `mode` ignored on `PUT`

And web faults, tested by hand as with earlier specs: overwriting a chosen field, saving automatically, sending the text in the save request, not clearing the box, and hiding the §2.7 text while loading.

One-off faults under the project workflow: a slow model while other requests arrive, a reply that's cut off mid-JSON, a second suggestion pressed while the first is running, and a reply arriving after the person has already saved.

## 6. Decisions

The owner chose the recommendation on Q2 to Q4, approved the revised bar on Q1 after scoring the blind sheet, and approved downloading the candidate models.

| # | Question | Decision |
|---|---|---|
| Q1 | **What does 95% mean?** The first version counted a blank on an addressed dimension as a miss, and asked for 95% within one point and 95% left blank. The owner then scored 30 held-out notes blind, and scored 79% and 94% on those measures, because two careful people often disagree about whether a note addresses a dimension at all. Where both gave a score, they agreed 96.5% within one point. | **§3 as it now stands,** approved by the owner before any model saw the held-out split. 95% applies to suggested scores, with coverage and left blank set against the owner's own result. This is easier to pass than the first version. |
| Q2 | **Which languages?** | **English and Portuguese,** split evenly and reported separately. The bar applies to each language. |
| Q3 | **Who labels the evaluation set?** | **Claude writes the entries, and the owner scores 30 of them blind.** How far the scores differ shows how ambiguous the text is, the realistic ceiling for any model. |
| Q4 | **Is the §2.7 wording right?** | **Yes, as written.** The owner confirmed it, including the phone details. |

## 7. Added during implementation (for review)

- **Replaces §2.5's schema: the client doesn't use Ollama's `format`.** `gemma4` answers `501 structured output is unavailable` to both a schema and JSON mode, in Ollama 0.40.14, and it's the strongest candidate so far. The prompt asks for JSON, the client reads the first JSON object, and everything is still validated.
- **Adds a quote check.** For each dimension the model must quote the note's exact words, and code drops any score whose quote isn't in the note. Without it, `qwen3:8b` left unaddressed dimensions blank only 23 to 29% of the time. It discards the quote afterwards.
- **`trust_env=False` and no redirects,** because a proxy setting or a redirect could carry text off the machine, even with a loopback URL. Both are tested.
- **Fewer labelled scores than §3 estimated:** 215 on the held-out split, about 108 per language, rather than about 300. A measured 95% is good to about 4 points per language.
- **`either` in the evaluation set** marks dimensions a note only hints at, where a score and a blank are both fair. They aren't measured.
- **Distressing entries are left out of the owner's blind sheet.** They're the least ambiguous entries, and the owner doesn't need to read them.
- **A failed call counts as wrong in every measure,** including left blank, so a failure can't look like a correct blank.
- **Hand check results so far:** a marker sent to real Ollama wasn't in its output or anywhere under `~/.ollama`, its log shows `Ollama cloud disabled: true`, and it listens on `127.0.0.1` only. Not yet checked: a suggestion with the network off.
- **Results vary slightly between runs,** even at temperature 0 with a fixed seed.

- **The client reads scores written as text,** such as `"score": "3"`. The first held-out run dropped these, so the two smaller models scored almost nothing. That was a client bug rather than their result. All three models were rerun after the fix, with no change to the prompt, and only the fixed result is reported.
- **`--against-owner` added,** which judges a model against the owner's blind scores. It has no bar: the bar was set against the labels.

### Second PR: the API and screen

- **The owner chose `gemma4:26b` for now,** the only model that met the bar, and kept `gemma4:e4b` as a fallback. `qwen3:8b` was deleted.
- **The endpoint also applies the editable-day rule,** giving `422 date_out_of_range`, as saving does.
- **`mode` is always sent by the web app,** because the generated type requires it. A day edited later without suggestions becomes `structured` again, since saving replaces the whole day.
- **A person's own tags are offered first,** then the starter tags, each once.
- **A note that gives nothing to suggest says so,** rather than appearing to do nothing.
- **The first suggestion after starting Ollama took 25 seconds,** while the model loaded. The bar excludes this, but a person will notice it. The 60-second timeout leaves room for it.
- **The network check used a sandbox** rather than turning off the owner's network: `sandbox-exec` denied all outbound traffic except to localhost, with a control showing that an outside request failed inside it and worked outside it. A real suggestion through the real app worked, and a marker in the note wasn't in the app's log, Ollama's log, under `~/.ollama`, or in the database's log.
- **Web faults were run by hand,** as §5 says, because `make mutate` doesn't cover the frontend.
- **"No session needed" isn't a repeatable mutant,** because it takes two edits and the runner applies one. It was checked once by hand, and went red.

### Prompt moved out of the code (the owner's review of the second PR)

- **The wording is now in `src/lumen/suggestions/prompts/checkin_extraction_v1.txt`,** one file per version, with the rendering in `lumen.suggestions.prompt`. The owner raised this, and also PostgreSQL and Langfuse as places for it. The owner agreed to a file in git for now: an editable row could run a prompt nobody measured, the parser must change together with the prompt, and Langfuse's tracing would store Tier 0 text. Langfuse can be reconsidered for hosted agents, which only see redacted data, in its own spec.
- **The results below still apply.** The prompt hasn't changed since they were measured, and the move was checked byte for byte with all dimensions and starter tags, a subset, and no tags.
- **`evals/extraction/measured_prompt.json` records the measured prompt's SHA-256,** and a test fails if the prompt changes. The hash covers the rendered prompt rather than the file, so changing an anchor or a starter tag also needs a new measurement. A held-out run updates it only if the bar is met in both languages.
- **The record doesn't cover the model.** It names `gemma4:26b`, but `OLLAMA_MODEL` in `.env` can still select one that was never measured.
- **Rendering now happens outside the client's error handling,** so a broken template shows as a crash rather than as "the local model is unavailable". The hash test fails on a broken template first, so this has no test of its own.
- **No test for `$` in a tag:** tags can only match `^[a-z][a-z0-9_]{0,39}$`, and `Template` doesn't substitute into values anyway. The byte comparison included such values once.

### Held-out results (100 entries)

Each cell is English / Portuguese.

| Model | Size | Suggestions within one | Coverage | Left blank | Off by 3+ | Slowest 5% | Bar |
|---|---|---|---|---|---|---|---|
| **Bar** | | **≥95%** | **≥75%** | **≥90%** | **≤1%** | **<10 s** | |
| `gemma4:26b` | 16 GB | 99.1% / 98.0% | 99.1% / 93.4% | 95.8% / 95.5% | 0% / 0% | 4.2 / 4.7 s | **Met in both** |
| `gemma4:e4b` | 9.5 GB | 100% / 99.0% | 96.3% / 96.2% | 91.2% / **88.9%** | 0% / 0% | 1.4 / 1.4 s | English only |
| `qwen3:8b` | 5.2 GB | 99.0% / 97.9% | 95.4% / 90.6% | **87.4%** / **88.5%** | 0% / 0.9% | 5.5 / 6.7 s | Neither |

Exact match: `gemma4:26b` 79.8% / 74.5%, `gemma4:e4b` 78.0% / 71.7%, `qwen3:8b` 66.1% / 64.2%. `qwen3:8b` also failed 2 calls in English, one of them on a distressing note, which on its own fails the bar. `gemma4:26b` and `gemma4:e4b` failed none.

Tags (precision and recall): `gemma4:26b` 90.5% and 70.4% / 95.5% and 60.0%. Recall is weak on all three, and tags have no bar yet.

### Against the owner's blind scores (30 entries, 66 of the owner's scores)

Too few notes to judge precisely: one note moves off-by-3 by about 3 points.

| Rater | Suggestions within one | Coverage | Left blank | Off by 3+ |
|---|---|---|---|---|
| Claude's labels (the baseline) | 96.6% / 96.4% | 80.6% / 93.3% | 92.8% / 89.3% | 2.8% / 0% |
| `gemma4:26b` | 93.5% / 96.3% | 86.1% / 90.0% | 88.4% / 84.0% | 2.8% / 3.3% |
| `gemma4:e4b` | 97.0% / 96.6% | 91.7% / 96.7% | 82.6% / 76.0% | 2.8% / 0% |
| `qwen3:8b` | 93.8% / 100% | 88.9% / 93.3% | 84.1% / 80.0% | 2.8% / 0% |

### How far to trust these numbers

- **The labels and the notes have the same author, Claude,** which flatters language models. `gemma4:26b` beats the owner on those labels, and falls below the labels' own result against the owner's scores on left blank. The second table is the more independent one, and it's small.
- **The held-out notes are easier than the tuning ones,** because they were deliberately written to mention more dimensions: `gemma4:26b` has 99.1% / 93.4% coverage on them, against 90.2% / 88.9% on the tuning split.
- **All of it is synthetic.** Accuracy on real notes is unmeasured.
- **The evaluation asks for all seven dimensions at once, and the app asks for about five,** depending on the day, along with the person's own tags. So the app's prompt isn't exactly the measured one, and the effect hasn't been measured.
- **`gemma4:26b` peaks at about 23.5 GB of memory on this 24 GB machine.**
- **The held-out split has now been used,** and its results were read. Any future prompt change needs new held-out notes to be measured fairly.
