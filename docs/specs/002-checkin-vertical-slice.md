# Spec 002: Check-in vertical slice

**Status:** Approved (decisions in §6)
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
2. **Web app shell:** the `web/` project, toolchain (Q4), generated API types, the date and time helper (§2.4, AC-12), login and register screens, and a CI job.
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
- **Where it lives:** `web/` (PROJECT.MD §15). React with TypeScript in strict mode. Toolchain in Q4 (§6).
- **Generated API types:** TypeScript types are generated from FastAPI's OpenAPI schema into `web/src/api/schema.d.ts`. CI fails if the committed file is stale, so the frontend and backend can't drift apart silently.
- **Screens:**
  - **Log in / Register**
  - **Today:** the check-in form. Each dimension is a group of five labelled options with their anchor descriptions, operable by keyboard. There are tag chips plus a free entry field, and a date picker limited to the backfill window. If the day already has a check-in, the form is prefilled and shows when it was last saved, e.g. "Last saved 15 July at 21:00". The date stays in the line because a backfilled day can be saved on a later day.
  - **Overview:** see §2.5.
- **Dates and times (Q7).** The API and database stay in UTC, and the server neither knows nor stores the user's timezone. All of this goes through one tested helper in the web app:
  - **Instants (`recorded_at`):** converted to the browser's current timezone for display, in the browser's locale format. Someone travelling sees the time where they are now, not where they recorded it.
  - **Calendar days (`local_date`, `end`, chart dates):** never converted. Parsing `"2026-10-31"` with `new Date(...)` means midnight UTC, which displays as 30 October west of UTC.
  - **"Today":** the browser's local date, never the UTC date from `toISOString()`.
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
- **AC-12 (dates and times):** a Vitest test of the helper, with the timezone and locale (`en-GB`) fixed so the results don't depend on the machine:
  - **Summer time:** `2026-07-15T20:00:00Z` displays as 15 July, 21:00 in `Europe/Lisbon`.
  - **Winter time:** `2026-01-15T20:00:00Z` displays as 15 January, 20:00 in `Europe/Lisbon`.
  - **"Today" ahead of UTC:** at `2026-07-14T23:30:00Z`, today in `Europe/Lisbon` is `2026-07-15`.
  - **"Today" behind UTC:** at `2026-07-15T02:00:00Z`, today in `America/New_York` is `2026-07-14`.
  - **Calendar day:** `2026-10-31` displays as 31 October in `America/New_York`.

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

## 5. Added during implementation (for review)

### PR 1: check-in and overview API

| # | Addition | Reason |
|---|---|---|
| I1 | Data endpoints get their database session through `Depends(user_session, scope="function")`, so the transaction **commits before the response is sent**. | FastAPI's default for `yield` dependencies (`scope="request"`) commits *after* the response. If that commit failed, the client would already have seen `200` for a check-in that was never saved. Spec 001 introduced `user_session`, but nothing wrote through it until now. **Untested by justification:** the difference only shows when a commit itself fails, and this schema has no deferred constraints that fail at commit time. |
| I2 | AC-6's spot-check is now "stress's 12-week trend is `increasing` with outlook `worsening`", replacing "mood's change outlook is `worsening`". | The original was my guess, and the data says otherwise. With seed 42, mood's last 28 days are noisily *higher* (+0.40, 95% CI −0.09 to +0.90), so the change is correctly `unclear`. The stress check is also stronger: it proves polarity flows through the API, because rising stress is reported as worsening. |
| I3 | Request-size bounds: at most 14 score entries, 100 tags, and 100 characters per key or tag. Beyond those, the response is `422 invalid_request`. Scores must be JSON integers: `true`, `"4"` and `4.0` are rejected. | Bounds the work one request can cause. The domain still applies the real limits (20 tags, known dimensions). Without strict integers, Pydantic would silently accept `true` as `1`. |
| I4 | `rolling_7` lists only days that have a rolling mean. Days missing from the list are gaps for the chart to show. | That's what AC-7 implies (an empty list with no data). Joining the line across long gaps would invent a trend. |
| I5 | The date window applies only to **saving**. `GET /api/checkins/{date}` reads any date. | Reading old data harms nothing, and the overview reads 90 days anyway. |
| I6 | `GET /api/tags` lists only tags that at least one check-in still uses. | After an edit removes a tag, it shouldn't keep being suggested with a count of 0. |
| I7 | The plain index on `checkins (user_id, local_date)` is dropped. | The new unique constraint's index covers the same queries. |

