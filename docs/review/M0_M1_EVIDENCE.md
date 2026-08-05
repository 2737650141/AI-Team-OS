# M0–M1 源码证据封板（EVIDENCE SEAL）

> 文档状态：证据封板（主管令 003，任务 A）
> 封板时间：2026-08-05
> 封板 HEAD：`50e0663`（`fix: security review - redact result summaries, block all non-readonly tools, json idempotency keys`）
> 基线（本审计会话开始时 HEAD）：`dc07e1b`
> 内核版本：**Experimental Control Kernel v0.1**

本文档与 `artifacts/review/m0-m1/` 下的原始输出共同构成 M0–M1 证据封板。
所有原始输出均**逐字保存**，未删除 Warning，未伪造结果。

---

## 1. 证据文件索引

| 编号 | 证据 | 文件 | 结论 |
| -- | -- | -- | -- |
| A-01 | 项目目录树 | `artifacts/review/m0-m1/tree.txt` | 完成 |
| A-02 | Python 版本 | `python-version.txt` | Python 3.11.9 |
| A-02 | pytest | `pytest.txt` | **22 passed, 1 warning** |
| A-02 | ruff check | `ruff-check.txt` | **All checks passed**（全树） |
| A-02 | ruff format | `ruff-format.txt` | **3 files would be reformatted**（详见 §3.3） |
| A-02 | mypy | `mypy.txt` | **Success: no issues in 16 source files** |
| A-03 | CLI 运行 | `cli-run.txt` | completed；task `2a43533f6eaa` |
| A-04 | Checkpoint 跨进程恢复 | `cli-resume.txt` | 两进程恢复成功，工具未重跑 |
| A-05 | API 演示 | `api-demo.txt` | /health 200、POST /tasks 200、GET 200、404 |
| A-06 | Git 证据 | `git-status.txt` / `git-remote.txt` / `git-log.txt` / `git-diff-check.txt` / `git-commit-stats.txt` | 见 §6 |
| A-07 | 并行提交来源说明 | 本文档 §7 | 4 个并行提交已分析 |
| A-08 | 源码审阅包 | `artifacts/review/ai-team-os-m0-m1-source.zip` | 已生成 |

---

## 2. 运行环境

- OS：Windows（win32）；shell 统一 `PYTHONIOENCODING=utf-8`
- Python：3.11.9（`.venv/Scripts/python.exe`）
- 关键依赖（`importlib.metadata`）：
  - langgraph **1.2.10**
  - langgraph-checkpoint-sqlite **3.1.1**
  - fastapi 0.141.1
  - pydantic 2.13.4
  - pytest 8.4.2 / ruff 0.16.1 / mypy 1.20.2

## 3. 工具链原始输出与 Warning 解释

### 3.1 pytest（`pytest.txt`）
`python -m pytest -vv` → **22 passed**。

唯一 Warning：
```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated;
install `httpx2` instead.  (fastapi/testclient.py:1)
```
**解释**：来自 FastAPI 内部 `starlette.testclient`，与本项目代码无关。fastapi 0.141.1 的 TestClient 底层
仍用 `httpx`，Starlette 建议迁移 `httpx2`。属上游依赖演进提示，不阻塞 M1。

### 3.2 ruff check（`ruff-check.txt`）
`python -m ruff check .` → **All checks passed**。覆盖 `app/`、`tests/`、`artifacts/review/m0-m1/*.py`（证据脚本）。

### 3.3 ruff format（`ruff-format.txt`）
`python -m ruff format --check app/ tests/` → **3 files would be reformatted**：
- `app/core/budget.py:70` — `raise BudgetExceeded("usage", ...)` 单行化（格式偏好）
- `app/core/state.py:77` — `budget_usage` Field 单行化（格式偏好）
- `tests/test_audit.py:34` — PEM 字符串字面量单行化（格式偏好）

**解释**：三项均为**纯格式偏好差异**（多行可读性写法 vs ruff 的单行压缩偏好），无语法/逻辑问题。
封板选择**保留现有可读性写法**，不改格式，避免在"禁止重构"期间引入噪音 diff。已在
`M2_REUSE_FIRST_PLAN.md` 列入 `ruff format` 收尾项（非阻塞）。

