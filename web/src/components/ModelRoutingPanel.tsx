import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { TeamProvider, TeamRoleCard } from "../api/types";
import { useI18n } from "../i18n";

const ROLE_LABELS: Record<string, { zh: string; en: string }> = {
  supervisor: { zh: "总管", en: "Supervisor" },
  planner: { zh: "规划师", en: "Planner" },
  researcher: { zh: "研究员", en: "Researcher" },
  executor: { zh: "执行者", en: "Executor" },
  reviewer: { zh: "审查员", en: "Reviewer" },
  vision: { zh: "视觉专家", en: "Vision" },
  fast: { zh: "快速响应", en: "Fast" },
  deep_reasoning: { zh: "深度推理", en: "Deep reasoning" },
  voice_reasoning: { zh: "语音推理", en: "Voice reasoning" },
};

export function ModelRoutingPanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [scope, setScope] = useState<"global" | "project">("global");
  const [projectDraft, setProjectDraft] = useState("");
  const [projectId, setProjectId] = useState("");
  const routing = useQuery({
    queryKey: ["ai-team-routing", projectId],
    queryFn: () => api.teamRouting(projectId || undefined),
  });
  const test = useMutation({ mutationFn: api.testAiTeam });

  return (
    <section className="card model-routing-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">M6-A · Multi-Provider Expert Team</span>
          <h2>{zh ? "AI 团队模型路由" : "AI Team Model Routing"}</h2>
          <p className="muted">
            {zh
              ? "每个专家角色可独立选择 Provider 与模型。优先级：任务 > 项目 > 全局 > 已配置回退；系统绝不静默换模。"
              : "Choose a provider and model for every expert role. Precedence: task > project > global > configured fallback; silent fallback is prohibited."}
          </p>
        </div>
        <span className={`mode-badge ${routing.data?.roles.some((item) => item.health === "VALIDATED") ? "real" : "fake"}`}>
          {routing.isLoading ? "LOADING" : routing.data?.roles.some((item) => item.provider_id) ? "CONFIGURED" : "WAITING"}
        </span>
      </div>

      <div className="routing-toolbar">
        <label className="field">
          {zh ? "编辑范围" : "Editing scope"}
          <select value={scope} onChange={(event) => setScope(event.target.value as "global" | "project")}>
            <option value="global">{zh ? "全局默认" : "Global default"}</option>
            <option value="project">{zh ? "项目覆盖" : "Project override"}</option>
          </select>
        </label>
        {scope === "project" && (
          <label className="field project-route-input">
            {zh ? "项目 ID" : "Project ID"}
            <span className="inline-input-action">
              <input value={projectDraft} onChange={(event) => setProjectDraft(event.target.value)} placeholder="project-id" />
              <button className="btn" disabled={!projectDraft.trim()} onClick={() => setProjectId(projectDraft.trim())}>
                {zh ? "载入" : "Load"}
              </button>
            </span>
          </label>
        )}
        <div className="routing-policy">
          <small>{zh ? "回退策略" : "Fallback policy"}</small>
          <strong>{routing.data?.fallback_policy ?? "NO_SILENT_FALLBACK"}</strong>
          <small>{zh ? "Reviewer：只读，不执行操作" : "Reviewer: read-only, never executes"}</small>
        </div>
        <button className="btn btn-primary" disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? (zh ? "真实调用中…" : "Running real calls…") : (zh ? "测试 AI 团队" : "Test AI Team")}
        </button>
      </div>

      {routing.isError && <p className="msg error">{routing.error.message}</p>}
      {scope === "project" && !projectId && <p className="routing-notice">{zh ? "输入项目 ID 后可查看并编辑项目级覆盖。" : "Enter a project ID to view and edit project overrides."}</p>}
      <div className="model-route-grid">
        {(routing.data?.roles ?? []).map((card) => (
          <RoleRouteCard
            key={card.role}
            card={card}
            providers={routing.data?.providers ?? []}
            scope={scope}
            projectId={scope === "project" ? projectId : undefined}
            zh={zh}
          />
        ))}
      </div>

      {test.data && (
        <div className="team-test-results" role="status">
          <div><strong>{zh ? "真实团队测试" : "Real team test"}</strong><span>{test.data.status} · {test.data.ready}/{test.data.total}</span></div>
          {test.data.results.map((item) => (
            <span key={item.role} className={item.real_call ? "good" : "neutral"}>
              {roleLabel(item.role, zh)} · {item.status}{item.latency_ms != null ? ` · ${Math.round(item.latency_ms)}ms` : ""}
            </span>
          ))}
          <small>{zh ? "仅实际返回的 Provider 调用计为通过；隔离测试和缺少凭据不会伪装成功。" : "Only completed provider calls pass; isolated tests and missing credentials never report fake success."}</small>
        </div>
      )}
      {test.isError && <p className="msg error">{test.error.message}</p>}
    </section>
  );
}

