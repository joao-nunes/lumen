// AC-12 (spec 002): each case is run in a real process timezone, as a browser would be.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { formatDay, formatInstant, today } from "./dates";

const originalTz = process.env.TZ;

function inTimeZone(tz: string): void {
  process.env.TZ = tz;
}

beforeEach(() => {
  inTimeZone("UTC");
});

afterEach(() => {
  if (originalTz === undefined) {
    delete process.env.TZ;
  } else {
    process.env.TZ = originalTz;
  }
});

describe("instants are shown in the browser's timezone", () => {
  it("applies summer time", () => {
    inTimeZone("Europe/Lisbon");
    expect(formatInstant("2026-07-15T20:00:00Z", "en-GB")).toEqual({
      day: "15 July",
      time: "21:00",
    });
  });

  it("applies winter time", () => {
    inTimeZone("Europe/Lisbon");
    expect(formatInstant("2026-01-15T20:00:00Z", "en-GB")).toEqual({
      day: "15 January",
      time: "20:00",
    });
  });

  it("moves to the local day when that differs from the UTC day", () => {
    inTimeZone("Europe/Lisbon");
    expect(formatInstant("2026-07-14T23:30:00Z", "en-GB")).toEqual({
      day: "15 July",
      time: "00:30",
    });
  });
});

describe("today is the browser's local date", () => {
  it("is ahead of the UTC date east of UTC", () => {
    inTimeZone("Europe/Lisbon");
    expect(today(new Date("2026-07-14T23:30:00Z"))).toBe("2026-07-15");
  });

  it("is behind the UTC date west of UTC", () => {
    inTimeZone("America/New_York");
    expect(today(new Date("2026-07-15T02:00:00Z"))).toBe("2026-07-14");
  });
});

describe("calendar days are never converted", () => {
  it("stays on the same day west of UTC", () => {
    inTimeZone("America/New_York");
    expect(formatDay("2026-10-31", "en-GB")).toBe("31 October");
  });
});
