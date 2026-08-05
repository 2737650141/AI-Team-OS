# 沙箱执行安全（007 九/十/二十一）

## 威胁模型与防护

| 威胁                     | 防护 |
| ------------------------ | ---- |
| 源项目写入               | worktree 副本限定；源哈希校验（GT-W10） |
| 路径穿越                 | `_validate_rel_path`：绝对/../UNC/ADS 拒绝 + resolve 复查 |
| Symlink/Junction 逃逸    | 复制不保留链接；写路径 resolve 后必须仍在 worktree |
| Approval TOCTOU          | 操作/参数/目标三哈希绑定 + 执行前 re-verify |
| Patch 篡改               | 批准绑定 Diff 哈希；篡改 → 确定性拒绝（GT-W04） |
| 命令注入                 | 结构化 argv、禁 shell=True、注入模式拒绝（GT-W06） |
| 可执行文件替换           | 命令白名单映射固定（executable_id → argv 路径不可覆盖） |
| Git hooks                | `core.hooksPath` 指向空目录；不执行源项目 hooks |
| 环境变量泄漏             | 最小环境白名单；代理/凭据变量清除 |
| 子进程继承               | 固定 cwd、最小 env、进程树终止 |
| 网络逃逸                 | 不提供网络型命令；网络命令不可达（GT-W06/42） |
| 输出中的密钥             | stdout/stderr 统一脱敏（redact） |
| 删除与回滚               | 删除进回收区可恢复；回滚需审批 + Artifact |
| Checkpoint 重放重复执行   | 幂等键缓存 + Executor 审批复用 |
| 审批过期                 | TTL 检查（decide/verify 双向） |
| Artifact 篡改             | 内容哈希 + 索引 JSONL |

## 命令执行器（九）

白名单（第一版 10 项）：`python_pytest / python_mypy / python_ruff_check /
python_ruff_format_check / git_status / git_diff / git_diff_check / git_log /
git_add / git_commit`（另加受控 `git_init/git_config(--local)/git_rev_parse/
git_show/git_remote`）。

禁止：pip install、npm install、curl、wget、powershell、cmd、bash、sh、
arbitrary python -c、任意脚本路径、网络命令、系统管理命令。

参数校验：拒绝命令连接符（`; & |`）、重定向（`> <`）、管道、命令替换（`$(...)`）、
环境变量扩展（`${...}`）；参数长度/数量限制；pytest 目标限 worktree 内；
Git 目标限当前沙箱仓库。

运行限制：超时（默认 60s）、输出上限（256KB）、stdout/stderr 脱敏、进程树终止
（Windows taskkill /T）、工作目录固定、最小环境白名单、返回码记录、
运行前 approval、结果形成 CommandReport Artifact。

## 网络隔离（十）

```text
network_isolation=best_effort
```

不提供网络型命令 + 清除代理环境变量 + 命令白名单 + 测试 Fixture + 审计子进程行为。
**当前目录沙箱与命令白名单不是容器或虚拟机级强隔离；不得声称
`network_isolation=guaranteed`。**
