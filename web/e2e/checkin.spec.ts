// AC-9 (spec 002): the whole slice, by keyboard, under the Content-Security-Policy
// FastAPI really sends. `make e2e` runs it against the app `make run` serves.
import { expect, type Locator, type Page, test } from "@playwright/test";

const CORE_ANCHORS = {
  Mood: ["Very low", "Low", "Neutral", "Good", "Very good"],
  Energy: ["Depleted", "Low", "Moderate", "Good", "High"],
  Stress: ["Calm", "Mild", "Moderate", "High", "Overwhelmed"],
};

/** Presses Tab until `target` has focus, so nothing here ever clicks. */
async function tabTo(page: Page, target: Locator): Promise<void> {
  for (let presses = 0; presses < 60; presses++) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) return;
  }
  throw new Error("Tab never reached the target");
}

test("register, check in by keyboard, see the overview, reload, log out", async ({ page }) => {
  const policyViolations: string[] = [];
  page.on("console", (message) => {
    if (/content security policy/i.test(message.text())) policyViolations.push(message.text());
  });
  page.on("pageerror", (error) => {
    policyViolations.push(error.message);
  });

  // 1. Register. The header proves this run is under the real policy, not a dev server's.
  const response = await page.goto("/register");
  expect(response?.headers()["content-security-policy"]).toContain("default-src 'none'");
  await page.getByLabel("Email").fill(`e2e-${String(Date.now())}@example.com`);
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.getByRole("button", { name: "Create an account" }).click();

  // 2. The form: three core dimensions and two prompted ones, each with five anchors.
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  const groups = page.getByRole("group").filter({ has: page.getByRole("radio") });
  await expect(groups).toHaveCount(5);
  for (const group of await groups.all()) {
    await expect(group.getByRole("radio")).toHaveCount(5);
  }
  for (const [name, anchors] of Object.entries(CORE_ANCHORS)) {
    const labels = page.getByRole("group", { name }).locator("strong");
    await expect(labels).toHaveText(anchors);
  }

  // 2b. Spec 008 AC-9: add a dimension today didn't ask about. It's marked, and gets a group.
  const addControl = page.getByRole("combobox", { name: "Add another dimension" });
  // selectOption, not a click; ArrowDown opens the menu rather than choosing on macOS.
  const added = (await addControl.locator("option").nth(1).textContent()) ?? "";
  await addControl.selectOption({ index: 1 }); // the first dimension after "Choose one"
  await expect(groups).toHaveCount(6);
  await expect(page.getByText("Not asked today")).toHaveCount(1);

  // 3. Keyboard alone: Tab into each group, an arrow key chooses, then submit.
  await page.getByRole("combobox", { name: "Day" }).focus();
  for (const group of await groups.all()) {
    await tabTo(page, group.getByRole("radio").first());
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowDown"); // the second anchor
  }
  await tabTo(page, page.getByRole("button", { name: "Save check-in" }));
  await page.keyboard.press("Enter");

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const mood = page.getByRole("region", { name: "Mood" });
  await expect(mood.getByText("Not enough data yet (1 day)").first()).toBeVisible();
  // The chart really drew today's point, on the anchor axis, with high scores at the top.
  await expect(mood.locator("svg .recharts-line-dot")).toHaveCount(1);
  const top = await mood.locator("svg").getByText("Very good").boundingBox();
  const bottom = await mood.locator("svg").getByText("Very low").boundingBox();
  expect(top?.y).toBeLessThan(bottom?.y ?? 0);

  // 3b. Spec 009 AC-8: the added dimension's score was volunteered, so its chart draws one hollow
  // point and no filled one, and its heatmap cell is marked.
  const volunteered = page.getByRole("region", { name: added });
  await expect(volunteered.getByText("Also mentioned on 1 day without being asked")).toBeVisible();
  await expect(volunteered.locator('svg circle[fill="var(--background)"]')).toHaveCount(1);
  await expect(volunteered.locator('svg circle[fill="var(--chart-line)"]')).toHaveCount(0);
  // Never joined: the only drawn line is the 7-day average's, which Recharts renders even empty.
  await expect(
    volunteered.locator('svg path.recharts-curve[stroke="var(--chart-line)"]'),
  ).toHaveCount(1);
  const lately = page.getByRole("region", { name: "Lately" });
  await expect(lately.getByRole("list", { name: added }).locator("[data-volunteered]")).toHaveCount(
    1,
  );

  // 4. A reload keeps the session, and Today is prefilled.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.getByRole("link", { name: "Today" }).click();
  await expect(groups).toHaveCount(6);
  for (const group of await groups.all()) {
    await expect(group.getByRole("radio").nth(1)).toBeChecked();
  }
  await expect(page.getByText("Not asked today")).toHaveCount(1); // saved, and still marked

  // 4b. Dark mode is chosen from the footer and survives a reload; the page starts light.
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Dark mode" }).click();
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Dark mode" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // 5. Logging out returns to Log in.
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();

  expect(policyViolations).toEqual([]);
});

