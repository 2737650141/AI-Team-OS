// Setup 向导（010 三十七 / 009-A 二十一）：Step 1 Provider → 2 Connection → 3 Test → 4 Models → 5 GitHub → 6 Done
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useI18n } from "../i18n";

export function Setup() {
  const { t } = useI18n();
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
      setMsg(t("settings.saved"));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const test = async () => {
    try {
      // 先保存当前表单（否则 Test 拿不到刚输入的 Key，sa_20260808_120531）
      if (baseUrl || apiKey) await save();
      const r = await api.testConnection(provider);
      setTestMsg(`${t("settings.testPrefix")}: ${r.status}`);
    } catch (e) {
      setTestMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const STEPS = [
    t("setup.stepProvider"),
    t("setup.stepConnection"),
    t("setup.stepTest"),
    t("setup.stepModels"),
    t("setup.stepGithub"),
    t("setup.stepDone"),
  ];

  return (
    <div className="page narrow">
      <h1>{t("setup.welcome")}</h1>
      <p className="muted">{t("setup.noKeyRequired")}</p>
      <div className="steps">
        {STEPS.map((s, i) => (
          <span key={s} className={i + 1 === step ? "step on" : i + 1 < step ? "step done" : "step"}>
            {s}
          </span>
        ))}
      </div>

      {step === 1 && (
        <div className="card">
          <h2>{t("setup.step1Title")}</h2>
          {(["openai_compatible", "ollama"] as const).map((p) => (
            <label key={p} className="radio">
              <input
                type="radio"
                checked={provider === p}
                onChange={() => setProvider(p)}
              />
              {p === "openai_compatible" ? t("setup.openaiCompatible") : t("setup.ollamaLocal")}
            </label>
          ))}
          <button className="btn btn-primary" onClick={() => setStep(2)}>
            {t("setup.next")}
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="card">
          <h2>{t("setup.step2Title")}</h2>
          <label className="field">
            {t("settings.baseUrl")}
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={provider === "ollama" ? "http://127.0.0.1:11434" : "https://…/v1"}
            />
          </label>
          {provider !== "ollama" && (
            <label className="field">
              {t("settings.apiKey")}
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
            {t("setup.next")}
          </button>
        </div>
      )}

      {step === 3 && (
        <div className="card">
          <h2>Step 3 · {t("setup.stepTest")}</h2>
          <button className="btn" onClick={test}>
            {t("settings.testConnection")}
          </button>
          {testMsg && <p className="msg">{testMsg}</p>}
          <button className="btn btn-primary" onClick={save}>
            {t("common.save")}
          </button>
          {msg && <p className="msg">{msg}</p>}
          <button className="btn" onClick={() => setStep(4)}>
            {t("setup.next")}
          </button>
        </div>
      )}

      {step === 4 && (
        <div className="card">
          <h2>Step 4 · {t("setup.stepModels")}</h2>
          <p className="muted">{t("setup.modelsHint")}</p>
          <button className="btn btn-primary" onClick={() => setStep(5)}>
            {t("setup.next")}
          </button>
        </div>
      )}

      {step === 5 && (
        <div className="card">
          <h2>Step 5 · {t("setup.stepGithub")} ({t("setup.optional")})</h2>
          <p className="muted">{t("setup.githubHint")}</p>
          <button className="btn btn-primary" onClick={() => setStep(6)}>
            {t("setup.next")}
          </button>
        </div>
      )}

      {step === 6 && (
        <div className="card">
          <h2>{t("setup.stepDone")}</h2>
          <Link className="btn btn-primary" to="/">
            {t("setup.start")}
          </Link>
          <Link className="btn" to="/">
            {t("setup.tryDemo")}
          </Link>
        </div>
      )}
    </div>
  );
}
