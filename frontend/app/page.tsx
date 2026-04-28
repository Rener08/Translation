"use client";

import { FormEvent, useEffect, useState } from "react";

import { ContentChatPanel } from "./components/content-chat-panel";
import { JobResultPanel } from "./components/job-result-panel";
import { TranslationSettingsPanel } from "./components/translation-settings-panel";
import {
  JobResult,
  TranslationConfigPayload,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  defaultSettings,
  extractApiErrorMessage,
} from "./lib/job";

const DEFAULT_REWRITE_FOCUS =
  "保留原意和事实，不删关键信息，改写为更有节奏和可读性的中文内容。";

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
  const [isRunning, setIsRunning] = useState(false);
  const [settings, setSettings] = useState<TranslationSettings>(defaultSettings);
  const [rewriteFocus, setRewriteFocus] = useState(DEFAULT_REWRITE_FOCUS);
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
    ? "处理中"
    : jobResult
      ? "已完成"
      : "待运行";

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

      const data = (await response.json()) as JobResult;
      setJobResult(data);
      recordSearchHistory(
        youtubeUrl,
        data.video.title || youtubeUrl.trim() || "YouTube 视频",
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown request error";
      setErrorMessage(message);
    } finally {
      setIsRunning(false);
    }
  }

  if (!jobResult) {
    return (
      <main className="landing-shell">
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

          {isRunning ? <p className="landing-progress-text">正在处理</p> : null}

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
          <aside className="history-popover">
            <div className="history-popover-panel">
              <div className="history-popover-header">
                <h2 className="history-popover-title">历史对话</h2>
                <button
                  className="history-popover-close"
                  type="button"
                  onClick={() => setShowHistory(false)}
                >
                  ×
                </button>
              </div>
              <input
                className="history-popover-search"
                type="search"
                placeholder="搜索历史..."
                value={historyQuery}
                onChange={(event) => setHistoryQuery(event.target.value)}
              />
              <div className="history-popover-section">
                <div className="history-popover-section-header">搜索历史</div>
                <div className="history-popover-list">
                  {searchHistoryItems
                    .filter((item) => {
                      const query = historyQuery.trim().toLowerCase();
                      if (!query) {
                        return true;
                      }
                      return (
                        item.title.toLowerCase().includes(query) ||
                        item.url.toLowerCase().includes(query)
                      );
                    })
                    .map((item) => (
                      <button
                        key={item.url}
                        className="history-popover-item"
                        type="button"
                        onClick={() => {
                          setYoutubeUrl(item.url);
                          setShowHistory(false);
                        }}
                      >
                        <span className="history-popover-item-title">{item.title}</span>
                        <span className="history-popover-item-meta">{item.url}</span>
                      </button>
                    ))}
                </div>
              </div>
              <div className="history-popover-section">
                <div className="history-popover-section-header">对话历史</div>
                <div className="history-popover-list">
                  {historyItems.map((item) => (
                    <button
                      key={item.content_context_id}
                      className="history-popover-item"
                      type="button"
                      onClick={() => void openHistorySession(item.content_context_id)}
                    >
                      <span className="history-popover-item-title">
                        {item.video_title || "未命名视频"}
                      </span>
                      <span className="history-popover-item-meta">
                        {item.updated_at ? item.updated_at.replace("T", " ").slice(0, 16) : ""}
                      </span>
                    </button>
                  ))}
                  {!historyLoading && historyItems.length === 0 ? (
                    <p className="history-popover-note">暂无对话历史。</p>
                  ) : null}
                </div>
              </div>
              {historyLoading ? <p className="history-popover-note">加载中...</p> : null}
              {historyError ? <p className="history-popover-error">{historyError}</p> : null}
            </div>
          </aside>
        ) : null}
      </main>
    );
  }

  return (
    <main className="research-shell">
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
      <aside className="control-column">
        <section className="composer-panel">
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
                  正在处理，通常需要 1-3 分钟（下载音频、Whisper 转写、翻译）。
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
        <aside className="history-popover history-popover-result">
          <div className="history-popover-panel">
            <div className="history-popover-header">
              <h2 className="history-popover-title">历史对话</h2>
              <button
                className="history-popover-close"
                type="button"
                onClick={() => setShowHistory(false)}
                >
                  ×
                </button>
              </div>
              <input
                className="history-popover-search"
                type="search"
                placeholder="搜索历史..."
                value={historyQuery}
                onChange={(event) => setHistoryQuery(event.target.value)}
              />
              <div className="history-popover-section">
                <div className="history-popover-section-header">搜索历史</div>
                <div className="history-popover-list">
                  {searchHistoryItems
                    .filter((item) => {
                      const query = historyQuery.trim().toLowerCase();
                      if (!query) {
                        return true;
                      }
                      return (
                        item.title.toLowerCase().includes(query) ||
                        item.url.toLowerCase().includes(query)
                      );
                    })
                    .map((item) => (
                      <button
                        key={item.url}
                        className="history-popover-item"
                        type="button"
                        onClick={() => {
                          setYoutubeUrl(item.url);
                          setShowHistory(false);
                        }}
                      >
                        <span className="history-popover-item-title">{item.title}</span>
                        <span className="history-popover-item-meta">{item.url}</span>
                      </button>
                    ))}
                </div>
              </div>
              <div className="history-popover-section">
                <div className="history-popover-section-header">对话历史</div>
                <div className="history-popover-list">
                  {historyItems.map((item) => (
                    <button
                      key={item.content_context_id}
                      className="history-popover-item"
                      type="button"
                      onClick={() => void openHistorySession(item.content_context_id)}
                    >
                      <span className="history-popover-item-title">
                        {item.video_title || "未命名视频"}
                      </span>
                      <span className="history-popover-item-meta">
                        {item.updated_at ? item.updated_at.replace("T", " ").slice(0, 16) : ""}
                      </span>
                    </button>
                  ))}
                  {!historyLoading && historyItems.length === 0 ? (
                    <p className="history-popover-note">暂无对话历史。</p>
                  ) : null}
                </div>
              </div>
              {historyLoading ? <p className="history-popover-note">加载中...</p> : null}
              {historyError ? <p className="history-popover-error">{historyError}</p> : null}
          </div>
        </aside>
      ) : null}
    </main>
  );
}
