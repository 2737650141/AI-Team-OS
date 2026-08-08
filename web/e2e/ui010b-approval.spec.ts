// 010-B 六：Demo 审批页等待用户操作（只验证可见，不点击 Approve/Reject）
import { expect, test } from "@playwright/test";

const RUN = "496187744ea64471";

test("010-B approval page ready for user (no auto-approve)", async ({ page }) => {
  await page.goto(`/tasks/${RUN}`);
  // 审批卡片：原因/文件/风险/批准/拒绝（中文）
  await expect(page.getByRole("heading", { name: "审批" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "批准" })).toBeVisible();
  await expect(page.getByRole("button", { name: "拒绝" })).toBeVisible();
  await expect(page.getByText(/Approve|批准/)).toBeVisible();
  // Diff 与文件可见
  await expect(page.getByRole("heading", { name: "代码差异" })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "e2e/shots/ui010b-approval.png", fullPage: true });
  // 不点击任何审批按钮
});
