import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { ConnectionStatus, CustomProvider } from "../api/types";
import { ModelRoutingPanel } from "../components/ModelRoutingPanel";
import { PermissionSettingsPanel } from "../components/PermissionSettingsPanel";
import { StorageWorkspacePanel } from "../components/StorageWorkspacePanel";
import { VoiceSettingsPanel } from "../components/VoiceSettingsPanel";
import { useI18n } from "../i18n";
import { connectionLabel, displayLabel } from "../i18n/labels";

declare const __APP_BUILD_SHA__: string;
declare const __APP_BUILD_TIME__: string;

const ROLE_KEYS = ["supervisor", "planner", "researcher", "executor", "reviewer"];

export function Settings() {
  const { lang, t } = useI18n();
  const status = useQuery({ queryKey: ["settings"], queryFn: api.settingsStatus });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const conns = useQuery({ queryKey: ["connections"], queryFn: api.connections });
  const custom = useQuery({ queryKey: ["custom-providers"], queryFn: api.customProviders });
  const modelHealth = aggregateHealth([
    conns.data?.openai_compatible,
    conns.data?.test_provider,
  ]);
  const githubHealth = aggregateHealth([conns.data?.github, conns.data?.github_test]);
  const settingsData = status.data ?? {};
  const mcp = asRecord(settingsData.mcp);
  const sandbox = asRecord(settingsData.sandbox);

  return (
    <div className="page settings-page">
      <div className="page-heading">
        <div>
          <h1>{t("settings.title")}</h1>
          <p className="muted">{t("settings.productIntro")}</p>
        </div>
        <Link className="btn" to="/setup">{t("settings.runWizard")}</Link>
      </div>

      <div className="settings-grid">
        <SettingsCard
          title={t("settings.aiModels")}
          description={t("settings.aiModelsDesc")}
          provider={preferredProvider([conns.data?.test_provider, conns.data?.openai_compatible])}
          health={modelHealth}
          actionLabel={t("settings.configure")}
        >
          <ProviderEditor
            family="models"
            providers={[
              ["test_provider", t("settings.testProvider")],
              ["openai_compatible", t("settings.providerOpenAI")],
            ]}
            connections={conns.data}
          />
        </SettingsCard>

        <SettingsCard
          title="GitHub"
          description={t("settings.githubDesc")}
          provider={preferredProvider([conns.data?.github_test, conns.data?.github])}
          health={githubHealth}
          actionLabel={t("settings.configure")}
        >
          <ProviderEditor
            family="github"
            providers={[
              ["github_test", t("settings.githubTest")],
              ["github", "GitHub"],
            ]}
            connections={conns.data}
          />
        </SettingsCard>

        <SettingsCard
          title={t("settings.localModels")}
          description={t("settings.localModelsDesc")}
          provider="Ollama"
          health={conns.data?.ollama?.health ?? "missing"}
          actionLabel={t("settings.manage")}
        >
          <ProviderEditor
            family="models"
            providers={[["ollama", "Ollama"]]}
            connections={conns.data}
          />
        </SettingsCard>

        <SettingsCard
          title="MCP"
          description={t("settings.mcpDesc")}
          provider="MCP"
          health={String(mcp.status ?? "disabled")}
          actionLabel={t("settings.manage")}
        >
          <p className="muted">{t("settings.mcpManagedHint")}</p>
        </SettingsCard>

        <SettingsCard
          title={t("settings.sandbox")}
          description={t("settings.sandboxDesc")}
          provider={t("settings.localRuntime")}
          health={String(sandbox.status ?? health.data?.sandbox ?? "needs_check")}
          actionLabel={t("settings.manage")}
        >
          <dl className="detail-list">
            <div><dt>{t("settings.networkIsolation")}</dt><dd>{String(settingsData.network_isolation ?? "—")}</dd></div>
            <div><dt>{t("settings.allowedRoots")}</dt><dd>{String(asRecord(settingsData.allowed_read_roots).count ?? 0)}</dd></div>
          </dl>
        </SettingsCard>

        <SettingsCard
          title={t("settings.system")}
          description={t("settings.systemDesc")}
          provider="AI Team OS"
          health={health.data?.backend ?? "needs_check"}
          actionLabel={t("settings.manage")}
        >
          <dl className="detail-list">
            {Object.entries(health.data ?? {}).map(([key, value]) => (
              <div key={key}><dt>{displayLabel(key, lang)}</dt><dd>{connectionLabel(value, lang)}</dd></div>
            ))}
          </dl>
        </SettingsCard>
      </div>

      <PermissionSettingsPanel />

      <StorageWorkspacePanel />

      <InteractionSettingsPanel />

      <UsageHistoryPanel />

      <ModelRoutingPanel />

      <VoiceSettingsPanel />

      <VisionConnectionPanel />

      <div id="custom-providers"><CustomProvidersPanel providers={custom.data?.providers ?? []} /></div>

      <section className="card settings-section" aria-label={lang === "zh" ? "关于" : "About"}>
        <div className="section-heading">
          <div>
            <span className="eyebrow">AI Team OS</span>
            <h2>{lang === "zh" ? "开发者预览版" : "Developer Preview"}</h2>
            <p className="muted">
              {lang === "zh"
                ? "版本 0.1.0 · 本地优先的 Windows 桌面预览版"
                : "Version 0.1.0 · Local-first Windows desktop preview"}
            </p>
            <dl className="build-identity" aria-label={lang === "zh" ? "构建信息" : "Build identity"}>
              <div><dt>{lang === "zh" ? "构建" : "Build"}</dt><dd><code>{__APP_BUILD_SHA__}</code></dd></div>
              <div><dt>{lang === "zh" ? "前端构建时间" : "Frontend built"}</dt><dd>{__APP_BUILD_TIME__}</dd></div>
            </dl>
          </div>
        </div>
      </section>

      <details className="card advanced-raw">
        <summary>{t("settings.advancedConfig")}</summary>
        <p className="muted">{t("settings.advancedConfigHint")}</p>
        <pre className="json">{JSON.stringify(settingsData, null, 2)}</pre>
      </details>
      <p className="muted">
        {t("settings.setupPrompt")} <Link to="/setup">{t("settings.runWizard")}</Link>.
      </p>
    </div>
  );
}

function InteractionSettingsPanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["interaction-settings"], queryFn: api.interactionSettings });
  const mutation = useMutation({
    mutationFn: api.saveInteractionSettings,
    onSuccess: (data) => qc.setQueryData(["interaction-settings"], data),
  });
  const settings = query.data;
  if (!settings) return null;
  const save = (patch: Partial<typeof settings>) => mutation.mutate({ ...settings, ...patch });
  return <section className="card settings-section" id="interaction-settings">
    <div className="section-heading"><div><span className="eyebrow">JARVIS Experience</span><h2>{zh ? "交互与通知" : "Interaction & Notifications"}</h2><p className="muted">{zh ? "交互偏好只影响非安全打扰和进度密度，不会改变权限、敏感确认或 STOP。" : "Interaction preferences only affect non-security interruptions and progress detail. Permissions, sensitive confirmation, and STOP never change."}</p></div></div>
    <label className="field">{zh ? "交互模式" : "Interaction mode"}<select value={settings.mode} disabled={mutation.isPending} onChange={(event) => save({ mode: event.target.value as typeof settings.mode })}><option value="normal">{zh ? "标准" : "Normal"}</option><option value="minimal_interruption">{zh ? "少打扰" : "Minimal interruption"}</option></select></label>
    <div className="notification-settings"><label className="switch-row"><input type="checkbox" checked={settings.notify_completed} onChange={(event) => save({ notify_completed: event.target.checked })} /><span>{zh ? "任务完成" : "Task completed"}</span></label><label className="switch-row"><input type="checkbox" checked={settings.notify_approval} onChange={(event) => save({ notify_approval: event.target.checked })} /><span>{zh ? "需要确认" : "Approval required"}</span></label><label className="switch-row"><input type="checkbox" checked={settings.notify_failed} onChange={(event) => save({ notify_failed: event.target.checked })} /><span>{zh ? "任务失败" : "Task failed"}</span></label></div>
  </section>;
}

function UsageHistoryPanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["usage-settings"], queryFn: api.usageSettings });
  const mutation = useMutation({
    mutationFn: api.saveUsageSettings,
    onSuccess: (data) => qc.setQueryData(["usage-settings"], data),
  });
  const retention = query.data?.retention ?? "30";
  return <section className="card settings-section">
    <div className="section-heading"><div><span className="eyebrow">Token & Context Observatory</span><h2>{zh ? "用量历史" : "Usage history"}</h2><p className="muted">{zh ? "仅保存数字遥测，不保存提示词、回复、密钥或隐藏推理。" : "Stores numeric telemetry only—never prompts, responses, secrets, or hidden reasoning."}</p></div><Link className="btn" to="/usage">{zh ? "查看用量" : "Open Usage"}</Link></div>
    <label className="field">{zh ? "保留期限" : "Retention"}<select value={retention} disabled={mutation.isPending} onChange={(event) => mutation.mutate(event.target.value as "7" | "30" | "90" | "forever")}><option value="7">7 {zh ? "天" : "days"}</option><option value="30">30 {zh ? "天" : "days"}</option><option value="90">90 {zh ? "天" : "days"}</option><option value="forever">{zh ? "永久" : "Forever"}</option></select></label>
  </section>;
}

function VisionConnectionPanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["computer-vision"], queryFn: api.computerVision });
  const [pendingConsent, setPendingConsent] = useState(false);
  const [message, setMessage] = useState("");
  const provider = status.data?.vision_provider;
  const settings = status.data?.settings;
  const mutation = useMutation({
    mutationFn: (allow: boolean) => api.updateComputerVision({
      provider: settings?.route_provider || null,
      model: settings?.route_model || null,
      allow_external_processing: allow,
      consent_acknowledged: allow,
      auto_refresh: false,
    }),
    onSuccess: (data) => {
      qc.setQueryData(["computer-vision"], data);
      setPendingConsent(false);
      setMessage(zh ? "视觉隐私设置已更新。" : "Vision privacy settings updated.");
    },
    onError: (error: Error) => setMessage(error.message),
  });

  return <section className="card vision-connection-panel">
    <div className="section-heading"><div><span className="eyebrow">Vision capability · separate route</span><h2>{zh ? "视觉模型与屏幕隐私" : "Vision Model & Screen Privacy"}</h2><p className="muted">{zh ? "视觉模型与主 Agent 模型独立。未配置时继续使用 Accessibility 与本地确定性视觉。" : "Vision is routed separately from the main agent. Accessibility and local deterministic vision remain available without it."}</p></div><span className={`mode-badge ${provider?.multimodal_status === "VALIDATED" ? "real" : "fake"}`}>{provider?.multimodal_status ?? "NOT_CONFIGURED"}</span></div>
    <div className="vision-settings-grid"><label className="field">{zh ? "Vision Provider" : "Vision Provider"}<select value={settings?.route_provider ?? ""} disabled><option value="">{zh ? "未发现已验证图片能力的 Provider" : "No verified image-capable provider"}</option></select></label><label className="field">{zh ? "视觉模型" : "Vision model"}<select value={settings?.route_model ?? ""} disabled><option value="">NOT_CONFIGURED</option></select></label><div className="vision-route-state"><small>{zh ? "文本模型" : "Text model"}</small><strong>{provider?.text_model?.provider ?? "DeepSeek Official"} · {provider?.text_model?.model ?? "deepseek-v4-flash"}</strong><span>TEXT_MODEL = REAL · VISION_MODEL = {provider?.multimodal_status ?? "NOT_CONFIGURED"}</span></div></div>
    <div className="external-vision-gate"><div><strong>{zh ? "外部视觉处理" : "External Vision Processing"}</strong><p>{zh ? "允许截图由已配置的第三方视觉模型处理" : "Allow screenshots to be processed by the configured third-party vision model"}</p></div><label className="switch-row"><input type="checkbox" checked={Boolean(settings?.allow_external_processing || pendingConsent)} onChange={(event) => event.target.checked ? setPendingConsent(true) : mutation.mutate(false)} /><span>{settings?.allow_external_processing ? "ON" : "OFF"}</span></label></div>
    {pendingConsent && !settings?.allow_external_processing && <div className="vision-consent" role="alert"><strong>{zh ? "发送屏幕内容前请确认" : "Confirm before screen content can leave this computer"}</strong><p>{zh ? "截图内容可能发送到你配置的第三方模型服务。敏感输入区域会尽可能遮挡，但不要在包含敏感信息的屏幕开启此功能。" : "Screenshots may be sent to your configured third-party model service. Sensitive input regions are redacted where detectable, but do not enable this on screens containing sensitive information."}</p><div className="button-row"><button onClick={() => setPendingConsent(false)}>{zh ? "取消" : "Cancel"}</button><button className="danger" disabled={mutation.isPending || !settings?.route_provider} onClick={() => mutation.mutate(true)}>{zh ? "我了解并开启" : "I understand, enable"}</button></div>{!settings?.route_provider && <small>{zh ? "必须先配置已验证支持图片的视觉模型。" : "Configure a verified image-capable vision model first."}</small>}</div>}
    <div className="provider-actions"><a className="btn" href="#custom-providers">+ {zh ? "添加 Vision Provider" : "Add Vision Provider"}</a><span className="muted">Visual Mode: {settings?.allow_external_processing ? "External Multimodal" : "Local only"}</span></div>
    {message && <p className="muted">{message}</p>}
  </section>;
}

