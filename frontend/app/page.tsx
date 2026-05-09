"use client";

import { useEffect, useRef, useState } from "react";
import { Lightbulb, Sparkles, SquarePen, WandSparkles } from "lucide-react";

import { AppSidebar } from "./components/app-sidebar";
import { EntryView } from "./components/entry-view";
import { ResultView } from "./components/result-view";
import { TranslationSettingsPanel } from "./components/translation-settings-panel";
import { useJobRunner } from "./hooks/use-job-runner";
import {
  SidebarListItem,
  useSessionHistory,
} from "./hooks/use-session-history";
import { useRewriteChat } from "./hooks/use-rewrite-chat";
import { JobResult, TranslationSettings, defaultSettings } from "./lib/job";


const DEFAULT_REWRITE_FOCUS =
  "保留原意和事实，不删关键信息，改写为更有节奏和可读性的中文内容。";
const TRANSLATION_SETTINGS_STORAGE_KEY = "translation-settings";
const REWRITE_FOCUS_STORAGE_KEY = "translation-rewrite-focus";
const TRANSLATION_PROVIDER_VALUES = new Set([
  "deepseek",
  "openai",
  "ollama",
  "lmstudio",
]);
const SOURCE_MODE_VALUES = new Set(["subtitle_first", "force_audio"]);

const CHAT_SHORTCUTS = [
  {
    key: "summary",
    label: "总结",
    icon: Lightbulb,
    prompt: "请把这篇内容总结成 5 条核心观点。",
  },
  {
    key: "explain",
    label: "解释",
    icon: WandSparkles,
    prompt: "请解释这篇内容里最重要的 3 个概念，并给出通俗说明。",
  },
  {
    key: "polish",
    label: "润色",
    icon: Sparkles,
    prompt: "请在不改变事实的前提下润色这篇中文内容，让语句更流畅。",
  },
  {
    key: "reframe",
    label: "重构",
    icon: SquarePen,
    prompt: "请重构这篇文章结构，改成更清晰的总分总结构。",
  },
];

