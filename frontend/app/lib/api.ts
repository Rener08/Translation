import type {
  TranslationSettings,
  TranslationConfigPayload,
  TranslationProvider,
  UploadAudioResponse,
  SystemYtDlpCookiesResponse,
  YouTubeAccessStatusResponse,
  JobResult,
  JobRunStatusResponse,
  PreflightResponse,
  ProviderTestConnectionResponse,
  SettingsPreflightResult,
  ApiErrorDetails,
  ApiErrorResponseBody,
} from "./types";

import {
  configuredApiBaseUrl,
  LEGACY_DEEPSEEK_MODEL_MAP,
  DEEPSEEK_MODEL_OPTIONS,
  OPENAI_MODEL_OPTIONS,
  getProviderDefaultModel,
} from "./settings";

import { mapJobStageLabel, normalizeApiErrorMessage } from "./format";

let resolvedApiBaseUrl: string | null = null;
let lastKnownApiBaseUrl: string | null = null;

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

function parseApiErrorBody(rawText: string): ApiErrorDetails | null {
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

    return {
      message: detail || errorCode || trimmed,
      errorCode,
      retryable,
      requestId,
      status: 0,
    };
  } catch {
    return null;
  }
}

function defaultRetryableForStatus(status: number): boolean | null {
  if (status === 429 || status === 502 || status === 503 || status === 504) {
    return true;
  }
  if (status === 401 || status === 403 || status === 404) {
    return false;
  }
  return null;
}

export type ApiError = Error & {
  apiError: ApiErrorDetails;
};

function formatApiErrorDetails(details: ApiErrorDetails): string {
  const parts: string[] = [];
  if (details.errorCode) {
    parts.push(`[${details.errorCode}]`);
  }
  parts.push(normalizeApiErrorMessage(details.message, details.errorCode));
  if (details.retryable === true) {
    parts.push("（可重试）");
  }
  if (details.requestId) {
    parts.push(`request_id=${details.requestId}`);
  }
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

function createApiError(details: ApiErrorDetails): ApiError {
  const error = new Error(formatApiErrorDetails(details)) as ApiError;
  error.apiError = details;
  return error;
}

function createJobStatusError(
  message: string,
  errorCode: string,
  retryable: boolean | null,
): ApiError {
  return createApiError({
    message,
    errorCode: errorCode.trim() || "JOB_FAILED",
    retryable,
    requestId: "",
    status: 200,
  });
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
    "Cannot connect to backend API. Run ./start-dev.sh or ./start-backend.sh, or set NEXT_PUBLIC_API_BASE_URL.",
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

export function getProviderModelOptions(
  provider: TranslationProvider,
): string[] {
  if (provider === "openai") {
    return [...OPENAI_MODEL_OPTIONS];
  }
  if (provider === "deepseek") {
    return [...DEEPSEEK_MODEL_OPTIONS];
  }
  return [];
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
    const providerOptions = getProviderModelOptions(provider);
    if (providerOptions.includes(trimmedModel)) {
      return trimmedModel;
    }
    if (provider === "deepseek") {
      const legacyMappedModel = LEGACY_DEEPSEEK_MODEL_MAP[trimmedModel];
      if (legacyMappedModel) {
        return legacyMappedModel;
      }
      if (trimmedModel.startsWith("gpt-")) {
        return providerDefaultModel;
      }
      return trimmedModel;
    }
    if (provider === "openai") {
      if (trimmedModel.startsWith("deepseek-")) {
        return providerDefaultModel;
      }
      return trimmedModel;
    }
    return trimmedModel;
  }

  if (!trimmedModel) {
    return "";
  }
  return trimmedModel;
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

export async function extractApiErrorDetails(
  response: Response,
): Promise<ApiErrorDetails> {
  const rawText = (await response.text()).trim();
  const fallbackMessage = `Request failed with status ${response.status}`;
  const defaultErrorCode = `HTTP_${response.status}`;

  if (rawText) {
    const parsed = parseApiErrorBody(rawText);
    if (parsed) {
      return {
        message: parsed.message,
        errorCode: parsed.errorCode || defaultErrorCode,
        retryable: parsed.retryable ?? defaultRetryableForStatus(response.status),
        requestId: parsed.requestId,
        status: response.status,
      };
    }

    return {
      message: rawText,
      errorCode: defaultErrorCode,
      retryable: defaultRetryableForStatus(response.status),
      requestId: "",
      status: response.status,
    };
  }

  if (response.status === 502) {
    return {
      message:
        "Upstream video fetch failed while accessing YouTube. For restricted videos only, use YTDLP_COOKIES_FILE as an advanced fallback.",
      errorCode: defaultErrorCode,
      retryable: true,
      requestId: "",
      status: response.status,
    };
  }

  return {
    message: fallbackMessage,
    errorCode: defaultErrorCode,
    retryable: defaultRetryableForStatus(response.status),
    requestId: "",
    status: response.status,
  };
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

export async function loadYtDlpCookies(): Promise<SystemYtDlpCookiesResponse> {
  const response = await apiFetch("/api/system/yt-dlp-cookies");
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as SystemYtDlpCookiesResponse;
}

export async function uploadAudioFile(file: File): Promise<UploadAudioResponse> {
  const body = new FormData();
  body.append("file", file);
  const response = await apiFetch("/api/uploads/audio", {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as UploadAudioResponse;
}

export async function loadYouTubeAccessStatus(
  url: string,
): Promise<YouTubeAccessStatusResponse> {
  const response = await apiFetch("/api/system/youtube-access-status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url: url.trim() || null }),
  });
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as YouTubeAccessStatusResponse;
}

export async function saveYtDlpCookies(
  cookiesText: string,
): Promise<SystemYtDlpCookiesResponse> {
  const response = await apiFetch("/api/system/yt-dlp-cookies", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ cookies_text: cookiesText }),
  });
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as SystemYtDlpCookiesResponse;
}

export async function clearYtDlpCookies(): Promise<SystemYtDlpCookiesResponse> {
  const response = await apiFetch("/api/system/yt-dlp-cookies", {
    method: "DELETE",
  });
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as SystemYtDlpCookiesResponse;
}

export async function runPreflight(): Promise<PreflightResponse> {
  const response = await apiFetch("/api/system/preflight");
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as PreflightResponse;
}

export async function testProviderConnection(
  settings: TranslationSettings,
): Promise<ProviderTestConnectionResponse> {
  const response = await apiFetch("/api/provider/test-connection", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(buildTranslationConfig(settings)),
  });
  if (!response.ok) {
    throw createApiError(await extractApiErrorDetails(response));
  }
  return (await response.json()) as ProviderTestConnectionResponse;
}

