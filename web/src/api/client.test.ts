// AC-10 (spec 002). `fetch` and the cookie jar are the browser's; everything else is real.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createClient } from "./client";

const fetchMock = vi.fn<typeof fetch>();
const onSessionEnded = vi.fn<() => void>();

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function error(status: number, code: string): Response {
  return json(status, { error: { code, message: `message for ${code}` } });
}

function lastRequest(): { url: string; init: RequestInit; headers: Headers } {
  const [url, init] = fetchMock.mock.lastCall ?? [];
  return { url: url as string, init: init ?? {}, headers: new Headers(init?.headers) };
}

beforeEach(() => {
  fetchMock.mockReset();
  onSessionEnded.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("document", { cookie: "other=1; __Host-lumen_csrf=token-123" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CSRF", () => {
  it("sends the cookie's token and a JSON body on an unsafe request", async () => {
    fetchMock.mockResolvedValue(json(200, { saved: true }));

    const result = await createClient(onSessionEnded).send("PUT", "/checkins/2026-10-31", {
      scores: { mood: 3 },
    });

    const { url, init, headers } = lastRequest();
    expect(url).toBe("/api/checkins/2026-10-31");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe('{"scores":{"mood":3}}');
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("x-csrf-token")).toBe("token-123");
    expect(result).toEqual({ saved: true });
  });

  it("reads the unprefixed cookie when COOKIE_SECURE is off", async () => {
    vi.stubGlobal("document", { cookie: "lumen_csrf=plain-456" });
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await createClient(onSessionEnded).send("POST", "/auth/logout");

    expect(lastRequest().headers.get("x-csrf-token")).toBe("plain-456");
  });

  it("does not send the token on a GET", async () => {
    fetchMock.mockResolvedValue(json(200, {}));

    await createClient(onSessionEnded).get("/tags");

    expect(lastRequest().headers.has("x-csrf-token")).toBe(false);
  });
});

describe("401", () => {
  it("ends the session when the user is no longer logged in", async () => {
    fetchMock.mockResolvedValue(error(401, "not_authenticated"));

    await expect(createClient(onSessionEnded).get("/tags")).rejects.toMatchObject({
      status: 401,
      code: "not_authenticated",
    });
    expect(onSessionEnded).toHaveBeenCalledOnce();
  });

  it("leaves a wrong password to the form that submitted it", async () => {
    fetchMock.mockResolvedValue(error(401, "invalid_credentials"));

    await expect(
      createClient(onSessionEnded).send("POST", "/auth/login", { email: "a", password: "b" }),
    ).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
    expect(onSessionEnded).not.toHaveBeenCalled();
  });
});

describe("other failures", () => {
  it("raises the API's error code and message", async () => {
    fetchMock.mockResolvedValue(error(422, "weak_password"));

    const failure: unknown = await createClient(onSessionEnded)
      .send("POST", "/auth/register", {})
      .catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      status: 422,
      code: "weak_password",
      message: "message for weak_password",
    });
    expect(onSessionEnded).not.toHaveBeenCalled();
  });

  it("raises a clean error when the response isn't the API's JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 }));

    await expect(createClient(onSessionEnded).get("/tags")).rejects.toMatchObject({
      status: 502,
      code: "unexpected_response",
    });
  });
});
