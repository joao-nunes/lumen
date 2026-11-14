import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDay, formatShortDay } from "../lib/dates";
import type { ChartRow } from "../lib/overview";
import styles from "./OverviewScreen.module.css";

const SCORES = [1, 2, 3, 4, 5];
const AXIS_TEXT = { fill: "var(--muted)", fontSize: 12 };

/** Daily values as points and the 7-day average as a line, on the fixed 1–5 scale. */
export function DimensionChart({
  name,
  rows,
  anchors,
}: {
  name: string;
  rows: ChartRow[];
  anchors: string[];
}) {
  const monthlyTicks = rows.filter((_, index) => (rows.length - 1 - index) % 28 === 0);
  return (
    <div role="group" aria-label={`${name} chart. The values are also under Numbers.`}>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis
            dataKey="date"
            ticks={monthlyTicks.map(({ date }) => date)}
            interval={0}
            tickFormatter={(day: string) => formatShortDay(day)}
            tick={AXIS_TEXT}
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
          />
          <YAxis
            domain={[1, 5]}
            ticks={SCORES}
            interval={0}
            width={104}
            // Drawn here because Recharts' own tick wraps long anchors out of the chart.
            tick={({ x, y, index }) => (
              <text x={x} y={y} dy="0.32em" textAnchor="end" {...AXIS_TEXT}>
                {anchors[index]}
              </text>
            )}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            isAnimationActive={false}
            cursor={{ stroke: "var(--border)" }}
            content={({ active, label }) =>
              active ? <ChartTooltip row={rows.find(({ date }) => date === label)} /> : null
            }
          />
          <Line
            dataKey="daily"
            name="Daily"
            stroke="none"
            isAnimationActive={false}
            dot={{ r: 2.5, fill: "var(--chart-line)", fillOpacity: 0.55, stroke: "none" }}
            activeDot={{ r: 4, fill: "var(--chart-line)", stroke: "var(--background)" }}
          />
          <Line
            dataKey="volunteered"
            name="Mentioned, not asked"
            stroke="none"
            isAnimationActive={false}
            // Hollow, so it's told apart by shape, not colour. Never joined to the average (spec 009).
            dot={{ r: 3, fill: "var(--background)", stroke: "var(--chart-line)", strokeWidth: 1.5 }}
            activeDot={{ r: 4, fill: "var(--background)", stroke: "var(--chart-line)" }}
          />
          <Line
            dataKey="rolling"
            name="7-day average"
            stroke="var(--chart-line)"
            strokeWidth={2}
            strokeLinecap="round"
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 4, fill: "var(--chart-line)", stroke: "var(--background)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartTooltip({ row }: { row: ChartRow | undefined }) {
  if (row === undefined) {
    return null;
  }
  return (
    <div className={styles.tooltip}>
      <div>{formatDay(row.date)}</div>
      <div>
        <strong>{row.daily ?? "–"}</strong> Daily
      </div>
      <div>
        <strong>{row.rolling?.toFixed(2) ?? "–"}</strong> 7-day average
      </div>
      {row.volunteered !== null && (
        <div>
          <strong>{row.volunteered}</strong> Mentioned, not asked
        </div>
      )}
    </div>
  );
}
