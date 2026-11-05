// The wording is the product here (spec 002 §2.5): a swapped branch tells someone
// the opposite of what their data says, and nothing would crash.
import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { chartRows, directionLine, latelyLine } from "./overview";

type Change = components["schemas"]["ChangeOut"];
type Trend = components["schemas"]["TrendOut"];

function change(
  direction: Change["direction"],
  currentDays: number,
  previousDays: number,
  outlook: Change["outlook"] = "unknown",
): Change {
  const period = (n: number) => ({ start: "2026-10-01", end: "2026-10-28", mean: null, n });
  return {
    current: period(currentDays),
    previous: period(previousDays),
    delta: null,
    ci_low: null,
    ci_high: null,
    direction,
    outlook,
  };
}

function trend(direction: Trend["direction"], outlook: Trend["outlook"], n: number): Trend {
  return {
    start: "2026-08-09",
    end: "2026-10-31",
    slope_per_week: null,
    ci_low: null,
    ci_high: null,
    direction,
    outlook,
    n,
    n_effective: null,
  };
}

describe("latelyLine", () => {
  it.each([
    ["increasing", "Higher than the previous 4 weeks (based on 22 and 25 days)"],
    ["decreasing", "Lower than the previous 4 weeks (based on 22 and 25 days)"],
    ["flat", "No clear change (based on 22 and 25 days)"],
    ["unclear", "No clear change (based on 22 and 25 days)"],
  ] as const)("%s", (direction, expected) => {
    expect(latelyLine(change(direction, 22, 25))).toBe(expected);
  });

  it("describes the raw direction, so higher stress reads as higher, not as worse", () => {
    expect(latelyLine(change("increasing", 22, 25, "worsening"))).toBe(
      "Higher than the previous 4 weeks (based on 22 and 25 days)",
    );
  });

  it("counts the days of both periods when there isn't enough data", () => {
    expect(latelyLine(change("insufficient_data", 4, 2))).toBe("Not enough data yet (6 days)");
    expect(latelyLine(change("insufficient_data", 1, 0))).toBe("Not enough data yet (1 day)");
  });
});

describe("directionLine", () => {
  it.each([
    ["decreasing", "improving", "Gradually improving over 12 weeks (based on 70 days)"],
    ["increasing", "worsening", "Gradually worsening over 12 weeks (based on 70 days)"],
    ["flat", "stable", "Stable (based on 70 days)"],
    ["unclear", "unknown", "Unclear (based on 70 days)"],
  ] as const)("%s, %s", (direction, outlook, expected) => {
    expect(directionLine(trend(direction, outlook, 70))).toBe(expected);
  });

  it("says when there isn't enough data", () => {
    expect(directionLine(trend("insufficient_data", "unknown", 1))).toBe(
      "Not enough data yet (1 day)",
    );
  });
});

describe("chartRows", () => {
  const rows = chartRows(
    "2026-10-31",
    [
      { date: "2026-10-31", mean: 4 },
      { date: "2026-08-08", mean: 2 },
    ],
    [{ date: "2026-10-30", mean: 3.5, n: 3 }],
  );

  it("has one row per day of the 84 days ending on the given day, oldest first", () => {
    expect(rows).toHaveLength(84);
    expect(rows[0]).toEqual({ date: "2026-08-09", daily: null, rolling: null });
  });

  it("keeps a day without data as a gap, so the line is never joined across it", () => {
    expect(rows.slice(-2)).toEqual([
      { date: "2026-10-30", daily: null, rolling: 3.5 },
      { date: "2026-10-31", daily: 4, rolling: null },
    ]);
  });
});
