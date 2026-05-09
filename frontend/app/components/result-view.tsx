import { ArrowUp, Copy, Download } from "lucide-react";
import type { ComponentType } from "react";

import { JobResult } from "../lib/job";
import { ThreadMessage } from "../hooks/use-rewrite-chat";


type ChatShortcut = {
  key: string;
  label: string;
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
  prompt: string;
};

type ResultViewProps = {
  jobResult: JobResult;
  articleProfileLabel: string;
  translationText: string;
  rewriteProviderLabel: string;
  rewriteLoading: boolean;
  rewriteError: string;
  rewriteText: string;
  rewriteCopied: boolean;
  messages: ThreadMessage[];
  chatInput: string;
  chatSubmitting: boolean;
  chatError: string;
  shortcuts: ChatShortcut[];
  onCopyRewrite: () => Promise<void>;
  onExportRewrite: () => void;
  onSubmitShortcut: (prompt: string) => Promise<void>;
  onSubmitChat: () => Promise<void>;
  onChangeChatInput: (value: string) => void;
};

export function ResultView({
  jobResult,
  articleProfileLabel,
  translationText,
  rewriteProviderLabel,
  rewriteLoading,
  rewriteError,
  rewriteText,
  rewriteCopied,
  messages,
  chatInput,
  chatSubmitting,
  chatError,
  shortcuts,
  onCopyRewrite,
  onExportRewrite,
  onSubmitShortcut,
  onSubmitChat,
  onChangeChatInput,
}: ResultViewProps) {
  return (
    <section className="result-page">
      <div className="result-scroll">
        <article className="result-article">
          <h2>{jobResult.video.title || "Article Draft"}</h2>
          <p className="result-provider">文章规格：{articleProfileLabel}</p>
          {rewriteProviderLabel ? (
            <p className="result-provider">{rewriteProviderLabel}</p>
          ) : null}
          {rewriteError ? <p className="entry-error">{rewriteError}</p> : null}
          <div className="result-body">
            <pre>
              {rewriteLoading
                ? "正在生成文章草稿..."
                : rewriteText || "文章草稿为空，请尝试再次生成。"}
            </pre>
          </div>
          <div className="result-actions-inline">
            <button
              className="icon-ghost"
              type="button"
              aria-label={rewriteCopied ? "已复制" : "复制"}
              title={rewriteCopied ? "已复制" : "复制"}
              disabled={!rewriteText.trim()}
              onClick={() => void onCopyRewrite()}
            >
              <Copy size={16} />
            </button>
            <button
              className="icon-ghost"
              type="button"
              aria-label="导出"
              title="导出"
              disabled={!rewriteText.trim()}
              onClick={onExportRewrite}
            >
              <Download size={16} />
            </button>
          </div>
        </article>

        <details className="material-details">
          <summary>素材详情（转录/翻译）</summary>
          <div className="material-grid">
            <article className="material-card">
              <h3>英文转录</h3>
              <pre>{jobResult.transcript_en.text || "无转录文本。"}</pre>
            </article>
            <article className="material-card">
              <h3>中文翻译</h3>
              <pre>{translationText || "无翻译文本。"}</pre>
            </article>
          </div>
        </details>

        <section className="chat-thread">
          {messages.map((message, index) => (
            <article
              className={`chat-bubble ${message.role === "user" ? "is-user" : "is-assistant"}`}
              key={`${message.role}-${index}`}
            >
              <p>{message.content}</p>
            </article>
          ))}
          {messages.length === 0 ? (
            <p className="chat-placeholder">可继续追改、补充、压缩或重写结构。</p>
          ) : null}
        </section>
      </div>

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmitChat();
        }}
      >
        <div className="chat-shortcuts">
          {shortcuts.map((shortcut) => {
            const Icon = shortcut.icon;
            return (
              <button
                key={shortcut.key}
                className="icon-ghost"
                type="button"
                title={shortcut.label}
                aria-label={shortcut.label}
                disabled={chatSubmitting}
                onClick={() => void onSubmitShortcut(shortcut.prompt)}
              >
                <Icon size={15} />
              </button>
            );
          })}
        </div>
        <div className="chat-input-row">
          <textarea
            rows={2}
            placeholder="输入问题，回车发送，Shift+Enter 换行"
            value={chatInput}
            onChange={(event) => onChangeChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void onSubmitChat();
              }
            }}
          />
          <button
            className="entry-submit"
            type="submit"
            disabled={chatSubmitting || chatInput.trim().length === 0}
            aria-label="发送问题"
          >
            {chatSubmitting ? "…" : <ArrowUp size={16} strokeWidth={2.2} />}
          </button>
        </div>
        {chatError ? <p className="entry-error">{chatError}</p> : null}
      </form>
    </section>
  );
}
