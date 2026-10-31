# Spec 002: Check-in vertical slice

**Status:** Draft. Open questions in §6
**Milestone:** 2 (PROJECT.MD §14 and §16)
**Builds on:** spec 001 (auth HTTP layer), `lumen.domain`, `lumen.analytics`, RLS (`user_transaction`)

## 1. Goal

A user can open Lumen in the browser, log in, record today's check-in in under 30 seconds, and see how each dimension is moving. This is the first full path from check-in to structured data, multi-user persistence, analytics and trend visualization. Everything later (privacy layer, agents) is built around it.

### Non-goals
- **No free-text check-ins or local model:** those are Milestone 3. `mode` is always `structured`.
- **No agents, conversation, reminders or scheduler.**
- **No deleting check-ins, and no data export.** A wrong entry is fixed by editing it (§2.2).
- **No UI for password change or account settings:** the API exists (spec 001), the screens come later.
- **No tag effects, correlations or weekly means in the UI.** The analytics exist, but showing them invites over-reading; they belong with the Weekly Review (Milestone 6).
- **No mobile layout work** beyond not breaking at narrow widths. It's a desktop app.

## 2. Proposed decisions

### 2.1 Delivery: four PRs, one spec
1. **Check-in and overview API** (backend, TDD from AC-1 to AC-8).
2. **Web app shell:** the `web/` project, toolchain (Q4), generated API types, login and register screens, and a CI job.
3. **Check-in screen.**
4. **Overview screen** (charts), plus the end-to-end test (AC-9).

Each PR cites the acceptance criteria it covers. Adding the web CI job to the required checks needs a branch-protection change, which I'll propose in PR 2.

### 2.2 Check-in semantics
- **One check-in per local day (Q1).** Saving a day that already has a check-in **replaces** it: scores and tags are overwritten, not merged. A new unique constraint on `checkins (user_id, local_date)` enforces this, and saving is an upsert.
- **The client sends the local date.** The browser knows the user's timezone; the server doesn't. `recorded_at` is the server clock at the time of the last save.
- **Which dates are accepted (Q2).** With `D` = the server's current UTC date, `local_date` must be within `[D − 8, D + 1]`. That's 7 days of backfill, plus one day of slack either way, because timezones run from UTC−12 to UTC+14.
- **Dimensions (Q3).** All three core dimensions (mood, energy, stress) are required. Rotating dimensions are optional, and any of them is accepted. The server says which two are *prompted* that day (`dimensions_for(local_date)`); the UI shows only those.
- **Tags** use the existing normalization (`"Time outdoors"` → `time_outdoors`). At most 20 per check-in. The UI suggests the user's existing tags (most used first) and the starter list from PROJECT.MD §4.2. Starter tags are only stored once used.

### 2.3 API (JSON; every endpoint requires login and runs on the user-scoped RLS session)

| Method and path | Purpose |
|---|---|
| `GET /api/dimensions` | All 7 dimensions: key, display name, cadence, polarity, and the five anchors (label and description) |
| `GET /api/checkins/{local_date}` | `{local_date, prompted: [dimension…], checkin: {scores, tags, recorded_at} \| null}` |
| `PUT /api/checkins/{local_date}` | Body `{scores: {dimension: 1–5}, tags: [str]}`. Creates or replaces the check-in and returns the same shape as `GET` |
| `GET /api/tags` | The user's tags with usage counts, ordered by count descending, then name |
| `GET /api/overview?end={local_date}` | Per dimension, in `DIMENSIONS` order: the period change and trend from `summarize_all` (each with direction, outlook and data-point counts), plus `daily` (daily means) and `rolling_7` (7-day rolling mean) for the 84-day trend window |

- **Validation errors** use spec 001's error shape, with `422` and the codes `missing_core_dimension`, `invalid_score`, `unknown_dimension`, `invalid_tag`, `too_many_tags` and `date_out_of_range`.
- **The overview** is a faithful mapping of `lumen.analytics`: the API computes nothing of its own (PROJECT.MD §2.2). Every number travels with its data-point count (§7, "all analytics outputs must state the number of data points").
- **`end` is required,** so the server never guesses the user's "today".

### 2.4 Frontend
- **Where it lives:** `web/` (PROJECT.MD §15). React with TypeScript in strict mode. Toolchain in Q4.
- **Generated API types:** TypeScript types are generated from FastAPI's OpenAPI schema into `web/src/api/schema.d.ts`. CI fails if the committed file is stale, so the frontend and backend can't drift apart silently.
- **Screens:**
  - **Log in / Register**
  - **Today:** the check-in form. Each dimension is a group of five labelled options with their anchor descriptions, operable by keyboard. There are tag chips plus a free entry field, and a date picker limited to the backfill window. If the day already has a check-in, the form is prefilled.
  - **Overview:** see §2.5.
