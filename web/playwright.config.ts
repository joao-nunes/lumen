import { randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";

const PORT = 8001;
const database = (role: string) => `postgresql+psycopg://${role}:${role}@localhost:5432/lumen_test`;

export default defineConfig({
  testDir: "e2e",
  forbidOnly: true,
  reporter: "list",
  use: { baseURL: `http://localhost:${String(PORT)}` },
  webServer: {
    command: `make -C .. run PORT=${String(PORT)}`,
    url: `http://localhost:${String(PORT)}/login`,
    // Never reuse a running app: it would be using the development database.
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      DATABASE_URL: database("lumen_app"),
      AUTH_DATABASE_URL: database("lumen_auth"),
      SECRET_KEY: randomBytes(48).toString("base64url"),
    },
  },
});
