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

/** Canonical watch URL for attribution footers and exports. */
export function youtubeWatchUrl(videoId: string): string {
  const id = String(videoId || "").trim();
  if (!id) {
    return "";
  }
  return `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
}

/** Markdown body for export/download with source attribution (not added on clipboard copy). */
export function buildRewriteExportMarkdown(
  headingLine: string,
  bodyText: string,
  jobResult: JobResult,
): string {
  const title = String(jobResult.video.title || "").trim() || "未命名视频";
  const watch = youtubeWatchUrl(jobResult.video.video_id);
  const footer = [
    "",
    "---",
    "",
    `来源标题：${title}`,
    ...(watch ? [`来源链接：${watch}`] : []),
    "",
    "_本文由 Translation Writing Workbench 根据上述来源素材自动生成，请自行核对事实与版权。_",
    "",
  ].join("\n");
  return `${headingLine}\n\n${bodyText.trim()}\n${footer}`;
}

/** Safe ASCII-ish filename fragment from video title. */
export function rewriteExportBasename(jobResult: JobResult): string {
  const raw = String(jobResult.video.title || "").trim() || "rewrite";
  const collapsed = raw.replace(/\s+/g, "-");
  const safe = collapsed.replace(/[^a-zA-Z0-9\u4e00-\u9fff._-]+/g, "").slice(0, 80);
  return safe || "rewrite";
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export type JobRunStatusResponse = {
  ok: boolean;
  job_id: string;
  status: JobStatus;
  progress_value: number;
  progress_text?: string | null;
  stage?: "inspect" | "fetch_source" | "transcribe" | "translate" | "persist" | null;
  started_at?: string | null;
  updated_at?: string | null;
  timeout_sec?: number | null;
  result?: JobResult | null;
  error?: string | null;
  error_code?: string | null;
  retryable?: boolean | null;
};

type ApiErrorResponseBody = {
  detail?: unknown;
  error_code?: unknown;
  retryable?: unknown;
  request_id?: unknown;
};

type ParsedApiError = {
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

export const REWRITE_STYLE = {
  SPEECH_VERBATIM: "speech_verbatim",
  ARTICLE_LONGFORM: "article_longform",
} as const;

export type RewriteStyle =
  (typeof REWRITE_STYLE)[keyof typeof REWRITE_STYLE];

export const DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS =
  "保留原作者的说话节奏和口吻，只做轻度整理，不要总结化重写。";

export const DEFAULT_ARTICLE_LONGFORM_REWRITE_FOCUS =
  "改写成第三视角的中文文章，保留原意和事实，不删关键信息，不使用第一人称自述。";

export const LEGACY_ARTICLE_LONGFORM_REWRITE_FOCUS =
  "保留原意和事实，不删关键信息，改写为更有节奏和可读性的中文内容。";

export const SOURCE_MODE = {
  SUBTITLE_FIRST: "subtitle_first",
  FORCE_AUDIO: "force_audio",
} as const;

export type SourceMode = (typeof SOURCE_MODE)[keyof typeof SOURCE_MODE];

export type TranslationSettings = {
  provider: TranslationProvider;
  sourceMode: SourceMode;
  apiKey: string;
  baseUrl: string;
  model: string;
  headersJson: string;
  rewriteStyle: RewriteStyle;
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

const configuredApiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim();
let resolvedApiBaseUrl: string | null = null;
let lastKnownApiBaseUrl: string | null = null;

export const defaultApiBaseUrl = configuredApiBaseUrl || "http://localhost:8000";

export const defaultTranslationProvider = resolveProvider(
  process.env.NEXT_PUBLIC_DEFAULT_TRANSLATION_PROVIDER,
  "deepseek",
);

const OPENAI_DEFAULT_MODEL = "gpt-4.1-mini";
const DEEPSEEK_DEFAULT_MODEL = "deepseek-chat";
const KNOWN_REMOTE_DEFAULT_MODELS = new Set([
  OPENAI_DEFAULT_MODEL,
  DEEPSEEK_DEFAULT_MODEL,
]);

export function getProviderDefaultModel(provider: TranslationProvider): string {
  if (provider === "openai") {
    return OPENAI_DEFAULT_MODEL;
  }
  if (provider === "deepseek") {
    return DEEPSEEK_DEFAULT_MODEL;
  }
  return "";
}

export function getProviderModelPlaceholder(provider: TranslationProvider): string {
  const defaultModel = getProviderDefaultModel(provider);
  if (defaultModel) {
    return defaultModel;
  }
  return "留空，后端自动探测";
}

export function normalizeTranslationModel(
  provider: TranslationProvider,
  model: string,
): string {
  const trimmedModel = model.trim();
  const providerDefaultModel = getProviderDefaultModel(provider);
  if (providerDefaultModel) {
    if (!trimmedModel) {
      return providerDefaultModel;
    }
    if (trimmedModel === providerDefaultModel) {
      return trimmedModel;
    }
    if (KNOWN_REMOTE_DEFAULT_MODELS.has(trimmedModel)) {
      return providerDefaultModel;
    }
    return trimmedModel;
  }

  if (!trimmedModel) {
    return "";
  }
  if (KNOWN_REMOTE_DEFAULT_MODELS.has(trimmedModel)) {
    return "";
  }
  return trimmedModel;
}

export const defaultSettings: TranslationSettings = {
  provider: defaultTranslationProvider,
  sourceMode: SOURCE_MODE.SUBTITLE_FIRST,
  apiKey: "",
  baseUrl: "",
  model: getProviderDefaultModel(defaultTranslationProvider),
  headersJson: "",
  rewriteStyle: REWRITE_STYLE.SPEECH_VERBATIM,
};

function normalizeApiBase(url: string): string {
  return url.replace(/\/+$/, "");
}

function getApiBaseCandidates(): string[] {
  const candidates: string[] = [];
  const seen = new Set<string>();
  const push = (value: string) => {
    const normalized = normalizeApiBase(value.trim());
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    candidates.push(normalized);
  };

  if (configuredApiBaseUrl) {
    push(configuredApiBaseUrl);
  }

  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location;
    if (hostname) {
      push(`${protocol}//${hostname}:8000`);
      push(`${protocol}//${hostname}:8002`);
    }
  }

  push("http://localhost:8000");
  push("http://localhost:8002");
  push("http://127.0.0.1:8000");
  push("http://127.0.0.1:8002");

  return candidates;
}

