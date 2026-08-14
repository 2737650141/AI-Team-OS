import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { JarvisSession } from "../api/types";

const NEAR_BOTTOM_THRESHOLD = 120; // px：距底部低于该值视为“在底部”
const TRANSIENT_SCROLL_PREFIX = "ai-team-os.conversation-scroll.";

export interface ScrollState {
  scrollTop: number;
  anchorMessageId: string | null;
  wasNearBottom: boolean;
}

function captureScrollState(el: HTMLDivElement): ScrollState {
  const wasNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_THRESHOLD;
  const anchor = Array.from(el.querySelectorAll<HTMLElement>("[data-message-id]")).find(
    (item) => item.offsetTop + item.offsetHeight >= el.scrollTop,
  );
  return {
    scrollTop: Math.max(0, Math.round(el.scrollTop)),
    anchorMessageId: anchor?.dataset.messageId ?? null,
    wasNearBottom,
  };
}

function transientKey(sessionId: string) {
  return `${TRANSIENT_SCROLL_PREFIX}${sessionId}`;
}

function loadTransientScrollState(sessionId: string): ScrollState | null {
  try {
    const raw = window.sessionStorage.getItem(transientKey(sessionId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<ScrollState>;
    if (typeof value.scrollTop !== "number" || typeof value.wasNearBottom !== "boolean") {
      return null;
    }
    return {
      scrollTop: Math.max(0, Math.round(value.scrollTop)),
      anchorMessageId: typeof value.anchorMessageId === "string" ? value.anchorMessageId : null,
      wasNearBottom: value.wasNearBottom,
    };
  } catch {
    return null;
  }
}

function saveScrollState(sessionId: string, state: ScrollState) {
  try {
    window.sessionStorage.setItem(transientKey(sessionId), JSON.stringify(state));
  } catch {
    /* Backend persistence remains the durable fallback when sessionStorage is unavailable. */
  }
  void api.saveJarvisScroll(sessionId, {
    scroll_top: state.scrollTop,
    anchor_message_id: state.anchorMessageId,
    was_near_bottom: state.wasNearBottom,
  }).catch(() => {
    /* Saving scroll state must never interrupt the conversation. */
  });
}

/**
 * 024-C ConversationScrollController（前端行为部分）。
 *
 * 规则：
 * 1. 回到会话时，之前在底部 → 滚动到最新消息（自动跟随）。
 * 2. 之前看历史 → 恢复原位置（anchorMessageId / scrollTop）。
 * 3. 新消息且用户在底部 → 自动跟随。
 * 4. 新消息且用户看历史 → 不抢滚动，显示“↓ N 条新消息”。
 * 5. route switch 不得回到顶部（本 hook 挂在组件上，离开时保存状态）。
 * 6. conversation switch 状态隔离（状态按 sessionId 键控，互不覆盖）。
 */
export function useConversationScroll(
  sessionId: string,
  session: JarvisSession | undefined,
  messageCount: number,
  messageVersion = "",
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const stateRef = useRef<ScrollState>({ scrollTop: 0, anchorMessageId: null, wasNearBottom: true });
  const sessionRef = useRef(sessionId);
  const prevCountRef = useRef(0);
  const prevVersionRef = useRef("");
  const pendingRestoreRef = useRef<ScrollState | null>(null);
  const firstRenderRef = useRef(true);

  // conversation switch 状态隔离：切换会话时重置内部状态
  useEffect(() => {
    if (sessionRef.current !== sessionId) {
      const el = containerRef.current;
      saveScrollState(sessionRef.current, el ? captureScrollState(el) : stateRef.current);
      sessionRef.current = sessionId;
      stateRef.current = { scrollTop: 0, anchorMessageId: null, wasNearBottom: true };
      pendingRestoreRef.current = null;
      setUnreadCount(0);
      prevCountRef.current = 0;
      prevVersionRef.current = "";
      firstRenderRef.current = true;
    }
  }, [sessionId]);

  // 从后端读取该会话保存的滚动状态（仅首次进入该会话时）
  useEffect(() => {
    if (!session?.scroll || firstRenderRef.current === false) return;
    firstRenderRef.current = false;
    const transient = loadTransientScrollState(sessionId);
    pendingRestoreRef.current = transient ?? {
      scrollTop: session.scroll.scroll_top ?? 0,
      anchorMessageId: session.scroll.anchor_message_id ?? null,
      wasNearBottom: session.scroll.was_near_bottom ?? true,
    };
  }, [session, sessionId]);

  // 滚动监听：记录当前滚动位置 + 是否在底部
  const onScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    stateRef.current = captureScrollState(el);
    if (stateRef.current.wasNearBottom) setUnreadCount(0);
  }, []);

  // 消息数量变化时的行为
  useEffect(() => {
    const el = containerRef.current;
    const prevCount = prevCountRef.current;
    const prevVersion = prevVersionRef.current;
    prevCountRef.current = messageCount;
    prevVersionRef.current = messageVersion;
    if (prevCount === 0) return; // 首次挂载：只记录基准（ref 可能尚未挂载）
    if (!el || !session) return;
    const countDelta = messageCount - prevCount;
    const versionChanged = Boolean(prevVersion && messageVersion && prevVersion !== messageVersion);
    const incomingCount = countDelta > 0 ? countDelta : versionChanged ? 2 : 0;
    if (incomingCount <= 0) return;

    // 规则 1：之前在底部（含初始态）→ 新消息自动跟随
    if (stateRef.current.wasNearBottom) {
      el.scrollTop = el.scrollHeight;
      setUnreadCount(0);
      return;
    }
    // 规则 4：看历史时新消息 → 不抢滚动，显示 “↓ N 条新消息”
    setUnreadCount((n) => n + incomingCount);
  }, [messageCount, messageVersion, session]);

  // 路由返回/会话恢复：按保存状态恢复（规则 1/2/5）
  useEffect(() => {
    const restore = pendingRestoreRef.current;
    if (!restore) return;
    pendingRestoreRef.current = null;
    // 请求动画帧后恢复，确保 DOM 已渲染；rAF 回调里读取 ref，兼容 ref 晚于 effect 挂载
    requestAnimationFrame(() => {
      const el = containerRef.current;
      if (!el) return;
      if (restore.wasNearBottom) {
        el.scrollTop = el.scrollHeight; // 之前在底部 → 最新消息
      } else {
        const anchor = restore.anchorMessageId
          ? Array.from(el.querySelectorAll<HTMLElement>("[data-message-id]")).find(
              (item) => item.dataset.messageId === restore.anchorMessageId,
            )
          : null;
        el.scrollTop = anchor?.offsetTop ?? restore.scrollTop; // 看历史 → 恢复原位置
      }
    });
  }, [session]);

  // 离开组件时保存滚动状态到后端（route switch 不回到顶部）
  useEffect(() => {
    return () => {
      const el = containerRef.current;
      const state = el ? captureScrollState(el) : stateRef.current;
      // 会话隔离：只保存当前会话
      saveScrollState(sessionRef.current, state);
    };
  }, []);

  const jumpToLatest = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    stateRef.current = { scrollTop: el.scrollHeight, anchorMessageId: null, wasNearBottom: true };
    setUnreadCount(0);
  }, []);

  return { containerRef, onScroll, unreadCount, jumpToLatest };
}
