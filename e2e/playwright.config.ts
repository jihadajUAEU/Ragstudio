import { defineConfig } from "../frontend/node_modules/@playwright/test";

const baseURL = process.env.RAGSTUDIO_E2E_BASE_URL ?? "http://127.0.0.1:5173";

export default defineConfig({
  testDir: ".",
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    cwd: "../frontend",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  use: {
    baseURL,
  },
});
