"""MCP 只读适配层（006 十）：MCPToolAdapter + Fake MCP Server。

- 读取 MCP 工具 Schema → 转换为内部 ToolSpec；参数经 Pydantic/JSON Schema 校验。
- 重新设置本项目风险属性：一律 SAFE + read_only=True（不信任 MCP Server 自报）。
- 对无法确定只读性质的工具默认拒绝（10.2）。
- 所有调用仍经过 Tool Gateway（Evidence 固化/预算/配额由网关执行）。
- MCP Server 必须在本机静态配置中注册（10.1）；用户任务或 LLM 不能动态添加。
- 真实 stdio/HTTP MCP 冒烟可延后标记未配置（10.3），本阶段提供接口 + Fake 实现。
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from app.gateway.tool_gateway import ToolGateway
from app.tools.spec import RiskLevel, ToolSpec

# 写语义关键词：命中即拒绝（10.2：无法确定只读性质默认拒绝）
_WRITE_HINTS = (
    "write",
    "create",
    "delete",
    "update",
    "edit",
    "send",
    "post",
    "put",
    "patch",
    "execute",
    "run",
    "install",
    "push",
    "commit",
    "publish",
    "upload",
    "download",
    "shell",
    "terminal",
    "exec",
)


class MCPServerConfig(BaseModel):
    """MCP Server 静态注册项（10.1）。"""

    server_id: str
    transport: str = "memory"  # memory（Fake，测试）| stdio（真实，M3-B 后）
    command_or_url: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    read_only: bool = True
    timeout_seconds: int = 30
    enabled: bool = True


class FakeMCPServer:
    """进程内 Fake MCP Server（10.3）：确定性只读工具，供适配器/网关测试。"""

    def __init__(
        self, server_id: str, tools: dict[str, tuple[dict[str, Any], Callable[..., Any]]]
    ) -> None:
        self.server_id = server_id
        self._tools = tools  # name -> (input_schema, handler)
        self.call_count = 0

    def list_tools(self) -> dict[str, dict[str, Any]]:
        return {
            name: {"name": name, "input_schema": schema}
            for name, (schema, _) in self._tools.items()
        }

    def call(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self._tools:
            return {"ok": False, "error": f"unknown mcp tool: {tool_name}", "code": "not_found"}
        self.call_count += 1
        _, handler = self._tools[tool_name]
        try:
            return handler(**args)
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "mcp tool failed", "code": "error"}


def _is_read_only(name: str, description: str = "") -> bool:
    """只读判定（10.2）：写语义关键词命中 → 拒绝。

    说明（review sa_20260805_035741 should-fix-4）：这是关键词黑名单（命中即拒），
    未命中不代表一定安全——真正的防线是 1) 静态注册时管理员显式登记 allowed_tools；
    2) 转换后强制 read_only=True 且全经 Tool Gateway（结果只读处理、Evidence 固化）；
    3) 真实 stdio/http MCP Server 接入前必须人工评审工具清单（M3-B 仅 Fake 实现）。
    """
    lowered = f"{name} {description}".lower()
    return not any(hint in lowered for hint in _WRITE_HINTS)


class MCPToolAdapter:
    """MCP 适配器：静态注册 → Schema 转换 → 只读强制 → Tool Gateway 注册。"""

    def __init__(
        self,
        servers: dict[str, MCPServerConfig],
        fake_servers: dict[str, FakeMCPServer] | None = None,
    ) -> None:
        self._servers = servers
        self._fake_servers = fake_servers or {}
        self._converted: list[ToolSpec] = []

    def register_all(self, gateway: ToolGateway) -> list[ToolSpec]:
        """把已注册 Server 的已登记工具注册进 Tool Gateway（10.2）。"""
        self._converted = []
        for server_id, config in self._servers.items():
            if not config.enabled:
                continue
            server = self._fake_servers.get(server_id)
            if server is None:
                continue  # 真实 stdio/http server 未配置：冒烟单独标记（10.3）
            for tool_name, schema in server.list_tools().items():
                if tool_name not in config.allowed_tools:
                    continue  # 10.2：只允许已登记工具
                spec = self.convert(server_id, config, tool_name, schema, server)
                if spec is not None:
                    gateway.register(spec)
                    self._converted.append(spec)
        return self._converted

    def convert(
        self,
        server_id: str,
        config: MCPServerConfig,
        tool_name: str,
        mcp_schema: dict[str, Any],
        server: FakeMCPServer,
    ) -> ToolSpec | None:
        """Schema 转换（10.2）：只读强制 + 风险重设 + 默认拒绝不确定项。"""
        description = str(mcp_schema.get("description", ""))
        if not config.read_only or not _is_read_only(tool_name, description):
            return None  # 无法确定只读性质/已声明只读=false → 拒绝
        input_schema = mcp_schema.get("input_schema", mcp_schema.get("inputSchema", {}))
        props = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
        args_schema = {
            name: {"type": "str"}
            for name in props  # MCP JSON Schema → 内部简化类型
        }
        # 参数校验（10.1）：gateway 的 args_schema 检查；不信任自报类型，按字符串宽松
        tool = ToolSpec(
            name=f"mcp_{server_id}_{tool_name}",
            description=f"[mcp:{server_id}] {description[:120]}",
            input_schema={"name": "str", "args": "dict"},
            risk_level=RiskLevel.SAFE,  # 风险属性重设（10.1）
            read_only=True,  # 只读强制
            handler=lambda name=tool_name, srv=server, **kw: srv.call(name, kw),
            roles=("researcher",),
            args_schema=args_schema if args_schema else None,
        )
        return tool
