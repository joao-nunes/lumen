import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type KeyboardEvent, type SyntheticEvent, useState } from "react";
import { useNavigate } from "react-router";
import {
  type Day,
  type DimensionInfo,
  fetchDay,
  fetchDimensions,
  fetchTags,
  saveDay,
  type TagUsage,
} from "../api/checkins";
import { errorMessage } from "../api/client";
import { daysBack, formatDay, formatInstant, today as localToday } from "../lib/dates";
import styles from "./TodayScreen.module.css";

// Spec 002 Q2. The API's window is wider only to allow for timezones.
const BACKFILL_DAYS = 7;
// PROJECT.MD §4.2. Only stored once used.
const STARTER_TAGS = [
  "exercise",
  "alcohol",
  "caffeine_late",
  "social_time",
  "workday",
  "therapy_day",
  "poor_sleep",
  "conflict",
  "time_outdoors",
];

/** Same rule as the API's, so that a typed tag can find its existing checkbox. */
function normalizeTag(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

export function TodayScreen({ today = localToday() }: { today?: string }) {
  const [date, setDate] = useState(today);
  const dimensions = useQuery({ queryKey: ["dimensions"], queryFn: fetchDimensions });
  const tags = useQuery({ queryKey: ["tags"], queryFn: fetchTags });
  const day = useQuery({ queryKey: ["checkin", date], queryFn: () => fetchDay(date) });

  const isError = dimensions.isError || tags.isError || day.isError;
  return (
    <>
      <h1>Today</h1>
      <label className={styles.day}>
        Day
        <select
          value={date}
          onChange={(event) => {
            setDate(event.target.value);
          }}
        >
          {daysBack(today, BACKFILL_DAYS).map((option) => (
            <option key={option} value={option}>
              {option === today ? `Today, ${formatDay(option)}` : formatDay(option)}
            </option>
          ))}
        </select>
      </label>
      {isError && <p role="alert">Lumen couldn't be reached. Reload the page to try again.</p>}
      {!isError && dimensions.data && tags.data && day.data ? (
        // A new key per day: one day's unsaved answers must never reach another day.
        <CheckinForm key={date} dimensions={dimensions.data} usage={tags.data} day={day.data} />
      ) : (
        !isError && <p>Loading…</p>
      )}
    </>
  );
}

function CheckinForm({
  dimensions,
  usage,
  day,
}: {
  dimensions: DimensionInfo[];
  usage: TagUsage[];
  day: Day;
}) {
  const saved = day.checkin;
  const [scores, setScores] = useState<Record<string, number>>(saved?.scores ?? {});
  const [selectedTags, setSelectedTags] = useState<ReadonlySet<string>>(new Set(saved?.tags));
  const [typedTags, setTypedTags] = useState<string[]>([]);
  const [newTag, setNewTag] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const save = useMutation({
    mutationFn: () => saveDay(day.local_date, { scores, tags: [...selectedTags] }),
    onSuccess: async (result) => {
      // The form reads its answers once: a stale copy would bring back the old ones.
      queryClient.setQueryData(["checkin", day.local_date], result);
      await navigate("/overview");
    },
  });

  // Saving replaces the whole day, so anything already answered stays on the form,
  // even if it isn't prompted today: otherwise saving would silently delete it.
  const shown = dimensions.filter(
    ({ key }) => day.prompted.includes(key) || saved?.scores[key] !== undefined,
  );
  const tagChoices = [
    ...new Set([
      ...usage.map(({ name }) => name),
      ...STARTER_TAGS,
      ...(saved?.tags ?? []),
      ...typedTags,
    ]),
  ];

  function setTag(tag: string, selected: boolean) {
    setSelectedTags((current) => {
      const next = new Set(current);
      if (selected) {
        next.add(tag);
      } else {
        next.delete(tag);
      }
      return next;
    });
  }

  function addTag(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault(); // Enter would otherwise submit the whole check-in
    const tag = normalizeTag(newTag);
    if (tag !== "") {
      setTypedTags((current) => [...current, tag]);
      setTag(tag, true);
      setNewTag("");
    }
  }

  function handleSubmit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      {saved && <LastSaved recordedAt={saved.recorded_at} />}
      {shown.map((dimension) => (
        <fieldset key={dimension.key} className={styles.group}>
          <legend>{dimension.display_name}</legend>
          {dimension.anchors.map((anchor, index) => {
            const score = index + 1;
            return (
              <label key={score} className={styles.option}>
                <input
                  type="radio"
                  name={dimension.key}
                  value={score}
                  required={dimension.cadence === "core"}
                  checked={scores[dimension.key] === score}
                  onChange={() => {
                    setScores((current) => ({ ...current, [dimension.key]: score }));
                  }}
                />
                <span>
                  <strong>{anchor.label}</strong> {anchor.description}
                </span>
              </label>
            );
          })}
          {dimension.cadence === "rotating" && scores[dimension.key] !== undefined && (
            <button
              type="button"
              onClick={() => {
                setScores(({ [dimension.key]: _removed, ...rest }) => rest);
              }}
            >
              Clear
            </button>
          )}
        </fieldset>
      ))}
      <fieldset className={styles.group}>
        <legend>Tags</legend>
        <div className={styles.tags}>
          {tagChoices.map((tag) => (
            <label key={tag} className={styles.tag}>
              <input
                type="checkbox"
                value={tag}
                checked={selectedTags.has(tag)}
                onChange={(event) => {
                  setTag(tag, event.target.checked);
                }}
              />
              {tag}
            </label>
          ))}
        </div>
        <label className={styles.newTag}>
          Add a tag
          <input
            type="text"
            maxLength={100}
            value={newTag}
            onChange={(event) => {
              setNewTag(event.target.value);
            }}
            onKeyDown={addTag}
          />
        </label>
      </fieldset>
      {save.isError && <p role="alert">{errorMessage(save.error)}</p>}
      <button type="submit" disabled={save.isPending}>
        Save check-in
      </button>
    </form>
  );
}

function LastSaved({ recordedAt }: { recordedAt: string }) {
  const { day, time } = formatInstant(recordedAt);
  return <p className={styles.saved}>{`Last saved ${day} at ${time}`}</p>;
}
