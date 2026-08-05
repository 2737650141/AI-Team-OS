# 沙箱项目设置（007 二十二/4.2）

## 准备输入项目

1. 创建/选择一个只读输入项目目录（真实用户项目**不要**直接使用——系统只复制副本，
   但项目本身应保持稳定）。
2. 将项目放入 `AI_TEAM_ALLOWED_READ_ROOTS` 指定根目录下（分号分隔多根）。

```bash
export AI_TEAM_ALLOWED_READ_ROOTS="D:\agent\fixtures"
```

内置合成项目：`fixtures/sample-python`（含确定性 bug `buggy()` 恒错 +
失败测试 `tests/test_main.py`，供 GT-W01/W02/W07/W09 演示）。

## 运行沙箱任务

```bash
ai-team-os run sandbox_code_fix --project sample-python
# 或
ai-team-os run sandbox_create_readme --project sample-python
```

任务会**暂停在审批点**（`status: paused`），必须经审批后才修改沙箱副本——
不会自动修改任何文件。

## 查看状态

```bash
ai-team-os workspaces
ai-team-os workspace-status <task_id>
ai-team-os approvals <run_id>
ai-team-os diff <run_id>
ai-team-os artifacts <run_id>
```

## 审批与回滚

```bash
ai-team-os approve <run_id> <approval_id>          # 批准并恢复
ai-team-os reject <run_id> <approval_id> --reason "..."  # 拒绝（不应用）
ai-team-os rollback <run_id> --patch <approval_id> --approval <rollback_approval_id>
```

## 排除规则提醒

`.env*`、密钥、缓存、大型构建产物、`.git` 敏感文件不会复制进沙箱；
复制必要 Git 历史时必须清除 remote 与敏感配置。
