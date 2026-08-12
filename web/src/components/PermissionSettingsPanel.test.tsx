import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { PermissionSettingsPanel } from "./PermissionSettingsPanel";

describe("PermissionSettingsPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("requires one clear confirmation before enabling Maximum", async () => {
    vi.spyOn(api, "permissionMode").mockResolvedValue({
      mode: "standard", changed_at: "2026-08-12T00:00:00Z", changed_by_user: false,
      version: 1, maximum_confirmed: false, first_upgrade_notice: true,
    });
    vi.spyOn(api, "permissionHistory").mockResolvedValue({ actions: [] });
    const save = vi.spyOn(api, "savePermissionMode").mockResolvedValue({
      mode: "maximum", changed_at: "2026-08-12T00:00:01Z", changed_by_user: true,
      version: 2, maximum_confirmed: true,
    });
    render(<QueryClientProvider client={new QueryClient()}><PermissionSettingsPanel /></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "启用最高权限模式" }));
    expect(screen.getByRole("dialog", { name: "确认最高权限模式" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "启用最高权限" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("maximum", true));
  });
});
