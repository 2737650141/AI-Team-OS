# Demo Mode（010 三十二/三十八/三十九）

## 是什么

Demo Mode 让用户**没有配置任何 API Key** 也能完整体验 AI Team OS：
Fake Model + Fixture GitHub + Sandbox 示例项目 + Fake Approval Flow。

## 官方 Demo 任务

```text
修复示例 Python 项目里的一个失败测试。
（goal=sandbox_code_fix，project=sample-python）
```

示例项目：`fixtures/sample-python`（合成项目，含确定性 bug `buggy()` 恒错与
失败测试 `tests/test_main.py`）。

## 流程（010 三十八）

```text
输入任务 → Planner → Researcher → Evidence → Executor → Diff → Approval → Tests → Reviewer → Completed
```

- 后端以 `model_mode=fake` 运行 `DeterministicFakeModel`（M2/M3 确定性内核）。
- 沙箱工作区：`runtime/workspaces/<task_id>/`（写时复制，源项目不变）。
- 审批：首次运行暂停在 Approval interrupt → 用户 Approve/Reject → 恢复。
- 测试：Executor 在沙箱内跑白名单 pytest。
- 费用：Demo Mode Cost = $0。

## 如何开始

1. 启动（见 USER_GUIDE 第 1 步）。
2. 首页输入 `sandbox_code_fix`，Advanced → Project `sample-python`。
3. Start Task。

## 验证

`web/e2e/demo.spec.ts`（Playwright）自动覆盖：
打开 Dashboard → 创建 Demo 任务 → Planner/Evidence → Approval → Reject/Approve →
Tests → Completed → 刷新恢复。

运行 E2E 前置条件：
1. 用 `scripts/start_ai_team_os.ps1` 启动（或手动后端时设置
   `AI_TEAM_ALLOWED_READ_ROOTS=<仓库>/fixtures`——缺省时沙箱任务创建会失败）。
2. `cd web && npx playwright test`。
