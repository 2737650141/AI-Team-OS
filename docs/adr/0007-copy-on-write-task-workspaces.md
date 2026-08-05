# ADR-0007：写时复制任务工作区（copy-on-write task workspaces）

- 状态：已采纳（007 四）
- 日期：M3-C

## 背景

M3-C 引入受控写入与执行闭环。直接操作真实项目原件风险不可接受；必须保证
任何写入/命令/Git 操作只影响隔离副本，且源项目可验证不变。

## 决策

每个任务创建独立工作区 `runtime/workspaces/<task_id>/`：

- `input/`：输入项目只读快照（回滚基准）。
- `worktree/`：Executor 唯一可写目录（写时复制：创建时从源项目复制）。
- `artifacts/`、`backups/`、`logs/`、`manifest.json`。

输入项目经服务端静态配置的别名选择；复制时默认排除敏感文件
（`.env*`/密钥/缓存/构建产物/`.git` 敏感文件）；复制前记录源哈希。

## 后果

- 源项目绝对不变（GT-W10 哈希校验）。
- 回滚可基于 input 快照重建 worktree。
- 排除规则可能漏掉新敏感形态 → 维护 `SENSITIVE_*` 清单与打包扫描共用。
