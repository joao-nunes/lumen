// @vitest-environment jsdom
// The check-in form against a fake API: `fetch` is the only thing replaced.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatInstant } from "../lib/dates";
import { TodayScreen } from "./TodayScreen";

const TODAY = "2026-11-03";
const CORE = ["mood", "energy", "stress"];

function dimension(key: string, cadence: "core" | "rotating") {
  return {
    key,
    display_name: key,
    cadence,
    polarity: "higher_is_better",
    anchors: [1, 2, 3, 4, 5].map((n) => ({ label: `${key} ${String(n)}`, description: "" })),
  };
}

const DIMENSIONS = [
  ...CORE.map((key) => dimension(key, "core")),
  ...["sleep_quality", "motivation", "concentration", "social_connection"].map((key) =>
    dimension(key, "rotating"),
  ),
];

interface Day {
  local_date: string;
  prompted: string[];
  checkin: { scores: Record<string, number>; tags: string[]; recorded_at: string } | null;
}

let days: Record<string, Day>;
let tags: { name: string; count: number }[];
let puts: { url: string; body: { scores: Record<string, number>; tags: string[] } }[];
let putResponse: () => Response;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function emptyDay(date: string): Day {
  return { local_date: date, prompted: [...CORE, "sleep_quality", "motivation"], checkin: null };
}

const fakeFetch = vi.fn<typeof fetch>((input, init) => {
  const url = input as string;
  if (url === "/api/dimensions") return Promise.resolve(json(DIMENSIONS));
  if (url === "/api/tags") return Promise.resolve(json(tags));
  const date = url.replace("/api/checkins/", "");
  if (init?.method === "PUT") {
    puts.push({ url, body: JSON.parse(init.body as string) as (typeof puts)[number]["body"] });
    return Promise.resolve(putResponse());
  }
  return Promise.resolve(json(days[date] ?? emptyDay(date)));
});

function renderScreen() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<TodayScreen today={TODAY} />} />
          <Route
            path="/overview"
            element={
              <>
                <p>overview screen</p>
                <Link to="/">back</Link>
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function group(name: string): HTMLElement {
  return screen.getByRole("group", { name });
}

function radios(name: string): HTMLInputElement[] {
  return within(group(name)).getAllByRole<HTMLInputElement>("radio");
}

async function choose(name: string, score: number): Promise<void> {
  await userEvent.click(
    within(group(name)).getByRole("radio", { name: `${name} ${String(score)}` }),
  );
}

async function chooseCore(): Promise<void> {
  await choose("mood", 4);
  await choose("energy", 3);
  await choose("stress", 2);
}

function chosen(name: string): string | undefined {
  return radios(name).find((radio) => radio.checked)?.value;
}

function save(): Promise<void> {
  return userEvent.click(screen.getByRole("button", { name: "Save check-in" }));
}

beforeEach(() => {
  days = {};
  tags = [];
  puts = [];
  putResponse = () => json(emptyDay(TODAY));
  fakeFetch.mockClear();
  vi.stubGlobal("fetch", fakeFetch);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a new day", () => {
  it("asks the prompted dimensions, and saving sends exactly the answers", async () => {
    tags = [{ name: "workday", count: 3 }];
    renderScreen();
    await screen.findByRole("group", { name: "mood" });

    expect(
      screen
        .getAllByRole("group")
        .map((g) => within(g).getByText(/./, { selector: "legend" }).textContent),
    ).toEqual([...CORE, "sleep_quality", "motivation", "Tags"]);

    await chooseCore();
    await choose("sleep_quality", 5);
    await userEvent.click(screen.getByRole("checkbox", { name: "workday" }));
    await save();

    await screen.findByText("overview screen");
    expect(puts).toEqual([
      {
        url: `/api/checkins/${TODAY}`,
        body: { scores: { mood: 4, energy: 3, stress: 2, sleep_quality: 5 }, tags: ["workday"] },
      },
    ]);
  });

  it("won't save until every core dimension is answered", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    await choose("mood", 4);
    await choose("energy", 3);
    await choose("sleep_quality", 5);

    await save();

    expect(puts).toEqual([]);
    expect(screen.queryByText("overview screen")).toBeNull();
  });

  it("lets an optional answer be taken back, but not a core one", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    await chooseCore();
    await choose("sleep_quality", 5);

    expect(within(group("mood")).queryByRole("button", { name: "Clear" })).toBeNull();
    await userEvent.click(within(group("sleep_quality")).getByRole("button", { name: "Clear" }));
    await save();

    await screen.findByText("overview screen");
    expect(puts[0]?.body).toEqual({ scores: { mood: 4, energy: 3, stress: 2 }, tags: [] });
  });
});

describe("a day that already has a check-in", () => {
  const RECORDED_AT = "2026-11-03T20:00:00Z";

  beforeEach(() => {
    days[TODAY] = {
      ...emptyDay(TODAY),
      checkin: {
        // social_connection isn't prompted today, but saving replaces the whole day.
        scores: { mood: 2, energy: 3, stress: 4, social_connection: 5 },
        tags: ["exercise", "old_tag"], // old_tag isn't in the tag list, which may be stale
        recorded_at: RECORDED_AT,
      },
    };
  });

  it("is prefilled and says when it was last saved", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });

    expect(["mood", "energy", "stress"].map(chosen)).toEqual(["2", "3", "4"]);
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: "exercise" }).checked).toBe(true);
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: "old_tag" }).checked).toBe(true);
    const { day, time } = formatInstant(RECORDED_AT);
    expect(screen.getByText(`Last saved ${day} at ${time}`)).toBeTruthy();
  });

  it("keeps an answer to a dimension that isn't prompted today when saved again", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    expect(chosen("social_connection")).toBe("5");

    await choose("mood", 3);
    await save();

    await screen.findByText("overview screen");
    expect(puts[0]?.body).toEqual({
      scores: { mood: 3, energy: 3, stress: 4, social_connection: 5 },
      tags: ["exercise", "old_tag"],
    });
  });
});

