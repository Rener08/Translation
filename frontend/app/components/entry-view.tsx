import { ArrowUp } from "lucide-react";


type EntryViewProps = {
  youtubeUrl: string;
  isRunning: boolean;
  jobStatusMessage: string;
  errorMessage: string;
  onChangeUrl: (value: string) => void;
  onSubmit: () => void;
};

export function EntryView({
  youtubeUrl,
  isRunning,
  jobStatusMessage,
  errorMessage,
  onChangeUrl,
  onSubmit,
}: EntryViewProps) {
  return (
    <section className="entry-page">
      <h2 className="entry-title">YouTube 翻译助手</h2>
      <form
        className="entry-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmit();
        }}
      >
        <input
          type="url"
          placeholder="粘贴 YouTube 视频链接，例如：https://www.youtube.com/watch?v=..."
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
      {jobStatusMessage ? <p className="entry-status">{jobStatusMessage}</p> : null}
      {errorMessage ? <p className="entry-error">{errorMessage}</p> : null}
    </section>
  );
}
