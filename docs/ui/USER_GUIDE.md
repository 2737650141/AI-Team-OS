# 用户指南（010 五十五）

> 不需要了解代码，按下面步骤即可使用 AI Team OS。

## 1. 启动

双击运行：

```powershell
scripts\start_ai_team_os.ps1
```

（或在项目目录打开两个终端分别运行后端与前端命令，见 WEB_CONTROL_CENTER.md）
启动后浏览器自动打开 `http://127.0.0.1:5173`。

## 2. 打开网页

看到 **AI Team OS Control Center** 的深色界面（Dashboard）。

## 3. 跑 Demo（无需任何 Key）

1. 首页输入框输入：`sandbox_code_fix`。
2. 展开 **Advanced**，Project 填：`sample-python`。
3. 点 **Start Task**。
4. 自动进入任务页：看到 Planner 拆解、Agent 活动、Evidence 出现。
5. 新安装默认是 **标准模式**：普通代码修改、测试和本地 Commit 自动完成。
6. 如需逐步确认，先到 **Settings → Security & Permissions** 切换安全模式。
7. 看到 Diff、Tests、Reviewer，最后任务 Completed。

## 4. 选择权限模式

- **安全模式**：只读与真正低风险操作自动执行；写入、测试和电脑状态变化会询问。
- **标准模式（推荐）**：普通开发、Research 和电脑助理操作自动完成；删除、外部发送、
  系统修改和敏感行为才询问。
- **最高权限模式**：用户目标内的大多数操作完整自动执行。第一次启用只确认一次；密码、
  Secret、UAC、核心安全系统与 STOP 仍不可绕过。

模式保存在本地设置，重启和新任务继续生效。顶部权限 Badge 可随时返回设置页。

## 5. 设置 API Key（真实模型）

1. 左侧 **Settings** → **Connections**。
2. OpenAI Compatible 卡片：
   - Base URL：你的中转/官方地址（如 `https://api.openai.com/v1`）。
   - API Key：粘贴密钥（密码框，不会显示）。
   - Storage：选 **Save on this PC**（本机加密保存）或 **Session only**（重启失效）。
   - 点 **Test Connection** 验证，然后 **Save securely**。
3. GitHub 同样方式配置 Token（可选）。

以后无需再编辑 `.env` 或 `reasonix.toml`。

## 6. 创建真实任务

1. 首页输入任务描述（如 `github_compare_team`）。
2. Model Mode 选 **Real**（需已配置 Provider）。
3. **Start Task** → 观看团队工作。

## 7. 查看进度

- 任务页顶部：状态 / 阶段时间线。
- Plan 面板：子任务与依赖。
- Activity：实时事件流。
- Evidence / Diff / Tests / Reviewer：各区块。

## 8. 批准 / 拒绝重要操作

出现 Approval 卡片时查看 Diff，然后：

- **Approve**：AI 应用补丁 → 跑测试 → Reviewer。
- **Reject**：不应用，可填原因。

## 9. 查看最终结果

任务 Completed 后顶部状态变绿；Reviewer 显示通过；证据与测试结果可展开查看。

## 故障排查

| 现象 | 处理 |
| ---- | ---- |
| 页面打不开 | 确认后端 8000 与前端 5173 已启动（见第 1 步） |
| 任务报错 | 页面显示错误 ID/原因；详细日志见后端终端输出 |
| 想换 Key | Settings → Connections → 输入新 Key → Save（旧 Key 从本机移除，但**不会**在 Provider 后台吊销） |
# Usage & Context

Open **Usage** from the main navigation to see context-window pressure, provider-reported or
estimated tokens, cache/reasoning breakdowns, model/agent/provider totals, cost availability, and
the call timeline. `≈` means estimated; `Unavailable` means the system deliberately did not invent
a value. Set data retention under **Settings → Usage history**.