function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

async function probeApiBase(base: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(`${base}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
}

function parseApiErrorResponse(rawText: string): ParsedApiError | null {
  const trimmed = rawText.trim();
  if (!trimmed) {
    return null;
  }

  try {
    const parsed = JSON.parse(trimmed) as ApiErrorResponseBody;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }

    const detail =
      typeof parsed.detail === "string" ? parsed.detail.trim() : "";
    const errorCode =
      typeof parsed.error_code === "string" ? parsed.error_code.trim() : "";
    const requestId =
      typeof parsed.request_id === "string" ? parsed.request_id.trim() : "";
    const retryable =
      typeof parsed.retryable === "boolean" ? parsed.retryable : null;

    const message = detail || errorCode || trimmed;
    return {
      message,
      errorCode,
      retryable,
      requestId,
    };
  } catch {
    return null;
  }
}

function formatParsedApiError(error: ParsedApiError): string {
  const parts: string[] = [];
  const normalizedMessage = normalizeApiErrorMessage(error.message);
  if (error.errorCode) {
    parts.push(`[${error.errorCode}]`);
  }
  parts.push(normalizedMessage);
  if (error.retryable === true) {
    parts.push("（可重试）");
  }
  if (error.requestId) {
    parts.push(`request_id=${error.requestId}`);
  }
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

async function resolveApiBase(): Promise<string> {
  if (resolvedApiBaseUrl) {
    return resolvedApiBaseUrl;
  }

  if (configuredApiBaseUrl) {
    resolvedApiBaseUrl = normalizeApiBase(configuredApiBaseUrl);
    lastKnownApiBaseUrl = resolvedApiBaseUrl;
    return resolvedApiBaseUrl;
  }

  const candidates = getApiBaseCandidates();
  for (const base of candidates) {
    if (await probeApiBase(base)) {
      resolvedApiBaseUrl = base;
      lastKnownApiBaseUrl = base;
      return base;
    }
  }

  if (lastKnownApiBaseUrl) {
    resolvedApiBaseUrl = lastKnownApiBaseUrl;
    return lastKnownApiBaseUrl;
  }

  throw new Error(
    "Cannot connect to backend API. Start backend on port 8000 or 8002, or set NEXT_PUBLIC_API_BASE_URL.",
  );
}

/** Merge optional Bearer token for `/api/*` when NEXT_PUBLIC_API_AUTH_TOKEN matches backend API_AUTH_TOKEN (localhost MVP only). */
function applyPublicApiAuth(
  normalizedPath: string,
  init?: RequestInit,
): RequestInit {
  const token = (process.env.NEXT_PUBLIC_API_AUTH_TOKEN ?? "").trim();
  if (!token || !normalizedPath.startsWith("/api/")) {
    return { ...(init ?? {}) };
  }
  const headers = new Headers(init?.headers ?? undefined);
  if (!headers.has("Authorization") && !headers.has("x-api-token")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return { ...(init ?? {}), headers };
}

export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  let base = await resolveApiBase();
  const requestInit = applyPublicApiAuth(normalizedPath, init);

  try {
    const response = await fetch(`${base}${normalizedPath}`, requestInit);
    lastKnownApiBaseUrl = base;
    return response;
  } catch (error) {
    if (!isNetworkError(error)) {
      throw error;
    }
    // If we already have a configured or last-known backend URL, retry it once
    // before forcing a fresh /health probing flow.
    if (base) {
      try {
        const retryResponse = await fetch(`${base}${normalizedPath}`, requestInit);
        lastKnownApiBaseUrl = base;
        return retryResponse;
      } catch (retryError) {
        if (!isNetworkError(retryError)) {
          throw retryError;
        }
      }
    }
    resolvedApiBaseUrl = null;
    base = await resolveApiBase();
    return fetch(`${base}${normalizedPath}`, requestInit);
  }
}

export function buildTranslationConfig(
  settings: TranslationSettings,
): TranslationConfigPayload {
  const extraHeaders = parseHeadersJson(settings.headersJson);
  const model = normalizeTranslationModel(settings.provider, settings.model);

  const payload: TranslationConfigPayload = {
    provider: settings.provider,
  };

  if (settings.apiKey.trim()) {
    payload.api_key = settings.apiKey.trim();
  }

  if (settings.baseUrl.trim()) {
    payload.base_url = settings.baseUrl.trim();
  }

  if (model) {
    payload.model = model;
  }

  if (Object.keys(extraHeaders).length > 0) {
    payload.extra_headers = extraHeaders;
  }

  return payload;
}

export function parseHeadersJson(headersJson: string): Record<string, string> {
  if (!headersJson.trim()) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(headersJson);
  } catch {
    throw new Error("Custom headers must be a valid JSON object.");
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Custom headers must be a JSON object.");
  }

  const headers: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed)) {
    const normalizedKey = key.trim();
    const normalizedValue = String(value).trim();
    if (!normalizedKey || !normalizedValue) {
      continue;
    }
    headers[normalizedKey] = normalizedValue;
  }

  return headers;
}

