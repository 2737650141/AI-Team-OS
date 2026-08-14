// 024-C ConversationScrollController 前端行为测试（SCROLL 前端门禁）
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { JarvisSession } from "../api/types";
import { useConversationScroll } from "./useConversationScroll";

const session: JarvisSession = {
  session_id: "jarvis-test",
  messages: [],
  current_goal: null,
  current_task_reference: null,
  current_project: "default",
  no_write: false,
  scroll: { scroll_top: 0, anchor_message_id: null, was_near_bottom: true },
  created_at: "",
  updated_at: "",
};

function makeContainer(scrollHeight = 1000, clientHeight = 400) {
  const el = document.createElement("div");
  Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true, writable: true });
  Object.defineProperty(el, "clientHeight", { value: clientHeight, configurable: true, writable: true });
  Object.defineProperty(el, "scrollTop", { value: 0, configurable: true, writable: true });
  el.scrollTo = vi.fn(function (this: HTMLElement, options?: ScrollToOptions | number) {
    if (typeof options === "object" && options) this.scrollTop = options.top ?? this.scrollTop;
  });
  return el;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "saveJarvisScroll").mockResolvedValue(session);
});
afterEach(() => vi.restoreAllMocks());

describe("ConversationScrollController", () => {
  it("SCROLL-A: 之前在底部 → 回到会话滚动到最新消息", async () => {
    const el = makeContainer();
    const { result } = renderHook(() =>
      useConversationScroll("s1", { ...session, scroll: { scroll_top: 9999, anchor_message_id: null, was_near_bottom: true } }, 0),
    );
    act(() => { result.current.containerRef.current = el; });
    await act(async () => { await new Promise((r) => requestAnimationFrame(r)); });
    expect(el.scrollTop).toBe(el.scrollHeight);
  });

  it("SCROLL-B: 之前看历史 → 恢复原位置（scrollTop）", async () => {
    const el = makeContainer(2000, 400);
    const { result } = renderHook(() =>
      useConversationScroll("s1", { ...session, scroll: { scroll_top: 500, anchor_message_id: "msg-3", was_near_bottom: false } }, 0),
    );
    act(() => { result.current.containerRef.current = el; });
    await act(async () => { await new Promise((r) => requestAnimationFrame(r)); });
    expect(el.scrollTop).toBe(500);
  });

  it("SCROLL-C: 新消息且用户在底部 → 自动跟随", async () => {
    const el = makeContainer(1000, 400);
    el.scrollTop = 600; // 距底部 < 120 → 在底部
    const { result, rerender } = renderHook(
      ({ count }: { count: number }) => useConversationScroll("s1", { ...session, messages: Array.from({ length: count }, (_, i) => ({ role: "user", content: `m${i}` })) }, count),
      { initialProps: { count: 2 } },
    );
    act(() => { result.current.containerRef.current = el; });
    rerender({ count: 4 });
    expect(el.scrollTop).toBeGreaterThanOrEqual(600);
    expect(result.current.unreadCount).toBe(0);
  });

  it("SCROLL-D: 新消息且用户看历史 → 不抢滚动，显示 ↓ N 条新消息", async () => {
    const el = makeContainer(3000, 400);
    const { result, rerender } = renderHook(
      ({ count }: { count: number }) => useConversationScroll("s1", { ...session, messages: Array.from({ length: count }, (_, i) => ({ role: "user", content: `m${i}` })) }, count),
      { initialProps: { count: 2 } },
    );
    act(() => { result.current.containerRef.current = el; });
    el.scrollTop = 200; // 距底部 2400 → 看历史
    act(() => { result.current.onScroll(); }); // 让控制器记录“看历史”状态
    const before = el.scrollTop;
    rerender({ count: 5 });
    expect(el.scrollTop).toBe(before); // 不抢滚动
    expect(result.current.unreadCount).toBeGreaterThan(0); // ↓ N 条新消息
  });

  it("SCROLL-E: route switch 离开时保存滚动状态到后端", async () => {
    const el = makeContainer(1000, 400);
    el.scrollTop = 900; // 距底部 < 120 → 在底部
    const save = vi.spyOn(api, "saveJarvisScroll").mockResolvedValue(session);
    const { result, unmount } = renderHook(() => useConversationScroll("s1", session, 0));
    act(() => { result.current.containerRef.current = el; });
    unmount();
    expect(save).toHaveBeenCalledWith("s1", expect.objectContaining({ was_near_bottom: true }));
  });

  it("SCROLL-F: conversation switch 状态隔离（不同 session 互不覆盖）", async () => {
    const el = makeContainer();
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => useConversationScroll(id, { ...session, session_id: id }, 0),
      { initialProps: { id: "conv-a" } },
    );
    act(() => { result.current.containerRef.current = el; });
    // 切换到 conv-b：内部状态重置为默认
    rerender({ id: "conv-b" });
    expect(result.current.unreadCount).toBe(0);
  });
});