function RoleRouteCard({ card, providers, scope, projectId, zh }: {
  card: TeamRoleCard;
  providers: TeamProvider[];
  scope: "global" | "project";
  projectId?: string;
  zh: boolean;
}) {
  const qc = useQueryClient();
  const [providerId, setProviderId] = useState(card.provider_id ?? "");
  const [model, setModel] = useState(card.model ?? "");
  const [fallbackProviderId, setFallbackProviderId] = useState(card.fallback?.provider_id ?? "");
  const [fallbackModel, setFallbackModel] = useState(card.fallback?.model ?? "");
  const [tokenBudget, setTokenBudget] = useState(card.token_budget?.toString() ?? "");
  const [costBudget, setCostBudget] = useState(card.cost_budget?.toString() ?? "");
  const [message, setMessage] = useState("");
  const provider = providers.find((item) => item.provider_id === providerId);
  const fallbackProvider = providers.find((item) => item.provider_id === fallbackProviderId);
  const modelIds = useMemo(() => provider?.models ?? [], [provider]);
  const fallbackModelIds = useMemo(() => fallbackProvider?.models ?? [], [fallbackProvider]);

  useEffect(() => {
    setProviderId(card.provider_id ?? "");
    setModel(card.model ?? "");
    setFallbackProviderId(card.fallback?.provider_id ?? "");
    setFallbackModel(card.fallback?.model ?? "");
    setTokenBudget(card.token_budget?.toString() ?? "");
    setCostBudget(card.cost_budget?.toString() ?? "");
  }, [card]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["ai-team-routing"] });
  const save = useMutation({
    mutationFn: () => api.saveTeamRoute(card.role, {
      scope,
      project_id: scope === "project" ? projectId : null,
      provider_id: providerId,
      model,
      fallback_provider_id: fallbackProviderId || null,
      fallback_model: fallbackModel || null,
      token_budget: tokenBudget ? Number(tokenBudget) : null,
      cost_budget: costBudget ? Number(costBudget) : null,
    }),
    onSuccess: () => { setMessage(zh ? "路由已保存。" : "Route saved."); invalidate(); },
    onError: (error: Error) => setMessage(error.message),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteTeamRoute(card.role, scope, projectId),
    onSuccess: () => { setMessage(zh ? "当前范围的路由已移除。" : "Route removed for this scope."); invalidate(); },
    onError: (error: Error) => setMessage(error.message),
  });
  const blocked = !providerId || !model.trim() || (scope === "project" && !projectId);

  return (
    <article className={`model-route-card ${card.warning ? "warning" : ""}`}>
      <header>
        <div><h3>{roleLabel(card.role, zh)}</h3><small>{card.role === "reviewer" ? (zh ? "只读审查" : "Read-only review") : card.source ? `${zh ? "来源" : "Source"}: ${card.source}` : "WAITING"}</small></div>
        <span className={`connection-pill ${card.health === "VALIDATED" || card.health === "configured" ? "good" : "neutral"}`}>{card.health}</span>
      </header>
      <label className="field">Provider
        <select value={providerId} onChange={(event) => { setProviderId(event.target.value); setModel(""); }}>
          <option value="">{zh ? "选择 Provider" : "Select provider"}</option>
          {providers.map((item) => <option key={item.provider_id} value={item.provider_id}>{item.provider_name} · {item.health}</option>)}
        </select>
      </label>
      <label className="field">{zh ? "模型" : "Model"}
        <input list={`models-${card.role}`} value={model} onChange={(event) => setModel(event.target.value)} placeholder={zh ? "选择或手动输入模型 ID" : "Choose or enter a model ID"} />
        <datalist id={`models-${card.role}`}>{modelIds.map((item) => <option key={item} value={item} />)}</datalist>
      </label>
      <details>
        <summary>{zh ? "预算与显式回退" : "Budgets & explicit fallback"}</summary>
        <div className="route-budget-grid">
          <label className="field">{zh ? "Token 上限" : "Token budget"}<input type="number" min="1" value={tokenBudget} onChange={(event) => setTokenBudget(event.target.value)} /></label>
          <label className="field">{zh ? "成本上限" : "Cost budget"}<input type="number" min="0" step="0.001" value={costBudget} onChange={(event) => setCostBudget(event.target.value)} /></label>
        </div>
        <label className="field">{zh ? "回退 Provider（可选）" : "Fallback provider (optional)"}
          <select value={fallbackProviderId} onChange={(event) => { setFallbackProviderId(event.target.value); setFallbackModel(""); }}><option value="">{zh ? "不回退" : "No fallback"}</option>{providers.map((item) => <option key={item.provider_id} value={item.provider_id}>{item.provider_name}</option>)}</select>
        </label>
        {fallbackProviderId && <label className="field">{zh ? "回退模型" : "Fallback model"}<input list={`fallback-${card.role}`} value={fallbackModel} onChange={(event) => setFallbackModel(event.target.value)} /><datalist id={`fallback-${card.role}`}>{fallbackModelIds.map((item) => <option key={item} value={item} />)}</datalist></label>}
      </details>
      <div className="route-capabilities">
        {Object.entries(card.capability).filter(([, value]) => value === true).map(([key]) => <span key={key}>{key.replaceAll("_", " ")}</span>)}
        {!Object.values(card.capability).some((value) => value === true) && <span>{zh ? "能力待验证" : "Capabilities unverified"}</span>}
      </div>
      <dl className="route-metrics">
        <div><dt>{zh ? "延迟" : "Latency"}</dt><dd>{card.latency_ms == null ? "—" : `${Math.round(card.latency_ms)} ms`}</dd></div>
        <div><dt>{zh ? "成功率" : "Success"}</dt><dd>{card.success_rate == null ? "—" : `${(card.success_rate * 100).toFixed(1)}%`}</dd></div>
        <div><dt>{zh ? "成本" : "Cost"}</dt><dd>{card.cost_label}</dd></div>
      </dl>
      {card.warning && <p className="route-warning">⚠ {zh ? "Executor 与 Reviewer 使用同一模型，独立审查能力下降。" : "Executor and Reviewer use the same model; review independence is reduced."}</p>}
      <div className="provider-actions"><button className="btn btn-primary" disabled={blocked || save.isPending} onClick={() => save.mutate()}>{zh ? "保存路由" : "Save route"}</button><button className="btn" disabled={remove.isPending || (scope === "project" && !projectId)} onClick={() => remove.mutate()}>{zh ? "移除此范围" : "Remove scope"}</button></div>
      {message && <small className="msg">{message}</small>}
    </article>
  );
}

function roleLabel(role: string, zh: boolean) {
  return ROLE_LABELS[role]?.[zh ? "zh" : "en"] ?? role;
}
