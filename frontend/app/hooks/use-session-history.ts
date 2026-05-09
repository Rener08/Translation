"use client";

import { useEffect, useMemo, useState } from "react";

import { JobResult, apiFetch, extractApiErrorMessage } from "../lib/job";


export type SessionHistorySummary = {
  content_context_id: string;
  video_title?: string | null;
  video_url?: string | null;
  updated_at?: string | null;
};

export type SessionHistoryDetail = {
  content_context_id: string;
  video_id?: string | null;
  video_url?: string | null;
  video_title?: string | null;
  video_thumbnail?: string | null;
  video_duration_sec?: number | null;
  video_uploader?: string | null;
  source_type?: "captions" | "audio" | null;
  transcript_en_text?: string;
  transcript_en_segments?: Array<{
    index: number;
    start: number;
    end: number;
    text: string;
    speaker?: string | null;
  }>;
  translation_zh_segments?: Array<{
    index: number;
    start: number;
    end: number;
    source_text: string;
    translated_text: string;
  }>;
  rewritten_text?: string;
  rewrite_provider?: string | null;
  rewrite_model?: string | null;
  chat_turns?: Array<{
    role: "user" | "assistant";
    content: string;
    created_at?: string;
  }>;
};

export type RestoredConversationState = {
  rewrittenText: string;
  rewriteProviderLabel: string;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
};

export type SearchHistoryItem = {
  url: string;
  title: string;
  updated_at: string;
};

export type SidebarListItem =
  | {
      kind: "session";
      key: string;
      title: string;
      subtitle: string;
      contentContextId: string;
    }
  | {
      kind: "search";
      key: string;
      title: string;
      subtitle: string;
      url: string;
    };

type UseSessionHistoryParams = {
  activeContextId: string;
  query: string;
  onOpenSession: (payload: {
    youtubeUrl: string;
    jobResult: JobResult;
    restoredConversation: RestoredConversationState | null;
  }) => void;
};

const SEARCH_HISTORY_STORAGE_KEY = "translation-search-history";

export function useSessionHistory({
  activeContextId,
  query,
  onOpenSession,
}: UseSessionHistoryParams) {
  const [searchHistoryItems, setSearchHistoryItems] = useState<SearchHistoryItem[]>([]);
  const [historyItems, setHistoryItems] = useState<SessionHistorySummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SEARCH_HISTORY_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as SearchHistoryItem[];
      if (Array.isArray(parsed)) {
        setSearchHistoryItems(
          parsed
            .filter((item) => item && typeof item.url === "string")
            .slice(0, 20),
        );
      }
    } catch {
      setSearchHistoryItems([]);
    }
  }, []);

  async function loadHistory() {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const response = await apiFetch("/api/session-history?limit=30");
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as { items?: SessionHistorySummary[] };
      setHistoryItems(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Failed to load history.",
      );
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    void loadHistory();
  }, []);

  function recordSearchHistory(url: string, title: string) {
    const normalizedUrl = url.trim();
    if (!normalizedUrl) {
      return;
    }
    const nextItem: SearchHistoryItem = {
      url: normalizedUrl,
      title: title.trim() || normalizedUrl,
      updated_at: new Date().toISOString(),
    };
    setSearchHistoryItems((current) => {
      const next = [nextItem, ...current.filter((item) => item.url !== normalizedUrl)].slice(
        0,
        20,
      );
      try {
        window.localStorage.setItem(SEARCH_HISTORY_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Ignore storage failures.
      }
      return next;
    });
  }

  async function openHistorySession(contentContextId: string) {
    try {
      const response = await apiFetch(`/api/session-history/${contentContextId}`);
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as SessionHistoryDetail;
      const rewrittenText = String(data.rewritten_text || "").trim();
      const rewriteProvider = String(data.rewrite_provider || "").trim();
      const rewriteModel = String(data.rewrite_model || "").trim();
      const rewriteProviderLabel =
        rewriteProvider && rewriteModel
          ? `${rewriteProvider} · ${rewriteModel}`
          : rewriteProvider || rewriteModel;
      const restoredMessages = Array.isArray(data.chat_turns)
        ? data.chat_turns
            .filter(
              (turn): turn is { role: "user" | "assistant"; content: string } =>
                !!turn &&
                (turn.role === "user" || turn.role === "assistant") &&
                typeof turn.content === "string" &&
                turn.content.trim().length > 0,
            )
            .map((turn) => ({ role: turn.role, content: turn.content }))
        : [];
      onOpenSession({
        youtubeUrl: data.video_url ?? "",
        jobResult: {
          ok: true,
          video: {
            video_id: data.video_id ?? "",
            title: data.video_title ?? "未命名视频",
            thumbnail: data.video_thumbnail ?? null,
            duration_sec: data.video_duration_sec ?? null,
            uploader: data.video_uploader ?? null,
          },
          source_type: data.source_type ?? "captions",
          content_context_id: data.content_context_id,
          transcript_en: {
            text: data.transcript_en_text ?? "",
            segments: data.transcript_en_segments ?? [],
          },
          translation_zh: {
            segments: data.translation_zh_segments ?? [],
          },
        },
        restoredConversation:
          rewrittenText || restoredMessages.length > 0
            ? {
                rewrittenText,
                rewriteProviderLabel,
                messages: restoredMessages,
              }
            : null,
      });
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Failed to open history session.",
      );
    }
  }

  const sidebarItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const list: SidebarListItem[] = [];

    for (const item of historyItems) {
      const title = (item.video_title || "未命名视频").trim();
      const subtitle =
        (item.updated_at ? item.updated_at.replace("T", " ").slice(0, 16) : "") ||
        "";
      if (
        normalizedQuery &&
        !title.toLowerCase().includes(normalizedQuery) &&
        !(item.video_url ?? "").toLowerCase().includes(normalizedQuery)
      ) {
        continue;
      }
      list.push({
        kind: "session",
        key: `session-${item.content_context_id}`,
        title,
        subtitle,
        contentContextId: item.content_context_id,
      });
    }

    const knownUrls = new Set(historyItems.map((item) => item.video_url || ""));
    for (const item of searchHistoryItems) {
      const title = item.title.trim() || item.url;
      if (knownUrls.has(item.url)) {
        continue;
      }
      if (
        normalizedQuery &&
        !title.toLowerCase().includes(normalizedQuery) &&
        !item.url.toLowerCase().includes(normalizedQuery)
      ) {
        continue;
      }
      list.push({
        kind: "search",
        key: `search-${item.url}`,
        title,
        subtitle: item.url,
        url: item.url,
      });
    }

    return list;
  }, [historyItems, query, searchHistoryItems]);

  return {
    historyLoading,
    historyError,
    sidebarItems,
    loadHistory,
    openHistorySession,
    recordSearchHistory,
    activeContextId,
  };
}
