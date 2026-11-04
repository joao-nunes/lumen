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

export function createClient(_onSessionEnded: () => void): ApiClient {
  throw new Error("not implemented");
}
