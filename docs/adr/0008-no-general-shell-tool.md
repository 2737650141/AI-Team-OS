# ADR-0008：不提供通用 Shell 工具（no general shell tool）

- 状态：已采纳（007 九）
- 日期：M3-C

## 背景

通用 Shell 工具是命令注入与逃逸的高危面；M3-C 需要执行测试与 Git 命令，
但不能引入任意命令执行能力。

## 决策

不暴露通用 Shell 工具：

- 绝不使用 `shell=True`，不接受整段命令字符串。
- 只接受结构化 `executable_id + args[] + cwd_alias + timeout_seconds +
  environment_profile`。
- 第一版静态白名单 10 命令（pytest/mypy/ruff/git 只读+add+commit 等）；
  executable 路径由映射固定，用户/LLM 不能覆盖。
- 参数校验拒绝连接符/重定向/管道/命令替换/环境变量扩展/任意绝对路径。
- 运行限制：超时、输出上限、脱敏、进程树终止、固定 cwd、最小环境、返回码记录。

## 后果

- 新增命令必须显式加入白名单并审查（安全可控）。
- 网络命令不可达；`network_isolation=best_effort`（非强隔离，文档声明）。