### PR 2: web app shell

| # | Addition | Reason |
|---|---|---|
| I8 | **AC-10 is narrowed:** a `401` with code `invalid_credentials` doesn't send the user to *Log in*. | A wrong password is also a `401`. Followed literally, AC-10 would reload the login screen and lose the error. |
| I9 | A session ending is a full page load to `/login`, not a router navigation. | It also discards all of the user's data held in memory. |
| I10 | `make run` and `make dev` use `--no-access-log` and bind to `127.0.0.1`. | uvicorn's access log records client IP addresses, which Lumen never stores. |
| I11 | New setting `WEB_DIST`. The app **refuses to start** if that directory has no `index.html`. | An empty `WEB_DIST=` means the current directory, which would publish the repository, including `.env`. |
| I12 | Paths under `/api` never get the web app. Any other unknown path gets `index.html`, including a missing asset. | A reload on a browser route must load the app, and an API client must get a `404`, not a `200` with HTML. |
| I13 | The API client reads the CSRF cookie with or without the `__Host-` prefix. | The prefix depends on `COOKIE_SECURE`. Safari rejects Secure cookies on `http://localhost`, so using Safari locally needs `COOKIE_SECURE=false`. |
| I14 | Node 26 (pinned in `web/.nvmrc`, installed with fnm), and pnpm pinned through `packageManager`. TypeScript stays on 5.9. | Node 26 no longer includes corepack. `typescript-eslint` needs TypeScript below 6.1, and `openapi-typescript` needs 5.x. |
| I15 | Screens have no unit tests, and Testing Library and jsdom aren't installed yet. | The forms are linear glue over the tested client, and AC-9 covers them end to end in PR 4. For this PR, a throwaway browser script checked 14 behaviours under both `make run` and `make dev`. |
| I16 | The web mutants aren't in `scripts/mutate.py`, which only runs pytest. They were run once with a throwaway script: 16 of 16 caught. | The first run found a real gap (no test crossed a month boundary), so AC-12 has one extra case: `2027-01-01T02:00:00Z` is `2026-12-31` in `America/New_York`. Adding web mutants to `make mutate` is a follow-up. |
| I17 | *Today* and *Overview* are headings only. | They're filled in by PR 3 and PR 4. |

**Open for the owner:**
- **Required check:** add "Web (tests, build, API types)" to `master`'s required checks, as §2.1 proposed.
- **Content-Security-Policy:** FastAPI now serves HTML, and no CSP or other security headers are set. Adding them would be a separate small PR.

### PR 3: check-in screen

| # | Addition | Reason |
|---|---|---|
| I18 | The form also shows any dimension that day already has a score for, even if it isn't prompted. This goes beyond §2.2, which says the UI shows only the prompted ones. | Saving replaces the whole day, so hiding an answered dimension would silently delete its score on the next save. |
| I19 | The day picker is a dropdown of today and the 7 days before it, not a calendar. | It can't produce a date outside the window, and it's quick by keyboard. |
| I20 | The UI offers `[local today − 7, local today]`. The API's wider window only allows for timezones. | Tomorrow's date is accepted by the API, but the form has no reason to offer it. |
| I21 | Optional dimensions get a *Clear* button once answered. | Native radio buttons can't be unselected, so an optional answer couldn't otherwise be taken back. |
| I22 | Tags are shown as stored, e.g. `time_outdoors`. | It's the simplest honest display, and it matches what the user will see in later analytics. Friendlier labels can come later. |
| I23 | Typed tags are normalized in the browser with the same rule as the API. | A typed "Time-Outdoors" must select the existing tag rather than add a duplicate. The API stays the authority and rejects invalid tags. |
| I24 | The screen has component tests with Testing Library and jsdom. This reverses I15, which applied to the login forms. | This form has real branches, and a mistake here corrupts data without any visible error. |
| I25 | Check-in screen mutants were run once with a throwaway script: 21 of 21 caught. They aren't in `make mutate` (see I16). | The first run found two missing tests, and one check that could never fail, which was removed. |

### PR 4: overview screen and end-to-end test

