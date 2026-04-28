import { ViewState, formatProviderName } from "../lib/job";

type StatusCardProps = {
  viewState: ViewState;
  provider: string;
  sourceType?: string;
};

type StepState = "done" | "active" | "queued" | "error";

type PipelineStep = {
  code: string;
  title: string;
  detail: string;
  state: StepState;
};

function buildSteps(
  tone: ViewState["tone"],
  provider: string,
  sourceType?: string,
): PipelineStep[] {
  const sourceDetail = sourceType
    ? sourceType === "audio"
      ? "Media download completed and a local audio file is ready for Whisper."
      : "A non-audio source was reported by the backend."
    : "Awaiting media download from YouTube.";

  if (tone === "success") {
    return [
      {
        code: "01",
        title: "Inspect URL",
        detail: "Metadata and download information loaded from YouTube.",
        state: "done",
      },
      {
        code: "02",
        title: "Download audio",
        detail: sourceDetail,
        state: "done",
      },
      {
        code: "03",
        title: "Run Whisper",
        detail: "Whisper returned English transcript segments on device.",
        state: "done",
      },
      {
        code: "04",
        title: "Translate",
        detail: `Segment-aligned Simplified Chinese returned via ${formatProviderName(provider)}.`,
        state: "done",
      },
    ];
  }

  if (tone === "running") {
    return [
      {
        code: "01",
        title: "Inspect URL",
        detail: "Contacting the backend and validating the requested video.",
        state: "done",
      },
      {
        code: "02",
        title: "Download audio",
        detail: "Fetching a local audio file through yt-dlp for Whisper.",
        state: "active",
      },
      {
        code: "03",
        title: "Run Whisper",
        detail: "Transcript rows appear here after the local audio file is ready.",
        state: "queued",
      },
      {
        code: "04",
        title: "Translate",
        detail: `${formatProviderName(provider)} waits for each English segment before translation starts.`,
        state: "queued",
      },
    ];
  }

  if (tone === "error") {
    return [
      {
        code: "01",
        title: "Inspect URL",
        detail: "The backend accepted the request and started evaluation.",
        state: "done",
      },
      {
        code: "02",
        title: "Download audio",
        detail: sourceDetail,
        state: sourceType ? "done" : "active",
      },
      {
        code: "03",
        title: "Run Whisper",
        detail:
          sourceType === "audio"
            ? "The audio file exists; review the backend message to see whether Whisper or translation failed."
            : "The run ended before Whisper received the expected audio input.",
        state: sourceType ? "done" : "queued",
      },
      {
        code: "04",
        title: "Translate",
        detail: `The run ended before ${formatProviderName(provider)} completed the full segment set.`,
        state: "error",
      },
    ];
  }

  return [
    {
      code: "01",
      title: "Inspect URL",
      detail: "Ready to inspect the YouTube page and resolve download info.",
      state: "active",
    },
    {
      code: "02",
      title: "Download audio",
      detail: "The backend now downloads audio on every run for Whisper.",
      state: "queued",
    },
    {
      code: "03",
      title: "Run Whisper",
      detail: "Local Whisper transcribes the downloaded file into English segments.",
      state: "queued",
    },
    {
      code: "04",
      title: "Translate",
      detail: `${formatProviderName(provider)} receives one English segment at a time.`,
      state: "queued",
    },
  ];
}

function buildLogLines(
  viewState: ViewState,
  provider: string,
  sourceType?: string,
): string[] {
  const providerName = formatProviderName(provider);

  if (viewState.tone === "success") {
    return [
      `[ok] metadata loaded and source resolved to ${sourceType ?? "unknown"}.`,
      `[ok] English transcript is aligned and ready for review.`,
      `[ok] ${providerName} returned bilingual output for the completed run.`,
      `[ok] monitor status: stable`,
    ];
  }

  if (viewState.tone === "running") {
    return [
      `[run] backend accepted the job request.`,
      `[run] downloading local audio through yt-dlp.`,
      `[run] waiting for English segments before translation dispatch.`,
      `[run] translation target: ${providerName}`,
    ];
  }

  if (viewState.tone === "error") {
    return [
      `[warn] pipeline returned an error state.`,
      `[warn] inspect backend message below for the exact provider or source issue.`,
      `[warn] source path at failure: ${sourceType ?? "not finalized"}.`,
      `[warn] translation target at failure: ${providerName}`,
    ];
  }

  return [
    `[ready] backend endpoint armed and waiting for a job.`,
    `[ready] every run downloads audio first, then transcribes with local Whisper.`,
    `[ready] translation provider default: ${providerName}.`,
    `[ready] monitor status: idle`,
  ];
}

export function StatusCard({
  viewState,
  provider,
  sourceType,
}: StatusCardProps) {
  const providerName = formatProviderName(provider);
  const steps = buildSteps(viewState.tone, provider, sourceType);
  const logLines = buildLogLines(viewState, provider, sourceType);

  return (
    <article className={`status-board tone-${viewState.tone}`}>
      <div className="status-board-header">
        <div>
          <p className="card-label">Pipeline Monitor</p>
          <h2 className="status-title">Local execution grid</h2>
        </div>

        <div className="status-pill-row">
          <span className={`status-badge tone-${viewState.tone}`}>
            {viewState.label}
          </span>
          <span className="status-meta-chip">{providerName}</span>
          {sourceType ? (
            <span className="status-meta-chip source-chip">{sourceType}</span>
          ) : null}
        </div>
      </div>

      <div className="status-board-grid">
        <div className="pipeline-track">
          {steps.map((step) => (
            <div className={`pipeline-step is-${step.state}`} key={step.code}>
              <div className="pipeline-node">
                <span>{step.code}</span>
              </div>
              <div className="pipeline-copy">
                <h3>{step.title}</h3>
                <p>{step.detail}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="log-panel">
          <div className="terminal-bar">
            <span className="terminal-dots" />
            <span className="terminal-title">runtime.monitor.log</span>
          </div>
          <div className="terminal-lines">
            {logLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        </div>
      </div>

      <p className="status-message">{viewState.message}</p>
    </article>
  );
}
