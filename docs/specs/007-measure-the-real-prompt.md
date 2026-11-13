# Spec 007: Measure the prompt the app really sends

**Status:** Approved (decisions in §6)
**Builds on:** spec 006 (free-text check-ins, its bar and evaluation set)

## 1. Goal

`gemma4:26b` met spec 006's bar, but not with the prompt a person's suggestion uses:

| | Dimensions asked | Tags offered |
|---|---|---|
| **Evaluation** | All seven | The starter tags |
| **App** (`POST /api/checkins/{date}/suggestion`) | Five, depending on the day | The person's own tags, then the starter tags |

So the result may not describe what the app does. A shorter list could help the model, or it could push it to place a sentence about sleep under another dimension on a day sleep isn't asked. This spec measures the conditions the app really uses, so we know which.

### Non-goals
- **Changing the prompt.** If the result misses the bar, that comes back to the owner (§2.5).
- **A bar for tags,** which is a separate decision. Tag measures are still reported.
- **Pinning the model.** `OLLAMA_MODEL` can still select one that was never measured.
- **Real notes.** Everything stays synthetic, so accuracy on real notes stays unmeasured.
- **Limiting how many tags the app offers.** It sends every tag a person has used, so the prompt grows with them. The result may show whether this matters.

## 2. Proposed decisions

### 2.1 Every note is measured under both kinds of day

The schedule alternates between exactly two sets, which I confirmed over 800 days:

| Day type | Dimensions asked |
|---|---|
| A | mood, energy, stress, concentration, social connection |
| B | mood, energy, stress, sleep quality, motivation |

Each held-out note runs under both, 200 calls in all, because a person can write any note on either day. It should take about 10 to 15 minutes. Between them the two runs ask about all seven dimensions.

The day types come from `dimensions_for`, not a written copy, so a schedule change can't leave the evaluation behind (AC-2).

### 2.2 Only what was asked is measured

A dimension that wasn't asked isn't in the prompt, and the app drops any score for it, so it counts in no measure on that call. A note about sleep on a day sleep wasn't asked is therefore still a useful test: `left_blank` falls if the model puts that sentence under another dimension.

### 2.3 Invented tags stand in for a person's own

The evaluation offers a fixed list of invented tags first, then the starter tags, in the same order the app uses. No label uses an invented tag, so choosing one counts against precision. Real tags can't be used, because this repository is public.

The route and the evaluation share one function for this order, so they can't drift apart. There are 12 (Q1).

### 2.4 The existing held-out notes can be used

I told the owner this would need new held-out notes. **It doesn't, unless the prompt changes.** Notes stop being held out when a prompt is tuned on them. Prompt v1 is frozen, the runs on this split only ever printed totals, and this is the first measurement under these conditions. One caveat from spec 006: the first run on this split led to a client fix for scores written as text, though not to a prompt change.

The margin stays about 4 points per language. There are still 215 distinct labels, about 108 per language, because running each note twice measures the core dimensions twice against the same labels.

### 2.5 What the result decides

The bar is spec 006's, unchanged, applied to each language across both day types (Q2).

- **Met:** the new hash and results go in the implementation PR, and the app's measurement now matches what it sends.
- **Missed:** implementation stops and the options go to the owner, as in spec 006. The bar isn't lowered, and the prompt isn't tuned without their decision. The likely options are tuning on `dev` as a new prompt version, which would then need new held-out notes, trying `gemma4:e4b`, or limiting the tags offered.

Only `gemma4:26b` runs, since it's the model in use. `--against-owner` also runs under both day types, without a bar, as the more independent check.

### 2.6 The hash covers what's measured

`prompt_fingerprint()` hashes all seven dimensions with the starter tags today. It changes to hash the prompts for both day types with the evaluation's tags, in order. So `measured_prompt.json` changes, and until a real run meets the bar, the test that compares them fails. That's why the implementation PR can't merge without a result.

A person's real tags will still differ from the invented ones, so the app's prompt can't match the measured one exactly. This narrows the gap and doesn't remove it, and the spec will say so with the results.