function CustomProvidersPanel({ providers }: { providers: CustomProvider[] }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [storage, setStorage] = useState("session");
  const [modelsEndpoint, setModelsEndpoint] = useState("/models");
  const [defaultModel, setDefaultModel] = useState("");
  const [contextWindow, setContextWindow] = useState("");
  const [testProvider, setTestProvider] = useState(false);
  const [msg, setMsg] = useState("");
  const invalidate = () => qc.invalidateQueries({ queryKey: ["custom-providers"] });
  const create = useMutation({
    mutationFn: async () => {
      const provider = await api.createCustomProvider({
        provider_name: name,
        base_url: testProvider ? "https://third-party-test.invalid/v1" : baseUrl,
        models_endpoint: modelsEndpoint,
        chat_endpoint: "/chat/completions",
        default_model: defaultModel,
        context_window: contextWindow ? Number(contextWindow) : null,
        role_models: {},
        is_default: providers.length === 0,
        test_provider: testProvider,
      });
      if (apiKey) await api.saveCustomCredential(provider.provider_id, apiKey, storage);
      return provider;
    },
    onSuccess: () => {
      setAdding(false); setName(""); setBaseUrl(""); setApiKey(""); setMsg(zh ? "Provider 已保存。" : "Provider saved."); invalidate();
    },
    onError: (error) => setMsg(error instanceof Error ? error.message : String(error)),
  });
  return <section className="card custom-providers-section"><div className="section-heading"><div><span className="eyebrow">OpenAI Compatible · 0..N</span><h2>{zh ? "自定义 API Provider" : "Custom API Providers"}</h2><p className="muted">{zh ? "添加第三方中转或兼容网关，自动发现模型并为不同角色分配路由。" : "Add compatible gateways, discover models, and route roles independently."}</p></div><button className="btn btn-primary" onClick={() => setAdding((value) => !value)}>+ {zh ? "添加 Provider" : "Add Provider"}</button></div>
    {adding && <div className="custom-provider-form"><label className="field">{zh ? "Provider 名称" : "Provider name"}<input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field">Base URL<input value={baseUrl} disabled={testProvider} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://gateway.example.com/v1" /></label><label className="field">API Key<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label><label className="field">Models endpoint<input value={modelsEndpoint} onChange={(event) => setModelsEndpoint(event.target.value)} /></label><label className="field">{zh ? "默认模型（可稍后发现）" : "Default model (discover later)"}<input value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} /></label><label className="field">{zh ? "上下文窗口（高级）" : "Context Window (Advanced)"}<input type="number" min="1" value={contextWindow} onChange={(event) => setContextWindow(event.target.value)} placeholder="128000" /><small>{zh ? "手动值标记为 User Configured" : "Manual values are labeled User Configured"}</small></label><label className="field">{zh ? "凭据存储" : "Credential storage"}<select value={storage} onChange={(event) => setStorage(event.target.value)}><option value="session">{zh ? "仅本次会话" : "Session only"}</option><option value="secure">{zh ? "保存到此电脑" : "Save on this PC"}</option></select></label><label className="check-row"><input type="checkbox" checked={testProvider} onChange={(event) => setTestProvider(event.target.checked)} />{zh ? "隔离测试 Provider（不触网）" : "Isolated test provider (no network)"}</label><div className="provider-actions"><button className="btn btn-primary" disabled={create.isPending || !name || (!baseUrl && !testProvider)} onClick={() => create.mutate()}>{zh ? "保存" : "Save"}</button><button className="btn" onClick={() => setAdding(false)}>{zh ? "取消" : "Cancel"}</button></div></div>}
    {providers.length === 0 && !adding ? <p className="muted">{zh ? "还没有自定义 Provider。" : "No custom providers yet."}</p> : <div className="custom-provider-list">{providers.map((provider) => <CustomProviderCard key={provider.provider_id} provider={provider} zh={zh} onChanged={invalidate} />)}</div>}
    {msg && <p role="status" className="msg">{msg}</p>}
  </section>;
}

