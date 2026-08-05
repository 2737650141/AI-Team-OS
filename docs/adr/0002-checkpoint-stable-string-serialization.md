# ADR-0002：Checkpoint 状态序列化采用稳定字符串（003-A 四）

- 状态：**已接受**（2026-08-05，总管令 003-A 四）
- 相关文档：`docs/planning/STATE_MODEL.md`

## 背景

TaskStatus 等枚举类型在 Checkpoint（msgpack 序列化）与跨进程反序列化中存在类型兼容风险；
宽松环境变量（允许任意未知 msgpack 类型）不可作为长期方案。

## 决策

1. **Checkpoint 状态中保存稳定字符串值**：`TaskState.current_status`、`failure_code`、
   `paused_from_status` 使用 `TaskStatusStr` / `FailureCodeStr`
   （`Annotated[str, AfterValidator(枚举成员校验)]`）。
2. **Pydantic 边界再转换为 Enum**：需要枚举语义处（状态机、API）以 `TaskStatus(value)` 转换；
   未知字符串在反序列化时被 Pydantic 拒绝（fail-fast）。
3. 不依赖允许任意未知 msgpack 类型的宽松环境变量。

## 影响

- checkpoint 中保存的是稳定字符串（`"completed"` 而非枚举实例），跨版本、跨进程可读。
- 未知状态值（如未来版本写入了 `"bogus"`）在恢复时被拒绝，避免静默错误状态。

## 回归测试

- `tests/test_checkpoint.py::test_checkpoint_holds_stable_string` — checkpoint 中为 str
- `tests/test_checkpoint.py::test_unknown_status_rejected` — 未知值拒绝
- `tests/test_checkpoint.py::test_checkpoint_version_mismatch_rejected` — schema 版本不兼容拒绝