### 3.4 mypy（`mypy.txt`）
`python -m mypy app` → **Success: no issues found in 16 source files**。

## 4. A-03 CLI 运行证据（`cli-run.txt`）
```
task_id: 2a43533f6eaa
status:  completed
result:  [fake:fake] github_compare_mock
usage:   {'tokens': 131.0, 'cost': 0.0}
calls:   1
```
- run_id（最终 checkpoint）：`1f19066e-f6c0-6afc-8001-36b350b38521`
- 执行节点：`agent`（单节点图）；Fake Model 场景：`DeterministicFakeModel(responses={})` 未命中映射，回退模板
- 工具名称：无（M1 单节点图不调用 ToolGateway）
- token 使用：131 = 100 input + 31 output（与 audit `model_call` 一致）
- 审计日志路径：`data/audit.jsonl`；Checkpoint 路径：`data/checkpoints.db`
- 备注：`budget_usage` 字段未由节点回写，为 M1 已知简化（预算记账在 ModelGateway 内存侧）

## 5. A-04 Checkpoint 跨进程恢复证据（`cli-resume.txt`）

> 严格按令要求：**两个独立 OS 进程** + 真实 SQLite checkpoint，非单元测试模拟。

- 进程 A（`resume_part1.py`）：创建任务 `task-resume-demo-001`，`research` 节点执行并写入
  `tool_calls=1`、`budget_usage={tokens:100, cost:0.001}`，`analyze` 节点 `interrupt()` 暂停后**进程退出**。
- 进程 B（`resume_part2.py`）：新进程从 `resume-demo.db` 恢复。
  - task_id 不变：`task-resume-demo-001`
  - tool_calls **不清零**：恢复前 1 条 → 最终 1 条
  - budget_usage **不清零**：`{tokens:100, cost:0.001}` 保持
  - checkpoint 链 step 递增：`-1 → 0 → 1 → 2 → 3`（`source=input/loop`）
  - **已成功执行的工具未再次运行**：research 节点内嵌 `RESEARCH-RERUN` 标记最终数量 = 0
  - 最终状态：`completed`；`final_result=分析完成(decision=go): 跨进程恢复演示`

**发现的上游缺陷（登记到 reuse 审计）**：`langgraph 1.2.10` 中 `Command(resume=None)` 会触发
`UnboundLocalError: cannot access local variable 'resume_is_map'`（`langgraph/pregel/_loop.py:927`）。
恢复必须传实际值（`Command(resume="go")`）。这是官方库 bug，非本项目代码问题。

## 6. A-06 Git 证据（`git-*.txt`）

- `git status --short`：仅 `?? artifacts/`（本审计产出，未入库）
- `git remote -v`：**无远程**（本地仓库，未配置 origin —— 符合"不推送"禁令）
- `git log`：8 个提交，线性 `main`，见 §7 逐个说明
- `git diff --check`：无空白错误
- `git show --stat <每个提交>`：见 `git-commit-stats.txt`

## 7. A-07 并行提交来源说明（关键）

### 7.1 时间线
| Commit | 时间(committer, +0800) | 说明 |
| -- | -- | -- |
| `f3b7099` | 2026-08-04 21:25 | docs：Phase 0 架构（本审计会话前已存在） |
| `63d300b` | 2026-08-04 21:33 | M0 骨架 + M1 最小执行内核（本会话前已存在） |
| `e9073d1` | 2026-08-04 21:37 | requires_approval + 审计脱敏加强（本会话前已存在） |
| `dc07e1b` | 2026-08-04 21:41 | 审计脱敏 JSON-aware + PEM 整块（**本会话开始时 HEAD**） |
| `1580c9c` | 2026-08-05 08:19 | **并行会话** feat: m0-m1 kernel（model_gateway 增 estimate_cost；误提交 .reasonix） |
| `f67843d` | 2026-08-05 08:20 | **并行会话** chore: untrack .reasonix（撤回 1580c9c 的误提交） |
| `b5d29fa` | 2026-08-05 08:23 | **并行会话** fix: review findings（estimate_cost、幂等、脱敏、conn close、CLI 校验） |
| `50e0663` | 2026-08-05 08:27 | **并行会话** fix: security review（非只读一律拦截、结果脱敏、JSON 幂等键） |

