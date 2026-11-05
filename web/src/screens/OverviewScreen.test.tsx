// @vitest-environment jsdom
// The overview against a fake API: `fetch` is the only thing replaced. jsdom has no
// layout, so the chart draws nothing here; AC-9 draws it in a real browser.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatDay } from "../lib/dates";
import { OverviewScreen } from "./OverviewScreen";
import { TodayScreen } from "./TodayScreen";

const TODAY = "2026-11-03";

function dimensionInfo(key: string, name: string, polarity: string) {
  return {
    key,
    display_name: name,
    cadence: "core",
    polarity,
    anchors: [1, 2, 3, 4, 5].map((n) => ({ label: `${name} ${String(n)}`, description: "" })),
  };
}

const DIMENSIONS = [
  dimensionInfo("mood", "Mood", "higher_is_better"),
  dimensionInfo("energy", "Energy", "higher_is_better"),
  dimensionInfo("stress", "Stress", "higher_is_worse"),
];

function noData(dimension: string) {
  const period = { start: "2026-10-07", end: TODAY, mean: null, n: 0 };
  return {
    dimension,
    change: {
      current: period,
      previous: period,
      delta: null,
      ci_low: null,
      ci_high: null,
      direction: "insufficient_data",
      outlook: "unknown",
    },
    trend: {
      start: "2026-08-12",
      end: TODAY,
      slope_per_week: null,
      ci_low: null,
      ci_high: null,
      direction: "insufficient_data",
      outlook: "unknown",
      n: 0,
      n_effective: null,
    },
    daily: [],
    rolling_7: [],
  };
}

const STRESS = {
  dimension: "stress",
  change: {
    current: { start: "2026-10-07", end: TODAY, mean: 3.6, n: 22 },
    previous: { start: "2026-09-09", end: "2026-10-06", mean: 3.2, n: 25 },
    delta: 0.4,
    ci_low: 0.1,
    ci_high: 0.7,
    direction: "increasing",
    outlook: "worsening",
  },
  trend: {
    start: "2026-08-12",
    end: TODAY,
    slope_per_week: -0.05,
    ci_low: -0.08,
    ci_high: -0.02,
    direction: "decreasing",
    outlook: "improving",
    n: 70,
    n_effective: 40.5,
  },
  daily: [{ date: TODAY, mean: 4 }],
  rolling_7: [{ date: TODAY, mean: 3.25, n: 5 }],
};

let overview: () => unknown;
let overviewReady: Promise<void>;

const fakeFetch = vi.fn<typeof fetch>((input, init) => {
  const url = input as string;
  const respond = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body)));
  if (url === `/api/overview?end=${TODAY}`) {
    return overviewReady.then(() => new Response(JSON.stringify(overview())));
  }
  if (url === "/api/dimensions") return respond(DIMENSIONS);
  if (url === "/api/tags") return respond([]);
  if (url.startsWith("/api/checkins/")) {
    const saved = init?.method === "PUT";
    return respond({
      local_date: TODAY,
      prompted: ["mood", "energy", "stress"],
      checkin: saved ? { scores: {}, tags: [], recorded_at: `${TODAY}T12:00:00Z` } : null,
    });
  }
  return Promise.resolve(new Response("{}", { status: 404 }));
});

beforeEach(() => {
  vi.stubGlobal("fetch", fakeFetch);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  overviewReady = Promise.resolve();
  overview = () => ({
    end: TODAY,
    dimensions: [noData("mood"), noData("energy"), STRESS],
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderScreen(): void {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/overview"]}>
        <Routes>
          <Route path="/" element={<TodayScreen today={TODAY} />} />
          <Route path="/overview" element={<OverviewScreen today={TODAY} />} />
        </Routes>
        <Nav />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function Nav() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => void navigate("/")}>
      go to today
    </button>
  );
}

const card = (name: string) => screen.findByRole("region", { name });

describe("overview screen", () => {
  it("gives each dimension its own card, in the API's order, with no combined score", async () => {
    renderScreen();
    await card("Mood");
    expect(
      screen.getAllByRole("region").map((c) => within(c).getByRole("heading").textContent),
    ).toEqual(["Mood", "Energy", "Stress"]);
  });

  it("leads with the two plain-language lines, and keeps the axis note for higher-is-worse", async () => {
    renderScreen();
    const stress = within(await card("Stress"));
    expect(
      stress.getByText("Higher than the previous 4 weeks (based on 22 and 25 days)"),
    ).toBeTruthy();
    expect(stress.getByText("Gradually improving over 12 weeks (based on 70 days)")).toBeTruthy();
    expect(stress.getByText("Higher = more stress")).toBeTruthy();
    expect(within(await card("Mood")).queryByText(/^Higher = /)).toBeNull();
  });

  it("keeps the estimates and 95% intervals behind an expand control", async () => {
    renderScreen();
    const stress = await card("Stress");
    const details = stress.querySelector("details");
    expect(details?.open).toBe(false);
    expect(within(stress).getByText("Numbers").tagName).toBe("SUMMARY");
    const numbers = within(details as HTMLElement);
    expect(numbers.getByText("Last 4 weeks: average 3.60 (22 days)")).toBeTruthy();
    expect(numbers.getByText("Previous 4 weeks: average 3.20 (25 days)")).toBeTruthy();
    expect(numbers.getByText("Difference: +0.40 (95% interval +0.10 to +0.70)")).toBeTruthy();
    expect(numbers.getByText("Per week: −0.05 (95% interval −0.08 to −0.02)")).toBeTruthy();
  });

  it("says plainly when an estimate can't be computed yet, instead of showing a number", async () => {
    renderScreen();
    const numbers = within((await card("Mood")).querySelector("details") as HTMLElement);
    expect(numbers.getByText("Last 4 weeks: not enough data (0 days)")).toBeTruthy();
    expect(numbers.getByText("Difference: not enough data")).toBeTruthy();
    expect(numbers.getByText("Per week: not enough data")).toBeTruthy();
  });

  it("gives the chart's values in a table, one row per day with data", async () => {
    renderScreen();
    const table = within(await card("Stress")).getByRole("table", { hidden: true });
    const rows = within(table).getAllByRole("row", { hidden: true });
    expect(rows.map((row) => row.textContent)).toEqual([
      "DayDaily7-day average",
      `${formatDay(TODAY)}43.25`,
    ]);
  });

  it("never shows the overview from before a save", async () => {
    renderScreen();
    await card("Mood");
    await userEvent.click(screen.getByRole("button", { name: "go to today" }));

    let release = () => {};
    overviewReady = new Promise((resolve) => {
      release = resolve;
    });
    overview = () => ({
      end: TODAY,
      dimensions: [
        { ...noData("mood"), trend: { ...noData("mood").trend, n: 1 } },
        noData("energy"),
        noData("stress"),
      ],
    });
    for (const name of ["Mood", "Energy", "Stress"]) {
      await userEvent.click(
        within(await screen.findByRole("group", { name })).getByRole("radio", {
          name: `${name} 3`,
        }),
      );
    }
    await userEvent.click(screen.getByRole("button", { name: "Save check-in" }));

    await screen.findByRole("heading", { name: "Overview" });
    // The new overview hasn't arrived yet: a stale cached copy would be on screen now.
    expect(screen.queryByRole("region")).toBeNull();
    release();
    const mood = within(await card("Mood"));
    expect(mood.getAllByText("Not enough data yet (1 day)")).toHaveLength(1);
  });

  it("shows an error rather than an empty screen when the API can't be reached", async () => {
    fakeFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderScreen();
    expect((await screen.findByRole("alert")).textContent).toContain("couldn't be reached");
  });
});