// AC-15 (spec 006): a free-text note to a confirmed check-in, through the real client and API.
test("write a note, correct a suggestion, save it, and find no trace of the note", async ({
  page,
}) => {
  const policyViolations: string[] = [];
  const sentBodies: string[] = [];
  page.on("console", (message) => {
    if (/content security policy/i.test(message.text())) policyViolations.push(message.text());
  });
  page.on("pageerror", (error) => {
    policyViolations.push(error.message);
  });
  page.on("request", (request) => {
    if (!request.url().endsWith("/suggestion")) sentBodies.push(request.postData() ?? "");
  });

  await page.goto("/register");
  await page.getByLabel("Email").fill(`e2e-note-${String(Date.now())}@example.com`);
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.getByRole("button", { name: "Create an account" }).click();
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();

  // The safety text is there before anything is typed.
  await expect(page.getByText("SNS 24, 808 24 24 24, option 4")).toBeVisible();
  await expect(page.getByText("In an emergency, call 112.")).toBeVisible();

  const note = "stressful meeting, ok evening";
  await page.getByRole("textbox", { name: "Write about your day" }).fill(note);
  await page.getByRole("button", { name: "Suggest scores" }).click();

  // Suggested, marked, and not saved. Energy's quote isn't in the note, so it stays blank.
  const stress = page.getByRole("group", { name: "Stress" });
  const mood = page.getByRole("group", { name: "Mood" });
  const energy = page.getByRole("group", { name: "Energy" });
  await expect(stress.getByText("Suggested, please check")).toBeVisible();
  await expect(stress.getByRole("radio").nth(3)).toBeChecked();
  await expect(mood.getByRole("radio").nth(2)).toBeChecked();
  for (const radio of await energy.getByRole("radio").all()) {
    await expect(radio).not.toBeChecked();
  }
  await expect(page.getByRole("checkbox", { name: /workday/ })).toBeChecked();
  await expect(page.getByText("a_tag_nobody_offered")).toHaveCount(0);

  // Correct a suggestion, answer the rest, and save.
  await stress.getByRole("radio").nth(1).check();
  await expect(stress.getByText("Suggested, please check")).toHaveCount(0);
  await energy.getByRole("radio").nth(2).check();
  await page.getByRole("button", { name: "Save check-in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // Back on Today: the corrected value is what was saved, and the note is gone.
  await page.getByRole("link", { name: "Today" }).click();
  await expect(stress.getByRole("radio").nth(1)).toBeChecked();
  await expect(mood.getByRole("radio").nth(2)).toBeChecked();
  await expect(page.getByRole("textbox", { name: "Write about your day" })).toHaveValue("");

  expect(sentBodies.filter((body) => body.includes("stressful meeting"))).toEqual([]);
  const stored = await page.evaluate(() =>
    JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]),
  );
  expect(stored).not.toContain("stressful meeting");
  expect(page.url()).not.toContain("stressful");
  expect(policyViolations).toEqual([]);
});