describe("coming back after saving", () => {
  it("shows what was saved, so that saving again can't undo it", async () => {
    days[TODAY] = {
      ...emptyDay(TODAY),
      checkin: {
        scores: { mood: 1, energy: 1, stress: 1 },
        tags: [],
        recorded_at: "2026-11-03T08:00:00Z",
      },
    };
    putResponse = () =>
      json({
        ...emptyDay(TODAY),
        checkin: {
          scores: { mood: 5, energy: 1, stress: 1 },
          tags: [],
          recorded_at: "2026-11-03T20:00:00Z",
        },
      });
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    await choose("mood", 5);
    await save();
    await screen.findByText("overview screen");

    await userEvent.click(screen.getByRole("link", { name: "back" }));

    await screen.findByRole("group", { name: "mood" });
    expect(chosen("mood")).toBe("5");
  });
});

describe("choosing another day", () => {
  it("offers today and the 7 days before it, across a month boundary", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });

    const options = within(
      screen.getByRole("combobox", { name: "Day" }),
    ).getAllByRole<HTMLOptionElement>("option");
    expect(options.map((option) => option.value)).toEqual([
      "2026-11-03",
      "2026-11-02",
      "2026-11-01",
      "2026-10-31",
      "2026-10-30",
      "2026-10-29",
      "2026-10-28",
      "2026-10-27",
    ]);
  });

  it("shows that day's answers, never the previous day's unsaved ones", async () => {
    days["2026-11-01"] = {
      ...emptyDay("2026-11-01"),
      checkin: {
        scores: { mood: 1, energy: 1, stress: 5 },
        tags: [],
        recorded_at: "2026-11-01T20:00:00Z",
      },
    };
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    await choose("mood", 4);
    await userEvent.click(screen.getByRole("checkbox", { name: "exercise" }));

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Day" }), "2026-11-01");
    await waitFor(() => {
      expect(chosen("mood")).toBe("1");
    });
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: "exercise" }).checked).toBe(
      false,
    );

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Day" }), "2026-11-02");
    await waitFor(() => {
      expect(chosen("mood")).toBeUndefined();
    });

    await chooseCore();
    await save();
    await screen.findByText("overview screen");
    expect(puts[0]?.url).toBe("/api/checkins/2026-11-02");
    expect(puts[0]?.body.tags).toEqual([]);
  });

  it("doesn't carry unsaved answers between days that are already loaded", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    const day = screen.getByRole("combobox", { name: "Day" });
    await userEvent.selectOptions(day, "2026-11-02");
    await screen.findByRole("group", { name: "mood" });
    await userEvent.selectOptions(day, TODAY);
    await screen.findByRole("group", { name: "mood" });

    await choose("mood", 4);
    await userEvent.selectOptions(day, "2026-11-02");

    await screen.findByRole("group", { name: "mood" });
    expect(chosen("mood")).toBeUndefined();
  });
});

describe("tags", () => {
  it("suggests the user's own tags first, most used first, then the starter tags", async () => {
    tags = [
      { name: "yoga", count: 5 },
      { name: "exercise", count: 2 },
    ];
    renderScreen();
    await screen.findByRole("group", { name: "mood" });

    expect(
      within(group("Tags"))
        .getAllByRole("checkbox")
        .map((box) => box.getAttribute("value")),
    ).toEqual([
      "yoga",
      "exercise",
      "alcohol",
      "caffeine_late",
      "social_time",
      "workday",
      "therapy_day",
      "poor_sleep",
      "conflict",
      "time_outdoors",
    ]);
  });

  it("adds a typed tag with Enter, without submitting the form", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    await chooseCore();

    await userEvent.type(screen.getByRole("textbox", { name: "Add a tag" }), "Morning Run{Enter}");

    expect(puts).toEqual([]);
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: "morning_run" }).checked).toBe(
      true,
    );
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Add a tag" }).value).toBe("");

    // Typing an existing tag selects it rather than adding a duplicate.
    await userEvent.type(
      screen.getByRole("textbox", { name: "Add a tag" }),
      "Time-Outdoors{Enter}",
    );
    expect(screen.getAllByRole("checkbox", { name: "time_outdoors" })).toHaveLength(1);
    await save();

    await screen.findByText("overview screen");
    expect(puts[0]?.body.tags).toEqual(["morning_run", "time_outdoors"]);
  });
});

describe("when saving fails", () => {
  it("shows the API's message and keeps the answers", async () => {
    putResponse = () =>
      json({ error: { code: "invalid_tag", message: "Invalid tag: use letters" } }, 422);
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    await chooseCore();

    await save();

    expect((await screen.findByRole("alert")).textContent).toBe("Invalid tag: use letters");
    expect(screen.queryByText("overview screen")).toBeNull();
    expect(chosen("mood")).toBe("4");
  });
});
