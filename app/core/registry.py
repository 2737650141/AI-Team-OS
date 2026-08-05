"""Agent Registry（004 五）：确定性代码管理，LLM 不得创建新角色或修改工具白名单。"""

from __future__ import annotations

from app.core.schemas import AgentSpec


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        self._agents[spec.agent_id] = spec

    def get(self, agent_id: str) -> AgentSpec:
        if agent_id not in self._agents:
            raise KeyError(f"unknown agent: {agent_id}")
        return self._agents[agent_id]

    def by_role(self, role_type: str) -> list[AgentSpec]:
        return [a for a in self._agents.values() if a.role_type == role_type and a.enabled]

    def is_enabled(self, agent_id: str) -> bool:
        return self.get(agent_id).enabled

    def all(self) -> list[AgentSpec]:
        return list(self._agents.values())


def default_registry() -> AgentRegistry:
    """预注册五种核心角色类型（004 五）。

    Executor 只注册（enabled=False）：disabled Agent 不可被派发，
    第一条研究链路仅运行 Supervisor / Planner / Researcher / Reviewer。
    """
    registry = AgentRegistry()
    registry.register(
        AgentSpec(
            agent_id="supervisor",
            role_type="supervisor",
            display_name="Supervisor",
            goal="调度任务并保证验收标准达成",
            instructions=(
                "确定性调度 + 有限模型决策；不直接调用业务工具；Reviewer 未通过不得完成任务。"
            ),
            allowed_tools=[],
            token_limit=32000,
            max_tool_calls=0,
        )
    )
    registry.register(
        AgentSpec(
            agent_id="planner",
            role_type="planner",
            display_name="Planner",
            goal="把澄清后的目标拆解为结构化计划",
            instructions="输出 Plan Schema；不调用外部工具；预算分配总和不得超过任务总预算。",
            allowed_tools=[],
            token_limit=16000,
            max_tool_calls=0,
        )
    )
    registry.register(
        AgentSpec(
            agent_id="researcher",
            role_type="researcher",
            display_name="Researcher",
            goal="采集事实与证据",
            instructions=(
                "只允许只读 Fixture 工具；输出 ResearchReport；"
                "无 evidence 的 Claim 必须标记未验证；不能直接写 final_result。"
            ),
            allowed_tools=[
                "fixture_repo_lookup",
                "fixture_source_lookup",
                "local_read_text",
                "local_list_directory",
                "local_file_metadata",
                "local_read_json",
                "local_read_csv",
                "local_read_pdf",
            ],
            token_limit=64000,
            max_tool_calls=10,
        )
    )
    registry.register(
        AgentSpec(
            agent_id="executor",
            role_type="executor",
            display_name="Executor",
            goal="生成变更提案并经审批后实施（007 十二：正式启用）",
            instructions=(
                "只允许：创建 PatchProposal、读取 worktree、调用沙箱写工具、"
                "调用受限测试命令、生成 Artifact；禁止自行批准、访问源项目、"
                "调用网络、未登记命令、remote/push/发送/设备。"
            ),
            allowed_tools=[
                "sandbox_create_directory",
                "sandbox_write_file",
                "sandbox_apply_patch",
                "sandbox_copy_file",
                "sandbox_move_file",
                "sandbox_delete_path",
                "sandbox_restore_backup",
                "fixture_repo_lookup",
                "fixture_source_lookup",
            ],
            token_limit=64000,
            max_tool_calls=20,
            enabled=True,  # 007 十二：Executor 正式启用（M3-C）
        )
    )
    registry.register(
        AgentSpec(
            agent_id="reviewer",
            role_type="reviewer",
            display_name="Reviewer",
            goal="独立审查产物",
            instructions="确定性检查先行；LLM 评审不得把确定性失败改为通过。",
            allowed_tools=[],
            token_limit=16000,
            max_tool_calls=0,
        )
    )
    return registry
