"use client";

import { FormEvent, useState } from "react";

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

export default function HomePage() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [jobResult, setJobResult] = useState<JobResult | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [settings, setSettings] = useState<TranslationSettings>(defaultSettings);

  const runStateLabel = isRunning
    ? "处理中"
    : jobResult
      ? "已完成"
      : "待运行";

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
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown request error";
      setErrorMessage(message);
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main className="research-shell">
      <aside className="control-column">
        <section className="composer-panel">
          <form className="composer-form" onSubmit={handleRunJob}>
            <div className="composer-section">
              <div className="control-section-header">
                <div>
                  <p className="card-label">YouTube 链接</p>
                  <h1 className="panel-title">研究台</h1>
                </div>
                <span className="control-pill">{runStateLabel}</span>
              </div>

              <label className="sr-only" htmlFor="youtube-url">
                YouTube URL
              </label>
              <textarea
                id="youtube-url"
                name="youtube-url"
                className="url-input"
                rows={5}
                placeholder="https://www.youtube.com/watch?v=..."
                value={youtubeUrl}
                onChange={(event) => setYoutubeUrl(event.target.value)}
              />
            </div>

            <div className="composer-section">
              <TranslationSettingsPanel
                settings={settings}
                onChange={setSettings}
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
        <JobResultPanel jobResult={jobResult} settings={settings} />
      </section>

      <section className="chat-column">
        <ContentChatPanel jobResult={jobResult} settings={settings} />
      </section>
    </main>
  );
}
