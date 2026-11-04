/** The one place the app talks to the API (spec 002 §2.4). */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClient {
  get(path: string): Promise<unknown>;
  send(method: "POST" | "PUT", path: string, body?: unknown): Promise<unknown>;
}

// The name has a __Host- prefix only when COOKIE_SECURE is on.
const CSRF_COOKIE = /(?:^|;\s*)(?:__Host-)?lumen_csrf=([^;]*)/;

// A wrong password also gets a 401, but the session isn't what failed: the
// form that submitted it shows the error.
const WRONG_CREDENTIALS = "invalid_credentials";

function csrfToken(): string | undefined {
  return CSRF_COOKIE.exec(document.cookie)?.[1];
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const { error } = (await response.json()) as { error: { code: string; message: string } };
    return new ApiError(response.status, error.code, error.message);
  } catch {
    // Not the API's JSON, e.g. a proxy's error page.
    return new ApiError(response.status, "unexpected_response", "Lumen couldn't be reached.");
  }
}

export function createClient(onSessionEnded: () => void): ApiClient {
  async function request(path: string, init: RequestInit): Promise<unknown> {
    const response = await fetch(`/api${path}`, init);
    if (!response.ok) {
      const error = await toError(response);
      if (error.status === 401 && error.code !== WRONG_CREDENTIALS) {
        onSessionEnded();
      }
      throw error;
    }
    return response.status === 204 ? undefined : response.json();
  }

  return {
    get: (path) => request(path, { method: "GET" }),
    send: (method, path, body) => {
      const headers = new Headers();
      const token = csrfToken();
      if (token !== undefined) {
        headers.set("X-CSRF-Token", token);
      }
      if (body === undefined) {
        return request(path, { method, headers });
      }
      headers.set("Content-Type", "application/json");
      return request(path, { method, headers, body: JSON.stringify(body) });
    },
  };
}