export async function runSettingsPreflight(
  settings: TranslationSettings,
): Promise<SettingsPreflightResult> {
  const [runtime, provider] = await Promise.all([
    runPreflight(),
    testProviderConnection(settings),
  ]);

  const normalizedModel = normalizeTranslationModel(settings.provider, settings.model);
  const discoveredModels = provider.discovered_models.map((model) => String(model || "").trim()).filter(Boolean);
  const modelReady = normalizedModel
    ? discoveredModels.includes(normalizedModel)
    : provider.reachable;

  const allOk = runtime.all_ok && provider.reachable && modelReady;
  const runtimeDetails = runtime.checks.map((check) => `${check.label}: ${check.detail}`);
  const providerDetails = [
    provider.message,
    provider.reachable
      ? modelReady
        ? `当前模型 ${normalizedModel || provider.selected_model || "未指定"} 已通过 provider 检查。`
        : `当前模型 ${normalizedModel || "未指定"} 未出现在 provider 返回的模型列表中。`
      : "Provider 连接失败，请先检查 API Key 和 base_url。",
    discoveredModels.length > 0
      ? `可发现模型：${discoveredModels.slice(0, 4).join("、")}`
      : "Provider 未返回可发现模型列表。",
  ];

  return {
    runtime,
    provider,
    allOk,
    summary: allOk
      ? "本地运行环境与当前 provider/model 都已通过预检。"
      : "预检未通过，请先修复失败项后再提交。",
    details: [...runtimeDetails, ...providerDetails],
  };
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
      throw createApiError(await extractApiErrorDetails(response));
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
      throw createJobStatusError(detail, errorCode || "JOB_FAILED", data.retryable ?? null);
    }
    if (data.status === "cancelled") {
      throw createJobStatusError(
        data.error || "任务已取消。",
        data.error_code || "JOB_CANCELLED",
        false,
      );
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
