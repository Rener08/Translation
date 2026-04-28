"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ContentChatMessage,
  ContentChatResponse,
  JobResult,
  TranslationSettings,
  apiFetch,
  buildTranslationText,
  extractApiErrorMessage,
} from "../lib/job";

type ContentChatPanelProps = {
  jobResult: JobResult | null;
  settings: TranslationSettings;
};

type ThreadMessage = ContentChatMessage & {
  pending?: boolean;
};

export function ContentChatPanel({ jobResult, settings }: ContentChatPanelProps) {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const translationText = useMemo(
    () =>
      jobResult
        ? buildTranslationText(jobResult.translation_zh.segments)
        : "No Chinese translation returned.",
    [jobResult],
  );

  useEffect(() => {
    setMessages([]);
    setQuestion("");
    setErrorMessage("");
  }, [jobResult?.video.video_id]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || isSubmitting || !jobResult) {
      return;
    }

    const cleanHistory = messages
      .filter((message) => !message.pending)
      .map(({ role, content }) => ({ role, content }));
    const userMessage: ThreadMessage = { role: "user", content: trimmedQuestion };
    const pendingAssistantMessage: ThreadMessage = {
      role: "assistant",
      content: "思考中...",
      pending: true,
    };

    setIsSubmitting(true);
    setErrorMessage("");
    setQuestion("");
    setMessages([...cleanHistory, userMessage, pendingAssistantMessage]);

    try {
      const response = await apiFetch("/api/content-chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          content_context_id: jobResult.content_context_id,
          video_title: jobResult.video.title,
          transcript_en: jobResult.transcript_en.text,
          translation_zh: translationText,
          question: trimmedQuestion,
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
      setErrorMessage(
        error instanceof Error ? error.message : "Failed to answer this question.",
      );
      setMessages((current) => current.filter((message) => !message.pending));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="chat-card compact-chat-card">
      <div className="chat-card-header compact-chat-header simple-chat-header">
        <div>
          <p className="card-label">Chat</p>
          <h2 className="panel-title">Content Chat</h2>
        </div>
      </div>

      <div className="chat-thread compact-chat-thread">
        {!jobResult ? (
          <div className="chat-empty-state compact-chat-empty-state">
            <p>先运行一次转写和翻译。</p>
            <ul>
              <li>右侧聊天会自动使用当前视频内容。</li>
              <li>支持继续追问、总结、解释和提炼观点。</li>
            </ul>
          </div>
        ) : messages.length === 0 ? (
          <div className="chat-empty-state compact-chat-empty-state">
            <p>你可以直接从这里开始：</p>
            <ul>
              <li>右侧聊天会自动使用当前视频内容。</li>
              <li>支持继续追问、总结、解释和提炼观点。</li>
            </ul>
          </div>
        ) : (
          messages.map((message, index) => (
            <article
              className={`chat-message chat-message-${message.role}`}
              key={`${message.role}-${index}`}
            >
              <div className="chat-message-header">
                <span className="chat-role">
                  {message.role === "user" ? "我" : "内容助手"}
                </span>
              </div>
              <p className="chat-message-content">{message.content}</p>
            </article>
          ))
        )}
      </div>

      {errorMessage ? <p className="chat-error-text">{errorMessage}</p> : null}

      <form className="chat-form compact-chat-form" onSubmit={handleSubmit}>
        <textarea
          className="chat-question-input"
          rows={3}
          placeholder="输入问题，回车发送，Shift+Enter 换行。"
          value={question}
          disabled={!jobResult}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="chat-form-footer">
          <button
            className="primary-button compact-primary-button"
            type="submit"
            disabled={!jobResult || isSubmitting || question.trim().length === 0}
          >
            {isSubmitting ? "…" : "↑"}
          </button>
        </div>
      </form>
    </section>
  );
}
