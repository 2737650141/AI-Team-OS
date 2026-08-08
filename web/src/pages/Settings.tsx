import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { ConnectionStatus } from "../api/types";
import { useI18n } from "../i18n";
import { connectionLabel, displayLabel } from "../i18n/labels";

const ROLE_KEYS = ["supervisor", "planner", "researcher", "executor", "reviewer"];

export function Settings() {
  const { lang, t } = useI18n();
  const status = useQuery({ queryKey: ["settings"], queryFn: api.settingsStatus });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const conns = useQuery({ queryKey: ["connections"], queryFn: api.connections });
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
