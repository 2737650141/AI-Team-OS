// Setup 向导（010 三十七 / 009-A 二十一）：Step 1 Provider → 2 Connection → 3 Test → 4 Models → 5 GitHub → 6 Done
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";

export function Setup() {
  const [step, setStep] = useState(1);
  const [provider, setProvider] = useState("openai_compatible");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testMsg, setTestMsg] = useState("");
  const [msg, setMsg] = useState("");

  const save = async () => {
    try {
      await api.saveConnection(provider, {
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        storage_mode: "secure",
        local_provider: provider === "ollama",
      });
      setApiKey("");
      setMsg("Saved");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const test = async () => {
    try {
      const r = await api.testConnection(provider);
      setTestMsg(`Test: ${r.status}`);
    } catch (e) {
      setTestMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="page narrow">
      <h1>Welcome to AI Team OS</h1>
      <p className="muted">No API key required — you can always try Demo Mode.</p>
      <div className="steps">
        {["Provider", "Connection", "Test", "Models", "GitHub", "Done"].map((s, i) => (
          <span key={s} className={i + 1 === step ? "step on" : i + 1 < step ? "step done" : "step"}>
            {s}
          </span>
        ))}
      </div>

      {step === 1 && (
        <div className="card">
          <h2>Step 1 · Model Provider</h2>
          {(["openai_compatible", "ollama"] as const).map((p) => (
            <label key={p} className="radio">
              <input
                type="radio"
                checked={provider === p}
                onChange={() => setProvider(p)}
              />
              {p === "openai_compatible" ? "OpenAI Compatible" : "Ollama (local, no key)"}
            </label>
          ))}
          <button className="btn btn-primary" onClick={() => setStep(2)}>
            Next
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="card">
          <h2>Step 2 · API Connection</h2>
          <label className="field">
            Base URL
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={provider === "ollama" ? "http://127.0.0.1:11434" : "https://…/v1"}
            />
          </label>
          {provider !== "ollama" && (
            <label className="field">
              API Key
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </label>
          )}
          <button className="btn btn-primary" onClick={() => setStep(3)}>
            Next
          </button>
        </div>
      )}

      {step === 3 && (
        <div className="card">
          <h2>Step 3 · Test Connection</h2>
          <button className="btn" onClick={test}>
            Test
          </button>
          {testMsg && <p className="msg">{testMsg}</p>}
          <button className="btn btn-primary" onClick={save}>
            Save
          </button>
          {msg && <p className="msg">{msg}</p>}
          <button className="btn" onClick={() => setStep(4)}>
            Next
          </button>
        </div>
      )}

      {step === 4 && (
        <div className="card">
          <h2>Step 4 · Models</h2>
          <p className="muted">Use default model for all roles (per-role config coming in UI).</p>
          <button className="btn btn-primary" onClick={() => setStep(5)}>
            Next
          </button>
        </div>
      )}

      {step === 5 && (
        <div className="card">
          <h2>Step 5 · GitHub (optional)</h2>
          <p className="muted">Skip for now — can be added later in Settings → Connections.</p>
          <button className="btn btn-primary" onClick={() => setStep(6)}>
            Next
          </button>
        </div>
      )}

      {step === 6 && (
        <div className="card">
          <h2>Done</h2>
          <Link className="btn btn-primary" to="/">
            Start AI Team OS
          </Link>
          <Link className="btn" to="/tasks">
            Try Demo Mode
          </Link>
        </div>
      )}
    </div>
  );
}
