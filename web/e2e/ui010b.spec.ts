// 010-B 用户实机验收：首页（中文默认）+ Try Demo Mode + 语言切换 + Settings 安全显示
import { expect, test } from "@playwright/test";

test("010-B home page (zh default) + demo entry + language switch", async ({ page }) => {
  // 首页：AI Team OS + 控制中心 + 中文导航（010-B 四/九）
  await page.goto("/");
  await expect(page.getByText("AI Team OS")).toBeVisible();
  await expect(page.getByText("控制中心")).toBeVisible();
  await expect(page.getByText("仪表盘").first()).toBeVisible();
  await expect(page.getByText("任务").first()).toBeVisible();
  await expect(page.getByText("设置").first()).toBeVisible();
  await expect(page.getByText("系统健康")).toBeVisible();
  // Try Demo Mode 明显入口（010-B 五）
  const demo = page.getByRole("button", { name: /Try Demo Mode/ });
  await expect(demo).toBeVisible();
  await page.screenshot({ path: "e2e/shots/ui010b-home-zh.png", fullPage: true });

  // 语言切换 → English（010-B 九）
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByText("Control Center")).toBeVisible();
  await expect(page.getByText("Dashboard").first()).toBeVisible();
  await expect(page.getByText("System Health")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/ui010b-home-en.png", fullPage: true });
  // 切回中文
  await page.getByRole("button", { name: "简体中文" }).click();
  await expect(page.getByText("控制中心")).toBeVisible();

  // Settings：安全显示（010-B 十）——只显示状态，无 Key/凭据
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "连接" })).toBeVisible();
  await expect(page.getByText("OpenAI 兼容").first()).toBeVisible();
  await page.screenshot({ path: "e2e/shots/ui010b-settings.png", fullPage: true });
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("sk-");
  expect(body).not.toContain("reasonix");
  expect(body).not.toContain(".create_token");
});