## 3. Acceptance criteria

Unit tests, with no model. The real run is a measurement, not a test, as in spec 006.

- **AC-1 (only asked dimensions count):** a note labelled `mood: 4, sleep_quality: 2`, asked under day type A, answered `mood: 4`. The metrics show `addressed` 1, coverage and within one of 100%, `unaddressed` 4 and left blank of 100%. The sleep score counts in neither, and neither does motivation.
- **AC-2 (every day is covered):** over two years of dates, `dimensions_for` never returns a set outside the evaluation's day types, and those day types together include every dimension.
- **AC-3 (a note under each day):** `make eval-extraction` calls the model once per note per day type, with exactly the dimensions of that day type, reported per language across both, and the first call is still excluded from timing.
- **AC-4 (same tag order):** with used tags `["reading", "exercise"]`, the offered tags are `reading`, `exercise`, then the other starter tags, each once, through the same function in the route and in the evaluation. The existing route test keeps proving the route's behaviour.
- **AC-5 (invented tags can't score):** no label in `entries.jsonl` uses an invented tag, and none is a starter tag, so choosing one always lowers precision.
- **AC-6 (the hash):** the system prompts sent for each day type, with the evaluation's tags, hash to `prompt_fingerprint()`, and changing a day type's dimensions or an invented tag changes it. Spec 006's check on `measured_prompt.json` stays.

**Untested by justification:** report formatting and the run's wiring in `scripts/eval_extraction.py`, beyond AC-3's calls; the model's own accuracy, which the run measures.

## 4. Mutation check

Add to the `suggestions` group:
- unasked dimensions counted as unaddressed
- unasked dimensions counted as addressed
- only one day type measured
- each day type asked for all dimensions
- invented tags left out, or offered after the starter tags
- route builds its own tag order
- hash ignores the second day type, or the invented tags

## 5. Delivery

1. This spec.
2. One implementation PR, with the failing tests first, then the real run. Its results go in this spec's "Added during implementation" section, including any result that's worse than spec 006's.

## 6. Decisions

The owner approved every recommendation.

| # | Question | Decision |
|---|---|---|
| Q1 | How many invented tags? | **12.** |
| Q2 | Keep spec 006's bar, per language across both day types? | **Yes.** It was set before any model saw the held-out split, and changing it with results known would weaken it. |
| Q3 | If the bar is missed, should suggestions stay on until the owner decides? | **Yes.** The feature is only used by the owner, and nothing is saved without their confirmation. |

## 7. Added during implementation (for review)

### Prompt v1 missed the bar under the app's conditions

The first held-out run measured v1 on the original held-out notes, as §2.4 planned. Each cell is English / Portuguese.

| | Bar | Spec 006 conditions | App's conditions |
|---|---|---|---|
| Suggestions within one | ≥95% | 99.1 / 98.0 | 99.4 / 97.4 |
| Coverage | ≥75% | 99.1 / 93.4 | 99.4 / 91.1 |
| **Left blank** | ≥90% | 95.8 / 95.5 | 92.2 / **89.7** |
| Off by 3+ | ≤1% | 0 / 0 | 0 / 0 |
| Slowest 5% | <10 s | 4.2 / 4.7 s | 3.3 / 3.6 s |

Against the owner's blind scores, left blank fell from 88.4 / 84.0 to 84.6 / 78.1, and off by 3+ rose from 2.8 / 3.3 to 3.4 / 4.4. Implementation stopped there, and the options went to the owner.

### Diagnosis, on the tuning split only

The owner chose to diagnose before changing anything. Left blank, English / Portuguese:

| Condition | Left blank |
|---|---|
| All seven dimensions, starter tags | 95.5 / 92.8 |
| The same answers, counted as two day types | 94.5 / 90.7 |
| Two day types, starter tags | 92.3 / 88.6 |
| Two day types, invented tags too (the app) | 92.3 / 89.6 |

- **The shorter list was the main cause.** On about 7 notes, the model moved a note's content onto an asked dimension: "could not focus" became motivation on a day concentration wasn't asked, for example.
- **Some of the drop was only what's counted,** because the core dimensions count twice.
- **Invented tags didn't affect blanks,** but lowered tag precision.
- **A first attempt at this run was invalid:** Ollama had stopped, so nearly every call failed. The script now aborts after three failures in a row. The earlier held-out and owner runs had no failed calls.

### The owner chose a prompt v2

I recommended always asking about all seven dimensions and discarding the unasked ones. The owner chose a prompt v2 instead, accepting that it's more work.

- **New held-out notes were written and committed before v2 existed:** 100, half per language, with the same mix of kinds as before. That's 102 English labels and 101 Portuguese, with only starter tags. The Portuguese notes are separate scenarios, not translations.
- **v1's held-out notes became `test_v1`.** They've been read, so they're never tuned on or measured again. The owner's blind scores belong to 30 of them, so `--against-owner` still uses them, and a test checks that the blind sheet still picks those 30.
- **v2 names the dimensions that aren't asked,** each with its lowest and highest anchor, and tells the model to ignore what a note says about them rather than move it. The reply still asks only for that day's dimensions.
- **Tuned on `dev` in three rounds,** then committed before the held-out run:
  - **Round 1** was overcautious: it dropped mood when a note clearly stated it. Its totals were lost because I kept only the end of the output.
  - **Round 2** narrowed the rule to unasked dimensions only.
  - **Round 3** added the unasked dimensions' descriptions.
  - **A leak avoided:** one example I added during tuning was close to a held-out note I'd written, so I replaced it before measuring. A check found no other wording shared with the held-out notes.
- **On `dev`, v2 against v1 under the app's conditions:** left blank 94.5 / 90.2 against 92.3 / 89.6. Coverage was 89.4 / 85.7 against 90.9 / 89.3: it suggests slightly less.

### Prompt v2 meets the bar

One run, on the new held-out notes:

| | Bar | v2 |
|---|---|---|
| Suggestions within one | ≥95% | 98.7 / 100 |
| Coverage | ≥75% | 100 / 94.9 |
| Left blank | ≥90% | 96.6 / 93.4 |
| Off by 3+ | ≤1% | 0 / 0 |
| Slowest 5% | <10 s | 3.9 / 3.7 s |
| Failed calls on distressing notes | 0 | 0 / 0 |

Exact match was 84.6 / 75.8%. Tag precision and recall were 85.7 and 77.8% in English, and 90.6 and 63.0% in Portuguese.

Against the owner's blind scores, which have no bar:

| | v1, app's conditions | v2 |
|---|---|---|
| Left blank | 84.6 / 78.1 | 86.8 / 81.9 |
| Off by 3+ | 3.4 / 4.4 | 3.4 / 4.4 |
| Suggestions within one | 92.2 / 94.9 | 92.2 / 94.9 |

### How far to trust this

- **The new notes look easier than the tuning ones.** Coverage was 100% / 94.9% on them, and 89.4% / 85.7% on `dev`. I wrote them after seeing v1's diagnosis, though before v2, so they may be clearer than real notes.
- **The notes, labels and prompt all have one author, Claude.** The owner's blind scores are the more independent check: v2 improves on v1 there, but stays below the bar, as v1 did in spec 006.
- **Still synthetic,** so accuracy on real notes is unmeasured.
- **A person's real tags still differ from the invented ones,** and the record still doesn't cover the model.
- **I committed v2 once with an unexpected failing test,** because a test assumed unasked anchors never appear in the prompt. I updated the test and amended the commit before pushing. The prompt didn't change.

### Other changes

- **`offered_tags`** in `lumen.suggestions.model` is now shared by the route and the evaluation. The route test now checks that a person's own tags come first, which it didn't before.
- **One mutant covers both of §4's "unasked dimensions counted" items,** because they come from the same line.
- **Added mutants** for the schedule being read for too few days, unasked dimensions not being named, prompt v1 being used again, and a person's own tags being offered last.
