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
  suggestScores,
  type TagUsage,
} from "../api/checkins";
import { fetchContext } from "../api/context";
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

const MAX_NOTE_LENGTH = 2000;

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
  // The note is Tier 0: it lives only in this state, and only the suggestion request sends it.
  const [note, setNote] = useState("");
  const [suggestedScores, setSuggestedScores] = useState<Record<string, number>>({});
  const [suggestedTags, setSuggestedTags] = useState<ReadonlySet<string>>(new Set());
  const [usedSuggestions, setUsedSuggestions] = useState(false);
  // Dimensions the day didn't ask about, added by hand (spec 008): the server labels them volunteered.
  const [added, setAdded] = useState<string[]>([]);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // Only to say it's used (spec 010): the server reads the context itself when suggesting.
  const personalContext = useQuery({ queryKey: ["context"], queryFn: fetchContext });

  const suggest = useMutation({
    mutationFn: () => suggestScores(day.local_date, note.trim()),
    gcTime: 0, // Don't keep the request or reply in the mutation cache.
    onSuccess: ({ scores: suggested, tags: suggestedNames }) => {
      // Applied to the current answers, so a choice made while waiting is kept.
      setScores((current) => ({ ...suggested, ...current }));
      setSuggestedScores(suggested);
      setTypedTags((current) => [...current, ...suggestedNames]);
      setSelectedTags((current) => new Set([...current, ...suggestedNames]));
      setSuggestedTags(new Set(suggestedNames));
      if (Object.keys(suggested).length > 0 || suggestedNames.length > 0) {
        setUsedSuggestions(true);
      }
    },
  });

  const save = useMutation({
    mutationFn: () =>
      saveDay(day.local_date, {
        scores,
        tags: [...selectedTags],
        mode: usedSuggestions ? "free_text" : "structured",
      }),
    onSuccess: async (result) => {
      // The form reads its answers once: a stale copy would bring back the old ones.
      queryClient.setQueryData(["checkin", day.local_date], result);
      // Removed, not just marked stale: the next screen must not show the overview from before.
      queryClient.removeQueries({ queryKey: ["overview"] });
      await navigate("/overview");
    },
  });

  // Every score that will be saved has a row, however it got there (saved, suggested, changed),
  // so nothing is saved unseen. Saving replaces the whole day, so a saved answer the day didn't ask
  // for shows until it's cleared; clearing it removes the row and, on save, the score.
  const shown = dimensions.filter(
    ({ key }) => day.prompted.includes(key) || added.includes(key) || scores[key] !== undefined,
  );
  const addable = dimensions.filter((dimension) => !shown.includes(dimension));
  const tagChoices = [
    ...new Set([
      ...usage.map(({ name }) => name),
      ...STARTER_TAGS,
      ...(saved?.tags ?? []),
      ...typedTags,
    ]),
  ];

  function setTag(tag: string, selected: boolean) {
    setSuggestedTags((current) => {
      const next = new Set(current);
      next.delete(tag);
      return next;
    });
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
      <section className={styles.group}>
        <label className={styles.note}>
          Write about your day
          <textarea
            rows={4}
            maxLength={MAX_NOTE_LENGTH}
            autoComplete="off"
            spellCheck={false}
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </label>
        <button
          type="button"
          disabled={note.trim() === "" || suggest.isPending}
          onClick={() => {
            suggest.mutate();
          }}
        >
          Suggest scores
        </button>
        {personalContext.data?.text && (
          <p className={styles.suggested}>Using your personal context</p>
        )}
        {suggest.isPending && <p role="status">Suggesting…</p>}
        {suggest.isSuccess &&
          Object.keys(suggest.data.scores).length === 0 &&
          suggest.data.tags.length === 0 && (
            <p role="status">Nothing to suggest from that. You can fill in the form yourself.</p>
          )}
        {suggest.isError && (
          <p role="alert">
            Suggestions aren't available right now. You can fill in the form yourself.
          </p>
        )}
        {/* Spec 006 §2.7: always here, because nothing yet responds to what's written. */}
        <div className={styles.safety}>
          <p>
            Lumen only turns this text into suggested scores. No one reads it, and it can't respond
            to what you write.
          </p>
          <p>
            If you're struggling: SNS 24, 808 24 24 24, option 4 (psychological support, 24 hours).
          </p>
          <p>In an emergency, call 112.</p>
        </div>
      </section>
      {shown.map((dimension) => (
        <fieldset key={dimension.key} className={styles.group}>
          <legend>{dimension.display_name}</legend>
          {!day.prompted.includes(dimension.key) && (
            <p className={styles.notAsked}>Not asked today</p>
          )}
          {suggestedScores[dimension.key] !== undefined &&
            suggestedScores[dimension.key] === scores[dimension.key] && (
              <p className={styles.suggested}>Suggested, please check</p>
            )}
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
                    setSuggestedScores(({ [dimension.key]: _changed, ...rest }) => rest);
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
                setSuggestedScores(({ [dimension.key]: _changed, ...rest }) => rest);
                setAdded((current) => current.filter((key) => key !== dimension.key));
              }}
            >
              Clear
            </button>
          )}
        </fieldset>
      ))}
      {addable.length > 0 && (
        <label className={styles.addDimension}>
          Add another dimension
          <select
            value=""
            onChange={(event) => {
              const key = event.target.value;
              if (key) setAdded((current) => [...current, key]);
            }}
          >
            <option value="">Choose one</option>
            {addable.map((dimension) => (
              <option key={dimension.key} value={dimension.key}>
                {dimension.display_name}
              </option>
            ))}
          </select>
        </label>
      )}
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
              {suggestedTags.has(tag) && <em className={styles.suggested}>(suggested)</em>}
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
