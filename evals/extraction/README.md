# Evaluation set for free-text check-ins (spec 006)

`entries.jsonl` holds 150 synthetic check-ins, in English and European Portuguese, with their labels. **Everything here is invented. This repository is public, so no real check-in text ever goes in it.**

- `dev` (50 entries) is for tuning prompts.
- `test` (100 entries) is held out, and the result reported on it is the measurement.
- `either` lists dimensions a note only hints at, where a score and a blank are both fair. They aren't measured.

```bash
make eval-extraction MODEL=some-model              # the tuning split, with its misses
make eval-extraction MODEL=some-model SPLIT=test   # the held-out split, metrics only
```

A held-out run that meets the bar in both languages records the prompt's hash in `measured_prompt.json`, and a test fails if the prompt then changes. The developer guide explains how to change one.

## Scoring the blind sheet

`blind_sheet.csv` has 30 held-out entries, without their labels. The distressing entries are left out.

1. Copy it to `owner_scores.csv` and open it in a spreadsheet.
2. For each note, score only the dimensions it addresses, from 1 to 5, using the descriptions below.
3. **Leave a cell blank** if the note says nothing about that dimension. Most notes address only two or three.
4. Don't look at `entries.jsonl` while you do this, and don't overthink it: your first reading is what's useful.

Then `uv run python scripts/eval_extraction.py --agreement` compares your scores with the labels. Disagreement isn't a mistake on your part: it shows how much these notes can be read in different ways.

## The scale

**Mood** (`mood`).

| Score | Label | Description |
|---|---|---|
| 1 | Very low | Struggling to feel anything positive |
| 2 | Low | Mostly down, with brief better moments |
| 3 | Neutral | Neither good nor bad |
| 4 | Good | Generally positive |
| 5 | Very good | Clearly positive, light, engaged |

**Energy** (`energy`).

| Score | Label | Description |
|---|---|---|
| 1 | Depleted | Hard to get through basic tasks |
| 2 | Low | Running on reserves |
| 3 | Moderate | Enough for what the day needs |
| 4 | Good | Energy to spare for extra things |
| 5 | High | Energised and ready for anything |

**Stress** (`stress`). Higher is worse.

| Score | Label | Description |
|---|---|---|
| 1 | Calm | Relaxed, nothing pressing |
| 2 | Mild | Some pressure, easily manageable |
| 3 | Moderate | Noticeable pressure, still in control |
| 4 | High | Struggling to keep up, tense |
| 5 | Overwhelmed | Feels like too much to cope with |

**Sleep quality** (`sleep_quality`).

| Score | Label | Description |
|---|---|---|
| 1 | Very poor | Barely slept or woke up exhausted |
| 2 | Poor | Restless or too short |
| 3 | Okay | Adequate but not refreshing |
| 4 | Good | Woke up mostly rested |
| 5 | Very good | Deep, refreshing sleep |

**Motivation** (`motivation`).

| Score | Label | Description |
|---|---|---|
| 1 | None | Could not get myself to start anything |
| 2 | Low | Only did what was strictly necessary |
| 3 | Moderate | Got things done with some effort |
| 4 | Good | Wanted to make progress |
| 5 | High | Driven and eager |

**Concentration** (`concentration`).

| Score | Label | Description |
|---|---|---|
| 1 | Scattered | Could not hold focus at all |
| 2 | Poor | Frequently distracted |
| 3 | Okay | Focused in short stretches |
| 4 | Good | Focused most of the time |
| 5 | Sharp | Deep, sustained focus |

**Social connection** (`social_connection`).

| Score | Label | Description |
|---|---|---|
| 1 | Isolated | Felt alone or cut off |
| 2 | Distant | Little meaningful contact |
| 3 | Some | Some contact, neutral |
| 4 | Connected | Meaningful contact with others |
| 5 | Very connected | Felt close and supported |
