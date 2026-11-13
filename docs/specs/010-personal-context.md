# Spec 010: Personal context and stricter tags

**Status:** Approved (decisions in §6)
**Builds on:** spec 006 (suggestions), spec 008 (all seven dimensions)

## 1. Goal

The owner wrote *"Woke up well rested, although I woke up 3 times in the night"*. The model suggested sleep quality 3 and the tag `poor_sleep` every time. For the owner it's a 4, and not poor sleep: they often wake in the night and fall asleep again quickly.

There are two causes:

- **The model doesn't know the person's normal.** For many people, waking three times is a bad night. No wording of the anchors fixes that, because it depends on the person.
- **The tag rule is too weak.** The prompt already says to choose a tag "only if the note states it outright", and the model still picks `poor_sleep` from waking up. Measured tag precision is 61% / 67% (spec 008), and tags have no bar.

The owner chose two fixes:

- **Personal context:** a short note the person writes once, such as *"Waking a few times at night is normal for me"*, which the model sees with every suggestion.
- **A stricter tag rule in the prompt.**

### Non-goals
- **Weighing stated feelings over events in the prompt.** This was part of the option the owner didn't choose. Personal context is the fix for the owner's case.
- **The Memory Curator** (`PROJECT.MD` §4.10). Personal context is written by the person, not proposed by an agent, so it needs no approval step. The Curator can take it over later.
- **Showing volunteered scores in the overview,** which is spec 009.
- **Pinning the model.**

## 2. Proposed decisions

### 2.1 What personal context is

- **One short text per person,** written and edited by them, at most 750 characters (Q1).
- **Tier 0** (`PROJECT.MD` §8): it can name people and describe health, so it never leaves the machine. Only the local model sees it, and it's never sent to a hosted model.
- **Saved, unlike a free-text note.** The person writes it so it can be kept, and they can change or delete it at any time. Saving empty text deletes it.
- **Never logged.** `EventLog` already logs only allowlisted fields, so no change is needed there, and a test checks it (AC-4).

### 2.2 What it may change, and what it can't

The model gets the context in its own section of the prompt, marked as the person's description of their own normal, to use only when reading the note.

- **It can't invent a score.** Every score still needs a quote from the note, which the code checks. So a context saying *"I'm always tired"* can't produce an energy score on a day the note says nothing about energy.
- **It can't invent a tag.** The prompt says tags come from the note only, never from the context. Otherwise *"I drink coffee late every day"* would tag `caffeine_late` every day. The code can't check this the way it checks quotes, so the evaluation measures it (§2.6).
- **It can't change the rules.** The context sits after the rules and is described as information, not instructions. Only the person can write it, so this protects them from accidental wording rather than from an attacker.

### 2.3 Storage

A table `personal_context (user_id, text, updated_at)`, one row per person, with `user_id` as the primary key. It gets forced RLS with a `user_isolation` policy, and `lumen_app` gets `SELECT, INSERT, UPDATE, DELETE`, all in its migration, as `CLAUDE.md` requires for every new user-data table.

### 2.4 API

- `GET /api/context` returns `{"text": "..."}`, or `{"text": ""}` when there's none.
- `PUT /api/context` takes `{"text": "..."}`. Text is trimmed, at most 750 characters, and empty text deletes the row.
- **Suggestions read the context** in the same short transaction that reads the person's tags.

### 2.5 The web app

- **A "Personal context" page,** linked from the header next to Today and Overview (Q2). It has one text box, a character count and Save. It says what the context is for, that it stays on this machine, and that it can't create scores on its own.
- **Below the Suggest button,** "Using your personal context" appears when there is one, so the person knows it's being applied (Q3).

### 2.6 Prompt v3 and its measurement

Prompt v3 is v1 with two changes:

- **A personal context section,** filled in when there's a context, and left out otherwise.
- **A stricter tag rule,** with one example per kind of mistake. `poor_sleep` needs the note to say the sleep was bad; waking up isn't enough on its own. A tag comes from the note, never from the context.

It's measured as spec 008 was, with two additions:

- **A fourth set of held-out notes,** written and committed before v3. About half come with an invented personal context that changes the right reading, such as waking at night being normal, and their labels follow that context. Spec 008's notes become `test_v3`.
- **Tuned only on `dev`,** which gets some notes with contexts too.
- **The bar is spec 006's for scores,** per language, with and without context. **Tags get their own bar** (Q4).
- **`measured_requests`** includes the measured contexts, so the hash covers how a context is rendered.

### 2.7 Delivery: two PRs

1. **Storage, API and the page,** with the context not yet sent to the model. It's useful on its own, because the person can write their context while v3 is measured.
2. **Prompt v3,** the held-out notes, the measurement and the tag bar.

## 3. Acceptance criteria

**First PR**
- **AC-1 (save and read):** `PUT {"text": "  Waking at night is normal for me.  "}` stores it trimmed, and `GET` returns exactly that. A second `PUT` replaces it.
- **AC-2 (limits):** 751 characters gives `422`. `PUT {"text": ""}` deletes the row, and `GET` then returns `{"text": ""}`.
- **AC-3 (RLS and grants):** another user can't read or change the row, even with `lumen_app` and no filter. The new table is covered by the test that every user-owned table is protected.
- **AC-4 (never logged):** a context containing a marker is saved, read and used, and the marker isn't in the log, in any other table, or in an error message.
- **AC-5 (the page):** the page shows the saved context, counts characters and saves the edited text. Clearing it and saving deletes it.

**Second PR**
- **AC-6 (sent to the model):** with a context saved, the suggestion route passes it to the model. Without one, it passes nothing, and the prompt has no context section.
- **AC-7 (can't invent):** with a context and a note that says nothing about energy, a reply that scores energy with a quote from the context is dropped by the quote check.
- **AC-8 (shown):** the Today page says "Using your personal context" only when there is one.
- **AC-9 (measured):** `measured_requests()` includes the measured contexts, and `measured_prompt.json` holds the hash after a held-out run that meets both bars.

**Untested by justification:** the model's use of the context, which the evaluation measures.

## 4. Mutation check

Add to the `suggestions` and `checkins` groups, or a new `context` group:
- the context saved untrimmed, or over the limit
- empty text saved instead of deleted
- the route reads another user's context, or none
- the context sent when there's none
- quotes checked against the context as well as the note
- the context section kept when empty

## 5. Delivery

1. This spec.
2. The two PRs of §2.7, each with its tests failing first, fault injection, and an "Added during implementation" section here.

## 6. Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | How long can the context be? | **750 characters,** longer than the 500 recommended. |
| Q2 | Where do you edit it? | **Its own "Personal context" page, linked in the header.** |
| Q3 | Show "Using your personal context" by the Suggest button? | **Yes.** |
| Q4 | What bar for tags? | **Precision at least 85% per language,** and recall reported without a bar. |
| Q5 | Should the context ever reach a hosted model? | **No, never.** |
