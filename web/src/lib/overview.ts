/**
 * Turns the API's results into what the overview says and draws (spec 002 §2.5).
 * Nothing is computed here: the verdicts come from lumen.analytics.
 */
import type { components } from "../api/schema";
import { daysBack } from "./dates";

type Change = components["schemas"]["ChangeOut"];
type Trend = components["schemas"]["TrendOut"];
type DailyPoint = components["schemas"]["DailyPoint"];
type RollingPoint = components["schemas"]["RollingPoint"];

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
}

/** One row per day, oldest first. A day without data stays `null`: a gap, not a joined line. */
export function chartRows(end: string, daily: DailyPoint[], rolling: RollingPoint[]): ChartRow[] {
  const dailyByDate = new Map(daily.map(({ date, mean }) => [date, mean]));
  const rollingByDate = new Map(rolling.map(({ date, mean }) => [date, mean]));
  return daysBack(end, CHART_DAYS - 1)
    .reverse()
    .map((date) => ({
      date,
      daily: dailyByDate.get(date) ?? null,
      rolling: rollingByDate.get(date) ?? null,
    }));
}