export function buildTranslationText(segments: TranslationSegment[]): string {
  if (segments.length === 0) {
    return "No Chinese translation returned.";
  }

  return segments.map((segment) => segment.translated_text).join("\n");
}

export function formatProviderName(provider: TranslationProvider | string): string {
  if (provider === "openai") {
    return "OpenAI";
  }
  if (provider === "deepseek") {
    return "DeepSeek";
  }
  if (provider === "lmstudio") {
    return "LM Studio";
  }
  return "Ollama";
}

export async function extractApiErrorMessage(
  response: Response,
): Promise<string> {
  const rawText = (await response.text()).trim();

  if (rawText) {
    const parsed = parseApiErrorResponse(rawText);
    if (parsed) {
      return formatParsedApiError(parsed);
    }

    return normalizeApiErrorMessage(rawText);
  }

  if (response.status === 502) {
    return normalizeApiErrorMessage(
      "Upstream video fetch failed while accessing YouTube. For restricted videos only, use YTDLP_COOKIES_FILE as an advanced fallback.",
    );
  }

  return `Request failed with status ${response.status}`;
}

export async function waitForJobResult(
  jobId: string,
  onStatus?: (status: JobRunStatusResponse) => void,
  options?: { signal?: AbortSignal },
): Promise<JobResult> {
  const normalizedJobId = jobId.trim();
  if (!normalizedJobId) {
    throw new Error("Job id is missing.");
  }

  const signal = options?.signal;
  const deadline = Date.now() + 30 * 60 * 1000;
  let lastMessage = "正在等待任务完成...";
  let lastStage = "";

  while (Date.now() < deadline) {
    if (signal?.aborted) {
      throw new Error("Request aborted.");
    }
    const response = await apiFetch(`/api/jobs/${encodeURIComponent(normalizedJobId)}`);
    if (!response.ok) {
      throw new Error(await extractApiErrorMessage(response));
    }

    const data = (await response.json()) as JobRunStatusResponse;
    onStatus?.(data);
    if (data.progress_text) {
      lastMessage = data.progress_text;
    }
    if (typeof data.stage === "string" && data.stage.trim()) {
      lastStage = mapJobStageLabel(data.stage);
    }

    if (data.status === "done") {
      if (!data.result) {
        throw new Error("Job completed without a result.");
      }
      return data.result;
    }

    if (data.status === "failed") {
      let detail = data.error || lastMessage || "Job failed.";
      const errorCode = String(data.error_code || "").trim();
      if (errorCode === "JOB_INTERRUPTED_RESTART") {
        detail = `${detail} 后端重启会导致任务中断，请重新粘贴同一链接并开始处理。`;
      } else if (data.retryable) {
        detail = `${detail}（可重试：请稍后重试或重新提交同一链接。）`;
      }
      if (errorCode) {
        throw new Error(`[${errorCode}] ${detail}`);
      }
      throw new Error(detail);
    }
    if (data.status === "cancelled") {
      throw new Error(data.error || "任务已取消。");
    }

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        cleanup();
        resolve();
      }, 1000);

      const cleanup = () => {
        window.clearTimeout(timeout);
        signal?.removeEventListener("abort", onAbort);
      };

      const onAbort = () => {
        cleanup();
        reject(new Error("Request aborted."));
      };

      if (signal?.aborted) {
        cleanup();
        reject(new Error("Request aborted."));
        return;
      }

      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }

  if (lastStage) {
    throw new Error(`${lastMessage}（当前阶段：${lastStage}）`);
  }
  throw new Error(lastMessage || "Job timed out while waiting for completion.");
}

