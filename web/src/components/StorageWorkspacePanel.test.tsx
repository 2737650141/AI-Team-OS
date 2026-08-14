// 024-A Storage & Workspace 前端测试（STORAGE 前端门禁）
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { StorageSummary } from "../api/types";
import { I18nProvider } from "../i18n";
import { StorageWorkspacePanel } from "./StorageWorkspacePanel";

const summary: StorageSummary = {
  roots: [
    { key: "app_install", path: "C:\\Program Files\\AI Team OS", default_path: "C:\\Program Files\\AI Team OS", exists: true, size_bytes: 512000, user_selectable: false, cleanable: false, readonly: true },
    { key: "data", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os", exists: true, size_bytes: 1048576, user_selectable: false, cleanable: false, readonly: false },
    { key: "memory", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\memory", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\memory", exists: true, size_bytes: 2048, user_selectable: true, cleanable: false, readonly: false },
    { key: "workspace", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\workspaces", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\workspaces", exists: true, size_bytes: 40960, user_selectable: true, cleanable: false, readonly: false },
    { key: "artifact", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\artifacts", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\artifacts", exists: true, size_bytes: 1234, user_selectable: false, cleanable: false, readonly: false },
    { key: "snapshot", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\evidence", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\evidence", exists: true, size_bytes: 9999, user_selectable: false, cleanable: true, readonly: false },
    { key: "cache", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\cache", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\cache", exists: true, size_bytes: 880000, user_selectable: false, cleanable: true, readonly: false },
    { key: "log", path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\logs", default_path: "C:\\Users\\me\\AppData\\Roaming\\ai-team-os\\runtime\\logs", exists: false, size_bytes: null, user_selectable: false, cleanable: true, readonly: false },
  ],
  project_workspace_overrides: { "project-a": "D:\\ws\\project-a" },
  project_profiles: [{ project_id: "project-a", name: "Project A", workspace_path: "D:\\ws\\project-a", memory_scope: "project", artifact_path: "D:\\artifacts\\project-a" }],
  secret_policy: { storage: "windows_secure_store_dpapi", migration: "encrypted_blobs_only" },
  app_install_readonly: true,
};

const qc = () => new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

function renderPanel() {
  return render(
    <QueryClientProvider client={qc()}>
      <I18nProvider>
        <MemoryRouter>
          <StorageWorkspacePanel />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.restoreAllMocks());

describe("StorageWorkspacePanel", () => {
  it("shows all eight roots with sizes and read-only app install", async () => {
    vi.spyOn(api, "storageStatus").mockResolvedValue(summary);
    renderPanel();
    expect(await screen.findByText("应用安装目录")).toBeInTheDocument();
    expect(screen.getByText("记忆目录")).toBeInTheDocument();
    expect(screen.getByText("工作区目录")).toBeInTheDocument();
    expect(screen.getByText("缓存目录")).toBeInTheDocument();
    expect(screen.getByText("日志目录")).toBeInTheDocument();
    expect(screen.getAllByText("只读")).toHaveLength(1);
    expect(screen.getAllByText("可修改").length).toBe(2);
    expect(screen.getAllByText("可清理").length).toBe(3);
    // 大小显示（1.0 MB）
    expect(screen.getAllByText(/1\.0 MB/).length).toBeGreaterThan(0);
  });

  it("migrates a user-selectable root through the API", async () => {
    vi.spyOn(api, "storageStatus").mockResolvedValue(summary);
    const migrate = vi.spyOn(api, "migrateStorageRoot").mockResolvedValue({ key: "memory", migrated: true, from: summary.roots[2].path, to: "D:\\memory-new", size_bytes: 2048 });
    renderPanel();
    await screen.findByText("记忆目录");
    const changeButtons = screen.getAllByRole("button", { name: "修改目录" });
    expect(changeButtons.length).toBe(2);
    await userEvent.click(changeButtons[0]);
    const input = await screen.findByLabelText("记忆目录 新路径");
    await userEvent.type(input, "D:\\memory-new");
    await userEvent.click(screen.getByRole("button", { name: "迁移" }));
    await waitFor(() => expect(migrate).toHaveBeenCalledWith("memory", "D:\\memory-new"));
    expect(await screen.findByText(/已迁移 记忆目录/)).toBeInTheDocument();
  });

  it("cleans a cleanable root", async () => {
    vi.spyOn(api, "storageStatus").mockResolvedValue(summary);
    const clean = vi.spyOn(api, "cleanupStorageRoot").mockResolvedValue({ key: "cache", cleaned: true, removed_bytes: 880000 });
    renderPanel();
    await screen.findByText("缓存目录");
    const cleanButtons = screen.getAllByRole("button", { name: "安全清理" });
    expect(cleanButtons.length).toBe(3);
    // roots 顺序：snapshot / cache / log → cache 是第 2 个
    await userEvent.click(cleanButtons[1]);
    await waitFor(() => expect(clean).toHaveBeenCalledWith("cache"));
    expect(await screen.findByText(/已清理/)).toBeInTheDocument();
  });

  it("sets and clears a complete project storage profile", async () => {
    vi.spyOn(api, "storageStatus").mockResolvedValue(summary);
    const setOverride = vi.spyOn(api, "setWorkspaceOverride").mockResolvedValue({ project_id: "project-a", workspace: "D:\\ws\\project-a" });
    renderPanel();
    expect(await screen.findByText("Project A")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("项目 ID"), "project-b");
    await userEvent.type(screen.getByLabelText("项目名称"), "Project B");
    await userEvent.type(screen.getByLabelText("Workspace 路径"), "D:\\ws\\project-b");
    await userEvent.type(screen.getByLabelText("Artifact 路径"), "D:\\artifacts\\project-b");
    await userEvent.click(screen.getByRole("button", { name: "设置" }));
    await waitFor(() => expect(setOverride).toHaveBeenCalledWith("project-b", "D:\\ws\\project-b", "Project B", "project", "D:\\artifacts\\project-b"));
  });

  it("shows the secret migration policy", async () => {
    vi.spyOn(api, "storageStatus").mockResolvedValue(summary);
    renderPanel();
    await screen.findByText("应用安装目录");
    expect(screen.getByText(/Secret 策略/)).toBeInTheDocument();
    expect(screen.getByText(/windows_secure_store_dpapi/)).toBeInTheDocument();
    expect(screen.getByText(/encrypted_blobs_only/)).toBeInTheDocument();
    expect(screen.getByText(/App 安装目录只读，禁止写入用户数据/)).toBeInTheDocument();
  });
});
