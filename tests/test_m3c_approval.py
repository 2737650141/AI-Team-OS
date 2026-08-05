"""007 十九：Approval 测试（9-18）。"""

from __future__ import annotations

from app.core.approval import ApprovalError, ApprovalRequest, ApprovalService


def _svc(ttl: int = 3600) -> ApprovalService:
    return ApprovalService(ttl_seconds=ttl)


def _create(svc: ApprovalService, **kw) -> ApprovalRequest:
    defaults = dict(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="fix bug",
        target_paths=["src/main.py"],
        diff_ref="diff-1",
    )
    defaults.update(kw)
    return svc.create(**defaults)


# ---------- 9. 创建审批 ----------
def test_approval_created() -> None:
    svc = _svc()
    r = _create(svc)
    assert r.approval_id and r.status == "pending"
    assert r.operation_hash
    assert r.expires_at
    assert r.requested_at


# ---------- 10. interrupt 暂停（模型层见图测试） ----------
def test_approval_interrupt_marker() -> None:
    """审批与 interrupt 集成：请求含 run_id/subtask_id 供恢复定位。"""
    svc = _svc()
    r = _create(svc, run_id="r1", subtask_id="s1")
    assert r.run_id == "r1" and r.subtask_id == "s1"


# ---------- 11. 跨进程恢复（服务为进程内；checkpoint 层测试见 runner） ----------
def test_approval_reloadable() -> None:
    """ApprovalRequest 可序列化（checkpoint/API 传输）。"""
    svc = _svc()
    r = _create(svc)
    data = r.model_dump()
    restored = ApprovalRequest(**data)
    assert restored.approval_id == r.approval_id
    assert restored.operation_hash == r.operation_hash


# ---------- 12. 批准 ----------
def test_approve() -> None:
    svc = _svc()
    r = _create(svc)
    decided = svc.decide(r.approval_id, "approved", reason="ok")
    assert decided.status == "approved"
    assert decided.decided_at


# ---------- 13. 拒绝 ----------
def test_reject() -> None:
    svc = _svc()
    r = _create(svc)
    decided = svc.decide(r.approval_id, "rejected", reason="not now")
    assert decided.status == "rejected"


# ---------- 14. 过期 ----------
def test_expired() -> None:
    svc = _svc(ttl=-1)  # 过期时间在过去
    r = _create(svc)
    try:
        svc.decide(r.approval_id, "approved")
        assert False, "应抛 ApprovalError"
    except ApprovalError as exc:
        assert "expired" in str(exc)
    assert r.status == "expired"


# ---------- 15. 操作哈希 ----------
def test_operation_hash() -> None:
    svc = _svc()
    r = _create(svc)
    assert r.operation_hash == ApprovalService.operation_hash_of(
        "apply_patch", "sandbox_apply_patch", "fix bug", ["src/main.py"], None, "diff-1"
    )


# ---------- 16. 参数变化失效（GT-W04） ----------
def test_parameter_change_invalidates() -> None:
    svc = _svc()
    r = _create(svc, parameter_hash=ApprovalService.parameter_hash_of({"a": 1}))
    svc.decide(r.approval_id, "approved")
    # 执行时参数变化 → 哈希不匹配 → 拒绝
    try:
        svc.verify_execution(
            r, parameter_hash=ApprovalService.parameter_hash_of({"a": 2}), target_hash=""
        )
        assert False, "应抛 ApprovalError"
    except ApprovalError as exc:
        assert "parameter hash mismatch" in str(exc)


# ---------- 17. 重复批准幂等 ----------
def test_duplicate_approve_idempotent() -> None:
    svc = _svc()
    r = _create(svc)
    svc.decide(r.approval_id, "approved")
    again = svc.decide(r.approval_id, "approved")  # 幂等
    assert again.status == "approved"


# ---------- 18. 拒绝后不可批准 ----------
def test_rejected_cannot_approve() -> None:
    svc = _svc()
    r = _create(svc)
    svc.decide(r.approval_id, "rejected")
    try:
        svc.decide(r.approval_id, "approved")
        assert False, "应抛 ApprovalError"
    except ApprovalError as exc:
        assert "already rejected" in str(exc)


# ---------- 额外：目标哈希绑定 ----------
def test_target_hash_mismatch_rejected() -> None:
    svc = _svc()
    r = _create(svc, target_hash=ApprovalService.target_hash_of({"src/main.py": "aaa"}))
    svc.decide(r.approval_id, "approved")
    try:
        svc.verify_execution(
            r, parameter_hash="", target_hash=ApprovalService.target_hash_of({"src/main.py": "bbb"})
        )
        assert False, "应抛 ApprovalError"
    except ApprovalError as exc:
        assert "target hash mismatch" in str(exc)
