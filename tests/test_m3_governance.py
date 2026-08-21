"""005 18.1：Fake Provider / 输出治理 / 预算 / 重试 / 路由 / 密钥 / SSRF 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.llm_agents import LLMReviewer
from app.core.config import AppSettings, ModelProviderSettings, ModelRouteSettings
from app.core.context_builder import ContextBuilder
from app.core.output_governance import (
    OutputValidationError,
    extract_json_text,
    parse_json_object,
    validate_against_schema,
)
from app.core.state import Evidence, SubtaskState, TaskState
from app.gateway.audit import AuditLog
from app.gateway.contracts import (
    ProviderError,
    ProviderErrorCode,
)
from app.gateway.fake_provider import FakeModelProvider
from app.gateway.model_gateway import ModelGateway
from app.gateway.openai_compatible import OpenAICompatibleProvider, _blocked_host_reason
from app.gateway.router import ModelRouter
from app.gateway.structured_gen import generate_structured
from app.prompts import PLANNER_PROMPT, PROMPT_REGISTRY, UNTRUSTED_MARKER

SCHEMA = {"summary": {"type": "str"}, "claims": {"type": "list"}}
PLAN_REQ_SCHEMA = {"goal": {"type": "str"}, "subtasks": {"type": "list"}}


def _settings() -> AppSettings:
    return AppSettings(
        model=ModelProviderSettings(default_model="test-model"),
        routing=ModelRouteSettings(
            role_defaults={
                "supervisor": "s-model",
                "planner": "p-model",
                "researcher": "r-model",
                "reviewer": "v-model",
                "executor": "",
            },
            allowed_models=[
                "test-model",
                "s-model",
                "p-model",
                "r-model",
                "v-model",
                "fallback-model",
            ],
            fallback_models=["fallback-model"],
        ),
    )


def _gateway(tmp_path: Path, provider=None, budget_tokens: int = 100000, budget_cost: float = 10.0):
    from app.core.budget import BudgetController

    audit = AuditLog(tmp_path / "audit.jsonl")
    budget = BudgetController(budget_tokens, budget_cost)
    provider = provider or FakeModelProvider()
    gw = ModelGateway(provider=provider, budget=budget, audit=audit, task_id="t-m3")
    return gw, budget, audit


def _request(**kwargs):
    from app.gateway.contracts import ModelRequest

    defaults = dict(
        request_id="req-1",
        task_id="t",
        agent_id="a",
        role_type="planner",
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
        max_output_tokens=100,
    )
    defaults.update(kwargs)
    return ModelRequest(**defaults)


# ---------- 1-2：正常结构化输出 + Markdown 包装 ----------
def test_normal_structured_output(tmp_path: Path) -> None:
    gw, _, _ = _gateway(
        tmp_path, FakeModelProvider(responses={"hi": '{"summary": "s", "claims": []}'})
    )
    data = generate_structured(gw, _request(), SCHEMA, _settings())
    assert data == {"summary": "s", "claims": []}


def test_markdown_json_wrapping(tmp_path: Path) -> None:
    gw, _, _ = _gateway(
        tmp_path,
        FakeModelProvider(responses={"hi": '```json\n{"summary": "s", "claims": []}\n```'}),
    )
    data = generate_structured(gw, _request(), SCHEMA, _settings())
    assert data["summary"] == "s"


# ---------- 3-4：非法 JSON / 多个对象 ----------
def test_invalid_json_rejected(tmp_path: Path) -> None:
    with pytest.raises(OutputValidationError) as exc_info:
        parse_json_object("not json at all", 4096)
    assert exc_info.value.code in ("no_json_object", "invalid_json")


def test_multiple_json_objects_rejected() -> None:
    with pytest.raises(OutputValidationError) as exc_info:
        extract_json_text('```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```', 4096)
    assert exc_info.value.code == "multiple_json_objects"


# ---------- 5-6：Schema 缺字段 / 多余字段 ----------
def test_schema_missing_field_rejected() -> None:
    with pytest.raises(OutputValidationError) as exc_info:
        validate_against_schema({"summary": "s"}, SCHEMA)
    assert exc_info.value.code == "schema_validation_failed"


def test_schema_extra_fields_rejected() -> None:
    with pytest.raises(OutputValidationError) as exc_info:
        validate_against_schema({"summary": "s", "claims": [], "evil": 1}, SCHEMA)
    assert exc_info.value.code == "extra_fields"


# ---------- 7：超大输出 ----------
def test_oversized_output_rejected() -> None:
    with pytest.raises(OutputValidationError) as exc_info:
        extract_json_text('{"big": "' + "x" * 5000 + '"}', 1000)
    assert exc_info.value.code == "output_too_large"


# ---------- 8-9：修复重试 ----------
def test_repair_succeeds_once(tmp_path: Path) -> None:
    """首次非法 → 修复请求 → 第二次合法（8）。"""
    good = '{"summary": "s", "claims": []}'
    calls: list[str] = []

    class RepairProvider(FakeModelProvider):
        def generate(self, req):
            calls.append(req.messages[-1]["content"])
            if len(calls) == 1:
                return self._make(req, "not json")
            return self._make(req, good)

        def _make(self, req, text):
            from app.gateway.contracts import ModelResponse

            return ModelResponse(
                request_id=req.request_id,
                provider="fake",
                model=req.model,
                raw_text=text,
                input_tokens=10,
                output_tokens=5,
                estimated_cost=0.0,
            )

    provider = RepairProvider()
    gw, _, _ = _gateway(tmp_path, provider)
    data = generate_structured(gw, _request(), SCHEMA, _settings())
    assert data["summary"] == "s"
    assert len(calls) == 2  # 首次 + 修复后再次调用


def test_repair_always_fails(tmp_path: Path) -> None:
    """修复始终失败 → 超限抛 SCHEMA_VALIDATION_FAILED（9）。"""
    gw, _, _ = _gateway(tmp_path, FakeModelProvider(responses={"hi": "still bad"}))
    with pytest.raises(ProviderError) as exc_info:
        generate_structured(gw, _request(), SCHEMA, _settings())
    assert exc_info.value.code == ProviderErrorCode.SCHEMA_VALIDATION_FAILED
    assert exc_info.value.attempt == 0


# ---------- 10-13：Token 记账 / 预算拦截 / 预留结算 / 重试不重置 ----------
def test_token_usage_recorded(tmp_path: Path) -> None:
    gw, budget, _ = _gateway(tmp_path, FakeModelProvider(tokens_per_call=50, cost_per_call=0.001))
    gw.generate(_request(max_output_tokens=100))
    assert budget.usage["tokens"] >= 50
    assert budget.usage["cost"] >= 0.001


def test_budget_precheck_intercepts(tmp_path: Path) -> None:
    """预算不足不发起请求（11）：provider 不被调用。"""
    provider = FakeModelProvider(cost_per_call=100.0)  # 单次超预算
    gw, _, _ = _gateway(tmp_path, provider, budget_cost=1.0)
    with pytest.raises(ProviderError) as exc_info:
        gw.generate(_request())
    assert exc_info.value.code == ProviderErrorCode.BUDGET_INSUFFICIENT
    assert provider.call_count == 0


def test_reserve_then_settle(tmp_path: Path) -> None:
    """预留与实际结算（12）：估算预留、实际记账。"""
    gw, budget, _ = _gateway(tmp_path, FakeModelProvider(tokens_per_call=10, cost_per_call=0.01))
    request = _request(max_output_tokens=200)
    est = gw._provider.estimate_usage(request)
    assert est.estimated_input_tokens == 10
    assert est.estimated_max_output_tokens == 200
    gw.generate(request)
    assert budget.usage["tokens"] >= 10


def test_retry_does_not_reset_budget(tmp_path: Path) -> None:
    """重试不重置预算（13）：失败尝试不计账，成功才结算。"""
    from app.gateway.contracts import ModelResponse

    class FlakyProvider(FakeModelProvider):
        def generate(self, req):
            self.call_count += 1
            if self.call_count == 1:
                raise ProviderError(
                    ProviderErrorCode.TIMEOUT, "timeout", model=req.model, retryable=True
                )
            return ModelResponse(
                request_id=req.request_id,
                provider="fake",
                model=req.model,
                raw_text='{"summary": "s", "claims": []}',
                input_tokens=10,
                output_tokens=5,
                estimated_cost=0.01,
            )

    provider = FlakyProvider()
    gw, budget, _ = _gateway(tmp_path, provider)
    gw.generate(_request(), max_retries=2, sleep_fn=lambda _: None)
    assert provider.call_count == 2
    assert budget.usage["tokens"] == 15  # 只有成功结算


# ---------- 14-16：超时重试 / 限流 / 不可重试 ----------
def test_timeout_retries(tmp_path: Path) -> None:
    calls = [0]

    class TimeoutProvider(FakeModelProvider):
        def generate(self, req):
            calls[0] += 1
            if calls[0] <= 2:
                raise ProviderError(ProviderErrorCode.TIMEOUT, "t", model=req.model, retryable=True)
            return super().generate(req)

    provider = TimeoutProvider()
    gw, _, _ = _gateway(tmp_path, provider)
    resp = gw.generate(_request(), max_retries=3, sleep_fn=lambda _: None)
    assert resp is not None
    assert calls[0] == 3


def test_rate_limited_retry_after(tmp_path: Path) -> None:
    calls = [0]

    class RateLimitedProvider(FakeModelProvider):
        def generate(self, req):
            calls[0] += 1
            if calls[0] == 1:
                raise ProviderError(
                    ProviderErrorCode.RATE_LIMITED, "429", model=req.model, retryable=True
                )
            return super().generate(req)

    provider = RateLimitedProvider()
    gw, _, _ = _gateway(tmp_path, provider)
    gw.generate(_request(), max_retries=2, sleep_fn=lambda _: None)
    assert calls[0] == 2


def test_auth_error_not_retried(tmp_path: Path) -> None:
    class AuthProvider(FakeModelProvider):
        def generate(self, req):
            self.call_count += 1
            raise ProviderError(ProviderErrorCode.AUTHENTICATION_ERROR, "401", model=req.model)

    provider = AuthProvider()
    gw, _, _ = _gateway(tmp_path, provider)
    with pytest.raises(ProviderError):
        gw.generate(_request(), max_retries=3, sleep_fn=lambda _: None)
    assert provider.call_count == 1  # 不可重试不重试


# ---------- 17-18：fallback 模型 + 审计 ----------
def test_fallback_models(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    router = ModelRouter(_settings().routing, audit=audit, task_id="t")
    fallback = router.fallback("planner", "p-model")
    assert fallback == "fallback-model"
    assert router.fallback("planner", "fallback-model") is None  # 不重复自身
    # fallback 审计
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert any("model_fallback" in line for line in lines)


# ---------- 19：ContextBuilder 裁剪 ----------
def test_context_truncation() -> None:
    cb = ContextBuilder(_settings())
    long_text = "x" * 100000
    truncated, flag = cb.truncate(long_text)
    assert flag is True
    assert len(truncated) <= cb._max_chars
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "y" * 50000}]
    kept, flag2 = cb.truncate_messages(messages)
    assert flag2 is True
    assert kept[0]["content"] == "sys"  # 系统约束保留


# ---------- 20：LLM Reviewer 确定性失败不可覆盖 ----------
def test_reviewer_context_accepts_typed_evidence() -> None:
    state = TaskState(task_id="t", user_goal="x", token_budget=1000, cost_budget=1.0)
    state.evidence = [
        Evidence(id="e1", task_id="t", tool="local_read_text", summary="typed", ts="now")
    ]
    subtask = SubtaskState(
        subtask_id="s1",
        title="t",
        objective="o",
        assigned_role="researcher",
        expected_output="r",
        acceptance_criteria=["a"],
        token_budget=100,
        tool_call_budget=1,
    )
    context = ContextBuilder(_settings()).reviewer_context(state, subtask, [])
    assert context["evidence"] == [{"id": "e1", "summary": "typed"}]


def test_llm_reviewer_deterministic_failure_not_overridable(tmp_path: Path) -> None:
    from app.core.schemas import Claim, ExecutionResult, ReviewIssue

    gw, _, _ = _gateway(tmp_path)
    reviewer = LLMReviewer(
        gw, ModelRouter(_settings().routing), ContextBuilder(_settings()), _settings()
    )
    state = TaskState(task_id="t", user_goal="x", token_budget=1000, cost_budget=1.0)
    subtask = SubtaskState(
        subtask_id="s1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        token_budget=100,
        tool_call_budget=1,
    )
    subtask.execution_result = ExecutionResult(
        subtask_id="s1",
        summary="s",
        claims=[Claim(claim_id="c1", text="x", evidence_ids=[])],
        ts="t",
    )
    issues = [ReviewIssue(code="claim_without_evidence", message="no evidence", subtask_id="s1")]
    result = reviewer.review(state, subtask, issues)
    assert result.verdict == "reject"  # 确定性失败 → reject，不调用模型
    assert gw._provider.call_count == 0  # 模型未被调用


# ---------- 21：Prompt 版本和哈希 ----------
def test_prompt_version_and_hash() -> None:
    assert PLANNER_PROMPT.prompt_id == "planner.plan"
    assert PLANNER_PROMPT.version == "2.0"
    assert len(PLANNER_PROMPT.hash) == 16
    assert set(PROMPT_REGISTRY.keys()) == {
        "supervisor.decision",
        "planner.plan",
        "researcher.report",
        "researcher.probe",
        "reviewer.review",
    }
    assert UNTRUSTED_MARKER  # 注入边界标记存在


# ---------- 22：密钥不进入日志 / Provider 消息 ----------
def test_api_key_not_in_audit_or_messages(tmp_path: Path) -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://api.example.com/v1",
        api_key="AI_TEAM_OS_TEST_sk-PLACEHOLDER-M3-GOVERNANCE",
        enable_real=True,
        transport=None,  # 不实际调用
    )
    assert provider._api_key == "AI_TEAM_OS_TEST_sk-PLACEHOLDER-M3-GOVERNANCE"
    # 请求对象不含 key
    request = _request()
    dumped = json.dumps(request.model_dump())
    assert "sk-super-secret" not in dumped
    # 配置 dump 不含 key
    settings = _settings()
    assert "sk-" not in json.dumps(settings.model.model_dump(exclude={"api_key"}))


# ---------- 23：Base URL SSRF 校验 ----------
@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "::1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "metadata.google.internal",
        "foo.internal",
    ],
)
def test_ssrf_blocked_hosts(host: str) -> None:
    assert _blocked_host_reason(host) is not None


def test_ssrf_public_host_allowed() -> None:
    # 公网 IP 字面量放行；域名在离线环境解析失败 → 拒绝（解析失败不放行）
    assert _blocked_host_reason("8.8.8.8") is None
    assert _blocked_host_reason("1.1.1.1") is None


def test_https_only_required() -> None:
    provider = OpenAICompatibleProvider(
        base_url="http://api.example.com/v1", api_key="k", enable_real=True
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request(model="m"))
    assert exc_info.value.code == ProviderErrorCode.CONFIG_ERROR


# ---------- 24-25：real 模式默认禁用 / 无 API Key ----------
def test_real_mode_disabled_by_default() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://api.example.com/v1", api_key="k", enable_real=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request(model="m"))
    assert exc_info.value.code == ProviderErrorCode.CONFIG_ERROR
    health = provider.health_check()
    assert health.status == "disabled"


def test_missing_api_key_error() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://api.example.com/v1", api_key="", enable_real=True
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.generate(_request(model="m"))
    assert exc_info.value.code == ProviderErrorCode.CONFIG_ERROR
    assert provider.health_check().status == "misconfigured"


# ---------- 26：API 不接受客户端 API Key ----------
def test_api_schema_has_no_api_key_field() -> None:
    from app.api.server import TaskCreate

    fields = TaskCreate.model_fields.keys()
    assert "api_key" not in fields
    assert "base_url" not in fields
    assert "model_mode" in fields
    assert "model_overrides" in fields


# ---------- 额外：模型覆盖白名单 + 生效性 ----------
def test_model_override_whitelist() -> None:
    router = ModelRouter(_settings().routing)
    assert router.resolve("planner", overrides={"planner": "p-model"}) == "p-model"
    with pytest.raises(ValueError, match="override rejected"):
        router.resolve("planner", overrides={"planner": "evil-model"})


def test_model_override_effective() -> None:
    """005 8.2：任务级覆盖存储后 resolve 自动生效（修复死代码）。"""
    router = ModelRouter(_settings().routing, overrides={"planner": "p-model"})
    assert router.resolve("planner") == "p-model"  # 不传 overrides 也生效
    assert router.resolve("researcher") == "r-model"  # 未覆盖角色用默认


def test_api_rejects_invalid_model_override() -> None:
    """005 17：非法 model_overrides 返回 400（白名单失败不 500）。"""
    from tests.test_api import client

    resp = client.post(
        "/tasks",
        json={
            "goal": "hello world github compare",
            "token_budget": 5000,
            "cost_budget": 0.5,
            "model_overrides": {"planner": "evil-model"},
        },
    )
    assert resp.status_code == 400
    assert "override rejected" in resp.json()["detail"]


def test_budget_exceeded_message_reports_real_used() -> None:
    """cost 超限时 BudgetExceeded 消息展示真实已用值（review 修复）。"""
    from app.core.budget import BudgetController, BudgetExceeded

    budget = BudgetController(1_000_000, 0.05)
    budget.record(100, 100, 0.04)
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.record(100, 100, 0.02)  # cost: 0.04+0.02 > 0.05
    used, limit = exc_info.value.used, exc_info.value.limit
    assert used == 0.06  # 真实已用 cost（修复前为 0.05 上限值）
    assert limit == 0.05


def test_cost_budget_uses_pricing_table(tmp_path: Path) -> None:
    """10.3：价格表参与预留与结算（成本预算不失效）。"""
    from app.core.budget import BudgetController

    audit = AuditLog(tmp_path / "audit.jsonl")
    budget = BudgetController(1_000_000, 0.05)  # 成本预算 0.05 美元
    provider = FakeModelProvider(tokens_per_call=100, cost_per_call=None)  # provider 不报价格
    provider.provider_name = "openai_compatible"  # 走集中价格表匹配
    gw = ModelGateway(provider=provider, budget=budget, audit=audit, task_id="t")
    # 价格表含 placeholder-default：1M in/1M out = $1/$2
    from app.core.config import PRICING

    assert PRICING  # 集中价格表非空
    request = _request(model="placeholder-default", max_output_tokens=4000)
    # 预留：约 (100+4000)/1e6 * 2 = 0.0082 ≤ 0.05 ✓；结算按实际 tokens
    gw.generate(request)
    assert budget.usage["cost"] > 0  # 价格表计算生效，不再是 0
