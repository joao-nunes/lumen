# Spec 009: Volunteered scores in the overview

**Status:** Proposed. The owner has answered everything except Q7, where the heatmap goes (§6.2)
**Builds on:** spec 002 (overview), spec 008 (volunteered scores)

## 1. Goal

Since spec 008, a score for a dimension the day didn't ask about is saved and labelled **volunteered**, but the overview leaves it out. The owner decided volunteered scores should **appear in trends**, while staying **out of the statistics**. People mention a dimension mostly when it stands out, so these scores lean towards the extremes and would bias means, changes and correlations.

This spec shows volunteered scores on each dimension's chart, marked so they can't be mistaken for asked ones, and keeps every computed number asked-only. It also adds a calendar heatmap, which the owner asked for, showing each day's score for each dimension at a glance, volunteered ones included.

### Non-goals
- **The recurring-topic notice,** such as "you've brought up sleep on 5 of the last 14 days". The owner will decide after this spec whether it should be deterministic or handled by a conversational agent. Either way, per `CLAUDE.md`, the counting itself stays deterministic code.
- **Correlations,** which don't exist yet. When they're added, they'll use asked scores only (§2.4).
- **Changing the rotation schedule.**

## 2. Proposed decisions

### 2.1 What the API returns

Each dimension in `GET /api/overview` gains a `volunteered` list: one `{date, value}` for each day in the 84-day trend window with a volunteered score for that dimension.

- **Everything else stays asked-only:** `daily`, `rolling_7`, `change` and `trend`, so no number moves.
- **A day has at most one score per dimension,** so a day appears in `daily` or in `volunteered`, never both.
- **Core dimensions are never volunteered,** because every day asks about them, so their list is always empty.

### 2.2 How the chart shows them

- **A hollow circle** at the score, so asked and volunteered are told apart by shape as well as by the legend, never by colour alone.
- **Not joined to the 7-day average line,** which stays asked-only (Q2).
- **The legend gains "Mentioned, not asked"** (Q1). Hovering shows the day, the score and "mentioned, not asked".
- **The Numbers table gains a column** for volunteered scores, so the chart's data stays readable without the chart.

### 2.3 The summary text

The "Lately" and "Direction" lines stay asked-only. Under them, a dimension with volunteered scores in the window says how many: "Also mentioned on 4 days without being asked" (Q3).

A dimension with only volunteered scores in the window shows its hollow points, with "Not enough data yet" for the statistics, as now (Q4).

### 2.4 A calendar heatmap per dimension

The owner asked for a GitHub-style heatmap: one small calendar per dimension, one cell per day, coloured from good to bad, so a person can see at a glance how each one has been lately. **Volunteered scores enter it,** because it shows each day's score rather than computing anything from them.

- **Colour follows the outlook, not the raw number,** so good is always the same colour: high stress is bad, high mood is good.
- **A diverging scale:** good at one end, bad at the other, and the neutral middle score (3) in grey, as charts in this app use for "no clear change".
- **A day without a score is an empty cell,** never filled in, as elsewhere in the overview.
- **Not by colour alone:** every cell has the day and score as its accessible name and tooltip. The legend shows the five steps with their anchor labels, and the Numbers table already lists every value.
- **Volunteered cells are marked,** so the two kinds can be told apart here too (Q8).
- **The palette must pass the colour-blindness checker** the charts already use, in light and dark mode. A plain green-to-red scale fails it, because red against green is what red-green colour blindness can't separate (Q6).

### 2.5 Analytics

- **`list_observations` stays asked-only.** A new `list_volunteered` returns volunteered scores, for showing only.
- **The developer guide gets a rule** that statistics, including future correlations, use asked scores only, and why.

## 3. Acceptance criteria

The clock says Saturday 31 October 2026, which asks about sleep quality. Friday 30 October asks about concentration and social connection, so sleep there is volunteered.

- **AC-1 (API):** with sleep 5 saved on 31 October (asked) and sleep 1 on 30 October (volunteered), sleep's overview has `daily` `[{31 Oct, 5}]` and `volunteered` `[{30 Oct, 1}]`. Its `change` and `trend` are exactly those of the 31 October score alone.
- **AC-2 (window):** a volunteered score 85 days before `end` isn't listed. One on `end` is.
- **AC-3 (isolation):** another user's volunteered scores never appear.
- **AC-4 (core):** mood, energy and stress always have an empty `volunteered`.
- **AC-5 (chart):** the sleep chart draws one filled point and one hollow point. The legend shows "Mentioned, not asked", and the 7-day line passes through asked points only.
- **AC-6 (summary):** sleep shows "Also mentioned on 1 day without being asked". Mood shows no such line.
- **AC-7 (table):** the Numbers table lists 30 October with the volunteered score in its own column, and 31 October in Daily.
- **AC-8 (end to end):** the Playwright test adds a dimension the day didn't ask about, saves it, and finds a hollow point on that dimension's chart, under the real Content-Security-Policy.

- **AC-9 (heatmap colours):** for stress, a 1 has the "good" end colour and a 5 the "bad" end. For mood it's the other way round. A 3 is the neutral grey, and a day with no score has no fill.
- **AC-10 (heatmap contents):** the sleep calendar has a cell for 30 October, marked volunteered, with the accessible name "30 October: 1, Very poor, mentioned, not asked", and one for 31 October, unmarked. Days before the window aren't drawn.
- **AC-11 (palette):** the heatmap's five colours pass the checker in light and dark mode.

**Untested by justification:** the exact tooltip wording, which AC-5 covers through the legend.

## 4. Mutation check

Add to the `analytics` or `checkins` group:
- volunteered scores included in `daily` or the statistics
- the volunteered list unfiltered by user, or by window
- the volunteered list includes asked scores

The chart faults are run by hand: volunteered points drawn filled, joined to the line, or missing from the table. So are the heatmap faults: colour by raw score instead of outlook, a missing day filled in, volunteered cells unmarked or left out.

## 5. Delivery

1. This spec.
2. One implementation PR, with its tests failing first, fault injection, and an "Added during implementation" section here.

## 6. Decisions and open questions

### 6.1 Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | What does the legend call them? | **"Mentioned, not asked".** |
| Q2 | Should the 7-day average include volunteered scores? | **No,** because of the missing values. Instead, **add a GitHub-style heatmap per dimension, coloured from good to bad, with volunteered scores included** (§2.4). |
| Q3 | Show "Also mentioned on N days without being asked"? | **Yes.** |
| Q4 | A dimension with only volunteered scores? | **Show the points,** with "Not enough data yet" for the statistics. |
| Q5 | Record the notice in `PROJECT.MD` now? | **Not yet.** Whether the notice is deterministic or an agent will be discussed after this spec. |
| Q6 | Which colours? | **Green for good, and for bad a red-orange that's also much darker,** tuned until both pass the colour-blindness checker in light and dark mode. The hue changes only if they can't. |
| Q8 | How are volunteered cells marked? | **A small dot in the cell,** explained in the legend. |
| Q9 | How far back? | **The same 12 weeks as the charts,** one column per week, Monday at the top, the newest week on the right. |

### 6.2 Open questions about the heatmap

| # | Question | Recommendation |
|---|---|---|
| Q7 | **Where does it go?** | **One "Lately" section at the top of the overview,** with one small calendar per dimension side by side, so you see all seven at once. Each dimension's card keeps its line chart. |