export function mapJobStageLabel(stage: string): string {
  if (stage === "inspect") {
    return "解析视频";
  }
  if (stage === "fetch_source") {
    return "提取素材";
  }
  if (stage === "transcribe") {
    return "转录";
  }
  if (stage === "translate") {
    return "翻译整理";
  }
  if (stage === "persist") {
    return "保存结果";
  }
  return stage;
}

export function normalizeApiErrorMessage(message: string): string {
  const normalized = message.replace(/\s+/g, " ").trim();
  const lowered = normalized.toLowerCase();

  if (lowered.includes("could not copy chrome cookie database")) {
    return (
      "视频可能受限。若必须走登录态兜底，请先关闭 Chrome，再导出 cookies.txt 并设置 YTDLP_COOKIES_FILE。"
    );
  }

  if (lowered.includes("failed to decrypt with dpapi")) {
    return (
      "浏览器 cookies 无法解密。仅在受限视频场景下，改用导出的 cookies.txt（YTDLP_COOKIES_FILE）兜底。"
    );
  }

  if (lowered.includes("sign in to confirm you're not a bot")) {
    return (
      "该视频触发了 YouTube 登录验证。可继续重试字幕/音频路径；若仍失败，再配置 cookies.txt 作为高级兜底。"
    );
  }

  if (
    lowered.includes("http error 429") ||
    lowered.includes("too many requests") ||
    lowered.includes("unable to download webpage")
  ) {
    return (
      "YouTube 返回 429（访问过于频繁/风控拦截）。请稍后重试；仅在持续失败时，再配置 cookies.txt 兜底。"
    );
  }

  if (lowered.includes("remotedisconnected") || lowered.includes("connection aborted")) {
    return (
      "上游服务连接被中断（RemoteDisconnected），请重试；如果反复出现，请检查 " +
      "API Key、base_url 和模型可用性。"
    );
  }

  if (
    lowered.includes("whisper") &&
    (lowered.includes("failed") || lowered.includes("error") || lowered.includes("runtime"))
  ) {
    return "Whisper 处理失败，请检查本地模型、音频文件或设备配置。";
  }

  if (lowered.includes("job_interrupted_restart")) {
    return "任务因服务重启而中断，请重新提交同一视频链接。";
  }

  return normalized;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) {
    return "Unknown";
  }

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${remainingSeconds}s`;
  }

  if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`;
  }

  return `${remainingSeconds}s`;
}

export function formatTimestamp(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;

  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  }

  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

export function resolveProvider(
  rawValue: string | undefined,
  fallback: TranslationProvider,
): TranslationProvider {
  if (
    rawValue === "openai" ||
    rawValue === "deepseek" ||
    rawValue === "lmstudio" ||
    rawValue === "ollama"
  ) {
    return rawValue;
  }

  return fallback;
}