function CustomProviderCard({ provider, zh, onChanged }: { provider: CustomProvider; zh: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  const [search, setSearch] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [credentialStorage, setCredentialStorage] = useState("secure");
  const [defaultModel, setDefaultModel] = useState(provider.default_model);
  const [contextWindow, setContextWindow] = useState(provider.context_window ? String(provider.context_window) : "");
  const [roles, setRoles] = useState(provider.role_models);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const action = useMutation({
    mutationFn: async (kind: "test" | "model" | "discover" | "refresh" | "delete" | "credential" | "remove" | "save") => {
      if (kind === "test") return api.testCustomProvider(provider.provider_id);
      if (kind === "model") return api.testCustomModel(provider.provider_id, defaultModel);
      if (kind === "discover" || kind === "refresh") return api.discoverCustomModels(provider.provider_id, kind === "refresh");
      if (kind === "delete") return api.deleteCustomProvider(provider.provider_id);
      if (kind === "credential") return api.saveCustomCredential(provider.provider_id, apiKey, credentialStorage);
      if (kind === "remove") return api.deleteCustomCredential(provider.provider_id);
      return api.updateCustomProvider(provider.provider_id, {
        provider_name: provider.provider_name, base_url: provider.base_url, models_endpoint: provider.models_endpoint, chat_endpoint: provider.chat_endpoint, api_mode: "openai_compatible", default_model: defaultModel, role_models: roles, is_default: provider.is_default, local_provider: provider.local_provider, test_provider: provider.test_provider, context_window: contextWindow ? Number(contextWindow) : null,
      });
    },
    onSuccess: (result, kind) => { setApiKey(""); setMsg(kind === "discover" || kind === "refresh" ? `${(result as { count?: number }).count ?? 0} ${zh ? "个模型" : "models"}` : kind === "model" ? `${zh ? "真实推理通过" : "Real inference passed"} · ${(result as { total_tokens?: number }).total_tokens ?? "—"} tokens · ${(result as { latency_ms?: number }).latency_ms ?? "—"}ms` : (zh ? "操作成功" : "Done")); onChanged(); },
    onError: (error) => setMsg(error instanceof Error ? error.message : String(error)),
  });
  const modelIds = provider.discovered_models.map((item) => item.id).filter((id) => id.toLowerCase().includes(search.toLowerCase()));
  return (
    <article className="custom-provider-card">
      <div className="custom-provider-head">
        <div>
          <h3>
            {provider.provider_name}
            {provider.is_default && <span className="memory-scope">{zh ? "默认" : "Default"}</span>}
          </h3>
          <p className="muted">{provider.base_url} · {provider.model_count} {zh ? "个模型" : "models"}</p>
        </div>
        <span className={`connection-pill ${provider.configured ? "good" : "neutral"}`}>
          {provider.configured ? (zh ? "已配置" : "Configured") : (zh ? "未配置" : "Not configured")}
        </span>
        <span className={`connection-pill ${provider.model_discovery_status === "success" ? "good" : "neutral"}`}>{zh ? "模型发现" : "Discovery"}: {provider.model_discovery_status}</span>
        <span className={`connection-pill ${provider.invocation_status === "success" ? "good" : "neutral"}`}>{zh ? "模型推理" : "Invocation"}: {provider.invocation_status}</span>
      </div>
      <div className="provider-actions">
        <button className="btn" disabled={action.isPending || !provider.configured} onClick={() => action.mutate("test")}>{zh ? "测试连接" : "Test connection"}</button>
        <button className="btn" disabled={action.isPending || !provider.configured} onClick={() => action.mutate(provider.model_count ? "refresh" : "discover")}>{provider.model_count ? (zh ? "刷新模型" : "Refresh models") : (zh ? "发现模型" : "Discover models")}</button>
        <button className="btn btn-primary" disabled={action.isPending || !provider.configured || !defaultModel || provider.test_provider} onClick={() => action.mutate("model")}>{zh ? "测试模型" : "Test Model"}</button>
        <button className="btn" onClick={() => setOpen((value) => !value)}>{open ? (zh ? "收起" : "Close") : (zh ? "管理" : "Manage")}</button>
      </div>
      {open && (
        <div className="provider-manage">
          <label className="field">
            {provider.configured ? (zh ? "替换凭据" : "Replace credential") : "API Key"}
            <input type="password" value={apiKey} autoComplete="off" onChange={(event) => setApiKey(event.target.value)} />
          </label>
          <label className="field">{zh ? "凭据存储" : "Credential storage"}<select value={credentialStorage} onChange={(event) => setCredentialStorage(event.target.value)}><option value="secure">{zh ? "安全保存到此电脑" : "Save securely on this PC"}</option><option value="session">{zh ? "仅本次会话" : "Session only"}</option></select></label>
          <div className="provider-actions">
            <button className="btn" disabled={!apiKey || action.isPending} onClick={() => action.mutate("credential")}>{credentialStorage === "secure" ? (zh ? "安全保存" : "Save securely") : (zh ? "保存凭据" : "Save credential")}</button>
            {provider.configured && <button className="btn btn-danger" onClick={() => action.mutate("remove")}>{zh ? "移除凭据" : "Remove credential"}</button>}
          </div>
          <label className="field">{zh ? "搜索模型" : "Search models"}<input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <label className="field">{zh ? "上下文窗口（高级）" : "Context Window (Advanced)"}<input type="number" min="1" value={contextWindow} onChange={(event) => setContextWindow(event.target.value)} placeholder="128000" /><small>{provider.context_window_source === "USER_CONFIGURED" ? "User Configured" : (zh ? "未知时留空" : "Leave blank when unknown")}</small></label>
          <label className="field">
            {zh ? "默认模型" : "Default model"}
            {modelIds.length ? (
              <select value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)}><option value="">—</option>{modelIds.map((id) => <option key={id}>{id}</option>)}</select>
            ) : <input value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} />}
          </label>
          <div className="role-model-grid">
            {ROLE_KEYS.map((role) => (
              <label className="field" key={role}>{role}<select value={roles[role] ?? ""} onChange={(event) => setRoles((previous) => ({ ...previous, [role]: event.target.value }))}><option value="">{defaultModel || "default"}</option>{modelIds.map((id) => <option key={id}>{id}</option>)}</select></label>
            ))}
          </div>
          <div className="provider-actions"><button className="btn btn-primary" onClick={() => action.mutate("save")}>{zh ? "保存路由" : "Save routes"}</button><button className="btn btn-danger" onClick={() => setConfirmDelete(true)}>{zh ? "删除 Provider" : "Delete provider"}</button></div>
          {confirmDelete && <div className="forget-confirm" role="alert"><p>{zh ? "将删除 Provider 配置、模型缓存和测试凭据。" : "Provider configuration, model cache, and test credential will be removed."}</p><button className="btn btn-danger" onClick={() => action.mutate("delete")}>{zh ? "确定删除" : "Confirm delete"}</button><button className="btn" onClick={() => setConfirmDelete(false)}>{zh ? "取消" : "Cancel"}</button></div>}
        </div>
      )}
      {msg && <p className="msg" role="status">{msg}</p>}
    </article>
  );
}