| # | Addition | Reason |
|---|---|---|
| I26 | The overview's wording has tests, and three lines §2.5 didn't give exact wording for are decided. Flat and unclear changes both read "No clear change". A trend with too little data reads "Not enough data yet (N days)". Every line keeps its data basis. This narrows the "untested" justification for wording in §3; colours are still reviewed by eye. | A swapped branch would tell someone the opposite of what their data says, and nothing would crash. |
| I27 | "Not enough data yet" counts the days in both 4-week periods, so it can read "(22 days)". | That's what analytics reports: rotating dimensions can have 22 days and still not support a comparison, because neighbouring days are correlated. The owner kept this wording. |
| I28 | Outlook colour is a small dot beside each line: teal for better, violet for harder, grey otherwise. The chart itself is always blue. The legend names them "Getting better", "Getting harder" and "No clear change". | *Lately* and *Direction* can disagree, so one card can't have a single colour. Violet avoids alarm colours (§2.5). The colours pass the palette checker in both modes, apart from one contrast warning on the light-mode teal dot, and the words beside it carry the meaning. |
| I29 | *Numbers* also holds a table of the chart's values, newest first. The chart can be read with the arrow keys. | §2.5 only asked for the estimates there. A tooltip can't be the only way to read a value. |
| I30 | A card with no data has no chart. Daily points are smaller (radius 2.5) and paler than the chart guidance's default. | Seven empty charts say nothing. At 84 days, larger points would overlap. |
| I31 | Saving a check-in removes the cached overview rather than marking it stale. | Otherwise the screen you land on after saving briefly shows the overview from before the save. |
| I32 | Adds `recharts` and its peer `react-is`. The chart code loads only when the overview needs it: 97 kB gzipped for the main bundle, 105 kB for the chart. | Recharts is over half of the app's code, and login and *Today* don't use it. |
| I33 | y-axis labels are drawn by a small custom tick. | Recharts' own tick wrapped "Very connected" out of the chart, whatever the axis width. AC-9 checks high scores are at the top. |
| I34 | **AC-9 is `make e2e`:** `make run` on port 8001 (`make run` gains `PORT`), against `lumen_test`, in a new CI job, "End to end (Playwright)". It also fails on any CSP violation or uncaught page error, and checks the policy header is present. | It can run beside the everyday app, it can't touch the development database, and it never reuses a running server. |
| I35 | Overview mutants were run once with a throwaway script: 30 of 30 caught. They aren't in `make mutate` (see I16). A real browser checked the screen with 16 weeks of synthetic data, in light and dark, at phone width, and with the tooltip by mouse and keyboard. | Wording, numbers and the cache are what can quietly go wrong here. Layout and colour can only be checked by eye. |

**Decided by the owner (2026-11-05):**
- **Required check:** "End to end (Playwright)" is now one of `master`'s required checks.
- **Wording of I27:** "Not enough data yet (22 days)" stays as it is.
- **Colours and legend wording of I28:** kept for now.

## 6. Decisions

The owner approved every recommendation as written (PR #16).

| # | Question | Decision |
|---|---|---|
| Q1 | One check-in per day (saving again replaces it), or several per day (averaged)? | **One per day.** It matches "how was today", keeps the form idempotent, and analytics already work on daily means. Several per day would need a UI for choosing which one to edit. |
| Q2 | How far back can you enter or edit a day? | **7 days.** Enough to catch up after a missed weekend, but recent enough that memory of the day is still reliable. Older retrospective scores are known to be less accurate. |
| Q3 | Which dimensions are required? | **The 3 core dimensions required; rotating ones optional.** Requiring rotating dimensions adds friction (§2.10), and the analytics already handle sparse rotating data. |
| Q4 | Frontend toolchain (PROJECT.MD §18) | See the table below. |
| Q5 | How should uncertainty be shown? | **A plain-language verdict plus the data basis as the headline; the estimate and 95% interval behind an expand control.** Intervals are easy to misread, but hiding them completely would hide the method. |
| Q6 | A static safety note before the Safety workflow (Milestone 4)? | **Yes, one footer line:** "Lumen is not a crisis service. If you are in danger, contact your local emergency number." No specific number is shown. |
| Q7 | How does the web app show dates and times? (added after approval) | **Local time in the browser, UTC in the API and database (§2.4).** The *Today* form shows when the day was last saved. Approved by the owner on 2026-11-04. |

**Q4: toolchain**

| Concern | Decision | Why | Main alternative considered |
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
