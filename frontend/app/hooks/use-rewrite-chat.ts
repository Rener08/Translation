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

  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSubmitting, setChatSubmitting] = useState(false);
  const [chatError, setChatError] = useState("");
  const skipAutoRewriteForContextRef = useRef("");
  const currentContextId = jobResult?.content_context_id ?? "";

  const translationText = useMemo(
    () =>
      jobResult ? buildTranslationText(jobResult.translation_zh.segments) : "",
    [jobResult],
  );

  useEffect(() => {
    setChatInput("");
    setChatError("");
    setRewriteCopied(false);
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
    if (!jobResult || !translationText.trim()) {
      return;
    }
    if (skipAutoRewriteForContextRef.current === currentContextId) {
      skipAutoRewriteForContextRef.current = "";
      return;
    }
    void runRewrite(translationText);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentContextId, jobResult, rewriteFocus, translationText]);

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

    setRewriteLoading(true);
    setRewriteError("");
    setRewriteText("");
    setRewriteCopied(false);
    try {
      const response = await apiFetch("/api/content-rewrite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_text: source,
          translation_config: translationConfig,
          content_context_id: jobResult?.content_context_id || undefined,
          rewrite_focus: rewriteFocus.trim() || undefined,
        }),
      });
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as {
        rewritten_text: string;
        provider: string;
        model: string;
      };
      setRewriteText(data.rewritten_text ?? "");
      setRewriteProviderLabel(`${formatProviderName(data.provider)} · ${data.model}`);
    } catch (error) {
      setRewriteError(error instanceof Error ? error.message : "Failed to rewrite content.");
    } finally {
      setRewriteLoading(false);
    }
  }

  async function copyRewrite() {
    const text = rewriteText.trim();
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setRewriteCopied(true);
      window.setTimeout(() => setRewriteCopied(false), 1200);
    } catch {
      setRewriteCopied(false);
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
      });
      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }
      const data = (await response.json()) as ContentChatResponse;
      setMessages((current) => {
        const next = [...current];
        const pendingIndex = next.findIndex((message) => message.pending);
        if (pendingIndex >= 0) {
          next[pendingIndex] = { role: "assistant", content: data.answer };
          return next;
        }
        return [...next, { role: "assistant", content: data.answer }];
      });
    } catch (error) {
      setChatError(
        error instanceof Error ? error.message : "Failed to answer this question.",
      );
      setMessages((current) => current.filter((message) => !message.pending));
    } finally {
      setChatSubmitting(false);
    }
  }

  return {
    translationText,
    rewriteText,
    rewriteProviderLabel,
    rewriteLoading,
    rewriteError,
    rewriteCopied,
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
