export type TranscriptSegment = {
  index: number;
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
};

export type TranslationSegment = {
  index: number;
  start: number;
  end: number;
  source_text: string;
  translated_text: string;
};

export type JobResult = {
  ok: boolean;
  video: {
    video_id: string;
    title: string;
    thumbnail: string | null;
    duration_sec: number | null;
    uploader: string | null;
  };
  source_type: "captions" | "audio";
  content_context_id: string;
  transcript_en: {
    text: string;
    segments: TranscriptSegment[];
  };
  translation_zh: {
    segments: TranslationSegment[];
  };
};

export type UploadAudioResponse = {
  ok: boolean;
  audio_file_path: string;
  title: string;
  original_filename: string;
  media_type?: string | null;
  byte_count: number;
};

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export type JobRunStatusResponse = {
  ok: boolean;
  job_id: string;
  status: JobStatus;
  progress_value: number;
  progress_text?: string | null;
  stage?: "inspect" | "fetch_source" | "transcribe" | "persist" | null;
  started_at?: string | null;
  updated_at?: string | null;
  timeout_sec?: number | null;
  result?: JobResult | null;
  error?: string | null;
  error_code?: string | null;
  retryable?: boolean | null;
};

// Not re-exported from job.ts — internal use only
export type ApiErrorResponseBody = {
  detail?: unknown;
  error_code?: unknown;
  retryable?: unknown;
  request_id?: unknown;
};

export type ApiErrorDetails = {
  message: string;
  errorCode: string;
  retryable: boolean | null;
  requestId: string;
  status: number;
};

export type RecoveryActionKind =
  | "retry"
  | "retry-job"
  | "retry-rewrite"
  | "retry-detail-patch"
  | "fallback-audio"
  | "open-settings"
  | "run-preflight"
  | "reload-history"
  | "reset-session";

export type RecoveryAction = {
  kind: RecoveryActionKind;
  label: string;
  description: string;
  disabled?: boolean;
};

export type FailureDiagnostic = {
  source: "job" | "rewrite" | "detail_patch" | "preflight" | "history";
  title: string;
  message: string;
  details: string[];
  errorCode: string | null;
  retryable: boolean | null;
  requestId: string;
  stageLabel?: string | null;
  actions: RecoveryAction[];
};

// Not re-exported from job.ts — internal use only
export type ParsedApiError = {
  message: string;
  errorCode: string;
  retryable: boolean | null;
  requestId: string;
};

export type TranslationProvider =
  | "openai"
  | "deepseek"
  | "lmstudio"
  | "ollama";

// Inline literals to avoid circular dep with REWRITE_STYLE const in job.ts
export type RewriteStyle = "speech_verbatim" | "article_longform";

// Inline literals to avoid circular dep with SKILL_CONFIG_NAME const in job.ts
export type SkillConfigName = "kazix" | "latepost";

// Inline literals to avoid circular dep with SOURCE_MODE const in job.ts
export type SourceMode = "subtitle_first" | "force_audio";

export type TranslationSettings = {
  provider: TranslationProvider;
  sourceMode: SourceMode;
  apiKey: string;
  baseUrl: string;
  model: string;
  headersJson: string;
  rewriteStyle: RewriteStyle;
  skillConfigName: SkillConfigName;
};

export type TranslationConfigPayload = {
  provider: TranslationProvider;
  api_key?: string;
  base_url?: string;
  model?: string;
  extra_headers?: Record<string, string>;
};

export type ContentChatResponse = {
  ok: boolean;
  provider: TranslationProvider;
  model: string;
  answer: string;
};

export type ContentRewriteResponse = {
  ok: boolean;
  provider: TranslationProvider;
  model: string;
  rewritten_text: string;
  quality_issues?: string[];
  detail_coverage_issues?: string[];
};

export type SystemYtDlpCookiesResponse = {
  ok: boolean;
  mode: string;
  configured: boolean;
  active_for_yt_dlp: boolean;
  cookies_file: string;
  exists: boolean;
  cookies_text: string;
  byte_count: number;
};

export type PreflightCheck = {
  name: string;
  label: string;
  ok: boolean;
  detail: string;
};

export type PreflightResponse = {
  checks: PreflightCheck[];
  all_ok: boolean;
};

export type ProviderTestConnectionResponse = {
  ok: boolean;
  provider: TranslationProvider;
  reachable: boolean;
  selected_model: string | null;
  discovered_models: string[];
  message: string;
};

export type SettingsPreflightResult = {
  runtime: PreflightResponse;
  provider: ProviderTestConnectionResponse;
  allOk: boolean;
  summary: string;
  details: string[];
};

export type YouTubeAccessStatusResponse = {
  ok: boolean;
  runtime_ok: boolean;
  target_ok: boolean;
  probe_url: string;
  target_url?: string | null;
  normalized_url?: string | null;
  video_id?: string | null;
  title?: string | null;
  source_strategy?: "unknown" | "captions" | "audio" | null;
  cookies_configured: boolean;
  cookies_file_exists: boolean;
  cookies_active_for_yt_dlp: boolean;
  cookie_mode: string;
  error_code?: string | null;
  retryable?: boolean | null;
  message: string;
  recommended_action: string;
  subtitles: string[];
  automatic_captions: string[];
  checks: Record<string, string>;
};
