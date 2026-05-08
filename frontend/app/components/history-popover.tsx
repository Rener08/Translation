"use client";

type SearchHistoryItem = {
  url: string;
  title: string;
  updated_at: string;
};

type SessionHistorySummary = {
  content_context_id: string;
  video_title?: string | null;
  video_url?: string | null;
  updated_at?: string | null;
  rewritten_preview?: string;
  transcript_preview?: string;
  translation_preview?: string;
};

type HistoryPopoverProps = {
  variant?: "landing" | "result";
  historyQuery: string;
  visibleSearchHistoryItems: SearchHistoryItem[];
  historyItems: SessionHistorySummary[];
  historyLoading: boolean;
  historyError: string;
  onClose: () => void;
  onQueryChange: (value: string) => void;
  onSelectUrl: (url: string) => void;
  onSelectSession: (contentContextId: string) => void;
};

export function HistoryPopover({
  variant = "landing",
  historyQuery,
  visibleSearchHistoryItems,
  historyItems,
  historyLoading,
  historyError,
  onClose,
  onQueryChange,
  onSelectUrl,
  onSelectSession,
}: HistoryPopoverProps) {
  return (
    <aside
      className={`history-popover${variant === "result" ? " history-popover-result" : ""}`}
    >
      <div className="history-popover-panel">
        <div className="history-popover-header">
          <h2 className="history-popover-title">历史对话</h2>
          <button className="history-popover-close" type="button" onClick={onClose}>
            ×
          </button>
        </div>
        <input
          className="history-popover-search"
          type="search"
          placeholder="搜索历史..."
          value={historyQuery}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <div className="history-popover-section">
          <div className="history-popover-section-header">
            <span>搜索历史</span>
            <span className="history-popover-section-count">
              {visibleSearchHistoryItems.length}
            </span>
          </div>
          <div className="history-popover-list">
            {visibleSearchHistoryItems.map((item) => (
              <button
                key={item.url}
                className="history-popover-item"
                type="button"
                onClick={() => onSelectUrl(item.url)}
              >
                <span className="history-popover-item-title">{item.title}</span>
                <span className="history-popover-item-meta">{item.url}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="history-popover-section">
          <div className="history-popover-section-header">
            <span>对话历史</span>
            <span className="history-popover-section-count">{historyItems.length}</span>
          </div>
          <div className="history-popover-list">
            {historyItems.map((item) => (
              <button
                key={item.content_context_id}
                className="history-popover-item"
                type="button"
                onClick={() => onSelectSession(item.content_context_id)}
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
  );
}
