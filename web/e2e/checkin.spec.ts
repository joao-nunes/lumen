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

  // 4. A reload keeps the session, and Today is prefilled.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.getByRole("link", { name: "Today" }).click();
  for (const group of await groups.all()) {
    await expect(group.getByRole("radio").nth(1)).toBeChecked();
  }

  // 5. Logging out returns to Log in.
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();

  expect(policyViolations).toEqual([]);
});
