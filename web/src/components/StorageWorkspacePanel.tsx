import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, HardDrive, ShieldCheck, Trash2 } from "lucide-react";
import { FormEvent, useState } from "react";

import { api } from "../api/client";
import type { StorageRoot, StorageSummary } from "../api/types";
import { useI18n } from "../i18n";

const ROOT_LABELS: Record<string, [string, string]> = {
  app_install: ["应用安装目录", "App Install Root"],
  data: ["数据根目录", "Data Root"],
  memory: ["记忆目录", "Memory Root"],
  workspace: ["工作区目录", "Workspace Root"],
  artifact: ["交付物目录", "Artifact Root"],
  snapshot: ["快照目录", "Snapshot Root"],
  cache: ["缓存目录", "Cache Root"],
  log: ["日志目录", "Log Root"],
};

function formatBytes(value: number | null) {
  if (value === null) return "–";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function StorageWorkspacePanel() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["storage"], queryFn: api.storageStatus });
  const data = query.data;
  const [message, setMessage] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["storage"] });
  };

  const migrate = useMutation({
    mutationFn: ({ key, target }: { key: "memory" | "workspace"; target: string }) =>
      api.migrateStorageRoot(key, target),
    onSuccess: (result) => {
      setMessage(zh ? `已迁移 ${ROOT_LABELS[result.key][0]} → ${result.to}` : `Migrated ${ROOT_LABELS[result.key][1]} → ${result.to}`);
      refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const clean = useMutation({
    mutationFn: (key: "cache" | "log" | "snapshot") => api.cleanupStorageRoot(key),
    onSuccess: (result) => {
      setMessage(zh ? `已清理，释放 ${formatBytes(result.removed_bytes)}` : `Cleaned, freed ${formatBytes(result.removed_bytes)}`);
      refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const override = useMutation({
    mutationFn: ({ projectId, target }: { projectId: string; target: string | null }) =>
      api.setWorkspaceOverride(projectId, target),
    onSuccess: () => {
      setMessage(zh ? "Project Workspace override 已更新。" : "Project workspace override updated.");
      refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  if (query.isLoading) return <section className="card settings-section"><span className="eyebrow">Storage & Workspace</span><p className="muted">{zh ? "正在读取目录状态…" : "Loading storage status…"}</p></section>;
  if (!data) return null;

  return (
    <section className="card settings-section" id="storage-workspace">
      <div className="section-heading">
        <div>
          <span className="eyebrow"><HardDrive size={13} /> Storage & Workspace</span>
          <h2>{zh ? "存储与工作区" : "Storage & Workspace"}</h2>
          <p className="muted">
            {zh
              ? "应用安装目录只读。Memory 与 Workspace 可选择目录，路径修改会原子迁移、校验，失败自动回滚。Secret 以 DPAPI 密文迁移，绝不转明文。"
              : "The app install directory is read-only. Memory and Workspace accept custom directories; path changes migrate atomically, verify, and roll back on failure. Secrets migrate as DPAPI ciphertext, never plaintext."}
          </p>
        </div>
        <button className="btn" onClick={refresh}>{zh ? "刷新" : "Refresh"}</button>
      </div>

      <div className="storage-root-grid">
        {data.roots.map((root) => (
          <StorageRootRow key={root.key} root={root} zh={zh} onMigrate={(target) => migrate.mutate({ key: root.key as "memory" | "workspace", target })} onClean={() => clean.mutate(root.key as "cache" | "log" | "snapshot")} busy={migrate.isPending || clean.isPending} />
        ))}
      </div>

      <ProjectWorkspaceEditor overrides={data.project_workspace_overrides} zh={zh} onSave={(projectId, target) => override.mutate({ projectId, target })} />

      <div className="storage-policy">
        <ShieldCheck size={15} />
        <span>{zh ? "Secret 策略" : "Secret policy"}: {data.secret_policy.storage} · {data.secret_policy.migration}</span>
        {data.app_install_readonly && <em>{zh ? "App 安装目录只读，禁止写入用户数据" : "App install directory is read-only; no user data is written there"}</em>}
      </div>
      {message && <p className="muted storage-message" role="status">{message}</p>}
    </section>
  );
}

function StorageRootRow({ root, zh, onMigrate, onClean, busy }: {
  root: StorageRoot;
  zh: boolean;
  onMigrate: (target: string) => void;
  onClean: () => void;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState("");
  const [label] = ROOT_LABELS[root.key] ?? [root.key, root.key];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!target.trim()) return;
    onMigrate(target.trim());
    setEditing(false);
    setTarget("");
  };
  return (
    <div className={`storage-root ${root.readonly ? "readonly" : ""}`}>
      <div className="storage-root-head">
        <FolderOpen size={14} />
        <strong>{zh ? label : ROOT_LABELS[root.key][1]}</strong>
        {root.readonly && <em>{zh ? "只读" : "read-only"}</em>}
        {root.user_selectable && <em className="selectable">{zh ? "可修改" : "selectable"}</em>}
        {root.cleanable && <em className="cleanable">{zh ? "可清理" : "cleanable"}</em>}
      </div>
      <code className="storage-path" title={root.path}>{root.path}</code>
      <div className="storage-root-meta">
        <span>{zh ? "大小" : "Size"}: <b>{formatBytes(root.size_bytes)}</b></span>
        {!root.exists && <span className="muted">{zh ? "尚未创建" : "not created"}</span>}
      </div>
      <div className="storage-root-actions">
        {root.user_selectable && !editing && (
          <button className="btn small" disabled={busy} onClick={() => setEditing(true)}>{zh ? "修改目录" : "Change directory"}</button>
        )}
        {root.cleanable && (
          <button className="btn small danger" disabled={busy} onClick={onClean}><Trash2 size={12} />{zh ? "安全清理" : "Clean"}</button>
        )}
      </div>
      {editing && (
        <form className="storage-migrate" onSubmit={submit}>
          <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder={zh ? "输入新目录绝对路径" : "Absolute path of the new directory"} aria-label={`${label} ${zh ? "新路径" : "new path"}`} />
          <div className="button-row">
            <button type="submit" className="btn small" disabled={!target.trim() || busy}>{zh ? "迁移" : "Migrate"}</button>
            <button type="button" className="btn small" onClick={() => setEditing(false)}>{zh ? "取消" : "Cancel"}</button>
          </div>
        </form>
      )}
    </div>
  );
}

function ProjectWorkspaceEditor({ overrides, zh, onSave }: {
  overrides: Record<string, string>;
  zh: boolean;
  onSave: (projectId: string, target: string | null) => void;
}) {
  const [projectId, setProjectId] = useState("");
  const [target, setTarget] = useState("");
  const entries = Object.entries(overrides);
  return (
    <div className="storage-project-overrides">
      <div className="section-subheading"><strong>{zh ? "Project Workspace override" : "Project Workspace overrides"}</strong><p className="muted">{zh ? "每个项目可单独指定工作区目录；未设置时使用全局默认 Workspace。" : "Each project can pin its own workspace directory; unset projects use the global default Workspace."}</p></div>
      {entries.length > 0 && (
        <div className="override-list">
          {entries.map(([project, path]) => (
            <div key={project} className="override-row">
              <strong>{project}</strong><code>{path}</code>
              <button className="btn small" onClick={() => onSave(project, null)}>{zh ? "清除" : "Clear"}</button>
            </div>
          ))}
        </div>
      )}
      <form className="override-form" onSubmit={(event) => { event.preventDefault(); if (!projectId.trim() || !target.trim()) return; onSave(projectId.trim(), target.trim()); setProjectId(""); setTarget(""); }}>
        <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder={zh ? "项目 ID" : "Project ID"} aria-label={zh ? "项目 ID" : "Project ID"} />
        <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder={zh ? "该项目的 Workspace 目录" : "Workspace directory for this project"} aria-label={zh ? "该项目的工作区目录" : "Workspace directory"} />
        <button type="submit" className="btn small" disabled={!projectId.trim() || !target.trim()}>{zh ? "设置" : "Set"}</button>
      </form>
    </div>
  );
}

export function storageSummaryForTest(data: StorageSummary | undefined): string {
  return data ? `${data.roots.length} roots` : "loading";
}
