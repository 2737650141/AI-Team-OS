"""M1 工具：FixtureRepositoryLookupTool（本地 fixture，不访问网络）与 DangerousWriteTool。

对应黄金任务：GT-01（离线 Fixture）、GT-03（只读）、GT-10（dangerous 拦截）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.spec import RiskLevel, ToolSpec


class FixtureRepositoryLookupTool:
    """从本地 Fixture 读取仓库元数据（safe + read_only）。"""

    NAME = "fixture_repo_lookup"

    def __init__(self, fixture_path: Path) -> None:
        self._data: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.NAME,
            description="从本地 Fixture 读取开源仓库元数据（不访问网络）",
            input_schema={"repo_name": "str: 仓库名，如 langgraph"},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=self.handler,
        )

    def handler(self, repo_name: str) -> dict[str, Any]:
        if repo_name not in self._data:
            raise KeyError(f"fixture 中无仓库 {repo_name}")
        return self._data[repo_name]


class FixtureSourceLookupTool:
    """从本地 Fixture 读取多来源陈述（GT-05 冲突来源核查，safe + read_only）。"""

    NAME = "fixture_source_lookup"

    def __init__(self, fixture_path: Path) -> None:
        self._data: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.NAME,
            description="从本地 Fixture 读取来源陈述（含相互矛盾的来源，不访问网络）",
            input_schema={"source_id": "str: 来源 ID，如 langgraph_maintained"},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=self.handler,
        )

    def handler(self, source_id: str) -> dict[str, Any]:
        if source_id not in self._data:
            raise KeyError(f"fixture 中无来源 {source_id}")
        return self._data[source_id]


class DangerousWriteTool:
    """演示用危险写工具。M1 中 handler 永不执行（GT-10 M1 验收）。"""

    NAME = "dangerous_write"

    def __init__(self) -> None:
        self.exec_count = 0

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.NAME,
            description="演示用危险写工具（M1 中 handler 永不执行）",
            input_schema={"path": "str", "content": "str"},
            risk_level=RiskLevel.DANGEROUS,
            read_only=False,
            requires_approval=True,
            handler=self.handler,
        )

    def handler(self, path: str, content: str) -> dict[str, Any]:
        # Tool Gateway 确定性拦截发生在调用之前；本 handler 在 M1 不可达
        self.exec_count += 1
        raise RuntimeError("M1: dangerous handler must never execute")