- **Session handling:** one API client attaches `X-CSRF-Token` (read from the `__Host-lumen_csrf` cookie) to unsafe requests, and sends the user to *Log in* on any `401`.
- **Running it:**
  - `make dev` runs FastAPI (uvicorn, port 8000) and the Vite dev server (port 5173). Vite proxies `/api` to FastAPI, so the browser sees a single origin, already allowed by spec 001 Q4.
  - `make run` builds the frontend, and FastAPI serves it at `http://localhost:8000`. That is the everyday "desktop app".

### 2.5 Overview screen: presenting results honestly
- **One card per dimension. There is no combined "wellbeing score"** (PROJECT.MD §7).
- **Chart:**
  - **Data:** daily values as points and the 7-day rolling mean as a line, over 84 days.
  - **Y axis:** fixed at 1–5, labelled with the anchor names.
  - **Stress:** the axis is *not* flipped. The card says "higher = more stress", and colour follows the outlook rather than the raw direction.
- **Two plain-language lines, each with its data basis (Q5):**
  - *Lately:* "Lower than the previous 4 weeks (based on 22 and 25 days)", or "No clear change", or "Not enough data yet (6 days)".
  - *Direction:* "Gradually improving over 12 weeks (based on 70 days)", or "Stable", or "Unclear".
- **Numbers:** the estimate and its 95% interval are available on an expand control, never as the headline.
- **Tone:** wording is descriptive, never clinical or alarming (PROJECT.MD §2.1). Because one in twenty comparisons of unchanging data is flagged by chance, a "worsening" card never uses alarm colours or words like "warning".
- **Safety note (Q6):** a short footer line on every screen.

### 2.6 Database
- **One migration:** the unique constraint `uq_checkins_user_id_local_date`. It fails loudly if a dev database already holds two check-ins for one day; reseed in that case. The synthetic personas already produce one per day.
- **RLS:** no new tables, so the existing policies and grants cover everything. `lumen_app` already has `SELECT, INSERT, UPDATE, DELETE` on `checkins`, `checkin_scores` and `checkin_tags` (migration `3d3fd70e14a1`). Tags are only ever inserted, never changed, so their `SELECT, INSERT` grant is enough.

## 3. Acceptance criteria

Backend criteria are HTTP-level tests against the real test database with an injected clock, as in spec 001. Unless stated otherwise, the clock is **2026-10-31T12:00Z**.

**Check-ins**
- **AC-1 (save and read):** `PUT /api/checkins/2026-10-31` with `{mood: 4, energy: 3, stress: 2, sleep_quality: 5}` and tags `["Time outdoors", "exercise"]` gives `200`. `GET` for the same date returns exactly those scores, the tags `["exercise", "time_outdoors"]`, `prompted` equal to `dimensions_for(2026-10-31)`, and `recorded_at` equal to the clock.
- **AC-2 (replace, not merge):** a second `PUT` for the same date with `{mood: 2, energy: 2, stress: 4}` and no tags gives `200`. `GET` returns only those three scores: `sleep_quality` is gone and there are no tags. The overview counts **one** day of data for 2026-10-31.
- **AC-3 (validation):** each of these gives `422` with the listed code, and nothing is stored (a following `GET` shows `checkin: null`):
  - stress missing → `missing_core_dimension`
  - `mood: 6` → `invalid_score`
  - `"happiness": 3` → `unknown_dimension`
  - tag `"!!"` → `invalid_tag`
  - 21 tags → `too_many_tags`
- **AC-4 (date window):** `2026-11-01` and `2026-10-23` are accepted; `2026-11-02` and `2026-10-22` give `422 date_out_of_range`.
- **AC-5 (tags):** after check-ins tagged `[exercise]`, `[exercise, alcohol]` and `[alcohol, exercise, workday]`, `GET /api/tags` returns `exercise (3), alcohol (2), workday (1)` in that order.

**Overview**
- **AC-6 (faithful to analytics):** with the `burnout` persona (seed 42) saved through the API's database for 112 days ending 2026-10-31, `GET /api/overview?end=2026-10-31` equals, field for field, `summarize_all` and `rolling_mean` run directly on the same observations. Spot-check: mood's change outlook is `worsening`.
- **AC-7 (no data):** a new user gets `200`. Every dimension has direction `insufficient_data`, outlook `unknown` and zero data points, with empty `daily` and `rolling_7`.

