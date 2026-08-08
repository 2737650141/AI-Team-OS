// Settings/Connections 前端测试（010 四十九：Secret 表单）
// i18n 默认中文（010-B 九）；provider 显示标题（OpenAI 兼容 / Ollama）
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { I18nProvider } from "../i18n";
import { Settings } from "./Settings";

const qc = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.restoreAllMocks());

describe("Settings · Connections", () => {
  it("shows provider status without secrets", async () => {
    vi.spyOn(api, "settingsStatus").mockResolvedValue({ model_provider: { status: "Missing" } });
    vi.spyOn(api, "connections").mockResolvedValue({
      openai_compatible: {
        provider: "openai_compatible", configured: false, base_url: "",
        models: {}, storage: "missing", health: "missing",
      },
      github: { provider: "github", configured: false, base_url: "", models: {}, storage: "missing", health: "missing" },
      ollama: { provider: "ollama", configured: true, base_url: "http://127.0.0.1:11434", models: {}, storage: "local_provider", health: "configured" },
    });
    render(
      <QueryClientProvider client={qc()}>
        <I18nProvider>
          <MemoryRouter>
            <Settings />
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("连接")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("OpenAI 兼容")).toBeInTheDocument());
    expect(screen.getByText("Ollama")).toBeInTheDocument();
    // 安全显示：只显示状态，不显示 base_url / storage 细节
    await waitFor(() => expect(screen.getByText("已配置")).toBeInTheDocument());
    expect(screen.queryByText("http://127.0.0.1:11434")).not.toBeInTheDocument();
  });

  it("submits api key via password field and never stores it in the DOM", async () => {
    vi.spyOn(api, "settingsStatus").mockResolvedValue({});
    vi.spyOn(api, "connections").mockResolvedValue({
      openai_compatible: { provider: "openai_compatible", configured: false, base_url: "", models: {}, storage: "missing", health: "missing" },
      github: { provider: "github", configured: false, base_url: "", models: {}, storage: "missing", health: "missing" },
      ollama: { provider: "ollama", configured: false, base_url: "", models: {}, storage: "missing", health: "missing" },
    });
    const save = vi
      .spyOn(api, "saveConnection")
      .mockResolvedValue({ provider: "openai_compatible", configured: true });
    render(
      <QueryClientProvider client={qc()}>
        <I18nProvider>
          <MemoryRouter>
            <Settings />
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const keyInputs = await screen.findAllByLabelText("API Key");
    const keyInput = keyInputs[0];
    expect(keyInput.getAttribute("type")).toBe("password");
    await userEvent.type(keyInput, "SK-PLACEHOLDER-test-value");
    await userEvent.click(screen.getAllByRole("button", { name: /安全保存/ })[0]);
    await waitFor(() => expect(save).toHaveBeenCalled());
    // 提交后表单清空（不残留 Secret 值）
    await waitFor(() => expect((keyInput as HTMLInputElement).value).toBe(""));
  });
});