export default function HomePage() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [settings, setSettings] = useState<TranslationSettings>(defaultSettings);
  const [rewriteFocus, setRewriteFocus] = useState(DEFAULT_REWRITE_FOCUS);
  const [hasLoadedPreferences, setHasLoadedPreferences] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarQuery, setSidebarQuery] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const sidebarSearchInputRef = useRef<HTMLInputElement | null>(null);

  const activeContextId = jobResult?.content_context_id ?? "";

  const {
    historyLoading,
    historyError,
    sidebarItems,
    loadHistory,
    openHistorySession,
    recordSearchHistory,
  } = useSessionHistory({
    activeContextId,
    query: sidebarQuery,
    onOpenSession: ({ youtubeUrl: nextUrl, jobResult: nextResult }) => {
      setYoutubeUrl(nextUrl);
      setJobResult(nextResult);
      clearJobError();
    },
  });

  const {
    isRunning,
    jobStatusMessage,
    errorMessage,
    clearJobError,
    runJob,
  } = useJobRunner({
    settings,
    youtubeUrl,
    onJobResult: setJobResult,
    onJobSuccess: (result) => {
      recordSearchHistory(youtubeUrl, result.video.title || youtubeUrl);
      void loadHistory();
    },
  });

  const {
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
  } = useRewriteChat({
    jobResult,
    settings,
    rewriteFocus,
  });

  useEffect(() => {
    setSettings((current) => ({
      ...current,
      model: current.model.trim(),
    }));
  }, []);

  useEffect(() => {
    try {
      const rawSettings = window.localStorage.getItem(
        TRANSLATION_SETTINGS_STORAGE_KEY,
      );
      if (rawSettings) {
        const parsed = JSON.parse(rawSettings) as Partial<TranslationSettings>;
        setSettings((current) => ({
          ...current,
          provider: TRANSLATION_PROVIDER_VALUES.has(parsed.provider ?? "")
            ? (parsed.provider as TranslationSettings["provider"])
            : current.provider,
          sourceMode: SOURCE_MODE_VALUES.has(parsed.sourceMode ?? "")
            ? (parsed.sourceMode as TranslationSettings["sourceMode"])
            : current.sourceMode,
          baseUrl: typeof parsed.baseUrl === "string" ? parsed.baseUrl : current.baseUrl,
          model: typeof parsed.model === "string" ? parsed.model : current.model,
          headersJson:
            typeof parsed.headersJson === "string" ? parsed.headersJson : current.headersJson,
          apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : current.apiKey,
        }));
      }

      const rawRewriteFocus = window.localStorage.getItem(REWRITE_FOCUS_STORAGE_KEY);
      if (rawRewriteFocus) {
        setRewriteFocus(rawRewriteFocus);
      }
    } catch {
      // Ignore malformed local storage.
    }
    setHasLoadedPreferences(true);
  }, []);

  useEffect(() => {
    if (!hasLoadedPreferences) {
      return;
    }
    try {
      window.localStorage.setItem(
        TRANSLATION_SETTINGS_STORAGE_KEY,
        JSON.stringify(settings),
      );
      window.localStorage.setItem(REWRITE_FOCUS_STORAGE_KEY, rewriteFocus);
    } catch {
      // Ignore storage failures.
    }
  }, [hasLoadedPreferences, rewriteFocus, settings]);

  function clearConversation() {
    setYoutubeUrl("");
    setJobResult(null);
    setSidebarQuery("");
    clearJobError();
  }

  function toggleSidebarCollapsed() {
    setSidebarCollapsed((current) => !current);
  }

  function openSettingsModal() {
    setShowSettings(true);
  }

  function expandSidebarAndFocusSearch() {
    setSidebarCollapsed(false);
    window.setTimeout(() => {
      sidebarSearchInputRef.current?.focus();
    }, 30);
  }

  function handleSidebarItemClick(item: SidebarListItem) {
    if (item.kind === "session") {
      void openHistorySession(item.contentContextId);
      return;
    }
    setYoutubeUrl(item.url);
    if (jobResult) {
      setJobResult(null);
    }
  }

  return (
    <main className="app-root">
      <div className={`app-frame ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        <AppSidebar
          collapsed={sidebarCollapsed}
          query={sidebarQuery}
          activeContextId={activeContextId}
          historyLoading={historyLoading}
          historyError={historyError}
          items={sidebarItems}
          searchInputRef={sidebarSearchInputRef}
          onToggleCollapsed={toggleSidebarCollapsed}
          onOpenSearch={expandSidebarAndFocusSearch}
          onNewConversation={clearConversation}
          onOpenSettings={openSettingsModal}
          onChangeQuery={setSidebarQuery}
          onSelectItem={handleSidebarItemClick}
        />

        <section className="app-main">
          {!jobResult ? (
            <EntryView
              youtubeUrl={youtubeUrl}
              isRunning={isRunning}
              jobStatusMessage={jobStatusMessage}
              errorMessage={errorMessage}
              onChangeUrl={setYoutubeUrl}
              onSubmit={runJob}
            />
          ) : (
            <ResultView
              jobResult={jobResult}
              rewriteProviderLabel={rewriteProviderLabel}
              rewriteLoading={rewriteLoading}
              rewriteError={rewriteError}
              rewriteText={rewriteText}
              rewriteCopied={rewriteCopied}
              messages={messages}
              chatInput={chatInput}
              chatSubmitting={chatSubmitting}
              chatError={chatError}
              shortcuts={CHAT_SHORTCUTS}
              onCopyRewrite={copyRewrite}
              onExportRewrite={exportRewrite}
              onSubmitShortcut={submitChatQuestion}
              onSubmitChat={() => submitChatQuestion(chatInput)}
              onChangeChatInput={setChatInput}
            />
          )}
        </section>
      </div>

      {showSettings ? (
        <div
          className="settings-modal-backdrop"
          onClick={() => setShowSettings(false)}
          role="presentation"
        >
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-label="设置"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="settings-modal-header">
              <h3>设置</h3>
              <button
                className="icon-button"
                type="button"
                onClick={() => setShowSettings(false)}
                aria-label="关闭设置"
              >
                ×
              </button>
            </div>
            <TranslationSettingsPanel
              settings={settings}
              rewriteFocus={rewriteFocus}
              onChange={setSettings}
              onRewriteFocusChange={setRewriteFocus}
            />
          </section>
        </div>
      ) : null}
    </main>
  );
}