**Isolation**
- **AC-8:** users A and B each save a check-in for 2026-10-31. B's `GET /api/checkins/2026-10-31`, `GET /api/tags` and overview contain only B's data, and A's check-in is unchanged after B's `PUT`.

**Frontend**
- **AC-9 (end to end, Playwright, against the real backend):**
  1. Register.
  2. The *Today* form shows mood, energy and stress plus the two prompted rotating dimensions, each with its five anchor labels.
  3. Choosing values by keyboard alone and submitting leads to the *Overview*, where mood shows "Not enough data yet (1 day)".
  4. After a reload, the user is still logged in and *Today* is prefilled.
  5. Logging out returns to *Log in*.
- **AC-10 (API client):** an unsafe request carries `X-CSRF-Token` equal to the CSRF cookie, and a `401` on any request sends the user to *Log in*. Covered by a Vitest test with a mocked `fetch`, since the network is the slow dependency here.
- **AC-11 (contract):** CI fails when `web/src/api/schema.d.ts` differs from the types generated from the current backend.

**Untested by justification**
- **`GET /api/dimensions`:** a direct mapping of the `DIMENSIONS` constant. The generated types (AC-11) pin its shape, and AC-9 renders it.
- **Login, CSRF and `401` on the new routes:** these are enforced by the shared dependencies proven in spec 001 (AC-9 there and the mutation check). A route that forgot `CurrentUser` would have no `user_id` to work with, and AC-8 would fail.
- **Wording and colours on the Overview:** a mapping from `outlook` to text. AC-9 checks one case end to end; the rest is reviewed visually in PR 4.

## 4. Mutation check
Add mutants to `scripts/mutate.py` for:
- the upsert (merging instead of replacing)
- the date window bounds (off by one at either end)
- the core-dimension requirement
- the overview passing a different `end` or window to analytics

## 5. Added during implementation
*(empty until implementation)*

## 6. Open questions

| # | Question | Recommendation |
|---|---|---|
| Q1 | One check-in per day (saving again replaces it), or several per day (averaged)? | **One per day.** It matches "how was today", keeps the form idempotent, and analytics already work on daily means. Several per day would need a UI for choosing which one to edit. |
| Q2 | How far back can you enter or edit a day? | **7 days.** Enough to catch up after a missed weekend, but recent enough that memory of the day is still reliable. Older retrospective scores are known to be less accurate. |
| Q3 | Which dimensions are required? | **The 3 core dimensions required; rotating ones optional.** Requiring rotating dimensions adds friction (§2.10), and the analytics already handle sparse rotating data. |
| Q4 | Frontend toolchain (PROJECT.MD §18) | See the table below. |
| Q5 | How should uncertainty be shown? | **A plain-language verdict plus the data basis as the headline; the estimate and 95% interval behind an expand control.** Intervals are easy to misread, but hiding them completely would hide the method. |
| Q6 | A static safety note before the Safety workflow (Milestone 4)? | **Yes, one footer line:** "Lumen is not a crisis service. If you are in danger, contact your local emergency number." Which number to show, if any, is your call; it's easy to change later. |

**Q4: proposed toolchain**

| Concern | Recommendation | Why | Main alternative |
|---|---|---|---|
| Build tool | **Vite** | Standard for React SPAs; fast dev server with an `/api` proxy | none worth considering |
| Package manager | **pnpm** | Strict dependency resolution, and it doesn't run dependencies' install scripts by default (a supply-chain defence) | npm: one less tool to install |
| Language | **TypeScript, `strict`** | Matches mypy strict on the backend | — |
| Routing | **React Router** | Three screens; well known | TanStack Router |
| Server state | **TanStack Query** | Caching, refetch after saving, loading and error states without hand-written code | plain `fetch` with hooks |
| Styling | **CSS Modules, native form elements, no component library** | Few screens. Native radio groups give keyboard and screen-reader support for free | Tailwind; shadcn/ui |
| Charts | **Recharts** | React-native API, supports points plus line and fixed axes; widely recognized | Observable Plot (nicer for statistics, less idiomatic in React) |
| Lint and format | **ESLint (typescript-eslint) and Prettier**, run by pre-commit | Same "one command checks everything" as the backend | Biome |
| Tests | **Vitest and Testing Library** for units; **Playwright** for AC-9 | Minimal suite per our testing rules: one end-to-end test covers the slice | Cypress |
