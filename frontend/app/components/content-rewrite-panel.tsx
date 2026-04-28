"use client";

import { useEffect, useRef, useState } from "react";

import {
  ContentRewriteResponse,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  extractApiErrorMessage,
  formatProviderName,
} from "../lib/job";

type ContentRewritePanelProps = {
  settings: TranslationSettings;
  initialSourceText?: string;
  contentContextId?: string;
  rewriteFocus?: string;
  title?: string;
  subtitle?: string;
  sourceLocked?: boolean;
  resultOnly?: boolean;
};

export function ContentRewritePanel({
  settings,
  initialSourceText = "",
  contentContextId = "",
  rewriteFocus = "",
  title = "内容改写",
  subtitle = "粘贴原文后点击改写。",
  sourceLocked = false,
  resultOnly = false,
}: ContentRewritePanelProps) {
  const [rewriteSourceText, setRewriteSourceText] = useState(initialSourceText);
  const [rewrittenText, setRewrittenText] = useState("");
  const [rewriteErrorMessage, setRewriteErrorMessage] = useState("");
  const [isRewriting, setIsRewriting] = useState(false);
  const [isRewriteCopied, setIsRewriteCopied] = useState(false);
  const [rewriteProviderLabel, setRewriteProviderLabel] = useState("");
  const autoRewriteKeyRef = useRef("");

  useEffect(() => {
    setRewriteSourceText(initialSourceText);
    setRewrittenText("");
    setRewriteErrorMessage("");
    setIsRewriting(false);
    setIsRewriteCopied(false);
    setRewriteProviderLabel("");
    autoRewriteKeyRef.current = "";
  }, [initialSourceText]);

  async function executeRewrite(sourceOverride?: string) {
    const source = (sourceOverride ?? rewriteSourceText).trim();
    if (!source || isRewriting) {
      return;
    }

    let translationConfig;
    try {
      translationConfig = buildTranslationConfig(settings);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Invalid rewrite settings.";
      setRewriteErrorMessage(message);
      return;
    }

    setIsRewriting(true);
    setRewriteErrorMessage("");
    setRewrittenText("");
    setIsRewriteCopied(false);
    setRewriteProviderLabel("");

    try {
      const response = await apiFetch("/api/content-rewrite", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
          body: JSON.stringify({
            source_text: source,
            translation_config: translationConfig,
            content_context_id: contentContextId || undefined,
            rewrite_focus: rewriteFocus.trim() || undefined,
          }),
        });

      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }

      const data = (await response.json()) as ContentRewriteResponse;
      setRewrittenText(data.rewritten_text);
      setRewriteProviderLabel(
        `${formatProviderName(data.provider)} · ${data.model}`,
      );
    } catch (error) {
      setRewriteErrorMessage(
        error instanceof Error ? error.message : "Failed to rewrite content.",
      );
    } finally {
      setIsRewriting(false);
    }
  }

  async function handleRewrite() {
    await executeRewrite();
  }

  async function handleCopyRewrite() {
    if (!rewrittenText.trim()) {
      return;
    }

    try {
      await navigator.clipboard.writeText(rewrittenText);
      setIsRewriteCopied(true);
      window.setTimeout(() => setIsRewriteCopied(false), 1500);
    } catch {
      setIsRewriteCopied(false);
    }
  }

  async function handleExportRewrite() {
    const text = rewrittenText.trim();
    if (!text) {
      return;
    }

    const exportBlob = new Blob(
      [`# 中文改写\n\n${text}\n`],
      { type: "text/markdown;charset=utf-8" },
    );
    const url = URL.createObjectURL(exportBlob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "rewrite.md";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  useEffect(() => {
    if (!resultOnly) {
      return;
    }

    const normalizedSource = initialSourceText.trim();
    if (!normalizedSource) {
      setRewrittenText("");
      setRewriteErrorMessage("");
      autoRewriteKeyRef.current = "";
      return;
    }

    const rewriteKey = [
      normalizedSource,
      rewriteFocus.trim(),
      settings.provider,
      settings.baseUrl,
      settings.model,
      settings.apiKey,
      settings.headersJson,
      contentContextId,
    ].join("::");

    if (autoRewriteKeyRef.current === rewriteKey) {
      return;
    }

    autoRewriteKeyRef.current = rewriteKey;
    setRewriteSourceText(normalizedSource);
    void executeRewrite(normalizedSource);
  }, [
    initialSourceText,
    resultOnly,
    settings.apiKey,
    settings.baseUrl,
    settings.headersJson,
    settings.model,
    settings.provider,
    rewriteFocus,
    contentContextId,
  ]);

  if (resultOnly) {
    return (
      <section className="rewrite-result-only">
        <div className="rewrite-panel-header rewrite-result-header">
          <div>
            <p className="card-label">Write</p>
            <h2 className="panel-title">{title}</h2>
            <p className="rewrite-subtitle">改写内容会显示在这里，支持复制和导出。</p>
          </div>
          <div className="rewrite-result-actions">
            <button
              className="copy-answer-button"
              type="button"
              disabled={!rewrittenText.trim()}
              onClick={handleCopyRewrite}
            >
              {isRewriteCopied ? "已复制" : "复制"}
            </button>
            <button
              className="copy-answer-button"
              type="button"
              disabled={!rewrittenText.trim()}
              onClick={handleExportRewrite}
            >
              导出
            </button>
            <button
              className="copy-answer-button"
              type="button"
              disabled={!rewrittenText.trim()}
              onClick={() => void executeRewrite()}
            >
              再改写
            </button>
          </div>
        </div>
        {rewriteErrorMessage ? (
          <p className="chat-error-text">{rewriteErrorMessage}</p>
        ) : null}
        <textarea
          id="rewrite-output-text-main"
          className="rewrite-input rewrite-output-input rewrite-output-only-input"
          rows={22}
          value={rewrittenText}
          readOnly
          placeholder={
            isRewriting
              ? "正在生成改写结果..."
              : "先运行下载与翻译，改写结果会自动显示在这里。"
          }
        />
      </section>
    );
  }

  return (
    <section className="rewrite-panel rewrite-panel-large">
      <div className="rewrite-panel-header">
        <div>
          <p className="card-label">Rewrite</p>
          <h2 className="panel-title">{title}</h2>
          <p className="rewrite-subtitle">{subtitle}</p>
        </div>
        <p className="rewrite-provider-text">{rewriteProviderLabel}</p>
      </div>

      <div className="rewrite-field-stack">
        <label className="rewrite-field-label" htmlFor="rewrite-source-text-main">
          原文输入（翻译原文）
        </label>
        <textarea
          id="rewrite-source-text-main"
          className="rewrite-input"
          rows={10}
          value={rewriteSourceText}
          readOnly={sourceLocked}
          disabled={isRewriting}
          placeholder={
            sourceLocked
              ? "先运行下载与翻译，系统会自动填充翻译原文。"
              : "在这里粘贴需要改写的内容。"
          }
          onChange={
            sourceLocked ? undefined : (event) => setRewriteSourceText(event.target.value)
          }
        />
      </div>

      <div className="rewrite-action-row">
        <button
          className="primary-button compact-primary-button"
          type="button"
          disabled={isRewriting || rewriteSourceText.trim().length === 0}
          onClick={handleRewrite}
        >
          {isRewriting ? "改写中..." : "改写"}
        </button>
        <button
          className="copy-answer-button"
          type="button"
          disabled={!rewrittenText.trim()}
          onClick={handleCopyRewrite}
        >
          {isRewriteCopied ? "已复制" : "复制改写"}
        </button>
        <button
          className="copy-answer-button"
          type="button"
          disabled={!rewrittenText.trim()}
          onClick={handleExportRewrite}
        >
          导出
        </button>
      </div>

      {rewriteErrorMessage ? (
        <p className="chat-error-text">{rewriteErrorMessage}</p>
      ) : null}

      <div className="rewrite-field-stack">
        <label className="rewrite-field-label" htmlFor="rewrite-output-text-main">
          改写结果
        </label>
        <textarea
          id="rewrite-output-text-main"
          className="rewrite-input rewrite-output-input"
          rows={12}
          value={rewrittenText}
          readOnly
          placeholder="改写结果会显示在这里。"
        />
      </div>
    </section>
  );
}