function SettingsCard({
  title,
  description,
  provider,
  health,
  actionLabel,
  children,
}: {
  title: string;
  description: string;
  provider: string;
  health: string;
  actionLabel: string;
  children: React.ReactNode;
}) {
  const { lang, t } = useI18n();
  const [open, setOpen] = useState(false);
  const label = connectionLabel(health, lang);
  const tone = label === t("settings.connected") ? "good" : label === t("settings.notConfigured") ? "neutral" : "warn";
  return (
    <section className={`card settings-card settings-${tone}`}>
      <div className="settings-card-head">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className={`connection-pill ${tone}`}>{label}</span>
      </div>
      <div className="settings-provider"><span>{t("settings.provider")}</span><strong>{provider}</strong></div>
      <button className="btn settings-action" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {open ? t("common.close") : actionLabel}
      </button>
      {open && <div className="settings-editor">{children}</div>}
    </section>
  );
}

function ProviderEditor({
  family,
  providers,
  connections,
}: {
  family: "models" | "github";
  providers: Array<[string, string]>;
  connections: Record<string, ConnectionStatus> | undefined;
}) {
  const { lang, t } = useI18n();
  const qc = useQueryClient();
  const [provider, setProvider] = useState(providers[0][0]);
  const conn = connections?.[provider];
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [mode, setMode] = useState<"session" | "secure">("session");
  const [model, setModel] = useState("");
  const [useDefault, setUseDefault] = useState(true);
  const [roleModels, setRoleModels] = useState<Record<string, string>>({});
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [manualModel, setManualModel] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setBaseUrl(conn?.base_url ?? "");
    setModel(conn?.models.default ?? "");
    setRoleModels(conn?.models ?? {});
    setApiKey("");
    setMsg("");
  }, [conn, provider]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["connections"] });
    qc.invalidateQueries({ queryKey: ["settings"] });
  };
  const save = useMutation({
    mutationFn: () => api.saveConnection(provider, {
      base_url: baseUrl || undefined,
      api_key: apiKey || undefined,
      storage_mode: mode,
      local_provider: provider === "ollama",
      models: family === "models"
        ? useDefault
          ? { default: model }
          : { default: model, ...roleModels }
        : undefined,
    }),
    onSuccess: () => {
      setApiKey("");
      setMsg(t("settings.saved"));
      invalidate();
    },
    onError: (error) => setMsg(error instanceof Error ? error.message : String(error)),
  });
  const test = useMutation({
    mutationFn: () => api.testConnection(provider),
    onSuccess: (result) => {
      setMsg(`${t("settings.testPrefix")}: ${connectionLabel(result.status, lang)}`);
      invalidate();
    },
    onError: (error) => setMsg(error instanceof Error ? error.message : String(error)),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteCredential(provider),
    onSuccess: () => {
      setApiKey("");
      setMsg(t("settings.credentialRemoved"));
      invalidate();
    },
    onError: (error) => setMsg(error instanceof Error ? error.message : String(error)),
  });
  const discover = useMutation({
    mutationFn: () => api.discoverModels(provider),
    onSuccess: (result) => {
      setModelOptions(result.models);
      setManualModel(!result.supported || result.models.length === 0);
      if (!model && result.models[0]) setModel(result.models[0]);
      setMsg(result.models.length ? t("settings.modelsFound").replace("{count}", String(result.models.length)) : t("settings.manualModelHint"));
    },
    onError: () => {
      setManualModel(true);
      setMsg(t("settings.manualModelHint"));
    },
  });

  const providerLabel = useMemo(() => providers.find(([value]) => value === provider)?.[1] ?? provider, [provider, providers]);
  const noCredential = provider === "ollama";

  return (
    <div className="provider-editor">
      <label className="field">
        {t("settings.provider")}
        <select value={provider} onChange={(event) => setProvider(event.target.value)} aria-label={`${t("settings.provider")} ${family}`}>
          {providers.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <div className="inline-status">
        <span>{providerLabel}</span>
        <strong>{connectionLabel(conn?.health, lang)}</strong>
      </div>
      {!noCredential && (
        <label className="field">
          {family === "github" ? t("settings.token") : t("settings.apiKey")}
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={conn?.configured ? t("settings.replaceCredential") : t("settings.enterCredential")}
          />
        </label>
      )}
      {family === "models" && (
        <>
          <div className="model-row">
            <button className="btn" disabled={discover.isPending} onClick={() => discover.mutate()}>{t("settings.discoverModels")}</button>
            {modelOptions.length > 0 && !manualModel ? (
              <select value={model} onChange={(event) => setModel(event.target.value)} aria-label={t("settings.defaultModel")}>
                {modelOptions.map((item) => <option key={item}>{item}</option>)}
              </select>
            ) : (
              <input value={model} onChange={(event) => setModel(event.target.value)} placeholder={t("settings.manualModel")} aria-label={t("settings.defaultModel")} />
            )}
          </div>
          <label className="check-row">
            <input type="checkbox" checked={useDefault} onChange={(event) => setUseDefault(event.target.checked)} />
            {t("settings.useDefaultAll")}
          </label>
        </>
      )}
      <details>
        <summary>{t("settings.advancedConfig")}</summary>
        <label className="field">
          {t("settings.baseUrl")}
          <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} spellCheck={false} />
        </label>
        {!noCredential && (
          <label className="field">
            {t("settings.storage")}
            <select value={mode} onChange={(event) => setMode(event.target.value as "session" | "secure")}>
              <option value="session">{t("settings.sessionOnly")}</option>
              <option value="secure">{t("settings.saveOnThisPC")}</option>
            </select>
          </label>
        )}
        {family === "models" && !useDefault && (
          <div className="role-model-grid">
            {ROLE_KEYS.map((role) => (
              <label className="field" key={role}>
                {displayLabel(role, lang)}
                <input value={roleModels[role] ?? ""} onChange={(event) => setRoleModels((prev) => ({ ...prev, [role]: event.target.value }))} placeholder={model || t("settings.manualModel")} />
              </label>
            ))}
          </div>
        )}
      </details>
      <div className="provider-actions">
        <button className="btn" disabled={test.isPending || !conn?.configured} onClick={() => test.mutate()}>{t("settings.testConnection")}</button>
        <button className="btn btn-primary" disabled={save.isPending || (!noCredential && !apiKey && !conn?.configured)} onClick={() => save.mutate()}>{conn?.configured ? t("settings.update") : t("settings.saveSecurely")}</button>
        {conn?.configured && !noCredential && <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>{t("settings.removeCredential")}</button>}
      </div>
      {msg && <p className="msg" role="status">{msg}</p>}
    </div>
  );
}

function aggregateHealth(items: Array<ConnectionStatus | undefined>): string {
  const configured = items.find((item) => item?.configured);
  return configured?.health ?? "missing";
}

function preferredProvider(items: Array<ConnectionStatus | undefined>): string {
  const provider = items.find((item) => item?.configured)?.provider ?? items.find(Boolean)?.provider;
  const labels: Record<string, string> = {
    openai_compatible: "OpenAI Compatible",
    test_provider: "Test Provider",
    github_test: "GitHub Test",
    github: "GitHub",
    ollama: "Ollama",
  };
  return provider ? labels[provider] ?? provider.replaceAll("_", " ") : "—";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}
