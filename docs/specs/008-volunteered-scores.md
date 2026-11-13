# Spec 008: Volunteered scores

**Status:** Approved (decisions in §6)
**Builds on:** spec 002 (check-ins and overview), spec 006 and spec 007 (suggestions and their measurement)

## 1. Goal

The form asks about mood, energy and stress every day, and two of the four rotating dimensions. If someone writes *"I couldn't concentrate today"* on a day concentration isn't asked, Lumen currently discards it, and prompt v2 tells the model to ignore it.

The owner decided to keep it instead. A score for a dimension the day didn't ask about is **volunteered**:

- **The check-in records** whether each score was asked or volunteered.
- **Free text can suggest** a volunteered score, which the person confirms like any other.
- **The form can add** a dimension that wasn't asked.
- **Analytics decide** how to use volunteered scores. People mention a dimension mostly when it stands out, so volunteered scores lean towards the extremes, and statistics computed on them would be biased.

### Non-goals
- **Showing volunteered scores in the overview and trends, and the recurring-topic notice.** Both belong to spec 009, which already has the owner's decisions: volunteered scores appear in trends, are left out of correlations and similar statistics, and a notice points out a dimension volunteered often lately, whether its scores are high or low. Safety comes first.
- **Changing the rotation schedule,** which is still an open question in `PROJECT.MD` §18.
- **Pinning the model,** as in spec 007.

## 2. Proposed decisions

### 2.1 The owner's decisions

| Decision | Choice |
|---|---|
| Record asked or volunteered | **Yes, for every score** |
| Volunteered scores in trends | **Shown** (spec 009) |
| Volunteered scores in correlations and other statistics | **Left out** (spec 009, and §2.4 until then) |
| A notice for a dimension volunteered often | **Yes, for high and low scores** (spec 009) |
| Safety | **Comes first:** the crisis text and Milestone 4 take priority over any notice |
| "Add another dimension" on the form | **Yes,** so both ways of checking in behave the same |

### 2.2 Storage: one column, set by the server

`checkin_scores` gets `volunteered boolean NOT NULL`.

- **The server decides, at save time:** a score is volunteered if its dimension isn't in `dimensions_for(local_date)`. Clients don't send it, so a client can't mislabel a score, and the rule lives in one place.
- **It's stored, not worked out later,** because `prompted` comes from the date. If the schedule changes, working it out later would relabel past scores (developer guide, known issues). Re-saving a day recomputes it, but only the last 7 days can be edited.
- **No new table and no change to RLS:** the column is on an existing user-data table, whose policy and grants already cover it.

### 2.3 Existing scores

The migration labels existing scores using the schedule as it is today: any score whose dimension wasn't scheduled for its day is volunteered. The schedule is copied into the migration as SQL, so later changes to `dimensions_for` can't change what the migration does, and a test checks that the SQL agrees with `dimensions_for` (AC-4).

### 2.4 Analytics leave volunteered scores out until spec 009

`list_observations`, which feeds the overview, returns only asked scores. So the overview's means, changes and intervals stay as they are. A volunteered score is saved and shown on the day's form, but not in the overview until spec 009, as the owner accepted (Q2).

### 2.5 API

- **`GET /api/checkins/{date}`** adds `volunteered`, the list of the day's volunteered dimensions. `scores` keeps its shape, so nothing that reads it breaks.
- **`PUT /api/checkins/{date}`** doesn't change. It already accepts any known dimension.
- **`POST /api/checkins/{date}/suggestion`** asks the model about all seven dimensions and returns every score with evidence. The web app tells asked from volunteered with the day's `prompted` list.

### 2.6 The form

- **A volunteered score has its own row,** marked "Not asked today", with the existing Clear button. A suggested one also shows "(suggested)", as asked dimensions already do.
- **"Add another dimension"** lists the dimensions not on the form. Picking one adds its row with nothing selected, and the control disappears once all seven are shown.
- **A row added but left unscored isn't saved,** as with any dimension.

### 2.7 Suggestions: prompt v1's wording, all seven dimensions

The model is asked about all seven dimensions every time. This is the setup spec 006 tuned for and measured, and spec 007's diagnosis found it gave the most blanks right: 95.5% / 92.8% on `dev`. It also removes the problem v2 was written for, since nothing has to be ignored.

