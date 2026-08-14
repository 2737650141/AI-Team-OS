import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { I18nProvider } from "../i18n";
import type { UsageSummary } from "../api/types";
import { Usage } from "./Usage";

beforeEach(() => vi.restoreAllMocks());

it("renders task totals and every breakdown from one usage response", async () => {
  const summary = {
    has_data: true,
    requests: 5,
    total_tokens: 1500,
    input_tokens: 1250,
    output_tokens: 250,
    reasoning_tokens: null,
    cached_input_tokens: 400,
    cache_write_tokens: null,
    other_tokens: null,
    cost_total: null,
    currency: null,
    cache_hit_rate: 0.32,
    runtime_ms: 5000,
    average_latency_ms: 1000,
    usage_source: "REPORTED",
    last_compression: null,
    by_agent: [{ name: "planner", requests: 2, tokens: 600, latency_ms: 2000, cost: 0, cost_available: false }, { name: "researcher", requests: 3, tokens: 900, latency_ms: 3000, cost: 0, cost_available: false }],
    by_model: [{ name: "deepseek-v4-flash", requests: 5, tokens: 1500, latency_ms: 5000, cost: 0, cost_available: false }],
    by_provider: [{ name: "DeepSeek Official", requests: 5, tokens: 1500, latency_ms: 5000, cost: 0, cost_available: false }],
    by_task: [{ name: "task-1", requests: 5, tokens: 1500, latency_ms: 5000, cost: 0, cost_available: false }],
    timeline: Array.from({ length: 5 }, (_, index) => ({ timestamp: `2026-08-14T00:00:0${index}Z`, scope: "user_task", agent: index < 2 ? "planner" : "researcher", model: "deepseek-v4-flash", tokens: 300, source: "REPORTED", compression_triggered: false, compression_tokens_before: null, compression_tokens_after: null })),
    context: { current_tokens: 1500, limit: 1000000, percentage: 0.0015, status: "AMPLE", compression_threshold: 0.8, compression_threshold_tokens: 800000, until_compression: 798500, source: "REPORTED", role: "researcher", model: "deepseek-v4-flash" },
  } satisfies UsageSummary;
  vi.spyOn(api, "usage").mockResolvedValue(summary);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider><MemoryRouter initialEntries={["/usage?run=run-1"]}><Usage /></MemoryRouter></I18nProvider>
    </QueryClientProvider>,
  );

  await waitFor(() => expect(screen.getByText("模型请求")).toBeInTheDocument());
  expect(screen.getByText("5")).toBeInTheDocument();
  expect(screen.getAllByText("planner").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("researcher").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("deepseek-v4-flash").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("DeepSeek Official")).toBeInTheDocument();
  expect(screen.getAllByText("1500").length).toBeGreaterThanOrEqual(3);
});
