# 真实模型接入指南（docs/operations/REAL_MODEL_SETUP.md）

对应总管令 005 5.1/十六/十八.3/十九/二十一。M3-A 实现。

## 1. 环境变量配置

```bash
# 复制模板（只含占位符，不得放真实密钥）
cp .env.example .env.local            # 本应用不读取 .env 文件！
# API Key 必须通过真实环境变量提供：
export AI_TEAM_MODEL_API_KEY=sk-xxxx          # 真实 Key
export AI_TEAM_MODEL_BASE_URL=https://api.example.com/v1   # 仅 https://
export AI_TEAM_MODEL_DEFAULT=gpt-4o-mini      # 默认模型
export AI_TEAM_MODEL_PLANNER=                 # 可选角色覆盖（缺省继承 default）
export AI_TEAM_MODEL_RESEARCHER=
export AI_TEAM_MODEL_REVIEWER=
export AI_TEAM_MODEL_TIMEOUT_SECONDS=60
export AI_TEAM_MODEL_MAX_RETRIES=2
export AI_TEAM_MODEL_TEMPERATURE=0
export AI_TEAM_MODEL_MAX_OUTPUT_TOKENS=4096
```

> 注意：`ModelProviderSettings` 显式禁用 .env 文件加载（env_file=None），
> API Key 只从进程环境变量读取——避免密钥落入普通配置文件。

## 2. 启用真实模型

```bash
export AI_TEAM_MODEL_ENABLE_REAL=true
```

未启用时 `--model-mode real` 会立即得到明确配置错误（不会静默调用）。
缺 API Key / Base URL 同样明确报错。

## 3. 检查 Provider

```bash
ai-team-os providers            # 查看 provider/角色路由/允许模型（不含 Key）
ai-team-os provider-health      # healthy/disabled/misconfigured 等（不发起真实请求）
curl http://127.0.0.1:8000/providers/health   # API 方式
```

## 4. 运行 dry-run

```bash
ai-team-os run github_compare_team --model-mode real --dry-run
```

显示预计模型调用（按角色）、估算 Token 与预算，不发起任何真实调用。

## 5. 运行真实任务

```bash
ai-team-os run github_compare_team --model-mode real
ai-team-os run vague_goal --model-mode real
ai-team-os status <run_id>
ai-team-os trace <run_id>       # 展示使用量与状态（不含 Key）
```

真实任务仍使用本地 Fixture Evidence，不访问 GitHub/Web。

## 6. 手动集成测试（005 18.3）

仅当 `AI_TEAM_MODEL_ENABLE_REAL=true` 时运行：

```bash
python -m pytest tests/manual/test_real_model_manual.py -m real
```

至少连续运行三次，记录：是否完成、Plan Schema 是否通过、Evidence 引用有效性、
Reviewer 是否通过、是否触发修复、Token/费用/延迟、是否降级、三次输出一致性。
真实测试失败不影响自动测试结论（单独报告）。

## 7. 关闭真实调用

```bash
unset AI_TEAM_MODEL_ENABLE_REAL    # 或 export AI_TEAM_MODEL_ENABLE_REAL=false
```

恢复默认 fake 模式，全部离线可重复。

## 8. 确认没有泄漏 API Key

```bash
# 自动测试覆盖：
python -m pytest tests/test_m3_governance.py tests/test_m3_openai_provider.py -k "api_key or authorization or secret"

# 手动检查：trace/audit/checkpoint 中不得出现 Key
grep -r "sk-" data/ 2>/dev/null || echo "无泄漏"
```

## 9. 安全注意

- 应用仅限本地单用户开发模式，不得暴露到公网。
- Base URL 仅允许 https://，默认拒绝 localhost/内网/云元数据（SSRF 防护）。
- API Key 错误不会自动尝试未知 Provider。
