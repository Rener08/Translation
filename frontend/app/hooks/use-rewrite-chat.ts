"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  ContentChatResponse,
  JobResult,
  TranslationConfigPayload,
  TranslationSettings,
  apiFetch,
  buildRewriteExportMarkdown,
  buildTranslationConfig,
  buildTranslationText,
  extractApiErrorMessage,
  formatProviderName,
  rewriteExportBasename,
} from "../lib/job";


export type ThreadMessage = {
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
};

type UseRewriteChatParams = {
  jobResult: JobResult | null;
  settings: TranslationSettings;
  rewriteFocus: string;
  restoredConversation?: {
    rewrittenText: string;
    rewriteProviderLabel: string;
    messages: Array<{ role: "user" | "assistant"; content: string }>;
  } | null;
};

export function useRewriteChat({
  jobResult,
  settings,
  rewriteFocus,
  restoredConversation = null,
}: UseRewriteChatParams) {
  const [rewriteText, setRewriteText] = useState("");
  const [rewriteProviderLabel, setRewriteProviderLabel] = useState("");
  const [rewriteLoading, setRewriteLoading] = useState(false);
  const [rewriteError, setRewriteError] = useState("");
  const [rewriteCopied, setRewriteCopied] = useState(false);
  const [detailCoverageIssues, setDetailCoverageIssues] = useState<string[]>([]);
  const [detailPatchLoading, setDetailPatchLoading] = useState(false);

  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSubmitting, setChatSubmitting] = useState(false);
  const [chatError, setChatError] = useState("");
  const skipAutoRewriteForContextRef = useRef("");
  const contextVersionRef = useRef(0);
  const rewriteRequestSeqRef = useRef(0);
  const patchRequestSeqRef = useRef(0);
  const chatRequestSeqRef = useRef(0);
  const rewriteAbortRef = useRef<AbortController | null>(null);
  const patchAbortRef = useRef<AbortController | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const currentContextId = jobResult?.content_context_id ?? "";

  const translationText = useMemo(
    () =>
      jobResult ? buildTranslationText(jobResult.translation_zh?.segments ?? []) : "",
    [jobResult],
  );

  const rewriteSourceText = useMemo(
    () => jobResult?.transcript_en?.text ?? "",
    [jobResult],
  );

  useEffect(() => {
    contextVersionRef.current += 1;
    rewriteRequestSeqRef.current += 1;
    patchRequestSeqRef.current += 1;
    chatRequestSeqRef.current += 1;
    rewriteAbortRef.current?.abort();
    patchAbortRef.current?.abort();
    chatAbortRef.current?.abort();
    setChatInput("");
    setChatError("");
    setRewriteCopied(false);
    setDetailCoverageIssues([]);
    setRewriteLoading(false);
    setDetailPatchLoading(false);
    setChatSubmitting(false);
    if (!currentContextId) {
      setMessages([]);
      setRewriteText("");
      setRewriteError("");
      setRewriteProviderLabel("");
      return;
    }
    const hasRestoredRewrite = restoredConversation?.rewrittenText.trim().length;
    const hasRestoredMessages = (restoredConversation?.messages.length ?? 0) > 0;
    if (hasRestoredRewrite || hasRestoredMessages) {
      setMessages(restoredConversation?.messages ?? []);
      setRewriteText(restoredConversation?.rewrittenText ?? "");
      setRewriteError("");
      setRewriteProviderLabel(restoredConversation?.rewriteProviderLabel ?? "");
      skipAutoRewriteForContextRef.current = currentContextId;
      return;
    }
    setMessages([]);
    setRewriteText("");
    setRewriteError("");
    setRewriteProviderLabel("");
  }, [currentContextId, restoredConversation]);

  useEffect(() => {
    return () => {
      rewriteAbortRef.current?.abort();
      patchAbortRef.current?.abort();
      chatAbortRef.current?.abort();
    };
  }, []);

  function isCurrentRequest(
    contextVersion: number,
    requestSeq: number,
    requestType: "rewrite" | "patch" | "chat",
    controller: AbortController,
  ): boolean {
    const currentSeq =
      requestType === "rewrite"
        ? rewriteRequestSeqRef.current
        : requestType === "patch"
          ? patchRequestSeqRef.current
          : chatRequestSeqRef.current;
    return (
      contextVersion === contextVersionRef.current &&
      requestSeq === currentSeq &&
      !controller.signal.aborted
    );
  }

  useEffect(() => {
    if (!jobResult || !rewriteSourceText.trim()) {
      return;
    }
    if (skipAutoRewriteForContextRef.current === currentContextId) {
      skipAutoRewriteForContextRef.current = "";
      return;
    }
    void runRewrite(rewriteSourceText);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentContextId, jobResult, rewriteFocus, rewriteSourceText]);

  async function runRewrite(sourceText: string) {
    const source = sourceText.trim();
    if (!source) {
      return;
    }
    let translationConfig: TranslationConfigPayload;
    try {
      translationConfig = buildTranslationConfig(settings);
    } catch (error) {
      setRewriteError(
        error instanceof Error ? error.message : "Invalid rewrite settings.",
      );
      return;
    }

    const contextVersion = contextVersionRef.current;
    const requestSeq = rewriteRequestSeqRef.current + 1;
    rewriteRequestSeqRef.current = requestSeq;
    rewriteAbortRef.current?.abort();
    const controller = new AbortController();
    rewriteAbortRef.current = controller;
    setRewriteLoading(true);
    setRewriteError("");
    setRewriteText("");
    setRewriteCopied(false);
    setDetailCoverageIssues([]);
    try {
      const response = await apiFetch("/api/content-rewrite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_text: source,
          translation_config: translationConfig,
          rewrite_style: settings.rewriteStyle,
          skill_config_name: settings.skillConfigName,
          content_context_id: jobResult?.content_context_id || undefined,
          rewrite_focus: rewriteFocus.trim() || undefined,
        }),
        signal: controller.signal,
      });
      if (!isCurrentRequest(contextVersion, requestSeq, "rewrite", controller)) {
        return;
      }
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as {
        rewritten_text: string;
        provider: string;
        model: string;
        detail_coverage_issues?: string[];
      };
      setRewriteText(data.rewritten_text ?? "");
      setRewriteProviderLabel(`${formatProviderName(data.provider)} · ${data.model}`);
      setDetailCoverageIssues(
        Array.isArray(data.detail_coverage_issues) ? data.detail_coverage_issues : [],
      );
    } catch (error) {
      if (!isCurrentRequest(contextVersion, requestSeq, "rewrite", controller)) {
        return;
      }
      if (controller.signal.aborted) {
        return;
      }
      setRewriteError(error instanceof Error ? error.message : "Failed to rewrite content.");
    } finally {
      if (isCurrentRequest(contextVersion, requestSeq, "rewrite", controller)) {
        if (rewriteAbortRef.current === controller) {
          rewriteAbortRef.current = null;
        }
        setRewriteLoading(false);
      }
    }
  }

  async function requestDetailPatch() {
    if (detailPatchLoading || rewriteLoading) {
      return;
    }
    const currentRewrite = rewriteText.trim();
    const sourceText = rewriteSourceText.trim();
    if (!currentRewrite || !sourceText || detailCoverageIssues.length === 0) {
      return;
    }
    let translationConfig: TranslationConfigPayload;
    try {
      translationConfig = buildTranslationConfig(settings);
    } catch (error) {
      setRewriteError(
        error instanceof Error ? error.message : "Invalid rewrite settings.",
      );
      return;
    }

    const contextVersion = contextVersionRef.current;
    const requestSeq = patchRequestSeqRef.current + 1;
    patchRequestSeqRef.current = requestSeq;
    patchAbortRef.current?.abort();
    const controller = new AbortController();
    patchAbortRef.current = controller;
    const missingLines = detailCoverageIssues.map((issue) => `- ${issue}`).join("\n");
    const patchFocus = [
      "你将修订一篇已经生成的中文正文。",
      "",
      "原始素材：",
      sourceText,
      "",
      "当前完整草稿：",
      currentRewrite,
      "",
      "缺失细节：",
      missingLines,
      "",
      "要求：",
      "1. 只把缺失细节自然补回正文。",
      "2. 不新增事实。",
      "3. 不改写成摘要。",
      "4. 必须输出修订后的完整正文，不要只输出补充段落。",
    ].join("\n");

    setDetailPatchLoading(true);
    setRewriteError("");
    setRewriteCopied(false);
    try {
      const response = await apiFetch("/api/content-rewrite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_text: sourceText,
          translation_config: translationConfig,
          rewrite_style: settings.rewriteStyle,
          skill_config_name: settings.skillConfigName,
          content_context_id: jobResult?.content_context_id || undefined,
          rewrite_focus: patchFocus,
        }),
        signal: controller.signal,
      });
      if (!isCurrentRequest(contextVersion, requestSeq, "patch", controller)) {
        return;
      }
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as {
        rewritten_text: string;
        provider: string;
        model: string;
        detail_coverage_issues?: string[];
      };
      setRewriteText(data.rewritten_text ?? "");
      setRewriteProviderLabel(`${formatProviderName(data.provider)} · ${data.model}`);
      setDetailCoverageIssues(
        Array.isArray(data.detail_coverage_issues) ? data.detail_coverage_issues : [],
      );
    } catch (error) {
      if (!isCurrentRequest(contextVersion, requestSeq, "patch", controller)) {
        return;
      }
      if (controller.signal.aborted) {
        return;
      }
      setRewriteError(error instanceof Error ? error.message : "Failed to patch details.");
    } finally {
      if (isCurrentRequest(contextVersion, requestSeq, "patch", controller)) {
        if (patchAbortRef.current === controller) {
          patchAbortRef.current = null;
        }
        setDetailPatchLoading(false);
      }
    }
  }

  async function copyRewrite() {
    const text = rewriteText.trim();
    if (!text) {
      return;
    }
    try {
      const copied = await writeTextToClipboard(text);
      if (!copied) {
        throw new Error("Clipboard write is unavailable.");
      }
      setRewriteCopied(true);
      window.setTimeout(() => setRewriteCopied(false), 1200);
    } catch {
      setRewriteCopied(false);
    }
  }

  async function writeTextToClipboard(text: string): Promise<boolean> {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch {
        // Fall through to the legacy selection-based path.
      }
    }

    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "true");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      const copied = document.execCommand("copy");
      document.body.removeChild(textarea);
      return copied;
    } catch {
      return false;
    }
  }

  function exportRewrite() {
    const text = rewriteText.trim();
    if (!text || !jobResult) {
      return;
    }
    const markdown = buildRewriteExportMarkdown("# 中文改写", text, jobResult);
    const blob = new Blob([markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${rewriteExportBasename(jobResult)}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function submitChatQuestion(rawQuestion: string) {
    const question = rawQuestion.trim();
    if (!question || !jobResult || chatSubmitting) {
      return;
    }
    const cleanHistory = messages
      .filter((message) => !message.pending)
      .map(({ role, content }) => ({ role, content }));
    const userMessage: ThreadMessage = { role: "user", content: question };
    const pendingAssistantMessage: ThreadMessage = {
      role: "assistant",
      content: "思考中...",
      pending: true,
    };

    setChatSubmitting(true);
    setChatError("");
    setChatInput("");
    setMessages([...cleanHistory, userMessage, pendingAssistantMessage]);
    const contextVersion = contextVersionRef.current;
    const requestSeq = chatRequestSeqRef.current + 1;
    chatRequestSeqRef.current = requestSeq;
    chatAbortRef.current?.abort();
    const controller = new AbortController();
    chatAbortRef.current = controller;
    try {
      const response = await apiFetch("/api/content-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content_context_id: jobResult.content_context_id,
          video_title: jobResult.video.title,
          transcript_en: jobResult.transcript_en.text,
          translation_zh: translationText,
          question,
          messages: cleanHistory,
          chat_config: {
            provider: settings.provider,
            api_key: settings.apiKey.trim() || undefined,
            base_url: settings.baseUrl.trim() || undefined,
            model: settings.model.trim() || undefined,
          },
        }),
        signal: controller.signal,
      });
      if (!isCurrentRequest(contextVersion, requestSeq, "chat", controller)) {
        return;
      }
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as ContentChatResponse;
      setMessages((current) => {
        if (!isCurrentRequest(contextVersion, requestSeq, "chat", controller)) {
          return current.filter((message) => !message.pending);
        }
        const next = [...current];
        const pendingIndex = next.findIndex((message) => message.pending);
        if (pendingIndex >= 0) {
          next[pendingIndex] = { role: "assistant", content: data.answer };
          return next;
        }
        return [...next, { role: "assistant", content: data.answer }];
      });
    } catch (error) {
      if (!isCurrentRequest(contextVersion, requestSeq, "chat", controller)) {
        return;
      }
      if (controller.signal.aborted) {
        return;
      }
      setChatError(
        error instanceof Error ? error.message : "Failed to answer this question.",
      );
      setMessages((current) => current.filter((message) => !message.pending));
    } finally {
      if (isCurrentRequest(contextVersion, requestSeq, "chat", controller)) {
        if (chatAbortRef.current === controller) {
          chatAbortRef.current = null;
        }
        setChatSubmitting(false);
      }
    }
  }

  return {
    translationText,
    rewriteText,
    rewriteProviderLabel,
    rewriteLoading,
    rewriteError,
    rewriteCopied,
    detailCoverageIssues,
    detailPatchLoading,
    requestDetailPatch,
    messages,
    chatInput,
    chatSubmitting,
    chatError,
    setChatInput,
    submitChatQuestion,
    copyRewrite,
    exportRewrite,
  };
}
