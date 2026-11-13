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
