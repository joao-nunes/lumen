/**
 * Turns the API's results into what the overview says and draws (spec 002 §2.5).
 * Nothing is computed here: the verdicts come from lumen.analytics.
 */
import type { components } from "../api/schema";
import { daysBack, weekday } from "./dates";

type Change = components["schemas"]["ChangeOut"];
type Trend = components["schemas"]["TrendOut"];
type DailyPoint = components["schemas"]["DailyPoint"];
type RollingPoint = components["schemas"]["RollingPoint"];
type VolunteeredPoint = components["schemas"]["VolunteeredPoint"];
type Polarity = components["schemas"]["Polarity"];

const CHART_DAYS = 84;

export function days(count: number): string {
  return count === 1 ? "1 day" : `${String(count)} days`;
}

const notEnoughData = (count: number) => `Not enough data yet (${days(count)})`;

/** Says which way the numbers moved. The outlook's colour says whether that's good. */
export function latelyLine(change: Change): string {
  const { current, previous, direction } = change;
  if (direction === "insufficient_data") {
    return notEnoughData(current.n + previous.n);
  }
  const basis = `(based on ${String(current.n)} and ${days(previous.n)})`;
  switch (direction) {
    case "increasing":
      return `Higher than the previous 4 weeks ${basis}`;
    case "decreasing":
      return `Lower than the previous 4 weeks ${basis}`;
    case "flat":
    case "unclear":
      return `No clear change ${basis}`;
  }
}

export function directionLine(trend: Trend): string {
  const basis = `(based on ${days(trend.n)})`;
  if (trend.direction === "insufficient_data") {
    return notEnoughData(trend.n);
  }
  switch (trend.outlook) {
    case "improving":
      return `Gradually improving over 12 weeks ${basis}`;
    case "worsening":
      return `Gradually worsening over 12 weeks ${basis}`;
    case "stable":
      return `Stable ${basis}`;
    case "unknown":
      return `Unclear ${basis}`;
  }
}

export interface ChartRow {
  date: string;
  daily: number | null;
  rolling: number | null;
  // A score the day didn't ask for: shown, never in the average (spec 009).
  volunteered: number | null;
}

/** One row per day, oldest first. A day without data stays `null`: a gap, not a joined line. */
export function chartRows(
  end: string,
  daily: DailyPoint[],
  rolling: RollingPoint[],
  volunteered: VolunteeredPoint[] = [],
): ChartRow[] {
  const dailyByDate = new Map(daily.map(({ date, mean }) => [date, mean]));
  const rollingByDate = new Map(rolling.map(({ date, mean }) => [date, mean]));
  const volunteeredByDate = new Map(volunteered.map(({ date, value }) => [date, value]));
  return daysBack(end, CHART_DAYS - 1)
    .reverse()
    .map((date) => ({
      date,
      daily: dailyByDate.get(date) ?? null,
      rolling: rollingByDate.get(date) ?? null,
      volunteered: volunteeredByDate.get(date) ?? null,
    }));
}

/** The heatmap's colour step, 1 the bad end to 5 the good end, whichever way the scale runs. */
export function heatStep(value: number, polarity: Polarity): number {
  const step = Math.round(value);
  return polarity === "higher_is_worse" ? 6 - step : step;
}

/** The chart's 84 days as week columns, Monday first; `null` where a column has no day of them. */
export function calendarWeeks(end: string): (string | null)[][] {
  const window = daysBack(end, CHART_DAYS - 1).reverse();
  const first = window[0] ?? end;
  const cells: (string | null)[] = [...Array<null>(weekday(first)).fill(null), ...window];
  while (cells.length % 7 !== 0) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, week) => cells.slice(week * 7, week * 7 + 7));
}

export function mentionedLine(count: number): string {
  return `Also mentioned on ${days(count)} without being asked`;
}
