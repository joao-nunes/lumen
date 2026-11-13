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
let puts: {
  url: string;
  body: { scores: Record<string, number>; tags: string[]; mode?: string };
}[];
let putResponse: () => Response;
let suggestions: { url: string; body: string }[];
let suggestionResponse: () => Promise<Response>;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function emptyDay(date: string): Day {
  return { local_date: date, prompted: [...CORE, "sleep_quality", "motivation"], checkin: null };
}

const fakeFetch = vi.fn<typeof fetch>((input, init) => {
  const url = input as string;
  if (url.endsWith("/suggestion")) {
    suggestions.push({ url, body: init?.body as string });
    return suggestionResponse();
  }
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
        body: {
          scores: { mood: 4, energy: 3, stress: 2, sleep_quality: 5 },
          tags: ["workday"],
          mode: "structured",
        },
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
    expect(puts[0]?.body).toEqual({
      scores: { mood: 4, energy: 3, stress: 2 },
      tags: [],
      mode: "structured",
    });
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
      mode: "structured",
    });
  });
});

describe("a dimension the day didn't ask about (spec 008)", () => {
  function addable(): string[] {
    const control = screen.queryByRole<HTMLSelectElement>("combobox", {
      name: "Add another dimension",
    });
    return control ? [...control.options].slice(1).map((option) => option.value) : [];
  }

  async function add(key: string): Promise<void> {
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Add another dimension" }),
      key,
    );
  }

  function notAsked(name: string): boolean {
    return within(group(name)).queryByText("Not asked today") !== null;
  }

  it("AC-7: marks a saved answer the day didn't ask for", async () => {
    days[TODAY] = {
      ...emptyDay(TODAY),
      checkin: {
        scores: { mood: 2, energy: 3, stress: 4, social_connection: 5 },
        tags: [],
        recorded_at: "2026-11-03T20:00:00Z",
      },
    };
    renderScreen();
    await screen.findByRole("group", { name: "mood" });

    expect([...CORE, "sleep_quality", "social_connection"].map(notAsked)).toEqual([
      false,
      false,
      false,
      false,
      true,
    ]);
  });

  it("AC-8: adds one, saves it, and offers only the rest", async () => {
    renderScreen();
    await screen.findByRole("group", { name: "mood" });
    expect(addable()).toEqual(["concentration", "social_connection"]);

    await add("concentration");
    expect(notAsked("concentration")).toBe(true);
    expect(chosen("concentration")).toBeUndefined();
    expect(addable()).toEqual(["social_connection"]);

    await add("social_connection"); // added but left blank: not saved
    expect(screen.queryByRole("combobox", { name: "Add another dimension" })).toBeNull();
    await chooseCore();
    await choose("concentration", 2);
    await save();

    await screen.findByText("overview screen");
    expect(puts[0]?.body).toEqual({
      scores: { mood: 4, energy: 3, stress: 2, concentration: 2 },
      tags: [],
      mode: "structured",
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

describe("free text", () => {
  const NOTE = "marker_note slept badly, stressful meeting";
  const SAFETY = [
    "Lumen only turns this text into suggested scores. No one reads it, and it can't respond to what you write.",
    "If you're struggling: SNS 24, 808 24 24 24, option 4 (psychological support, 24 hours).",
    "In an emergency, call 112.",
  ];

  function reply(scores: Record<string, number>, suggestedTags: string[] = []) {
    return () => Promise.resolve(json({ scores, tags: suggestedTags }));
  }

  function box(): HTMLTextAreaElement {
    return screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Write about your day" });
  }

  function suggestButton(): HTMLButtonElement {
    return screen.getByRole<HTMLButtonElement>("button", { name: "Suggest scores" });
  }

  async function write(note = NOTE): Promise<void> {
    await userEvent.type(
      await screen.findByRole("textbox", { name: "Write about your day" }),
      note,
    );
  }

  async function writeAndSuggest(note = NOTE): Promise<void> {
    await write(note);
    await userEvent.click(suggestButton());
  }

  function expectSafetyTextVisible(): void {
    for (const line of SAFETY) {
      expect(screen.getByText(line).closest("[hidden]")).toBeNull();
    }
  }

  beforeEach(() => {
    suggestions = [];
    suggestionResponse = reply({});
  });

  it("AC-14: shows the safety text before anything is typed, and while loading or failed", async () => {
    let finish: (response: Response) => void = () => undefined;
    suggestionResponse = () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    renderScreen();
    await screen.findByRole("textbox", { name: "Write about your day" });
    expectSafetyTextVisible();

    await writeAndSuggest();
    expectSafetyTextVisible();
    expect(suggestButton().disabled || screen.queryByRole("status") !== null).toBe(true);

    finish(json({ error: { code: "suggestions_unavailable", message: "x" } }, 503));
    await screen.findByRole("alert");
    expectSafetyTextVisible();
  });

  it("AC-11: fills blank fields and tags, marks them as suggested, and saves nothing", async () => {
    suggestionResponse = reply({ mood: 2, stress: 4 }, ["poor_sleep"]);
    renderScreen();

    await writeAndSuggest();

    await waitFor(() => {
      expect(chosen("mood")).toBe("2");
    });
    expect(chosen("stress")).toBe("4");
    expect(chosen("energy")).toBeUndefined();
    expect(within(group("mood")).getByText("Suggested, please check")).toBeTruthy();
    expect(within(group("energy")).queryByText("Suggested, please check")).toBeNull();
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: /poor_sleep/ }).checked).toBe(
      true,
    );
    expect(screen.getByText("(suggested)")).toBeTruthy();
    expect(puts).toEqual([]);
    expect(suggestions[0]?.url).toBe(`/api/checkins/${TODAY}/suggestion`);
    expect(JSON.parse(suggestions[0]?.body ?? "")).toEqual({ text: NOTE });
  });

  it("spec 008 AC-11: a suggested score the day didn't ask for gets its own row", async () => {
    suggestionResponse = reply({ mood: 4, energy: 3, stress: 2, concentration: 1 });
    renderScreen();

    await writeAndSuggest();

    const concentration = await screen.findByRole("group", { name: "concentration" });
    expect(chosen("concentration")).toBe("1");
    expect(within(concentration).getByText("Not asked today")).toBeTruthy();
    expect(within(concentration).getByText("Suggested, please check")).toBeTruthy();
    expect(within(group("mood")).queryByText("Not asked today")).toBeNull();
    await save();

    await screen.findByText("overview screen");
    expect(puts[0]?.body).toEqual({
      scores: { mood: 4, energy: 3, stress: 2, concentration: 1 },
      tags: [],
      mode: "free_text",
    });
  });

  it("keeps a suggested row the day didn't ask for when its score is changed", async () => {
    suggestionResponse = reply({ mood: 4, energy: 3, stress: 2, sleep_quality: 4 });
    days[TODAY] = { ...emptyDay(TODAY), prompted: CORE };
    renderScreen();
    await writeAndSuggest();
    await screen.findByRole("group", { name: "sleep_quality" });

    await choose("sleep_quality", 2); // the person disagrees with the model

    const sleep = screen.getByRole("group", { name: "sleep_quality" });
    expect(chosen("sleep_quality")).toBe("2");
    expect(within(sleep).getByText("Not asked today")).toBeTruthy();
    expect(within(sleep).queryByText("Suggested, please check")).toBeNull();
    await save();

    await screen.findByText("overview screen");
    expect(puts[0]?.body.scores).toEqual({ mood: 4, energy: 3, stress: 2, sleep_quality: 2 });
  });

  it("AC-11: never overwrites a choice, even one made while waiting for the model", async () => {
    let finish: (response: Response) => void = () => undefined;
    suggestionResponse = () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    renderScreen();
    await write();
    await choose("mood", 5);
    await userEvent.click(suggestButton());
    await choose("stress", 1); // while the model is thinking

    finish(json({ scores: { mood: 1, stress: 5, energy: 3 }, tags: [] }));

    await waitFor(() => {
      expect(chosen("energy")).toBe("3");
    });
    expect(chosen("mood")).toBe("5");
    expect(chosen("stress")).toBe("1");
    expect(within(group("mood")).queryByText("Suggested, please check")).toBeNull();
    expect(within(group("energy")).getByText("Suggested, please check")).toBeTruthy();
  });

  it("AC-11: doesn't overwrite a score already saved for the day", async () => {
    days[TODAY] = {
      ...emptyDay(TODAY),
      checkin: {
        scores: { mood: 5, energy: 5, stress: 1 },
        tags: [],
        recorded_at: "2026-11-03T08:00:00Z",
      },
    };
    suggestionResponse = reply({ mood: 1 });
    renderScreen();

    await writeAndSuggest();

    await waitFor(() => {
      expect(suggestions).toHaveLength(1);
    });
    expect(chosen("mood")).toBe("5");
  });

  it("AC-11: changing a suggestion removes its mark", async () => {
    suggestionResponse = reply({ mood: 2 }, ["poor_sleep"]);
    renderScreen();
    await writeAndSuggest();
    await within(group("mood")).findByText("Suggested, please check");

    await choose("mood", 3);
    await choose("mood", 2); // back to the same value: this time it's the person's own choice
    await choose("mood", 3);
    expect(within(group("mood")).queryByText("Suggested, please check")).toBeNull();
    await choose("mood", 2);
    expect(within(group("mood")).queryByText("Suggested, please check")).toBeNull();
    await choose("mood", 3);
    await userEvent.click(screen.getByRole("checkbox", { name: /poor_sleep/ }));

    expect(chosen("mood")).toBe("3");
    expect(within(group("mood")).queryByText("Suggested, please check")).toBeNull();
    expect(screen.queryByText("(suggested)")).toBeNull();
    expect(screen.getByRole<HTMLInputElement>("checkbox", { name: /poor_sleep/ }).checked).toBe(
      false,
    );
  });

  it("AC-11: offers a suggested tag that isn't on the form yet", async () => {
    tags = [];
    suggestionResponse = reply({}, ["a_tag_of_mine"]);
    renderScreen();

    await writeAndSuggest();

    const tag = await screen.findByRole<HTMLInputElement>("checkbox", { name: /a_tag_of_mine/ });
    expect(tag.checked).toBe(true);
  });

  it("says so when the note gives nothing to suggest", async () => {
    renderScreen();
    await writeAndSuggest();
    expect(
      await screen.findByText("Nothing to suggest from that. You can fill in the form yourself."),
    ).toBeTruthy();
  });

  it("AC-12: a failure shows a message, keeps the text, and the form still saves", async () => {
    suggestionResponse = () =>
      Promise.resolve(json({ error: { code: "suggestions_unavailable", message: "x" } }, 503));
    renderScreen();
    await writeAndSuggest();

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Suggestions aren't available right now. You can fill in the form yourself.",
    );
    expect(box().value).toBe(NOTE);

    await chooseCore();
    await save();
    await screen.findByText("overview screen");
    expect(puts[0]?.body.mode).toBe("structured");
  });

  it("AC-13: the save holds no free text, and clears the box", async () => {
    suggestionResponse = reply({ mood: 2, energy: 3, stress: 4 });
    renderScreen();
    await writeAndSuggest();
    await waitFor(() => {
      expect(chosen("mood")).toBe("2");
    });

    await save();
    await screen.findByText("overview screen");

    expect(puts[0]?.body).toEqual({
      scores: { mood: 2, energy: 3, stress: 4 },
      tags: [],
      mode: "free_text",
    });
    expect(JSON.stringify(puts)).not.toContain("marker_note");
    expect(localStorage).toHaveLength(0);
    expect(sessionStorage).toHaveLength(0);
    expect(window.location.href).not.toContain("marker_note");

    await userEvent.click(screen.getByRole("link", { name: "back" }));
    expect(
      (await screen.findByRole<HTMLTextAreaElement>("textbox", { name: "Write about your day" }))
        .value,
    ).toBe("");
  });

  it("AC-13: a form used without suggestions stays a structured check-in", async () => {
    suggestionResponse = reply({});
    renderScreen();
    await writeAndSuggest();
    await screen.findByText(/^Nothing to suggest/);

    await chooseCore();
    await save();
    await screen.findByText("overview screen");

    expect(puts[0]?.body.mode).toBe("structured");
    expect(JSON.stringify(puts)).not.toContain("marker_note");
  });

  it("keeps the browser from storing or sending the text elsewhere", async () => {
    renderScreen();
    await write("x");
    expect(box().getAttribute("autocomplete")).toBe("off");
    expect(box().getAttribute("spellcheck")).toBe("false");
    expect(box().maxLength).toBe(2000);
  });

  it("can't suggest from an empty box, or twice at once", async () => {
    let finish: (response: Response) => void = () => undefined;
    suggestionResponse = () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    renderScreen();
    await screen.findByRole("textbox", { name: "Write about your day" });
    expect(suggestButton().disabled).toBe(true);
    await write("   ");
    expect(suggestButton().disabled).toBe(true);
    await userEvent.clear(box());

    await writeAndSuggest();
    expect(suggestButton().disabled).toBe(true);
    await userEvent.click(suggestButton());
    expect(suggestions).toHaveLength(1);
    finish(json({ scores: {}, tags: [] }));
    await screen.findByText(/^Nothing to suggest/);
  });

  it("doesn't carry the note to another day", async () => {
    renderScreen();
    await write();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Day" }), "2026-11-02");

    await waitFor(() => {
      expect(box().value).toBe("");
    });
  });
});
