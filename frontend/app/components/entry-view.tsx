import { useRef } from "react";

import { ArrowUp, CircleX, Plus } from "lucide-react";

type EntryViewProps = {
  youtubeUrl: string;
  selectedAudioName: string;
  isRunning: boolean;
  jobStatusMessage: string;
  errorMessage: string;
  onChangeUrl: (value: string) => void;
  onPickAudioFile: (file: File | null) => void;
  onSubmit: () => void;
  onCancel: () => void;
};

export function EntryView({
  youtubeUrl,
  selectedAudioName,
  isRunning,
  jobStatusMessage,
  errorMessage,
  onChangeUrl,
  onPickAudioFile,
  onSubmit,
  onCancel,
}: EntryViewProps) {
  const hasUploadedAudio = selectedAudioName.trim().length > 0;
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function openFilePicker() {
    if (isRunning) {
      return;
    }
    fileInputRef.current?.click();
  }

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
          type="button"
          className="entry-upload-button"
          disabled={isRunning}
          onClick={openFilePicker}
          aria-label="上传本地音频或视频"
          title="上传本地音频或视频"
        >
          <Plus size={18} strokeWidth={2.2} />
        </button>
        <input
          key={selectedAudioName || "empty-upload"}
          ref={fileInputRef}
          className="entry-upload-input"
          type="file"
          accept="audio/*,video/*,.m4a,.mp3,.wav,.webm,.mp4,.mov,.mkv,.flac,.ogg,.opus,.aac"
          disabled={isRunning}
          onChange={(event) => onPickAudioFile(event.target.files?.[0] ?? null)}
        />
        <button
          type="submit"
          className="entry-submit"
          disabled={isRunning || (youtubeUrl.trim().length === 0 && !hasUploadedAudio)}
          aria-label="提交任务"
        >
          {isRunning ? "…" : <ArrowUp size={17} strokeWidth={2.2} />}
        </button>
        {isRunning ? (
          <button
            type="button"
            className="entry-cancel"
            onClick={onCancel}
            aria-label="取消任务"
          >
            <CircleX size={15} strokeWidth={2.1} />
            取消
          </button>
        ) : null}
      </form>

      {hasUploadedAudio ? (
        <div className="entry-selection-row">
          <span className="entry-selection-chip" title={selectedAudioName}>
            {selectedAudioName}
          </span>
          <button
            type="button"
            className="entry-selection-clear"
            onClick={() => onPickAudioFile(null)}
            disabled={isRunning}
          >
            清空
          </button>
        </div>
      ) : null}

      {jobStatusMessage ? <p className="entry-status">{jobStatusMessage}</p> : null}
      {errorMessage ? <p className="entry-error">{errorMessage}</p> : null}
    </section>
  );
}
