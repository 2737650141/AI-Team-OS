# GitHub 只读工具设置（docs/operations/GITHUB_TOOL_SETUP.md）

对应总管令 006 六。M3-B 实现。

## 1. Token（可选）

```bash
export AI_TEAM_GITHUB_TOKEN=ghp_xxx   # 仅本机环境变量
```

- 无 Token：允许公开仓库（受 GitHub 未认证限流 60 次/小时）。
- 有 Token：提高限流（5000 次/小时）并允许 search_code。
- Token 只存在于 GitHubClient 私有字段，不进入状态/日志/Evidence/回执。

## 2. 可用工具

github_repo_info / github_read_file / github_list_directory / github_list_commits /
github_list_issues / github_get_issue / github_list_pull_requests / github_get_pull_request /
github_search_repositories / github_search_code——全部只读（仅 GET），仅 researcher 角色可用。

## 3. 使用

```bash
ai-team-os tools                          # 列出全部只读工具
ai-team-os tool-info github_repo_info
ai-team-os run github_real_compare --model-mode real   # 真实模型 + 真实 GitHub 只读
```

仓库标识接受 `owner/repo` 或 `https://github.com/owner/repo`；非 GitHub 域名与
路径穿越被确定性拒绝。

## 4. 限流与错误

401（Token 无效）/ 403（无权限或限流用尽）/ 404（不存在）/ 429（限流）分类明确，
错误消息为安全消息（不含原始响应体）。
