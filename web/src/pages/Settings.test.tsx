// Settings/Connections 前端测试（010 四十九：Secret 表单）
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
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
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Connections")).toBeInTheDocument());
    expect(screen.getByText("openai_compatible")).toBeInTheDocument();
    expect(screen.getByText("ollama")).toBeInTheDocument();
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
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const keyInputs = await screen.findAllByLabelText("API Key");
    const keyInput = keyInputs[0];
    expect(keyInput.getAttribute("type")).toBe("password");
    await userEvent.type(keyInput, "SK-PLACEHOLDER-test-value");
    await userEvent.click(screen.getAllByRole("button", { name: /Save securely/ })[0]);
    await waitFor(() => expect(save).toHaveBeenCalled());
    // 提交后表单清空（不残留 Secret 值）
    await waitFor(() => expect((keyInput as HTMLInputElement).value).toBe(""));
  });
});
