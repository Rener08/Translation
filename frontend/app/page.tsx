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
  RestoredConversationState,
  useSessionHistory,
} from "./hooks/use-session-history";
import { useRewriteChat } from "./hooks/use-rewrite-chat";
import {
  DEFAULT_ARTICLE_LONGFORM_REWRITE_FOCUS,
  DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS,
  LEGACY_ARTICLE_LONGFORM_REWRITE_FOCUS,
  JobResult,
  TranslationSettings,
  defaultSettings,
} from "./lib/job";
const TRANSLATION_SETTINGS_STORAGE_KEY = "translation-settings";
const REWRITE_FOCUS_STORAGE_KEY = "translation-rewrite-focus";
const TRANSLATION_PROVIDER_VALUES = new Set([
  "deepseek",
  "openai",
  "ollama",
  "lmstudio",
]);
const SOURCE_MODE_VALUES = new Set(["subtitle_first", "force_audio"]);
const REWRITE_STYLE_VALUES = new Set(["speech_verbatim", "article_longform"]);

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
  const [rewriteFocus, setRewriteFocus] = useState(
    DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS,
  );
  const [restoredConversation, setRestoredConversation] =
    useState<RestoredConversationState | null>(null);
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
    onOpenSession: ({
      youtubeUrl: nextUrl,
      jobResult: nextResult,
      restoredConversation: nextConversation,
    }) => {
      invalidateCurrentRun();
      setYoutubeUrl(nextUrl);
      setRestoredConversation(nextConversation);
      setJobResult(nextResult);
      clearJobError();
    },
  });

  const {
    isRunning,
    jobStatusMessage,
    errorMessage,
    clearJobError,
    invalidateCurrentRun,
    runJob,
  } = useJobRunner({
    settings,
    youtubeUrl,
    onJobResult: (result) => {
      setRestoredConversation(null);
      setJobResult(result);
    },
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
  } = useRewriteChat({
    jobResult,
    settings,
    rewriteFocus,
    restoredConversation,
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
      let nextRewriteStyle: TranslationSettings["rewriteStyle"] =
        defaultSettings.rewriteStyle;
      if (rawSettings) {
        const parsed = JSON.parse(rawSettings) as Partial<TranslationSettings>;
        nextRewriteStyle = REWRITE_STYLE_VALUES.has(parsed.rewriteStyle ?? "")
          ? (parsed.rewriteStyle as TranslationSettings["rewriteStyle"])
          : defaultSettings.rewriteStyle;
        const nextProvider = TRANSLATION_PROVIDER_VALUES.has(parsed.provider ?? "")
          ? (parsed.provider as TranslationSettings["provider"])
          : defaultSettings.provider;
        const nextSourceMode = SOURCE_MODE_VALUES.has(parsed.sourceMode ?? "")
          ? (parsed.sourceMode as TranslationSettings["sourceMode"])
          : defaultSettings.sourceMode;
        const nextBaseUrl =
          typeof parsed.baseUrl === "string" ? parsed.baseUrl : defaultSettings.baseUrl;
        const nextModel =
          typeof parsed.model === "string" ? parsed.model : defaultSettings.model;
        const safeSettings: TranslationSettings = {
          provider: nextProvider,
          sourceMode: nextSourceMode,
          apiKey: "",
          baseUrl: nextBaseUrl,
          model: nextModel,
          headersJson: "",
          rewriteStyle: nextRewriteStyle,
        };
        setSettings((current) => ({
          ...current,
          ...safeSettings,
        }));
        window.localStorage.setItem(
          TRANSLATION_SETTINGS_STORAGE_KEY,
          JSON.stringify({
            provider: safeSettings.provider,
            sourceMode: safeSettings.sourceMode,
            baseUrl: safeSettings.baseUrl,
            model: safeSettings.model,
            rewriteStyle: safeSettings.rewriteStyle,
          }),
        );
      }

      const rawRewriteFocus = window.localStorage.getItem(REWRITE_FOCUS_STORAGE_KEY);
      if (rawRewriteFocus) {
        const normalizedRewriteFocus =
          nextRewriteStyle === "article_longform"
            ? rawRewriteFocus === DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS ||
              rawRewriteFocus === LEGACY_ARTICLE_LONGFORM_REWRITE_FOCUS
              ? DEFAULT_ARTICLE_LONGFORM_REWRITE_FOCUS
              : rawRewriteFocus
            : rawRewriteFocus === DEFAULT_ARTICLE_LONGFORM_REWRITE_FOCUS ||
                rawRewriteFocus === LEGACY_ARTICLE_LONGFORM_REWRITE_FOCUS
              ? DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS
              : rawRewriteFocus;
        setRewriteFocus(normalizedRewriteFocus);
      } else {
        setRewriteFocus(
          nextRewriteStyle === "article_longform"
            ? DEFAULT_ARTICLE_LONGFORM_REWRITE_FOCUS
            : DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS,
        );
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
      const persistedSettings: TranslationSettings = {
        ...settings,
        apiKey: "",
        headersJson: "",
      };
      window.localStorage.setItem(
        TRANSLATION_SETTINGS_STORAGE_KEY,
        JSON.stringify({
          provider: persistedSettings.provider,
          sourceMode: persistedSettings.sourceMode,
          baseUrl: persistedSettings.baseUrl,
          model: persistedSettings.model,
          rewriteStyle: persistedSettings.rewriteStyle,
        }),
      );
      window.localStorage.setItem(REWRITE_FOCUS_STORAGE_KEY, rewriteFocus);
    } catch {
      // Ignore storage failures.
    }
  }, [hasLoadedPreferences, rewriteFocus, settings]);

  function clearConversation() {
    invalidateCurrentRun();
    setYoutubeUrl("");
    setJobResult(null);
    setRestoredConversation(null);
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
      invalidateCurrentRun();
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
              detailCoverageIssues={detailCoverageIssues}
              detailPatchLoading={detailPatchLoading}
              messages={messages}
              chatInput={chatInput}
              chatSubmitting={chatSubmitting}
              chatError={chatError}
              shortcuts={CHAT_SHORTCUTS}
              onCopyRewrite={copyRewrite}
              onExportRewrite={exportRewrite}
              onRequestDetailPatch={requestDetailPatch}
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
