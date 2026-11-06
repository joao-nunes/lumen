// @vitest-environment jsdom
// Logging out against a fake API: `fetch` is the only thing replaced.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthenticatedLayout } from "./AuthenticatedLayout";

const fetchMock = vi.fn<typeof fetch>();

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

function renderLayout() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <Routes>
          <Route element={<AuthenticatedLayout />}>
            <Route path="/" element={<p>Today screen</p>} />
          </Route>
          <Route path="/login" element={<p>Log in page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((url) =>
    Promise.resolve(
      url === "/api/auth/me"
        ? json(200, { user_id: "u", email: "joao@example.com" })
        : json(403, { error: { code: "csrf_failed", message: "Reload the page and try again" } }),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("says so when logging out fails, and stays on the page", async () => {
  renderLayout();

  await userEvent.click(await screen.findByRole("button", { name: "Log out" }));

  expect((await screen.findByRole("alert")).textContent).toBe("Reload the page and try again");
  expect(screen.queryByText("Today screen")).not.toBeNull();
  expect(screen.queryByText("Log in page")).toBeNull();
});

it("goes to the login page when logging out works", async () => {
  fetchMock.mockImplementation((url) =>
    Promise.resolve(
      url === "/api/auth/me"
        ? json(200, { user_id: "u", email: "joao@example.com" })
        : new Response(null, { status: 204 }),
    ),
  );
  renderLayout();

  await userEvent.click(await screen.findByRole("button", { name: "Log out" }));

  await screen.findByText("Log in page");
  expect(screen.queryByRole("alert")).toBeNull();
});
