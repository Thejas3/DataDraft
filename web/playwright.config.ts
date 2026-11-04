import { defineConfig, devices } from "@playwright/test";

// One E2E (R8/D11): paste a trade -> ruling -> shareable card. The API is the seeded
// test server (tests/e2e_server.py), so no Sleeper, nflverse or Claude calls happen.
const API_PORT = 8766;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: `../.venv/bin/python ../tests/e2e_server.py ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/session`,
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
    },
    {
      command: `npx next dev -p ${WEB_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/login`,
      env: { DATADRAFT_API_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
