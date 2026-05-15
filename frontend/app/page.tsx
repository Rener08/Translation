"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  JobResult,
  TranslationSettings,
  defaultSettings,
  getDefaultRewriteFocusForSettings,
  getDefaultSkillConfigNameForRewriteStyle,
  normalizeTranslationModel,
} from "./lib/job";
const TRANSLATION_SETTINGS_STORAGE_KEY = "translation-settings";
const TRANSLATION_PROVIDER_VALUES = new Set([
  "deepseek",
  "openai",
  "ollama",
  "lmstudio",
]);
const REWRITE_STYLE_VALUES = new Set(["speech_verbatim", "article_longform"]);
const SKILL_CONFIG_NAME_VALUES = new Set(["kazix", "latepost"]);

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
  const [uploadedAudioFile, setUploadedAudioFile] = useState<File | null>(null);
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [settings, setSettings] = useState<TranslationSettings>(defaultSettings);
  const [restoredConversation, setRestoredConversation] =
    useState<RestoredConversationState | null>(null);
  const [hasLoadedPreferences, setHasLoadedPreferences] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarQuery, setSidebarQuery] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const sidebarSearchInputRef = useRef<HTMLInputElement | null>(null);

  const activeContextId = jobResult?.content_context_id ?? "";
  const rewriteFocus = useMemo(
    () => getDefaultRewriteFocusForSettings(settings.rewriteStyle, settings.skillConfigName),
    [settings.rewriteStyle, settings.skillConfigName],
  );

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
      invalidateCurrentRun({ cancelBackend: true });
      setYoutubeUrl(nextUrl);
      setUploadedAudioFile(null);
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
    cancelJob,
  } = useJobRunner({
    settings,
    youtubeUrl,
    uploadedAudioFile,
    onJobResult: (result) => {
      setUploadedAudioFile(null);
      setRestoredConversation(null);
      setJobResult(result);
    },
    onJobSuccess: (result) => {
      if (youtubeUrl.trim()) {
        recordSearchHistory(youtubeUrl, result.video.title || youtubeUrl);
      }
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
      let nextSkillConfigName: TranslationSettings["skillConfigName"] =
        defaultSettings.skillConfigName;
      if (rawSettings) {
        const parsed = JSON.parse(rawSettings) as Partial<TranslationSettings>;
        nextRewriteStyle = REWRITE_STYLE_VALUES.has(parsed.rewriteStyle ?? "")
          ? (parsed.rewriteStyle as TranslationSettings["rewriteStyle"])
          : defaultSettings.rewriteStyle;
        nextSkillConfigName = SKILL_CONFIG_NAME_VALUES.has(parsed.skillConfigName ?? "")
          ? (parsed.skillConfigName as TranslationSettings["skillConfigName"])
          : getDefaultSkillConfigNameForRewriteStyle(nextRewriteStyle);
        const nextProvider = TRANSLATION_PROVIDER_VALUES.has(parsed.provider ?? "")
          ? (parsed.provider as TranslationSettings["provider"])
          : defaultSettings.provider;
        const nextBaseUrl =
          typeof parsed.baseUrl === "string" ? parsed.baseUrl : defaultSettings.baseUrl;
        const nextModel =
          typeof parsed.model === "string" ? parsed.model : defaultSettings.model;
        const safeSettings: TranslationSettings = {
          provider: nextProvider,
          sourceMode: defaultSettings.sourceMode,
          apiKey: "",
          baseUrl: nextBaseUrl,
          model: normalizeTranslationModel(nextProvider, nextModel),
          headersJson: "",
          rewriteStyle: nextRewriteStyle,
          skillConfigName: nextSkillConfigName,
        };
        setSettings((current) => ({
          ...current,
          ...safeSettings,
        }));
        window.localStorage.setItem(
          TRANSLATION_SETTINGS_STORAGE_KEY,
          JSON.stringify({
            provider: safeSettings.provider,
            baseUrl: safeSettings.baseUrl,
            model: safeSettings.model,
            rewriteStyle: safeSettings.rewriteStyle,
            skillConfigName: safeSettings.skillConfigName,
          }),
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
          baseUrl: persistedSettings.baseUrl,
          model: normalizeTranslationModel(
            persistedSettings.provider,
            persistedSettings.model,
          ),
          rewriteStyle: persistedSettings.rewriteStyle,
          skillConfigName: persistedSettings.skillConfigName,
        }),
      );
    } catch {
      // Ignore storage failures.
    }
  }, [hasLoadedPreferences, settings]);

  function clearConversation() {
    invalidateCurrentRun({ cancelBackend: true });
    setYoutubeUrl("");
    setUploadedAudioFile(null);
    setJobResult(null);
    setRestoredConversation(null);
    setSidebarQuery("");
    clearJobError();
  }

  function handleYoutubeUrlChange(value: string) {
    setYoutubeUrl(value);
    if (value.trim()) {
      setUploadedAudioFile(null);
    }
  }

  function handlePickAudioFile(file: File | null) {
    setUploadedAudioFile(file);
    if (file) {
      setYoutubeUrl("");
    }
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
      invalidateCurrentRun({ cancelBackend: true });
      void openHistorySession(item.contentContextId);
      return;
    }
    invalidateCurrentRun({ cancelBackend: true });
    setYoutubeUrl(item.url);
    setUploadedAudioFile(null);
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
              selectedAudioName={uploadedAudioFile?.name ?? ""}
              isRunning={isRunning}
              jobStatusMessage={jobStatusMessage}
              errorMessage={errorMessage}
              onChangeUrl={handleYoutubeUrlChange}
              onPickAudioFile={handlePickAudioFile}
              onSubmit={runJob}
              onCancel={cancelJob}
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
              onChange={setSettings}
            />
          </section>
        </div>
      ) : null}
    </main>
  );
}