- **The wording stays v1's,** with no new tuning (Q1). The invented tags stay, as in spec 007.
- **Measured once, on new held-out notes,** because spec 007's have been read. They're written and committed before the run, and spec 007's `test` split becomes `test_v2`.
- **Spec 006's bar, per language,** across all seven dimensions.
- **If the bar is missed,** implementation stops and the options go to the owner, as before.
- **v2 stays in the repository** with its results, as the record of what was measured.

### 2.8 Delivery: two PRs

1. **Storage, API, analytics and the form,** including "add another dimension". It's useful without suggestions, and has no model in it.
2. **Suggestions for all seven dimensions,** with the new held-out notes and the measurement. That run takes time and could miss the bar, so it shouldn't hold up the first PR.

## 3. Acceptance criteria

Saturday 7 November 2026 asks about concentration and social connection, so sleep quality and motivation are volunteered on that day.

**First PR**
- **AC-1 (labelled on save):** a save for 2026-11-07 with mood, energy, stress, concentration and sleep quality gives `volunteered: ["sleep_quality"]` from `GET`. In the database, only that row has `volunteered` true.
- **AC-2 (the client can't set it):** a `volunteered` field in the request body changes nothing.
- **AC-3 (re-save):** saving the same day again without sleep quality removes its row, and `volunteered` becomes empty.
- **AC-4 (existing scores):** on a database at the previous revision, scores saved on a day type A date and a day type B date, scheduled and not, are labelled correctly by the upgrade. The migration's SQL agrees with `dimensions_for` on every day of 2026 and 2027. The downgrade drops the column.
- **AC-5 (RLS and grants unchanged):** another user still can't read or change these rows.
- **AC-6 (analytics leave them out):** a volunteered sleep score of 1 on a day doesn't change the sleep overview, and an asked one does.
- **AC-7 (the form, volunteered row):** a saved day with a volunteered score shows it marked "Not asked today", and clearing it and saving removes it.
- **AC-8 (the form, add another dimension):** on 2026-11-07 the control lists sleep quality and motivation only. Adding sleep quality, scoring it 2 and saving sends it, and the control then lists motivation only.
- **AC-9 (end to end):** the existing Playwright check-in adds a dimension, saves, reloads and sees it marked "Not asked today".

**Second PR**
- **AC-10 (all seven asked):** the suggestion route asks the model about all seven dimensions on any day, and returns a volunteered score with evidence. With the fake model, "couldn't concentrate" on 2026-11-08 returns `concentration`.
- **AC-11 (suggested volunteered row):** on the form, a suggested volunteered score appears marked "Not asked today" and "(suggested)", and saving after confirming sends it.
- **AC-12 (measured):** `measured_requests()` is a single request, with all seven dimensions and the invented tags, and `measured_prompt.json` holds its hash after a held-out run that meets the bar.

**Untested by justification:** the wording of the labels, which AC-7 and AC-11 pin through the screen; the model's accuracy, which the run measures.

## 4. Mutation check

Add to the `checkins` or `suggestions` group:
- volunteered set from the client's body
- every score labelled asked, and every score labelled volunteered
- labelled by today's schedule rather than the check-in's day
- the migration's schedule shifted by a day
- volunteered scores included in observations
- the suggestion route asks only the day's dimensions
- "add another dimension" lists dimensions already on the form

## 5. Delivery

1. This spec.
2. The two PRs of §2.8, each with its tests failing first, fault injection, and an "Added during implementation" section here.

## 6. Decisions

The owner approved every recommendation.

| # | Question | Decision |
|---|---|---|
| Q1 | Use prompt v1's wording for all seven dimensions, without tuning? | **Yes.** If it misses the bar, the options come back to the owner. |
| Q2 | Volunteered scores saved but not in the overview until spec 009? | **Yes, acceptable.** |
| Q3 | Label existing scores from today's schedule? | **Yes.** |
| Q4 | What to call them on the form? | **"Not asked today".** |

## 7. Added during implementation (for review)

### First PR: storage, API, analytics and the form

- **`Checkin.volunteered` is a required keyword field,** so every way of making a check-in has to decide it: `volunteered_for(day, scores)` for a new one, the stored labels for a saved one. The synthetic personas only score what each day asks, so they volunteer nothing.
- **The column has no default after the migration,** so an insert that forgets the label fails rather than calling the score asked.
- **The migration's schedule is SQL with the rotating order written out,** and its test runs it on every day of 2026 and 2027 against `dimensions_for`. The test downgrades to the previous revision, adds data, upgrades, and always upgrades back to head.
- **The form labels a row "Not asked today" from the day's `prompted` list,** not the stored labels, so a row added by hand is marked before it's saved. They can only differ if the schedule changes.
- **In the end-to-end test, the dimension is chosen with Playwright's `selectOption`,** not the keyboard: on macOS Chromium, ArrowDown opens the menu instead of choosing.
- **One form fault survived at first:** the "add another dimension" control left on screen with nothing to choose. The test now checks that the control is gone.
- **After pulling this, run `uv run alembic upgrade head`,** or saving a check-in returns `500` on an existing database. The migration labels existing scores.
- **Not tested separately:** a domain check that only scored dimensions can be volunteered, since every caller builds the labels from the scores. RLS and grants are unchanged, and the existing test that every user-owned table is protected still covers `checkin_scores` (AC-5).

### Second PR: suggestions for all seven dimensions

- **New held-out notes were written and committed before any suggestion code,** in `a6229b5`: 100, half per language, with 100 English labels and 101 Portuguese across all seven dimensions, and only starter tags. They're new scenarios, and the Portuguese ones aren't translations. Spec 007's held-out notes became `test_v2`.
- **The code was committed before the measurement,** in `d5e2035`. That's prompt v1's wording, untuned, as decided in Q1. The rendering for v2's unasked list is gone, because nothing uses it; the v2 file stays as the record of spec 007.
- **The schedule's day types are gone from the evaluation:** every note is asked once, about all seven dimensions, as the app now does.
- **A bug the form test found:** a suggested score for a dimension that wasn't on the form would have been saved without ever being shown. It now gets its own row, marked "Not asked today" and "Suggested, please check". That's the existing mark for a suggested score; the spec's "(suggested)" is the mark for tags.

- **Mutation check:** 76 of 77 `suggestions` and `checkins` mutants were caught. The one that survived, "each note asked for every dimension", is now equivalent to the code, because every note is asked about all seven, so it was removed. "Measured for the day's dimensions, not all seven" covers the same risk. The form fault, a suggested volunteered score getting no row, went red by hand.

### The first held-out run was invalid

Ollama stopped partway through the first run: about 35 English calls worked, then every call failed. The run reported that outage as results: Portuguese at 0%, every call failed. I don't know why it stopped; the owner's Ollama had been running, and my command only stopped it at the end. The run printed only totals, swamped by failures, and no note-level results.

- **`collect` now stops after three failed calls in a row** (`RunAbortedError`), with a test and two mutants. It was committed in `eb8dc7d`, without changing the prompt or the route.
- **The same frozen code was then measured again,** on the same notes. That's a second attempt at the measurement, after the first measured only the outage. Nothing was tuned between them.
- **My command also stopped all of Ollama when it finished,** including the copy the owner had started. I restarted it afterwards, and from now on I'll only stop processes I started.

### Results: prompt v1, all seven dimensions, meets the bar

One valid run, on the new held-out notes. Each cell is English / Portuguese.

| | Bar | Result |
|---|---|---|
| Suggestions within one | ≥95% | 99.0 / 100 |
| Coverage | ≥75% | 96.0 / 98.0 |
| Left blank | ≥90% | 96.4 / 95.6 |
| Off by 3+ | ≤1% | 0 / 0 |
| Slowest 5% | <10 s | 4.3 / 5.5 s |
| Failed calls on distressing notes | 0 | 0 / 0 |

Exact match was 72.0 / 78.2%. **Tag precision fell to 61.1 / 66.7%,** against 85.7 / 90.6% for v2. With all seven dimensions to fill in, the model also picks more tags, and the invented tags are offered too. Tags still have no bar, and this is worth deciding.

Against the owner's blind scores, which have no bar:

| | Within one | Coverage | Left blank | Off by 3+ |
|---|---|---|---|---|
| Spec 007, v2 | 92.2 / 94.9 | 86.4 / 86.7 | 86.8 / 81.9 | 3.4 / 4.4 |
| This, v1 for all seven | 93.5 / 96.3 | 86.1 / 90.0 | 91.3 / 85.3 | 2.8 / 3.3 |

### How far to trust this

- **The new notes may be easier than real ones:** coverage is 96 / 98%. I wrote them knowing the earlier sets' weak spots.
- **The notes, labels and prompt all have one author, Claude.** The owner's scores are the more independent check, and v1 for all seven does best there of anything measured so far, though still below the bar.
- **Still synthetic,** so accuracy on real notes is unmeasured. A person's real tags still differ from the invented ones, and the record doesn't cover the model.