### 7.2 逐提交来源审查
| Commit | 创建者/来源 | 改动文件 | 改动目的 | 人工复核 | 是否覆盖另一会话 | 重复/冲突/非预期 |
| -- | -- | -- | -- | -- | -- | -- |
| `1580c9c` | Reasonix 并行会话 | `.reasonix/*`（误提交）、`app/gateway/model_gateway.py` | 声称"m0-m1 kernel"，实际只新增 `estimate_cost` 接口 | 未发现人工复核痕迹 | **是**：在 `dc07e1b` 之上重放 M1 主体（模型网关接口演进） | **重复**：与已存在 M1 内容重叠；`.reasonix` 为**非预期误提交**（下个提交立即撤回） |
| `f67843d` | Reasonix 并行会话 | `.gitignore`（+3 行 `.reasonix/`）、删除 1580c9c 的 `.reasonix` | 撤回宿主状态目录 | 否 | 否 | 修正性提交，方向正确 |
| `b5d29fa` | Reasonix 并行会话 | `cli.py`、`budget.py`、`model_gateway.py`、`tool_gateway.py`、`runner.py` | review findings：走 `estimate_cost` 接口、blocked 幂等、args 脱敏、conn close、CLI 预算校验 | 否（无 review 记录） | 部分：`tool_gateway.py` 与 `dc07e1b`/`e9073d1` 已有改动叠加 | **非预期**：`conn.close()` 修正了 `runner.py` 在 `dc07e1b` 中缺失的 finally 关闭（合理）；`budget.py` 修正 used 报告口径（合理） |
| `50e0663` | Reasonix 并行会话 | `tool_gateway.py`（25 行）、`tests/test_tool_gateway.py`（+31 行） | security review：**非只读工具一律拦截**（防错标）、result_summary/summary 脱敏、JSON 幂等键 | 否（无 review 记录） | **是**：重写了 `tool_gateway.py` 的拦截分支与幂等键，与 `dc07e1b`/`e9073d1` 对同一函数的改动重叠 | **冲突风险**：`dc07e1b`/`e9073d1` 的 tool_gateway 改动被 1580c9c 基线重放后又被 50e0663 覆盖式改写；最终语义合并为"更严拦截 + 更全脱敏"，**功能上等价或更严**，无回退 |

### 7.3 结论
1. **存在并行会话提交**：4 个提交在 2026-08-05 08:19–08:27 出现（本审计 08:36 开始前完成）。
   时间与 git 树均为线性 `main`，未形成分支分叉。
2. **重复与误提交**：`1580c9c` 重复了 M1 主体并误提交 `.reasonix`，`f67843d` 立即修正。无遗留 `.reasonix` 入库（已验证 `git ls-files | grep reasonix` 为空）。
3. **非预期改动**：`b5d29fa` 修正 `runner.py` 连接关闭与 `budget.py` 口径、`50e0663` 收紧非只读拦截，均**未在命令/文档中预告**，属并行会话自行决定。功能上均合理且更安全。
4. **覆盖审查**：`dc07e1b`/`e9073d1` 的 tool_gateway 与 audit 改动被并行会话并入并强化，**未发生功能回退**。审计脱敏（`audit.py` 的 `_SECRET_RE`）在 `50e0663` 中完整保留。
5. **风险**：并行提交缺乏 review 记录与任务号关联；`1580c9c` 的重复重放表明并行会话之间**缺少同步机制**。建议总管在 M2 引入"单写者"提交纪律或 PR review gate（列入 M2 治理项，非本轮改动）。

**结论：并行提交来源已说明；未发现破坏性覆盖、重复代码或非预期行为进入当前内核。测试全绿验证了功能等价。**

