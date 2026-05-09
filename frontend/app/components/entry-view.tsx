import { ArrowUp } from "lucide-react";


type EntryViewProps = {
  youtubeUrl: string;
  isRunning: boolean;
  jobStatusMessage: string;
  errorMessage: string;
  onChangeUrl: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => Promise<void>;
};

export function EntryView({
  youtubeUrl,
  isRunning,
  jobStatusMessage,
  errorMessage,
  onChangeUrl,
  onSubmit,
  onCancel,
}: EntryViewProps) {
  return (
    <section className="entry-page">
      <h2 className="entry-title">链接素材 → 中文文章</h2>
      <form
        className="entry-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmit();
        }}
      >
        <input
          type="url"
          placeholder="粘贴 YouTube 链接，生成中文文章草稿"
          value={youtubeUrl}
          onChange={(event) => onChangeUrl(event.target.value)}
        />
        <button
          type="submit"
          className="entry-submit"
          disabled={isRunning || youtubeUrl.trim().length === 0}
          aria-label="提交链接"
        >
          {isRunning ? "…" : <ArrowUp size={17} strokeWidth={2.2} />}
        </button>
      </form>
      {isRunning ? (
        <button
          type="button"
          className="entry-cancel"
          onClick={() => void onCancel()}
        >
          取消当前任务
        </button>
      ) : null}
      {jobStatusMessage ? <p className="entry-status">{jobStatusMessage}</p> : null}
      {errorMessage ? <p className="entry-error">{errorMessage}</p> : null}
    </section>
  );
}
