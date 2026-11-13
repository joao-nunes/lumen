// @vitest-environment jsdom
// The light/dark switch: light unless the person chose dark, remembered in this browser only.
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyTheme, storedTheme } from "../lib/theme";
import { ThemeToggle } from "./ThemeToggle";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the theme", () => {
  it("is light until dark is chosen, and remembers each choice", async () => {
    applyTheme(storedTheme()); // what main.tsx does before the first render
    render(<ThemeToggle />);
    const toggle = screen.getByRole("button", { name: "Dark mode" });
    expect([document.documentElement.dataset.theme, toggle.ariaPressed]).toEqual([
      "light",
      "false",
    ]);

    await userEvent.click(toggle);
    expect([document.documentElement.dataset.theme, toggle.ariaPressed]).toEqual(["dark", "true"]);
    expect(localStorage.getItem("lumen-theme")).toBe("dark");

    await userEvent.click(toggle);
    expect([document.documentElement.dataset.theme, toggle.ariaPressed]).toEqual([
      "light",
      "false",
    ]);
    expect(localStorage.getItem("lumen-theme")).toBe("light");
  });

  it("starts dark only from a stored dark choice, and falls back to light if storage fails", () => {
    localStorage.setItem("lumen-theme", "dark");
    expect(storedTheme()).toBe("dark");
    localStorage.setItem("lumen-theme", "purple");
    expect(storedTheme()).toBe("light");

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(storedTheme()).toBe("light");
    render(<ThemeToggle />);
    expect(() => {
      screen.getByRole("button", { name: "Dark mode" }).click();
    }).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark"); // still switches for this visit
  });
});
