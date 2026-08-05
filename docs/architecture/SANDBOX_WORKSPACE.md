# 沙箱工作区（007 四）

## 目标

用户代码任务在**任务隔离沙箱副本**中执行，绝不操作真实项目原件。所有写入、命令、
Git 操作只发生在 `runtime/workspaces/<task_id>/` 内。

## 目录结构

```text
runtime/workspaces/<task_id>/
├─ input/         输入快照（只读，回滚基准）
├─ worktree/      Executor 唯一可写目录
├─ artifacts/     报告、Diff、测试结果（Artifact 内容落盘）
├─ backups/       修改前备份 + backup-manifest.jsonl（回滚映射）
├─ trash/         删除回收区（可恢复，不立即物理删除）
├─ logs/          脱敏执行日志
└─ manifest.json  WorkspaceManifest 元数据
```

整个 `runtime/` 被 Git 忽略。

## 输入项目复制（4.2）

用户通过服务端静态配置的项目别名选择输入项目（`AI_TEAM_ALLOWED_READ_ROOTS` +
`--project <alias>`，别名限 `[A-Za-z0-9_-]{1,64}`，客户端不能传任意路径）。

复制流程：

```text
允许项目目录 → 安全校验（别名 + resolve 复查）→ 复制到 worktree（+ input 快照）
→ 记录源文件哈希 → 后续只操作副本
```

默认排除（不复制进沙箱）：

```text
.env*  .venv/  node_modules/  dist/  build/  __pycache__/
.git/  .git/objects/  .git/config  *.pem  *.key  credentials*  secrets*
id_rsa  id_ed25519  id_ecdsa  id_dsa
```

可以复制必要 Git 历史时，必须清除 remote 与敏感配置（本阶段默认不复制 .git）。

## WorkspaceManifest（4.3）

`workspace_id / task_id / source_project_alias / source_root_hash / worktree_path /
created_at / file_count / total_bytes / excluded_paths / git_initialized /
current_revision / status`。

## 配额

- 大项目配额：50 MB、20000 文件（超出明确报错）。
- 源项目哈希在复制前记录；`verify_source_unchanged` 用于 GT-W10 源保护验证。

## 隔离等级声明

**当前目录沙箱不是容器或虚拟机级强隔离。** 进程与文件系统隔离依赖路径校验、
命令白名单与运行目录限定；无 Docker/OS 沙箱时不得声称容器级安全。
