import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useId } from "react";
import { type DimensionInfo, fetchDimensions } from "../api/checkins";
import { type DimensionOverview, fetchOverview } from "../api/overview";
import { formatDay, today as localToday } from "../lib/dates";
import { chartRows, days, directionLine, latelyLine } from "../lib/overview";
import styles from "./OverviewScreen.module.css";

// Recharts is most of the app's code, and only this screen needs it.
const DimensionChart = lazy(() =>
  import("./DimensionChart").then((chart) => ({ default: chart.DimensionChart })),
);

export function OverviewScreen({ today = localToday() }: { today?: string }) {
  const overview = useQuery({ queryKey: ["overview", today], queryFn: () => fetchOverview(today) });
  const dimensions = useQuery({ queryKey: ["dimensions"], queryFn: fetchDimensions });

  if (overview.isError || dimensions.isError) {
    return (
      <>
        <h1>Overview</h1>
        <p role="alert">Lumen couldn't be reached. Reload the page to try again.</p>
      </>
    );
  }
  if (!overview.data || !dimensions.data) {
    return (
      <>
        <h1>Overview</h1>
        <p>Loading…</p>
      </>
    );
  }

  const info = new Map(dimensions.data.map((dimension) => [dimension.key, dimension]));
  return (
    <>
      <h1>Overview</h1>
      <Legend />
      <div className={styles.cards}>
        {overview.data.dimensions.map((result) => {
          const dimension = info.get(result.dimension);
          return (
            dimension && (
              <DimensionCard
                key={result.dimension}
                end={overview.data.end}
                dimension={dimension}
                result={result}
              />
            )
          );
        })}
      </div>
    </>
  );
}

function Legend() {
  return (
    <ul className={styles.legend}>
      <li>
        <span className={styles.keyPoint} /> Daily
      </li>
      <li>
        <span className={styles.keyLine} /> 7-day average
      </li>
      <li>
        <span className={`${styles.dot ?? ""} ${styles.improving ?? ""}`} /> Getting better
      </li>
      <li>
        <span className={`${styles.dot ?? ""} ${styles.worsening ?? ""}`} /> Getting harder
      </li>
      <li>
        <span className={`${styles.dot ?? ""} ${styles.unknown ?? ""}`} /> No clear change
      </li>
    </ul>
  );
}

function DimensionCard({
  end,
  dimension,
  result,
}: {
  end: string;
  dimension: DimensionInfo;
  result: DimensionOverview;
}) {
  const headingId = useId();
  const rows = chartRows(end, result.daily, result.rolling_7);
  return (
    <section className={styles.card} aria-labelledby={headingId}>
      <h2 id={headingId}>{dimension.display_name}</h2>
      {dimension.polarity === "higher_is_worse" && (
        <p className={styles.note}>{`Higher = more ${dimension.display_name.toLowerCase()}`}</p>
      )}
      <dl className={styles.lines}>
        <dt>Lately</dt>
        <dd>
          <span className={`${styles.dot ?? ""} ${styles[result.change.outlook] ?? ""}`} />
          {latelyLine(result.change)}
        </dd>
        <dt>Direction</dt>
        <dd>
          <span className={`${styles.dot ?? ""} ${styles[result.trend.outlook] ?? ""}`} />
          {directionLine(result.trend)}
        </dd>
      </dl>
      {result.daily.length > 0 && (
        <Suspense fallback={<div className={styles.chartSpace} />}>
          <DimensionChart
            name={dimension.display_name}
            rows={rows}
            anchors={dimension.anchors.map(({ label }) => label)}
          />
        </Suspense>
      )}
      <details className={styles.numbers}>
        <summary>Numbers</summary>
        <Numbers result={result} />
        {result.daily.length > 0 && (
          <div className={styles.values}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  <th scope="col">Daily</th>
                  <th scope="col">7-day average</th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter(({ daily, rolling }) => daily !== null || rolling !== null)
                  .reverse()
                  .map(({ date, daily, rolling }) => (
                    <tr key={date}>
                      <th scope="row">{formatDay(date)}</th>
                      <td>{daily ?? "–"}</td>
                      <td>{rolling?.toFixed(2) ?? "–"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}

function signed(value: number): string {
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(2)}`;
}

function estimate(value: number | null, low: number | null, high: number | null): string {
  if (value === null || low === null || high === null) {
    return "not enough data";
  }
  return `${signed(value)} (95% interval ${signed(low)} to ${signed(high)})`;
}

function average(mean: number | null, count: number): string {
  return mean === null
    ? `not enough data (${days(count)})`
    : `average ${mean.toFixed(2)} (${days(count)})`;
}

function Numbers({ result: { change, trend } }: { result: DimensionOverview }) {
  return (
    <ul className={styles.estimates}>
      <li>{`Last 4 weeks: ${average(change.current.mean, change.current.n)}`}</li>
      <li>{`Previous 4 weeks: ${average(change.previous.mean, change.previous.n)}`}</li>
      <li>{`Difference: ${estimate(change.delta, change.ci_low, change.ci_high)}`}</li>
      <li>{`Per week: ${estimate(trend.slope_per_week, trend.ci_low, trend.ci_high)}`}</li>
    </ul>
  );
}
