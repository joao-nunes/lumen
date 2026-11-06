# Spec 004: Password change rate limit

**Status:** Approved (decisions in §5)
**Builds on:** spec 001 (auth HTTP layer, login rate limit in §2.5)

## 1. Goal

`POST /api/auth/password` needs the current password, so that a stolen session can't take over the account. But nothing limits how often it can be tried, and `401` against any other answer confirms a guess. Someone holding a stolen session can therefore guess the password until they find it, or until the session ends (12 hours idle, 7 days at most), then change it and lock the owner out.

This spec limits those guesses.

### Non-goals
- **Registration:** the owner decided it stays unlimited.
- **Login:** its limit stays as it is, including the gap in Q2.
- **A password change screen:** the web app has none. This changes the API only.
- **Cleaning up old attempts:** this waits for the scheduler milestone, like `auth.login_attempts` (spec 001 I4).

## 2. Proposed decisions

### 2.1 Rule

The same rule as login, with the same numbers:

- After **5 wrong current passwords within 15 minutes** for a user, further changes are refused with `429 too_many_attempts` and `Retry-After`, until the oldest of those failures is 15 minutes old.
- **During a lockout, even the correct password is refused,** without checking it. Otherwise the responses would still confirm guesses.
- **Refused requests aren't recorded,** so retrying doesn't extend the lockout.
- **A successful change resets the count.**
- **A correct current password with a weak new one (`422`)** neither counts as a failure nor resets the count. The password was right, but nothing changed.
- **A lockout ends no sessions and blocks nothing else** (Q1).

### 2.2 Counted per user, separately from login

A new table, `auth.password_change_attempts (user_id, attempted_at, succeeded)`. `user_id` references `users.id` with `ON DELETE CASCADE`, and `lumen_auth` gets `SELECT, INSERT` only. It's indexed on `(user_id, attempted_at)`.

- **Per user, not per session,** so logging in again or using a second session doesn't start a new count.
- **Not shared with `auth.login_attempts`,** for two reasons:
  - Anyone can fail a login for any email, so a shared count would let a stranger block the owner's password change.
  - A successful login resets the login count, so a shared count would give a thief more guesses each time the owner logs in.

It holds no IP addresses, and it isn't user content, so like the rest of the `auth` schema it is protected by grants rather than RLS.

### 2.3 Parallel requests can't get extra guesses

Checking a password takes Argon2 time, so requests sent together could all read a count below 5 before any failure is recorded. The check therefore starts by locking the user's `auth.password_credentials` row (`SELECT ... FOR UPDATE`) and holds it until the transaction ends. `lumen_auth` already has `UPDATE` on that table, which the lock requires.

### 2.4 Code

- The window and count logic in `LoginRateLimiter.retry_after` is shared rather than copied, and `RateLimitPolicy` is reused.
- `TooManyAttemptsError` is reused, so the `429` handler doesn't change. Its message becomes "Too many attempts; try again later", since it no longer applies only to login. The `code` stays the same.
- The route commits after a wrong password, as login does, or the failure would be lost.

## 3. Acceptance criteria

HTTP tests against the real test database, with an injected clock. All wrong passwords are sent with a valid session.

- **AC-1 (lockout):** registered at T0, with 5 wrong current passwords one minute apart (T0 to T0+4):
  - At T0+4, an attempt with the **correct** password gets `429 too_many_attempts` and `Retry-After: 660`.
  - The old password still logs in, and the session still works.
  - At T0+15 the correct password gets `204`.
- **AC-2 (refusals don't extend it):** 5 more attempts during the lockout don't change when it ends: at T0+15 the change still succeeds.
- **AC-3 (a new session doesn't help):** 5 failures from session A, then the correct password from session B gets `429`.
- **AC-4 (separate from login, both ways):**
  - 5 failed logins for the email don't stop a password change.
  - 5 failed password changes don't stop a login.
- **AC-5 (other users):** one user's lockout doesn't affect another's password change.
- **AC-6 (reset):** 4 failures, a successful change, then 4 more failures, and a further change with the new password gets `204`.
- **AC-7 (weak new password):** 4 failures, then the correct password with a weak new one gets `422`. A fifth wrong password gets `401`, and the next attempt gets `429`. This shows the `422` neither counted nor reset.
- **AC-8 (parallel):** 10 wrong passwords sent at once give exactly 5 `401` and 5 `429`.
- **AC-9 (grants):** `lumen_auth` can select and insert on the new table but not update or delete, and `lumen_app` can't touch it.

**Untested by justification:** `Retry-After` rounding and the `429` shape, which login's tests already prove through the same handler; `ON DELETE CASCADE`, since nothing deletes users yet and it matches the existing `auth` tables.

## 4. Mutation check

Add to the `auth` or `http` group:
- limit not checked on password change
- correct password accepted during a lockout
- failure not committed
- refused attempts recorded
- successful change doesn't reset the count
- `422` counted as a failure, and `422` counted as a success
- row lock removed
- counted per session instead of per user
- login failures counted towards the password change limit

## 5. Decisions

The owner approved both recommendations.

| # | Question | Decision |
|---|---|---|
| Q1 | Should reaching the limit also end the user's sessions? It would cut off a thief, but anyone mistyping 5 times would be logged out everywhere. | **No.** The limit already makes guessing impractical, and the app has no way yet to tell the owner why they were logged out. |
| Q2 | Login has the same parallel gap as §2.3, from reading the code; it hasn't been reproduced. It has no row to lock, because unknown emails are counted too, so it would need another mechanism, such as an advisory lock on the email. Fix it here? | **Not here.** Add it to the developer guide's known issues and decide it separately. |
