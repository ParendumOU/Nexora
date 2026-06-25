"use client";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getUserWsUrl } from "@/lib/utils";
import { ensureFreshToken } from "@/lib/api";

/**
 * Single per-user WebSocket that replaces polling for the chat list and
 * notifications. The backend (/ws/user) pushes:
 *   - { type: "notification", notification }      -> refresh the bell
 *   - { type: "chat_created"|"chat_deleted"|"chat_restored"|"chat_title_updated" }
 *   - { type: "chat_created"|"project_created"|"project_updated" }  (org channel)
 * On any of these we invalidate the relevant react-query caches, so data is
 * refetched on change instead of on a timer.
 *
 * Robustness: exponential backoff reconnect, immediate reconnect when the tab
 * regains focus or the network comes back online, and a server keepalive ping.
 * Nothing here blocks rendering — it's a fire-and-forget effect.
 */
export function useUserSocket(enabled: boolean) {
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    closedRef.current = false;

    const invalidateChats = () => {
      qc.invalidateQueries({ queryKey: ["chats"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    };
    const invalidateNotifs = () => qc.invalidateQueries({ queryKey: ["notifications"] });

    const clearRetry = () => {
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };

    const scheduleReconnect = () => {
      if (closedRef.current) return;
      clearRetry();
      const attempt = attemptRef.current;
      // 500ms * 2^attempt + jitter, capped at 30s
      const delay = Math.min(500 * 2 ** attempt + Math.random() * 500, 30_000);
      attemptRef.current = attempt + 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    async function connect() {
      if (closedRef.current) return;
      // Refresh the token first if it's expired/expiring, so the socket never
      // connects with a stale token (which the server rejects with 4401).
      const token = await ensureFreshToken();
      if (closedRef.current) return;
      if (!token) {
        scheduleReconnect();
        return;
      }
      let ws: WebSocket;
      try {
        const { url, protocols } = getUserWsUrl();
        ws = new WebSocket(url, protocols);
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
      };

      ws.onmessage = (ev) => {
        let data: { type?: string };
        try {
          data = JSON.parse(ev.data);
        } catch {
          return;
        }
        switch (data.type) {
          case "notification":
            invalidateNotifs();
            break;
          case "chat_created":
          case "chat_deleted":
          case "chat_restored":
          case "chat_title_updated":
          case "project_created":
          case "project_updated":
            invalidateChats();
            break;
          case "ping":
            try { ws.send(JSON.stringify({ type: "pong" })); } catch { /* noop */ }
            break;
          default:
            break;
        }
      };

      ws.onclose = () => {
        if (!closedRef.current) scheduleReconnect();
      };
      ws.onerror = () => {
        try { ws.close(); } catch { /* onclose handles retry */ }
      };
    }

    // Reconnect promptly when the tab refocuses or network returns, but only if
    // the socket isn't already open.
    const wake = () => {
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        attemptRef.current = 0;
        clearRetry();
        connect();
      }
    };
    const onVisible = () => { if (document.visibilityState === "visible") wake(); };

    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisible);

    connect();

    return () => {
      closedRef.current = true;
      clearRetry();
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", onVisible);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
        try { ws.close(); } catch { /* noop */ }
      }
    };
  }, [enabled, qc]);
}
