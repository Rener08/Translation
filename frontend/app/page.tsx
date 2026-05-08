"use client";

import { FormEvent, useEffect, useState } from "react";

import { ContentChatPanel } from "./components/content-chat-panel";
import { HistoryPopover } from "./components/history-popover";
import { JobResultPanel } from "./components/job-result-panel";
import { TranslationSettingsPanel } from "./components/translation-settings-panel";
import {
  JobResult,
  TranslationConfigPayload,
  normalizeTranslationModel,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  defaultSettings,
  extractApiErrorMessage,
  waitForJobResult,
} from "./lib/job";

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

type SessionHistorySummary = {
  content_context_id: string;
  video_title?: string | null;
  video_url?: string | null;
  updated_at?: string | null;
  rewritten_preview?: string;
  transcript_preview?: string;
  translation_preview?: string;
};

type SearchHistoryItem = {
  url: string;
  title: string;
  updated_at: string;
};

type SessionHistoryDetail = {
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
};

export default function HomePage() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [jobStatusMessage, setJobStatusMessage] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [settings, setSettings] = useState<TranslationSettings>(defaultSettings);
  const [rewriteFocus, setRewriteFocus] = useState(DEFAULT_REWRITE_FOCUS);
  const [hasLoadedPreferences, setHasLoadedPreferences] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [searchHistoryItems, setSearchHistoryItems] = useState<SearchHistoryItem[]>(
    [],
  );
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyItems, setHistoryItems] = useState<SessionHistorySummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  const runStateLabel = isRunning
    ? jobStatusMessage || "处理中"
    : jobResult
      ? "已完成"
      : "待运行";

  const visibleSearchHistoryItems = searchHistoryItems.filter((item) => {
    const query = historyQuery.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return (
      item.title.toLowerCase().includes(query) || item.url.toLowerCase().includes(query)
    );
  });

  useEffect(() => {
    if (!showHistory) {
      return;
    }

    let cancelled = false;

    async function loadHistory() {
      setHistoryLoading(true);
      setHistoryError("");
      try {
        const response = await apiFetch("/api/session-history?limit=8");
        if (!response.ok) {
          throw new Error(await extractApiErrorMessage(response));
        }
        const data = (await response.json()) as {
          items?: SessionHistorySummary[];
        };
        if (!cancelled) {
          setHistoryItems(Array.isArray(data.items) ? data.items : []);
        }
      } catch (error) {
        if (!cancelled) {
          setHistoryError(
            error instanceof Error ? error.message : "Failed to load history.",
          );
        }
      } finally {
        if (!cancelled) {
          setHistoryLoading(false);
        }
      }
    }

    void loadHistory();

    return () => {
      cancelled = true;
    };
  }, [showHistory]);

  useEffect(() => {
    setSettings((current) => {
      const nextModel = normalizeTranslationModel(
        current.provider,
        current.model,
      );
      if (nextModel === current.model.trim()) {
        return current;
      }
      return { ...current, model: nextModel };
    });
  }, [settings.model, settings.provider]);

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
          apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : current.apiKey,
          baseUrl: typeof parsed.baseUrl === "string" ? parsed.baseUrl : current.baseUrl,
          model: typeof parsed.model === "string" ? parsed.model : current.model,
          headersJson:
            typeof parsed.headersJson === "string" ? parsed.headersJson : current.headersJson,
        }));
      }

      const rawRewriteFocus = window.localStorage.getItem(REWRITE_FOCUS_STORAGE_KEY);
      if (rawRewriteFocus) {
        setRewriteFocus(rawRewriteFocus);
      }
    } catch {
      // Ignore malformed local storage and fall back to defaults.
    }

    setHasLoadedPreferences(true);
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem("translation-search-history");
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

  useEffect(() => {
    if (!hasLoadedPreferences) {
      return;
    }
    try {
      window.localStorage.setItem(
        TRANSLATION_SETTINGS_STORAGE_KEY,
        JSON.stringify(settings),
      );
    } catch {
      // Ignore storage failures in private/incognito mode.
    }
  }, [hasLoadedPreferences, settings]);

  useEffect(() => {
    if (!hasLoadedPreferences) {
      return;
    }
    try {
      window.localStorage.setItem(REWRITE_FOCUS_STORAGE_KEY, rewriteFocus);
    } catch {
      // Ignore storage failures in private/incognito mode.
    }
  }, [hasLoadedPreferences, rewriteFocus]);

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
      const next = [
        nextItem,
        ...current.filter((item) => item.url !== normalizedUrl),
      ].slice(0, 20);
      try {
        window.localStorage.setItem(
          "translation-search-history",
          JSON.stringify(next),
        );
      } catch {
        // Ignore storage failures in private/incognito mode.
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
      setYoutubeUrl(data.video_url ?? "");
      setJobResult({
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
      });
      setShowHistory(false);
      setErrorMessage("");
      setIsRunning(false);
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Failed to open history session.",
      );
    }
  }

  async function handleRunJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    let translationConfig: TranslationConfigPayload;
    try {
      translationConfig = buildTranslationConfig(settings);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Invalid translation settings.";
      setErrorMessage(message);
      setJobResult(null);
      return;
    }

    setIsRunning(true);
    setJobResult(null);
    setErrorMessage("");
    setJobStatusMessage("正在提交任务...");

    try {
      const response = await apiFetch("/api/jobs/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          url: youtubeUrl,
          source_mode: settings.sourceMode,
          translation_config: translationConfig,
        }),
      });

      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }

      const submission = (await response.json()) as {
        ok?: boolean;
        job_id?: string;
        status?: string;
        progress_text?: string | null;
      };
      const jobId = typeof submission.job_id === "string" ? submission.job_id.trim() : "";
      if (!jobId) {
        throw new Error("Job submission did not return a job id.");
      }
      if (submission.progress_text) {
        setJobStatusMessage(submission.progress_text);
      }

      const data = await waitForJobResult(jobId, (status) => {
        const statusText =
          typeof status.progress_text === "string" ? status.progress_text.trim() : "";
        if (statusText) {
          setJobStatusMessage(statusText);
          return;
        }
        if (status.status === "queued") {
          setJobStatusMessage("任务已排队...");
          return;
        }
        if (status.status === "running") {
          setJobStatusMessage("任务处理中...");
        }
      });
      setJobResult(data);
      setJobStatusMessage("");
      recordSearchHistory(
        youtubeUrl,
        data.video.title || youtubeUrl.trim() || "YouTube 视频",
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown request error";
      setErrorMessage(message);
      setJobStatusMessage("");
    } finally {
      setIsRunning(false);
    }
  }

  if (!jobResult) {
      return (
      <main className={`landing-shell ${showHistory ? "landing-shell-history-open" : ""}`}>
        <div className="taskbar-rail" aria-label="任务栏">
          <div className="taskbar-rail-shell">
            <button
              className="taskbar-icon-button"
              type="button"
              aria-label="历史对话"
              onClick={() => setShowHistory((current) => !current)}
            >
              ⟲
            </button>
            <button
              className="taskbar-icon-button"
              type="button"
              aria-label="新建对话"
              onClick={() => {
                setYoutubeUrl("");
                setErrorMessage("");
                setShowHistory(false);
                setHistoryQuery("");
              }}
            >
              ＋
            </button>
          </div>
        </div>
        <section className="landing-stage">
          <div className="landing-title-wrap">
            <h1 className="landing-title">YouTube 翻译助手</h1>
          </div>

          <form className="landing-composer" onSubmit={handleRunJob}>
            <label className="sr-only" htmlFor="youtube-url">
              YouTube URL
            </label>
            <input
              id="youtube-url"
              name="youtube-url"
              className="landing-url-input"
              placeholder="https://www.youtube.com/watch?v=..."
              value={youtubeUrl}
              onChange={(event) => setYoutubeUrl(event.target.value)}
            />
            <button
              className="landing-run-button"
              type="submit"
              disabled={isRunning || youtubeUrl.trim().length === 0}
              aria-label="开始处理"
            >
              {isRunning ? "…" : "▶"}
            </button>
          </form>

          {isRunning ? (
            <p className="landing-progress-text">
              {jobStatusMessage || "正在处理"}
            </p>
          ) : null}

          {errorMessage ? <p className="control-error-text landing-error-text">{errorMessage}</p> : null}
        </section>

        <button
          className="landing-settings-toggle"
          type="button"
          aria-label={showSettings ? "关闭设置" : "打开设置"}
          onClick={() => setShowSettings((current) => !current)}
        >
          ⚙
        </button>

        {showSettings ? (
          <aside className="landing-settings-popover">
            <div className="composer-panel landing-settings-panel">
              <TranslationSettingsPanel
                settings={settings}
                rewriteFocus={rewriteFocus}
                onChange={setSettings}
                onRewriteFocusChange={setRewriteFocus}
              />
            </div>
          </aside>
        ) : null}

        {showHistory ? (
          <HistoryPopover
            historyQuery={historyQuery}
            visibleSearchHistoryItems={visibleSearchHistoryItems}
            historyItems={historyItems}
            historyLoading={historyLoading}
            historyError={historyError}
            onClose={() => setShowHistory(false)}
            onQueryChange={setHistoryQuery}
            onSelectUrl={(url) => {
              setYoutubeUrl(url);
              setShowHistory(false);
            }}
            onSelectSession={(contentContextId) => void openHistorySession(contentContextId)}
          />
        ) : null}
      </main>
    );
  }

  return (
    <main className={`research-shell ${showHistory ? "research-shell-history-open" : ""}`}>
      <aside className="control-column">
        <section className="composer-panel">
          <div className="taskbar-rail taskbar-rail-result" aria-label="任务栏">
            <div className="taskbar-rail-shell">
              <button
                className="taskbar-icon-button"
                type="button"
                aria-label="历史对话"
                onClick={() => setShowHistory((current) => !current)}
              >
                ⟲
              </button>
              <button
                className="taskbar-icon-button"
                type="button"
                aria-label="新建对话"
                onClick={() => {
                  setJobResult(null);
                  setYoutubeUrl("");
                  setErrorMessage("");
                  setShowHistory(false);
                  setShowSettings(false);
                  setHistoryQuery("");
                }}
              >
                ＋
              </button>
            </div>
          </div>
          <form className="composer-form" onSubmit={handleRunJob}>
            <div className="composer-section">
              <div className="control-section-header">
                <div>
                  <p className="card-label">YouTube 链接</p>
                  <h1 className="panel-title">YouTube 翻译助手</h1>
                </div>
                <span className="control-pill">{runStateLabel}</span>
              </div>

              <label className="sr-only" htmlFor="youtube-url">
                YouTube URL
              </label>
              <input
                id="youtube-url"
                name="youtube-url"
                className="url-input"
                placeholder="https://www.youtube.com/watch?v=..."
                value={youtubeUrl}
                onChange={(event) => setYoutubeUrl(event.target.value)}
              />
            </div>

            <div className="composer-section">
              <TranslationSettingsPanel
                settings={settings}
                rewriteFocus={rewriteFocus}
                onChange={setSettings}
                onRewriteFocusChange={setRewriteFocus}
              />
            </div>

            <div className="composer-section composer-actions">
              <button
                className="primary-button"
                type="submit"
                disabled={isRunning || youtubeUrl.trim().length === 0}
              >
                {isRunning ? "处理中..." : "开始处理"}
              </button>
              {isRunning ? (
                <p className="composer-help-text">
                  {jobStatusMessage || "正在处理"}，通常需要 1-3 分钟（下载音频、Whisper 转写、翻译）。
                </p>
              ) : null}
            </div>

            {errorMessage ? <p className="control-error-text">{errorMessage}</p> : null}
          </form>
        </section>
      </aside>

      <section className="desk-column">
        <JobResultPanel
          jobResult={jobResult}
          settings={settings}
          rewriteFocus={rewriteFocus}
        />
      </section>

      <section className="chat-column">
        <ContentChatPanel jobResult={jobResult} settings={settings} />
      </section>

      {showHistory ? (
        <HistoryPopover
          variant="result"
          historyQuery={historyQuery}
          visibleSearchHistoryItems={visibleSearchHistoryItems}
          historyItems={historyItems}
          historyLoading={historyLoading}
          historyError={historyError}
          onClose={() => setShowHistory(false)}
          onQueryChange={setHistoryQuery}
          onSelectUrl={(url) => {
            setYoutubeUrl(url);
            setShowHistory(false);
          }}
          onSelectSession={(contentContextId) => void openHistorySession(contentContextId)}
        />
      ) : null}
    </main>
  );
}
