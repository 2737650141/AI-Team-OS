# 审批使用指南（007 十六/十七）

## 何时需要审批

| 操作                 | 等级     |
| -------------------- | -------- |
| 读取沙箱文件         | none     |
| 生成但不应用补丁     | none     |
| 在沙箱创建新文件     | preview/explicit |
| 修改沙箱文件         | explicit |
| 删除沙箱文件         | explicit |
| 运行允许的测试命令   | explicit |
| 创建本地 commit      | explicit |
| 修改源项目           | forbidden |
| push/PR/发送/设备    | forbidden |

## 流程

```text
run sandbox_*  → paused（awaiting approval）
approvals <run_id>  → 查看审批（含 Diff 引用）
diff <run_id>       → 查看 Diff（批准前必须看到）
approve/reject      → 决策落盘 → 恢复任务
```

## 安全语义

- 批准绑定操作/参数/目标三哈希 + 有效期；参数变化旧批准立即失效。
- 拒绝后任务标记 `rejected_by_user`，不应用补丁，提案与 Diff 保留。
- 本地 commit 是**本地** commit（`local_only=true`），绝不表述为"已发布/已推送"。
- API 仅本机单用户；Approve 只提交 approval_id 与可选说明，不能修改审批参数。
