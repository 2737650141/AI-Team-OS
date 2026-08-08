// Settings + Connections（010 二十五/三十~三十六 / 009-A）
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";

export function Settings() {
  const status = useQuery({ queryKey: ["settings"], queryFn: api.settingsStatus });
  const conns = useQuery({ queryKey: ["connections"], queryFn: api.connections });

  return (
    <div className="page">
      <h1>Settings</h1>
      <div className="card">
        <h2>System Status</h2>
        <pre className="json">{JSON.stringify(status.data ?? {}, null, 2)}</pre>
      </div>
      <div className="card">
        <h2>Connections</h2>
        <p className="muted">
          Configure model providers / GitHub / Ollama. Credentials never leave this machine.
        </p>
        <div className="conn-grid">
          <ProviderCard provider="openai_compatible" conn={conns.data?.openai_compatible} />
          <ProviderCard provider="github" conn={conns.data?.github} />
          <ProviderCard provider="ollama" conn={conns.data?.ollama} local />
        </div>
      </div>
      <p className="muted">
        First-time setup? <Link to="/setup">Run the setup wizard</Link>.
      </p>
    </div>
  );
}

function ProviderCard({
  provider,
  conn,
  local,
}: {
  provider: string;
  conn: import("../api/types").ConnectionStatus | undefined;
  local?: boolean;
}) {
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
      setMsg("Saved");
      invalidate();
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : String(e)),
  });

  const test = useMutation({
    mutationFn: () => api.testConnection(provider),
    onSuccess: (r) => setMsg(`Test: ${r.status}`),
    onError: (e) => setMsg(e instanceof Error ? e.message : String(e)),
  });

  const remove = useMutation({
    mutationFn: () => api.deleteCredential(provider),
    onSuccess: () => {
      setApiKey("");
      setMsg("Credential removed");
      invalidate();
    },
  });

  return (
    <div className="card provider-card">
      <div className="provider-head">
        <strong>{provider}</strong>
        <span className={conn?.configured ? "dot green" : "dot gray"} />
        <span className="muted">{conn?.storage ?? "missing"}</span>
      </div>
      <label className="field">
        Base URL
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={local ? "http://127.0.0.1:11434" : "https://…/v1"}
          spellCheck={false}
        />
      </label>
      <label className="field">
        API Key
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={conn?.configured ? "•••••••• (configured)" : "Enter API key"}
        />
      </label>
      <div className="field">
        Storage
        <label className="seg">
          <button className={mode === "secure" ? "on" : ""} onClick={() => setMode("secure")}>
            Save on this PC
          </button>
          <button className={mode === "session" ? "on" : ""} onClick={() => setMode("session")}>
            Session only
          </button>
        </label>
      </div>
      <div className="provider-actions">
        <button className="btn" disabled={test.isPending} onClick={() => test.mutate()}>
          Test Connection
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
          Save securely
        </button>
        <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
          Remove
        </button>
      </div>
      {msg && <p className="msg">{msg}</p>}
    </div>
  );
}
