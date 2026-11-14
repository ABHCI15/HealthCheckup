import { defineConfig } from "@playwright/test";

// Tests run against the built app served by the Python API, with live data sources.
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8000", viewport: { width: 1440, height: 900 }, screenshot: "only-on-failure" },
  webServer: {
    command: "cd .. && venv/bin/uvicorn api:app --port 8000",
    url: "http://127.0.0.1:8000/api/status",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
