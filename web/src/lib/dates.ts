/**
 * Every date and time the app shows goes through here (spec 002 §2.4, Q7).
 *
 * Instants, such as recorded_at, are converted to the browser's timezone.
 * Calendar days, such as local_date, name a day rather than a moment, so they
 * are never converted. `locale` defaults to the browser's.
 */

/** The browser's local date. `toISOString()` would give the UTC date. */
export function today(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${String(now.getFullYear())}-${month}-${day}`;
}

export function formatInstant(iso: string, locale?: string): { day: string; time: string } {
  const instant = new Date(iso);
  return {
    day: new Intl.DateTimeFormat(locale, { day: "numeric", month: "long" }).format(instant),
    time: new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(instant),
  };
}

export function formatDay(day: string, locale?: string): string {
  // new Date("2026-10-31") is midnight UTC, so it must also be formatted in UTC:
  // in the browser's timezone it would be 30 October anywhere west of UTC.
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(day));
}
