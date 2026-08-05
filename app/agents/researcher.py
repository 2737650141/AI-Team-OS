"""DeterministicFakeResearcher（004 九）：只允许只读 Fixture 工具，结构化输出。

场景：
- repository_research：fixture_repo_lookup（github_compare 的 s1/s2）。
- conflicting_sources_research：fixture_source_lookup（GT-05 多来源矛盾核查）。
- summarize：汇总子任务（s3），基于其他子任务的 ExecutionResult，不调用工具。

约束：无 evidence 的 Claim 必须标记未验证（unverified_items）；不写 final_result；
不直接调用 Reviewer；工具执行仍经 Tool Gateway（唯一执行入口）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.schemas import Claim, ExecutionResult
from app.core.state import SubtaskState
from app.gateway.audit import redact
from app.gateway.tool_gateway import ToolGateway


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeResearcher:
    def __init__(self, tool_gateway: ToolGateway) -> None:
        self._gw = tool_gateway

    def run(
        self,
        subtask: SubtaskState,
        all_subtasks: list[SubtaskState],
        review_scenario: str | None = None,
    ) -> ExecutionResult:
        # role 按子任务细分（"researcher:<subtask_id>"），供 Reviewer 按子任务统计工具调用
        role = f"researcher:{subtask.subtask_id}"
        claims: list[Claim] = []
        evidence_refs: list[str] = []
        unverified: list[str] = []

        for ref in subtask.input_refs:
            if ref.startswith("fixture_repo_lookup:"):
                repo = ref.split(":", 1)[1]
                result = self._gw.invoke("fixture_repo_lookup", {"repo_name": repo}, role=role)
                if result.ok:
                    data = result.data
                    eid = result.evidence_id or (
                        self._gw.evidence[-1]["id"] if self._gw.evidence else ""
                    )
                    evidence_refs.append(eid)
                    claims.extend(
                        [
                            Claim(
                                claim_id=f"{subtask.subtask_id}-c-license",
                                text=f"{repo} 许可证为 {data['license']}",
                                evidence_ids=[eid],
                                confidence=0.95,
                            ),
                            Claim(
                                claim_id=f"{subtask.subtask_id}-c-stars",
                                text=f"{repo} stars={data['stars']}",
                                evidence_ids=[eid],
                                confidence=0.95,
                            ),
                            Claim(
                                claim_id=f"{subtask.subtask_id}-c-active",
                                text=f"{repo} 最近提交 {data['pushed_at']}，处于活跃维护",
                                evidence_ids=[eid],
                                confidence=0.9,
                            ),
                        ]
                    )
                else:
                    unverified.append(
                        f"fixture_repo_lookup({repo}) 失败: {redact(str(result.error))}"
                    )
            elif ref.startswith("fixture_source_lookup:"):
                source_id = ref.split(":", 1)[1]
                result = self._gw.invoke(
                    "fixture_source_lookup", {"source_id": source_id}, role=role
                )
                if result.ok:
                    data = result.data
                    eid = result.evidence_id or (
                        self._gw.evidence[-1]["id"] if self._gw.evidence else ""
                    )
                    evidence_refs.append(eid)
                    claim_id = f"{subtask.subtask_id}-c-{source_id}"
                    claims.append(
                        Claim(
                            claim_id=claim_id,
                            text=f"[来源 {source_id}] {data['claim']}（置信度 "
                            f"{data['confidence']}）",
                            evidence_ids=[eid],
                            confidence=float(data["confidence"]),
                        )
                    )
                    # 矛盾检测（GT-05）：langgraph 有两个相反来源时显式标记
                    if source_id == "langgraph_abandoned":
                        unverified.append(
                            "langgraph 维护状态来源矛盾：langgraph_maintained(0.9) 与 "
                            "langgraph_abandoned(0.3) 结论相反，需人工核实"
                        )
                else:
                    unverified.append(
                        f"fixture_source_lookup({source_id}) 失败: {redact(str(result.error))}"
                    )
            elif ref in {s.subtask_id for s in all_subtasks}:
                dep = next(s for s in all_subtasks if s.subtask_id == ref)
                if dep.execution_result:
                    for claim in dep.execution_result.claims:
                        claims.append(
                            Claim(
                                claim_id=f"{subtask.subtask_id}-agg-{claim.claim_id}",
                                text=f"（汇总自 {ref}）{claim.text}",
                                evidence_ids=claim.evidence_ids,
                                confidence=claim.confidence,
                            )
                        )
                    evidence_refs.extend(dep.execution_result.evidence_refs)
                    unverified.extend(dep.execution_result.unverified_items)
            else:
                unverified.append(f"未知输入引用: {ref}")

        # 返工场景（GT-11 review_reject_once_then_pass）：首次产出时 s3 的汇总 claim 不带证据，
        # 确定性 Reviewer 将拒绝；返工（rework_count>0）后补全。
        if (
            subtask.subtask_id == "s3"
            and subtask.rework_count == 0
            and review_scenario == "review_reject_once_then_pass"
        ):
            claims = [
                Claim(
                    claim_id="s3-c-skip",
                    text="汇总结论（未附证据）",
                    evidence_ids=[],
                    confidence=0.0,
                )
            ]

        summary = f"{subtask.title}：完成（claims={len(claims)}, evidence={len(evidence_refs)})"
        return ExecutionResult(
            subtask_id=subtask.subtask_id,
            summary=summary,
            artifacts=[f"report:{subtask.subtask_id}"],
            claims=claims,
            evidence_refs=evidence_refs,
            unverified_items=unverified,
            ts=_now(),
        )
