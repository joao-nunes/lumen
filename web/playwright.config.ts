import { randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";

const PORT = 8001;
const OLLAMA_PORT = 11499; // the stub, so that a real Ollama is never needed or reached
const database = (role: string) => `postgresql+psycopg://${role}:${role}@localhost:5432/lumen_test`;

export default defineConfig({
  testDir: "e2e",
  forbidOnly: true,
  reporter: "list",
  // A Portuguese browser, so a date that follows the browser's locale fails (spec 002 Q8).
  use: { baseURL: `http://localhost:${String(PORT)}`, locale: "pt-PT" },
  webServer: [
    {
      command: `node e2e/fake-ollama.mjs ${String(OLLAMA_PORT)}`,
      port: OLLAMA_PORT,
      reuseExistingServer: false,
    },
    {
      command: `make -C .. run PORT=${String(PORT)}`,
      url: `http://localhost:${String(PORT)}/login`,
      // Never reuse a running app: it would be using the development database.
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: database("lumen_app"),
        AUTH_DATABASE_URL: database("lumen_auth"),
        SECRET_KEY: randomBytes(48).toString("base64url"),
        OLLAMA_URL: `http://127.0.0.1:${String(OLLAMA_PORT)}`,
        OLLAMA_MODEL: "stub",
      },
    },
  ],
});
