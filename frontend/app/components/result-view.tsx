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
  rewriteProviderLabel: string;
  rewriteLoading: boolean;
  rewriteError: string;
  rewriteText: string;
  rewriteCopied: boolean;
  detailCoverageIssues: string[];
  detailPatchLoading: boolean;
  messages: ThreadMessage[];
  chatInput: string;
  chatSubmitting: boolean;
  chatError: string;
  shortcuts: ChatShortcut[];
  onCopyRewrite: () => Promise<void>;
  onExportRewrite: () => void;
  onRequestDetailPatch: () => Promise<void>;
  onSubmitShortcut: (prompt: string) => Promise<void>;
  onSubmitChat: () => Promise<void>;
  onChangeChatInput: (value: string) => void;
};

export function ResultView({
  jobResult,
  rewriteProviderLabel,
  rewriteLoading,
  rewriteError,
  rewriteText,
  rewriteCopied,
  detailCoverageIssues,
  detailPatchLoading,
  messages,
  chatInput,
  chatSubmitting,
  chatError,
  shortcuts,
  onCopyRewrite,
  onExportRewrite,
  onRequestDetailPatch,
  onSubmitShortcut,
  onSubmitChat,
  onChangeChatInput,
}: ResultViewProps) {
  const showDetailCoverageNotice =
    !rewriteLoading && rewriteText.trim().length > 0 && detailCoverageIssues.length > 0;
  return (
    <section className="result-page">
      <div className="result-scroll">
        <article className="result-article">
          <h2>{jobResult.video.title || "中文改写结果"}</h2>
          {rewriteProviderLabel ? (
            <p className="result-provider">{rewriteProviderLabel}</p>
          ) : null}
          {rewriteError ? <p className="entry-error">{rewriteError}</p> : null}
          {showDetailCoverageNotice ? (
            <div
              className="result-detail-coverage"
              role="status"
              aria-live="polite"
            >
              <span className="result-detail-coverage-text">
                {detailPatchLoading
                  ? "正在补足缺失细节..."
                  : `有 ${detailCoverageIssues.length} 处细节可能缺失`}
              </span>
              <button
                className="result-detail-coverage-action"
                type="button"
                disabled={detailPatchLoading}
                onClick={() => void onRequestDetailPatch()}
              >
                {detailPatchLoading ? "补足中..." : "再次补足"}
              </button>
            </div>
          ) : null}
          <div className="result-body">
            <pre>
              {rewriteLoading
                ? "正在生成改写内容..."
                : rewriteText || "改写结果为空，请尝试再次改写。"}
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
            <p className="chat-placeholder">有问题，尽管问</p>
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
