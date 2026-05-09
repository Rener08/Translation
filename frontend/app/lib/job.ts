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

export type JobStatus = "queued" | "running" | "done" | "failed";

export type JobRunStatusResponse = {
  ok: boolean;
  job_id: string;
  status: JobStatus;
  progress_value: number;
  progress_text?: string | null;
  result?: JobResult | null;
  error?: string | null;
};

export type TranslationProvider =
  | "openai"
  | "deepseek"
  | "lmstudio"
  | "ollama";

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
};

export type TranslationConfigPayload = {
  provider: TranslationProvider;
  api_key?: string;
  base_url?: string;
  model?: string;
  extra_headers?: Record<string, string>;
};

export type ContentChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ContentChatSettings = {
  provider: TranslationProvider;
  apiKey: string;
  baseUrl: string;
  model: string;
  customPrompt: string;
  headersJson: string;
};

export type ContentChatConfigPayload = {
  provider: TranslationProvider;
  api_key?: string;
  base_url?: string;
  model?: string;
  custom_prompt?: string;
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
};

export type ViewState = {
  tone: "idle" | "running" | "success" | "error";
  label: string;
  message: string;
};

const configuredApiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim();
let resolvedApiBaseUrl: string | null = null;
let lastKnownApiBaseUrl: string | null = null;

export const defaultApiBaseUrl = configuredApiBaseUrl || "http://localhost:8000";

export const defaultTranslationProvider = resolveProvider(
  process.env.NEXT_PUBLIC_DEFAULT_TRANSLATION_PROVIDER,
  "deepseek",
);

export const defaultContentChatProvider = resolveProvider(
  process.env.NEXT_PUBLIC_DEFAULT_CHAT_PROVIDER,
  "ollama",
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
};

export const defaultContentChatSettings: ContentChatSettings = {
  provider: defaultContentChatProvider,
  apiKey: "",
  baseUrl: "",
  model: "",
  customPrompt: "",
  headersJson: "",
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

export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  let base = await resolveApiBase();

  try {
    const response = await fetch(`${base}${normalizedPath}`, init);
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
        const retryResponse = await fetch(`${base}${normalizedPath}`, init);
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
    return fetch(`${base}${normalizedPath}`, init);
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

export function buildContentChatConfig(
  settings: ContentChatSettings,
): ContentChatConfigPayload {
  const extraHeaders = parseHeadersJson(settings.headersJson);
  const model = normalizeTranslationModel(settings.provider, settings.model);

  const payload: ContentChatConfigPayload = {
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

  if (settings.customPrompt.trim()) {
    payload.custom_prompt = settings.customPrompt.trim();
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
    try {
      const parsed = JSON.parse(rawText) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) {
        return normalizeApiErrorMessage(parsed.detail);
      }
    } catch {
      return normalizeApiErrorMessage(rawText);
    }

    return normalizeApiErrorMessage(rawText);
  }

  if (response.status === 502) {
    return normalizeApiErrorMessage(
      "Upstream video fetch failed while accessing YouTube. If yt-dlp is using browser cookies, fully close Chrome or configure YTDLP_COOKIES_FILE with an exported cookies.txt file.",
    );
  }

  return `Request failed with status ${response.status}`;
}

export async function waitForJobResult(
  jobId: string,
  onStatus?: (status: JobRunStatusResponse) => void,
): Promise<JobResult> {
  const normalizedJobId = jobId.trim();
  if (!normalizedJobId) {
    throw new Error("Job id is missing.");
  }

  const deadline = Date.now() + 30 * 60 * 1000;
  let lastMessage = "正在等待任务完成...";

  while (Date.now() < deadline) {
    const response = await apiFetch(`/api/jobs/${encodeURIComponent(normalizedJobId)}`);
    if (!response.ok) {
      throw new Error(await extractApiErrorMessage(response));
    }

    const data = (await response.json()) as JobRunStatusResponse;
    onStatus?.(data);
    if (data.progress_text) {
      lastMessage = data.progress_text;
    }

    if (data.status === "done") {
      if (!data.result) {
        throw new Error("Job completed without a result.");
      }
      return data.result;
    }

    if (data.status === "failed") {
      throw new Error(data.error || lastMessage || "Job failed.");
    }

    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }

  throw new Error(lastMessage || "Job timed out while waiting for completion.");
}

export function getViewState(
  errorMessage: string,
  isRunning: boolean,
  jobResult: JobResult | null,
): ViewState {
  if (errorMessage) {
    return {
      tone: "error",
      label: "Failed",
      message: errorMessage,
    };
  }

  if (isRunning) {
    return {
      tone: "running",
      label: "Processing",
      message:
        "Downloading audio, running local Whisper, and generating bilingual output.",
    };
  }

  if (jobResult) {
    const sourceMessage =
      jobResult.source_type === "audio"
        ? "Finished with downloaded audio as the source. Whisper transcription and the Chinese translation are ready."
        : "Finished with subtitles as the source. The Chinese translation is ready without an audio download.";

    return {
      tone: "success",
      label: "Complete",
      message: sourceMessage,
    };
  }

  return {
    tone: "idle",
    label: "Ready",
    message:
      "Paste one YouTube link, add a translation API key if needed, and run the download -> Whisper -> translate pipeline.",
  };
}

export function normalizeApiErrorMessage(message: string): string {
  const normalized = message.replace(/\s+/g, " ").trim();
  const lowered = normalized.toLowerCase();

  if (lowered.includes("could not copy chrome cookie database")) {
    return (
      "yt-dlp could not read Chrome cookies. Close all Chrome processes first, " +
      "or export a cookies.txt file and set YTDLP_COOKIES_FILE in .env."
    );
  }

  if (lowered.includes("failed to decrypt with dpapi")) {
    return (
      "yt-dlp could not decrypt browser cookies on this Windows account. " +
      "Use an exported cookies.txt file and set YTDLP_COOKIES_FILE in .env."
    );
  }

  if (lowered.includes("sign in to confirm you're not a bot")) {
    return (
      "YouTube is asking for a signed-in browser session. Configure " +
      "YTDLP_COOKIES_FILE with an exported cookies.txt file, or try " +
      "YTDLP_COOKIES_FROM_BROWSER after fully closing the browser."
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
