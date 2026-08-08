import { defineConfig } from "@playwright/test";

// E2E（010 五十二）：前置条件——后端 :8000 与前端 :5173 已启动。
// 一键启动：scripts/start_ai_team_os.ps1（自动设置 AI_TEAM_ALLOWED_READ_ROOTS=fixtures，
// 否则沙箱任务会 500：project alias not found）。
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
