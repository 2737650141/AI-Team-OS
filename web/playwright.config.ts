import { defineConfig } from "@playwright/test";

// E2E（010 五十二）：需要后端 :8000 与前端 :5173 已启动（scripts/start_ui 辅助）
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["list"]],
});
