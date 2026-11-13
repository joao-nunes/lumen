# Spec 009: Volunteered scores in the overview

**Status:** Proposed, awaiting the owner's decisions in §6
**Builds on:** spec 002 (overview), spec 008 (volunteered scores)

## 1. Goal

Since spec 008, a score for a dimension the day didn't ask about is saved and labelled **volunteered**, but the overview leaves it out. The owner decided volunteered scores should **appear in trends**, while staying **out of the statistics**. People mention a dimension mostly when it stands out, so these scores lean towards the extremes and would bias means, changes and correlations.

This spec shows volunteered scores on each dimension's chart, marked so they can't be mistaken for asked ones, and keeps every computed number asked-only.

### Non-goals
- **The recurring-topic notice,** such as "you've brought up sleep on 5 of the last 14 days". The owner wants it done later by a **conversational agent**. Per `CLAUDE.md`, the counting stays deterministic code, and the agent only interprets and phrases it. That agent needs its own spec, including its safety rules and what it may send to a hosted model.
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

### 2.4 Analytics

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

**Untested by justification:** the exact tooltip wording, which AC-5 covers through the legend.

## 4. Mutation check

Add to the `analytics` or `checkins` group:
- volunteered scores included in `daily` or the statistics
- the volunteered list unfiltered by user, or by window
- the volunteered list includes asked scores

The chart faults are run by hand: volunteered points drawn filled, joined to the line, or missing from the table.

## 5. Delivery

1. This spec.
2. One implementation PR, with its tests failing first, fault injection, and an "Added during implementation" section here.

## 6. Open questions for the owner

| # | Question | Recommendation |
|---|---|---|
| Q1 | **What does the legend call them?** | **"Mentioned, not asked".** It says what happened without judging it, and matches "Not asked today" on the form. |
| Q2 | **Should the 7-day average include volunteered scores?** | **No.** It's a statistic, so it would lean towards the days that stood out. |
| Q3 | **Show "Also mentioned on N days without being asked"?** | **Yes.** It makes the count visible without turning it into a statistic. The later agent can build on it. |
| Q4 | **A dimension with only volunteered scores:** show the points, with "Not enough data yet" for the statistics? | **Yes.** It's honest: the points are real, but there's nothing unbiased to compute. |
| Q5 | **Record the conversational agent's notice in `PROJECT.MD` now,** as planned future work? | **Yes, one line** under the agents, so it isn't lost. Its design waits for its own spec. |
