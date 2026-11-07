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
