// Settings + Connections（010 二十五/三十~三十六 / 009-A）
// 010-B 九：i18n；010-B 十：安全显示（仅 Configured/Not configured/Healthy/Disabled）
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useI18n } from "../i18n";

export function Settings() {
  const { t } = useI18n();
  const status = useQuery({ queryKey: ["settings"], queryFn: api.settingsStatus });
  const conns = useQuery({ queryKey: ["connections"], queryFn: api.connections });

  return (
    <div className="page">
      <h1>{t("settings.title")}</h1>
      <div className="card">
        <h2>{t("settings.systemStatus")}</h2>
        <pre className="json">{JSON.stringify(status.data ?? {}, null, 2)}</pre>
      </div>
      <div className="card">
        <h2>{t("settings.connections")}</h2>
        <p className="muted">{t("settings.intro")}</p>
        <div className="conn-grid">
          <ProviderCard
            provider="openai_compatible"
            conn={conns.data?.openai_compatible}
            title={t("settings.providerOpenAI")}
          />
          <ProviderCard provider="github" conn={conns.data?.github} title={t("settings.providerGithub")} />
          <ProviderCard
            provider="ollama"
            conn={conns.data?.ollama}
            local
            title={t("settings.providerOllama")}
          />
        </div>
      </div>
      <p className="muted">
        {t("settings.setupPrompt")} <Link to="/setup">{t("settings.runWizard")}</Link>.
      </p>
    </div>
  );
}

function ProviderCard({
  provider,
  conn,
  local,
  title,
}: {
  provider: string;
  conn: import("../api/types").ConnectionStatus | undefined;
  local?: boolean;
  title: string;
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [baseUrl, setBaseUrl] = useState(conn?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [mode, setMode] = useState<"session" | "secure">("secure");
  const [msg, setMsg] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["connections"] });
    qc.invalidateQueries({ queryKey: ["settings"] });
  };

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.saveConnection(provider, body),
    onSuccess: () => {
      setApiKey(""); // 提交后立即清空前端变量（010 三十一）
      setMsg(t("settings.saved"));
      invalidate();
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : String(e)),
  });

  const test = useMutation({
    mutationFn: () => api.testConnection(provider),
    onSuccess: (r) => setMsg(`${t("settings.testPrefix")}: ${r.status}`),
    onError: (e) => setMsg(e instanceof Error ? e.message : String(e)),
  });

  const remove = useMutation({
    mutationFn: () => api.deleteCredential(provider),
    onSuccess: () => {
      setApiKey("");
      setMsg(t("common.delete"));
      invalidate();
    },
  });

  return (
    <div className="card provider-card">
      <div className="provider-head">
        <strong>{title}</strong>
        <span className={conn?.configured ? "dot green" : "dot gray"} />
        {/* 010-B 十：只显示状态，不显示任何凭据信息 */}
        <span className="muted">{conn?.configured ? t("settings.configured") : t("settings.notConfigured")}</span>
      </div>
      {local && <p className="muted">{t("settings.ollamaDesc")}</p>}
      <label className="field">
        {t("settings.baseUrl")}
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={local ? "http://127.0.0.1:11434" : "https://…/v1"}
          spellCheck={false}
        />
      </label>
      <label className="field">
        {t("settings.apiKey")}
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={t("settings.maskEmpty")}
        />
      </label>
      <div className="field">
        {t("settings.storage")}
        <label className="seg">
          <button className={mode === "secure" ? "on" : ""} onClick={() => setMode("secure")}>
            {t("settings.saveOnThisPC")}
          </button>
          <button className={mode === "session" ? "on" : ""} onClick={() => setMode("session")}>
            Session only
          </button>
        </label>
      </div>
      <div className="provider-actions">
        <button className="btn" disabled={test.isPending} onClick={() => test.mutate()}>
          {t("settings.testConnection")}
        </button>
        <button
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() =>
            save.mutate({
              base_url: baseUrl || undefined,
              api_key: apiKey || undefined,
              storage_mode: mode,
              local_provider: !!local,
            })
          }
        >
          {t("settings.saveSecurely")}
        </button>
        <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          {t("common.delete")}
        </button>
      </div>
      {msg && <p className="msg">{msg}</p>}
    </div>
  );
}
