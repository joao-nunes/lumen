import type { DimensionInfo } from "../api/checkins";
import type { DimensionOverview } from "../api/overview";
import { formatDay } from "../lib/dates";
import { calendarWeeks, heatStep } from "../lib/overview";
import styles from "./OverviewScreen.module.css";

const STEPS = [1, 2, 3, 4, 5];

/**
 * Spec 009: one small calendar per dimension, a cell per day of the 84, coloured from the bad end
 * to the good end. Volunteered scores enter it, because it shows each day's score rather than
 * computing with them. Colour is never the only channel: every cell is named, and Numbers lists
 * every value. Cells are coloured through `data-step` and CSS, not inline styles (the CSP).
 */
export function Lately({
  end,
  results,
  info,
}: {
  end: string;
  results: DimensionOverview[];
  info: Map<string, DimensionInfo>;
}) {
  const weeks = calendarWeeks(end);
  return (
    <section className={styles.lately} aria-labelledby="lately-heading">
      <h2 id="lately-heading">Lately</h2>
      <ul className={styles.heatLegend}>
        <li>Harder</li>
        {STEPS.map((step) => (
          <li key={step} className={styles.heatCell} data-step={step} aria-hidden="true" />
        ))}
        <li>Better</li>
        <li>
          <span className={styles.heatCell} aria-hidden="true" /> No score
        </li>
        <li>
          <span
            className={styles.heatCell}
            data-step={3}
            data-volunteered="true"
            aria-hidden="true"
          />{" "}
          Mentioned, not asked
        </li>
      </ul>
      <div className={styles.calendars}>
        {results.map((result) => {
          const dimension = info.get(result.dimension);
          return (
            dimension && (
              <Calendar
                key={result.dimension}
                weeks={weeks}
                dimension={dimension}
                result={result}
              />
            )
          );
        })}
      </div>
    </section>
  );
}

function Calendar({
  weeks,
  dimension,
  result,
}: {
  weeks: (string | null)[][];
  dimension: DimensionInfo;
  result: DimensionOverview;
}) {
  const asked = new Map(result.daily.map(({ date, mean }) => [date, mean]));
  const volunteered = new Map(result.volunteered.map(({ date, value }) => [date, value]));
  return (
    <figure className={styles.calendar}>
      <figcaption>{dimension.display_name}</figcaption>
      <ul aria-label={dimension.display_name} className={styles.calendarGrid}>
        {weeks.flat().map((day, index) => {
          if (day === null) {
            // Outside the 84 days: keeps the week columns aligned, and isn't drawn.
            return (
              <li key={`outside-${String(index)}`} className={styles.outside} aria-hidden="true" />
            );
          }
          const mentioned = volunteered.get(day);
          const value = asked.get(day) ?? mentioned;
          if (value === undefined) {
            const name = `${formatDay(day)}: no score`;
            return <li key={day} className={styles.heatCell} aria-label={name} title={name} />;
          }
          const score = Math.round(value);
          const anchor = dimension.anchors[score - 1]?.label ?? "";
          const name = `${formatDay(day)}: ${String(score)}, ${anchor}${
            mentioned === undefined ? "" : ", mentioned, not asked"
          }`;
          return (
            <li
              key={day}
              className={styles.heatCell}
              data-step={heatStep(value, dimension.polarity)}
              data-volunteered={mentioned === undefined ? undefined : "true"}
              aria-label={name}
              title={name}
            />
          );
        })}
      </ul>
    </figure>
  );
}
