"use client";

import { useEffect, useMemo, useState } from "react";

import {
  JobResult,
  TranslationSettings,
  apiFetch,
  defaultSettings,
  extractApiErrorMessage,
  getDefaultSkillConfigNameForRewriteStyle,
  normalizeTranslationModel,
} from "../lib/job";
import type { FailureDiagnostic, RecoveryAction } from "../lib/types";

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
  source_mode?: "subtitle_first" | "force_audio" | null;
  translation_provider?: string | null;
  translation_model?: string | null;
  translation_base_url?: string | null;
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
  rewrite_base_url?: string | null;
  rewrite_style?: "speech_verbatim" | "article_longform" | null;
  skill_config_name?: "kazix" | "latepost" | null;
  rewrite_focus?: string | null;
  rewrite_source_text?: string;
  rewrite_quality_issues?: string[];
  rewrite_detail_coverage_issues?: string[];
  rewrite_failure_error_code?: string | null;
  rewrite_failure_message?: string | null;
  rewrite_failure_retryable?: boolean | null;
  rewrite_failure_details?: string[];
  chat_turns?: Array<{
    role: "user" | "assistant";
    content: string;
    created_at?: string;
  }>;
};

export type RestoredSettingsSnapshot = Pick<
  TranslationSettings,
  "provider" | "sourceMode" | "baseUrl" | "model" | "rewriteStyle" | "skillConfigName"
>;

export type RestoredFailureState = {
  source: FailureDiagnostic["source"];
  message: string;
  errorCode: string | null;
  retryable: boolean | null;
  details: string[];
};

export type RestoredConversationState = {
  rewrittenText: string;
  rewriteProviderLabel: string;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  detailCoverageIssues: string[];
  failure: RestoredFailureState | null;
};

export function buildRestoredSessionState(data: SessionHistoryDetail): {
  youtubeUrl: string;
  restoredSettings: RestoredSettingsSnapshot;
  jobResult: JobResult;
  restoredConversation: RestoredConversationState | null;
} {
  const rewrittenText = String(data.rewritten_text || "").trim();
  const translationProvider = String(
    data.rewrite_provider || data.translation_provider || defaultSettings.provider,
  ).trim();
  const rewriteProvider = translationProvider;
  const rewriteModel = String(
    data.rewrite_model || data.translation_model || defaultSettings.model,
  ).trim();
  const rewriteBaseUrl = String(
    data.rewrite_base_url || data.translation_base_url || "",
  ).trim();
  const rewriteStyle = (data.rewrite_style ?? defaultSettings.rewriteStyle) as RestoredSettingsSnapshot["rewriteStyle"];
  const skillConfigName =
    data.skill_config_name ??
    getDefaultSkillConfigNameForRewriteStyle(rewriteStyle);
  const sourceMode = (data.source_mode ?? defaultSettings.sourceMode) as RestoredSettingsSnapshot["sourceMode"];
  const normalizedModel = normalizeTranslationModel(
    rewriteProvider as RestoredSettingsSnapshot["provider"],
    rewriteModel,
  );
  const rewriteProviderLabel =
    rewriteProvider && normalizedModel
      ? `${rewriteProvider} · ${normalizedModel}`
      : rewriteProvider || normalizedModel;
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
  const detailCoverageIssues = Array.isArray(data.rewrite_detail_coverage_issues)
    ? data.rewrite_detail_coverage_issues
        .map((issue) => String(issue || "").trim())
        .filter(Boolean)
    : [];
  const failureMessage = String(data.rewrite_failure_message || "").trim();
  const failureErrorCode = String(data.rewrite_failure_error_code || "").trim();
  const failureDetails = Array.isArray(data.rewrite_failure_details)
    ? data.rewrite_failure_details
        .map((detail) => String(detail || "").trim())
        .filter(Boolean)
    : [];
  const failure =
    failureMessage || failureErrorCode
      ? {
          source:
            detailCoverageIssues.length > 0 ? ("detail_patch" as const) : ("rewrite" as const),
          message: failureMessage || "上次改写失败。",
          errorCode: failureErrorCode || null,
          retryable:
            typeof data.rewrite_failure_retryable === "boolean"
              ? data.rewrite_failure_retryable
              : null,
          details: failureDetails,
        }
      : null;

  return {
    youtubeUrl: data.video_url ?? "",
    restoredSettings: {
      provider: rewriteProvider as RestoredSettingsSnapshot["provider"],
      sourceMode,
      baseUrl: rewriteBaseUrl,
      model: normalizedModel,
      rewriteStyle,
      skillConfigName,
    },
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
      rewrittenText ||
      restoredMessages.length > 0 ||
      detailCoverageIssues.length > 0 ||
      failure
        ? {
            rewrittenText,
            rewriteProviderLabel,
            messages: restoredMessages,
            detailCoverageIssues,
            failure,
          }
        : null,
  };
}

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
    restoredSettings: RestoredSettingsSnapshot;
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
  const [historyFailureDiagnostic, setHistoryFailureDiagnostic] =
    useState<FailureDiagnostic | null>(null);

  function buildRecoveryAction(
    kind: RecoveryAction["kind"],
    label: string,
    description: string,
    disabled = false,
  ): RecoveryAction {
    return {
      kind,
      label,
      description,
      ...(disabled ? { disabled: true } : {}),
    };
  }

  function setHistoryFailure(
    title: string,
    message: string,
    errorCode: string | null,
    retryable: boolean | null,
    details: string[],
  ) {
    const diagnostic: FailureDiagnostic = {
      source: "history",
      title,
      message,
      details,
      errorCode,
      retryable,
      requestId: "",
      actions: [
        buildRecoveryAction("reload-history", "重新加载历史", "再次读取本地会话历史。"),
      ],
    };
    setHistoryFailureDiagnostic(diagnostic);
    setHistoryError(message);
  }

  function clearHistoryFailure() {
    setHistoryFailureDiagnostic(null);
    setHistoryError("");
  }

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
    clearHistoryFailure();
    try {
      const response = await apiFetch("/api/session-history?limit=30");
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as { items?: SessionHistorySummary[] };
      setHistoryItems(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load history.";
      setHistoryError(message);
      setHistoryFailure(
        "历史加载失败",
        message,
        null,
        true,
        ["请稍后重新加载历史，或检查后端是否可访问。"],
      );
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      clearHistoryFailure();

      const restored = buildRestoredSessionState(data);
      onOpenSession({
        ...restored,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to open history session.";
      setHistoryError(message);
      setHistoryFailure(
        "历史重开失败",
        message,
        null,
        true,
        ["请重新尝试打开相同会话，或重新加载历史列表。"],
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
    historyFailureDiagnostic,
    sidebarItems,
    loadHistory,
    openHistorySession,
    recordSearchHistory,
    activeContextId,
  };
}
