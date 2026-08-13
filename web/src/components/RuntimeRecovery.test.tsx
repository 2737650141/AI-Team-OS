import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppRootErrorBoundary } from "./AppRootErrorBoundary";
import { RuntimeRecoveryView } from "./RuntimeRecoveryView";
import { ActivityFeed } from "./ActivityFeed";
import { I18nProvider } from "../i18n";

function Broken(): never {
  throw new Error("synthetic render failure");
}

describe("desktop runtime recovery", () => {
  it("FREEZE01 catches a fatal React render error", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<AppRootErrorBoundary><Broken /></AppRootErrorBoundary>);
    expect(screen.getByText("AI Team OS 遇到了界面错误")).toBeInTheDocument();
    error.mockRestore();
  });

  it("FREEZE02 renders backend disconnect without a blank page", async () => {
    const reload = vi.fn();
    render(<RuntimeRecoveryView kind="core" onReload={reload} />);
    expect(screen.getByText("AI Core 连接已中断")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "重新加载界面" }));
    expect(reload).toHaveBeenCalledOnce();
  });

  it("FREEZE06 keeps a 1000 event burst to 300 visible rows", () => {
    const events = Array.from({ length: 1000 }, (_, index) => ({
      event_id: `event-${index}`,
      event_type: "task_progress",
      task_id: "task",
      run_id: "run",
      sequence: index,
      timestamp: new Date(index * 1000).toISOString(),
      summary: "progress",
      actor_type: "system",
      actor_id: "runtime",
      payload_safe: {},
    }));
    const { container } = render(<I18nProvider><ActivityFeed events={events} /></I18nProvider>);
    expect(container.querySelectorAll(".feed-item")).toHaveLength(300);
  });
});
