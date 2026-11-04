# Spec 003: HTTP security headers

**Status:** Proposed (open questions in §5)
**Builds on:** spec 001 (auth HTTP layer), spec 002 (FastAPI serves the built frontend)

## 1. Goal

FastAPI now serves Lumen's web pages, and those pages show sensitive personal data. If a bug ever lets someone inject script, the browser should refuse to run it or send data elsewhere. This spec adds the headers that make the browser enforce that.

### Non-goals
- **`make dev`:** Vite serves the page there and its hot reload needs inline script, so the policy applies only to pages FastAPI serves.
- **Deployment and HTTPS:** Lumen runs on `localhost` (see Q2).

## 2. Proposed decisions

### 2.1 Headers on every FastAPI response

| Header | Value | What it does |
|---|---|---|
| `Content-Security-Policy` | see §2.2 | Limits what the page may load, run and contact |
| `X-Content-Type-Options` | `nosniff` | Stops the browser treating a file as a different type, such as running JSON as script |
| `Referrer-Policy` | `no-referrer` | Keeps Lumen's URLs, which contain dates, from being sent to other sites |
| `Cross-Origin-Opener-Policy` | `same-origin` | Stops other windows getting a handle on Lumen's |
| `Cross-Origin-Resource-Policy` | `same-origin` | Stops other sites embedding Lumen's responses |
| `Permissions-Policy` | `camera=(), geolocation=(), microphone=()` | Lumen uses none of these, so injected script can't either |

`X-Frame-Options` is left out: `frame-ancestors` does the same job in every current browser.

### 2.2 Content-Security-Policy

```
default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

- **Everything is denied unless listed,** and only Lumen's own origin is listed.
- **No `'unsafe-inline'` or `'unsafe-eval'`.** The built page has no inline script or style, so it doesn't need them.
- **`connect-src 'self'`** limits where script can send data. This matters for Lumen's privacy promise: even injected script can't post check-ins to another site.

### 2.3 Personal data isn't cached

Responses under `/api/` also get `Cache-Control: no-store`, so check-ins and overview data aren't written to the browser's disk cache. Pages and assets contain no personal data and are unaffected.

### 2.4 Where it lives

One ASGI middleware, outermost, so that requests refused by the existing request guard also get the headers. A response from an unhandled crash (`500`) doesn't pass through it, and that's accepted: it contains no page or personal data.

## 3. Acceptance criteria

HTTP-level tests, with no database needed:

- **AC-1 (every response):** the exact headers of §2.1 and §2.2 are on all of these:
  - `GET /`
  - a static asset
  - `GET /api/auth/me` when logged out (`401`)
  - an unknown `/api` path (`404`)
  - a `POST` refused by the Origin check (`403`)
- **AC-2 (caching):** `Cache-Control: no-store` is on the `/api` responses above and absent from `GET /` and the asset.
- **AC-3 (Q1):** with no frontend configured, `/docs`, `/redoc` and `/openapi.json` give `404`, and `make check-schema` still works.

**Checked in a real browser, once, with a throwaway script** (a Playwright test belongs to spec 002 AC-9):
- The full login flow under `make run` causes no CSP violations.
- A script injected into the page doesn't run, and a `fetch` to another origin is blocked.

**Untested by justification:** the meaning of each header is the browser's behaviour, not ours. AC-1 pins the exact values, and the browser check confirms the policy works with the real page.

## 4. Mutation check

Add to the `http` group:
- middleware not installed
- middleware inside the request guard, so refused requests lose the headers
- `'unsafe-inline'` added to `script-src`
- `connect-src` widened
- `no-store` missing, and `no-store` applied to everything
- API docs routes left on

## 5. Open questions

| # | Question | Recommendation |
|---|---|---|
| Q1 | This policy breaks FastAPI's `/docs` page, which loads its code from a third-party CDN and runs an inline script. Exempt it, or remove the docs routes? | **Remove `/docs`, `/redoc` and `/openapi.json`.** Nothing in the repo uses them, and an exemption would run third-party code on the same origin as your session. Generating the frontend's types doesn't use these routes, and `make schema` still produces the full API description in `web/openapi.json`. |
| Q2 | Add `Strict-Transport-Security`? | **Not yet.** Browsers ignore it over plain HTTP, so it does nothing on `http://localhost`. Decide it with deployment, when HTTPS exists. |

**A risk for spec 002's PR 4:** Recharts may need inline styles that `style-src 'self'` blocks. Styles React sets from script are allowed, but I haven't tested Recharts under this policy. PR 4 will check it, and any change to the policy would come back to you rather than being loosened silently. For that reason AC-9 should run against `make run`, so the end-to-end test runs under the real policy.
