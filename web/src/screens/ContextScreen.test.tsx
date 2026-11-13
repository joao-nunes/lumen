// @vitest-environment jsdom
// Spec 010 AC-5: the personal context page, against a fake API.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContextScreen } from "./ContextScreen";

let saved: string;
let puts: unknown[];

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

const fakeFetch = vi.fn<typeof fetch>((_input, init) => {
  if (init?.method === "PUT") {
    const body = JSON.parse(init.body as string) as { text: string };
    puts.push(body);
    saved = body.text.trim();
    return Promise.resolve(json({ text: saved }));
  }
  return Promise.resolve(json({ text: saved }));
});

function renderScreen() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ContextScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function box(): Promise<HTMLTextAreaElement> {
  return screen.findByRole<HTMLTextAreaElement>("textbox", { name: "Your personal context" });
}

beforeEach(() => {
  saved = "";
  puts = [];
  vi.stubGlobal("fetch", fakeFetch);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the personal context page", () => {
  it("shows what's saved, counts characters, and saves the edit", async () => {
    saved = "I nap most afternoons.";
    renderScreen();
    const textarea = await box();
    expect(textarea.value).toBe("I nap most afternoons.");
    expect(screen.getByText("22 / 750")).toBeTruthy();
    expect(textarea.maxLength).toBe(750);
    expect(textarea.getAttribute("spellcheck")).toBe("false"); // spelling services could send it elsewhere

    await userEvent.clear(textarea);
    await userEvent.type(textarea, "Waking at night is normal for me.");
    expect(screen.getByText("33 / 750")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(puts).toEqual([{ text: "Waking at night is normal for me." }]);
  });

  it("deletes it when cleared and saved", async () => {
    saved = "Something old.";
    renderScreen();
    await userEvent.clear(await box());
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(puts).toEqual([{ text: "" }]);
  });
});