## 8. A-08 源码审阅包
`artifacts/review/ai-team-os-m0-m1-source.zip` 已生成，包含：
- `app/`、`tests/`、`docs/`、`scripts/`
- `pyproject.toml`、`.gitignore`、`.env.example`、`README.md`、`.github/workflows/ci.yml`
- 上述全部证据文件（`*.txt`、`M0_M1_EVIDENCE.md`、复用审计三文档、M2 方案）
- 上游复用研究工作流原始结果：`artifacts/review/m0-m1/upstream-workflow-result.json`（6 仓库源码级审计 + LangGraph 深度对比 + 综合结论）
- **排除**：`.venv`、`.reasonix`、`data/`（含 SQLite 运行库）、`.env`、API Key、`*.db`、`__pycache__`、各缓存

---

## 9. 复现说明

| 项 | 命令 | 复现性 |
| -- | -- | -- |
| pytest | `.venv/Scripts/python -m pytest -vv` | 22 passed（HEAD=50e0663） |
| ruff check | `.venv/Scripts/python -m ruff check .` | All checks passed |
| ruff format | `.venv/Scripts/python -m ruff format --check app/ tests/` | 3 files（格式偏好，见 §3.3） |
| mypy | `.venv/Scripts/python -m mypy app` | Success（16 files） |
| CLI | `.venv/Scripts/ai-team-os run github_compare_mock --budget-tokens 5000` | 见 cli-run.txt |
| 跨进程恢复 | `python artifacts/review/m0-m1/resume_part1.py <run_id> <db>` → `resume_part2.py` | 见 cli-resume.txt |
| API | `python artifacts/review/m0-m1/api_demo.py` | 见 api-demo.txt |

*证据封板完成。原始输出逐字保存于 `artifacts/review/m0-m1/`。*

---

## 9. 003-A 修正复验（M2 准入，2026-08-05）

### 9.1 格式封板（003-A 一）
`ruff format app tests` → 3 files reformatted（budget.py / state.py / test_audit.py，纯格式偏好）；
`ruff format --check`、`ruff check`、`mypy app`（17 files）全部通过；`pytest -vv` → **27 passed**。

### 9.2 Runtime 恢复接入（003-A 二）
恢复能力已从实验脚本（本文件 §5 的 `resume_part1.py/part2.py`）迁入真实 Runtime：

- `app/runner.py`：`run_task`（支持 `--pause-after agent` 节点边界暂停，`update_state` 写回 paused）/
  `resume_task`（checkpoint 读取 → 重建 BudgetController 与 ToolGateway 历史 → `Command(resume=ResumePayload)` 继续）/
  `status_task`（只读快照）。
- `app/graph.py`：pause 节点（`interrupt` 在节点边界暂停，恢复后置 completed）。
- `app/cli.py`：`ai-team-os run github_compare_mock --pause-after agent` / `resume <run_id>` / `status <run_id>`。
- 跨进程集成测试：`tests/test_resume_integration.py::test_cross_process_pause_resume`
  （subprocess 真实两/三进程）断言 12 项不变性：task_id/run_id 不变、token_usage 不清零、
  tool_call_count 不清零且已成功工具不重复执行、checkpoint step 递增、幂等键有效、最终 completed。

### 9.3 ResumePayload 兼容层（003-A 三）
`app/core/resume.py` 定义 ResumePayload（action 禁止 None）；恢复前 Schema 校验；
任何路径不产生 `Command(resume=None)`（上游缺陷见 §5）。ADR：`docs/adr/0001`。

### 9.4 Checkpoint 类型兼容（003-A 四）
`TaskState` 状态字段改稳定字符串 + 枚举成员校验（`TaskStatusStr`/`FailureCodeStr`）；
保存后新进程反序列化、未知状态值拒绝、schema 版本不兼容三类测试齐备。ADR：`docs/adr/0002`。

### 9.5 复验基线
- pytest：**27 passed**（含跨进程恢复与兼容测试）
- mypy：17 source files，no issues
- ruff：check All checks passed；format 26 files already formatted
- git：工作区干净，未配置 remote，未 push
