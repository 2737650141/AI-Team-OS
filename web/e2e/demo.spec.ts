// E2E：Dashboard → 创建 Demo Task → Approval → Approve → Completed → 刷新恢复（010 五十二）
import { expect, test } from "@playwright/test";

test("demo task full lifecycle", async ({ page }) => {
  // 1. 打开 Dashboard
  await page.goto("/");
  await expect(page.getByText("AI Team OS", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("System Health")).toBeVisible();

  // 2. 创建 Demo 任务（沙箱修复场景 → 触发审批；需指定示例项目）
  await page.getByPlaceholder("What do you want the AI team to do?").fill("sandbox_code_fix");
  await page.getByText("Advanced").click();
  await page.getByPlaceholder("sample-python").fill("sample-python");
  await page.getByRole("button", { name: "Start Task" }).click();

  // 3. 自动跳转 Task Detail 并出现 Planner/证据/审批
  await page.waitForURL(/\/tasks\/[0-9a-f]+/, { timeout: 30_000 });
  await expect(page.getByText("Workflow")).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "e2e/shots/task-detail.png", fullPage: false });

  // 4. 等待 Approval 出现
  const approve = page.getByRole("button", { name: "Approve" });
  await expect(approve.first()).toBeVisible({ timeout: 120_000 });
  await page.screenshot({ path: "e2e/shots/approval.png", fullPage: false });

  // 5. Approve → 等待 completed（Review passed 唯一文本）
  await approve.first().click();
  await expect(page.locator("body")).toContainText(/Review passed/i, { timeout: 120_000 });
  await page.screenshot({ path: "e2e/shots/completed.png", fullPage: false });

  // 6. 刷新恢复（010 十五/二十六）
  await page.reload();
  await expect(page.getByText("Workflow")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 20_000 });
});
