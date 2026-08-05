"""DeterministicFakePlanner（004 八）：确定性计划生成，不调用外部工具。

场景（含负面场景，供 Plan 校验测试）：github_compare_plan / parallel_three_topics /
invalid_cycle_plan / over_budget_plan / unknown_agent_plan
"""

from __future__ import annotations

from app.core.schemas import Plan, SubtaskSpec


def _repo_subtask(sid: str, repo: str, deps: list[str] | None = None) -> SubtaskSpec:
    return SubtaskSpec(
        subtask_id=sid,
        title=f"获取 {repo} Fixture 信息",
        objective=f"读取 {repo} 仓库元数据并产出结构化报告",
        dependencies=deps or [],
        assigned_role="researcher",
        input_refs=[f"fixture_repo_lookup:{repo}"],
        expected_output=f"{repo} 元数据报告（license/stars/活跃度）",
        acceptance_criteria=["包含 license", "包含 stars", "包含活跃度", "每条结论带 evidence"],
        required_tools=["fixture_repo_lookup"],
        token_budget=600,
        tool_call_budget=2,
    )


def make_plan(scenario: str, goal: str, task_token_budget: int = 10000) -> Plan:
    """按场景生成 Plan。Planner 不调用外部工具（004 八）。"""
    if scenario == "github_compare_plan":
        return Plan(
            goal=goal,
            subtasks=[
                _repo_subtask("s1", "langgraph"),
                _repo_subtask("s2", "crewai"),
                SubtaskSpec(
                    subtask_id="s3",
                    title="汇总对比要求",
                    objective="基于 s1/s2 结果输出对比矩阵与选型建议",
                    dependencies=["s1", "s2"],
                    assigned_role="researcher",
                    input_refs=["s1", "s2"],
                    expected_output="对比矩阵报告（≥8 维度 + 选型建议）",
                    acceptance_criteria=["含 ≥8 对比维度", "每维度有 evidence", "含选型建议"],
                    required_tools=[],
                    token_budget=600,
                    tool_call_budget=0,
                ),
            ],
        )
    if scenario == "parallel_three_topics":
        return Plan(
            goal=goal,
            subtasks=[
                SubtaskSpec(
                    subtask_id="t1",
                    title="主题 A 来源核查",
                    objective="读取来源 A 并产出 Claim",
                    dependencies=[],
                    assigned_role="researcher",
                    input_refs=["fixture_source_lookup:langgraph_maintained"],
                    expected_output="主题 A 报告",
                    acceptance_criteria=["含证据"],
                    required_tools=["fixture_source_lookup"],
                    token_budget=500,
                    tool_call_budget=2,
                ),
                SubtaskSpec(
                    subtask_id="t2",
                    title="主题 B 来源核查",
                    objective="读取来源 B 并产出 Claim",
                    dependencies=[],
                    assigned_role="researcher",
                    input_refs=["fixture_source_lookup:langgraph_abandoned"],
                    expected_output="主题 B 报告",
                    acceptance_criteria=["含证据"],
                    required_tools=["fixture_source_lookup"],
                    token_budget=500,
                    tool_call_budget=2,
                ),
                SubtaskSpec(
                    subtask_id="t3",
                    title="主题 C 来源核查",
                    objective="读取来源 C 并产出 Claim",
                    dependencies=[],
                    assigned_role="researcher",
                    input_refs=["fixture_source_lookup:crewai_active"],
                    expected_output="主题 C 报告",
                    acceptance_criteria=["含证据"],
                    required_tools=["fixture_source_lookup"],
                    token_budget=500,
                    tool_call_budget=2,
                ),
            ],
        )
    if scenario == "sandbox_code_fix_plan":
        # 007 GT-W02/W07：读失败测试 Evidence → Executor 修复补丁
        return Plan(
            goal=goal,
            subtasks=[
                SubtaskSpec(
                    subtask_id="s1",
                    title="读取失败测试 Evidence",
                    objective="读取 worktree 中测试与源码，确认确定性 bug",
                    dependencies=[],
                    assigned_role="researcher",
                    input_refs=[
                        "local_read_text:src/main.py",
                        "local_read_text:tests/test_main.py",
                    ],
                    expected_output="bug 位置与失败原因",
                    acceptance_criteria=["识别 buggy() 恒错"],
                    required_tools=["local_read_text"],
                    token_budget=2000,
                    tool_call_budget=3,
                ),
                SubtaskSpec(
                    subtask_id="s2",
                    title="应用修复补丁",
                    objective="生成最小修复 PatchProposal，经审批后应用并运行 pytest",
                    dependencies=["s1"],
                    assigned_role="executor",
                    input_refs=[],
                    expected_output="patch 应用成功且 pytest 通过",
                    acceptance_criteria=["buggy() 返回 True", "pytest 通过", "仅修改 src/main.py"],
                    required_tools=["sandbox_apply_patch"],
                    token_budget=2000,
                    tool_call_budget=2,
                ),
            ],
        )
    if scenario == "sandbox_create_readme_plan":
        # 007 GT-W01：README 追加段落
        return Plan(
            goal=goal,
            subtasks=[
                SubtaskSpec(
                    subtask_id="s1",
                    title="新增 README 段落",
                    objective="在沙箱 worktree 的 README.md 追加确定性段落",
                    dependencies=[],
                    assigned_role="executor",
                    input_refs=[],
                    expected_output="README.md 追加段落",
                    acceptance_criteria=["段落存在", "源项目不变"],
                    required_tools=["sandbox_apply_patch"],
                    token_budget=2000,
                    tool_call_budget=2,
                ),
            ],
        )
    if scenario == "invalid_cycle_plan":
        return Plan(
            goal=goal,
            subtasks=[
                _repo_subtask("c1", "langgraph", deps=["c2"]),
                _repo_subtask("c2", "crewai", deps=["c1"]),
            ],
        )
    if scenario == "over_budget_plan":
        return Plan(
            goal=goal,
            subtasks=[
                SubtaskSpec(
                    subtask_id="o1",
                    title="超预算子任务 1",
                    objective="x",
                    dependencies=[],
                    assigned_role="researcher",
                    input_refs=[],
                    expected_output="报告",
                    acceptance_criteria=["a"],
                    required_tools=["fixture_repo_lookup"],
                    token_budget=4000,
                    tool_call_budget=1,
                ),
                SubtaskSpec(
                    subtask_id="o2",
                    title="超预算子任务 2",
                    objective="x",
                    dependencies=[],
                    assigned_role="researcher",
                    input_refs=[],
                    expected_output="报告",
                    acceptance_criteria=["a"],
                    required_tools=["fixture_repo_lookup"],
                    token_budget=4000,
                    tool_call_budget=1,
                ),
            ],
        )
    if scenario == "unknown_agent_plan":
        return Plan(
            goal=goal,
            subtasks=[
                SubtaskSpec(
                    subtask_id="u1",
                    title="未知角色子任务",
                    objective="x",
                    dependencies=[],
                    assigned_role="ghost_agent",
                    input_refs=[],
                    expected_output="报告",
                    acceptance_criteria=["a"],
                    token_budget=500,
                    tool_call_budget=1,
                )
            ],
        )
    raise ValueError(f"unknown plan scenario: {scenario}")
