# ADR-0001：ResumePayload 兼容层（规避 Command(resume=None) 上游缺陷）

- 状态：**已接受**（2026-08-05，总管令 003-A 三）
- 相关文档：`docs/review/M0_M1_EVIDENCE.md` §5（上游缺陷证据）

## 背景

跨进程恢复演示（M0_M1_EVIDENCE A-04）复现了 langgraph 1.2.10 的上游缺陷：

```text
Command(resume=None) 触发 UnboundLocalError:
cannot access local variable 'resume_is_map'
（langgraph/pregel/_loop.py:927）
```

即：当恢复值缺失（None）时，LangGraph 内部会异常。这是官方库 bug，不是本项目代码问题。

## 决策

1. 项目恢复接口**不允许把 None 作为恢复值**。
2. 定义统一恢复值 `ResumePayload`（`app/core/resume.py`）：
   - `action: str`（默认 `"continue"`，必填且非 None，经 Pydantic `model_validator` 校验）；
   - 恢复前执行 Schema 校验（`ResumePayload.model_validate` 路径由 Pydantic 强制）。
3. `resume_task(run_id, payload=None)` 在未传 payload 时使用默认
   `ResumePayload(action="continue")`——**任何代码路径都不会产生 `Command(resume=None)`**。
4. 恢复时从 checkpoint 读取的 TaskState 先经 `TaskState.model_validate` 做 Schema 校验
   （未知状态值 / schema 版本不匹配即拒绝，见 ADR-0002 与 003-A 四）。
5. **不修改 LangGraph 源码**；以本项目适配层隔离上游行为。

## 影响

- 恢复调用统一携带 `ResumePayload`；暂停点（graph 的 pause 节点）恢复后返回 completed。
- 上游修复此缺陷后，可移除默认值替换逻辑，但接口签名保持不变（向后兼容）。

## 回归测试

- `tests/test_resume_integration.py::test_resume_payload_rejects_none_action` — None 恢复值拒绝
- `tests/test_resume_integration.py::test_resume_missing_run_rejected` — 缺失 run 拒绝
- `tests/test_resume_integration.py::test_cross_process_pause_resume` — 真实跨进程恢复全链路
