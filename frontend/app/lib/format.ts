import type {
  TranslationSegment,
  TranslationProvider,
  ParsedApiError,
  ApiErrorResponseBody,
} from "./types";

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
  const normalizedMessage = normalizeApiErrorMessage(
    error.message,
    error.errorCode,
  );
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

export function normalizeApiErrorMessage(message: string, errorCode = ""): string {
  const normalized = message.replace(/\s+/g, " ").trim();
  const lowered = normalized.toLowerCase();
  let normalizedCode = errorCode.trim().toUpperCase();
  if (!normalizedCode) {
    const bracketMatch = normalized.match(/^\[([A-Z0-9_]+)\]\s*(.*)$/);
    if (bracketMatch) {
      normalizedCode = bracketMatch[1];
      return normalizeApiErrorMessage(bracketMatch[2] || normalized, normalizedCode);
    }
  }

  if (normalizedCode === "YOUTUBE_URL_INVALID") {
    return "请输入标准的 YouTube 视频链接。";
  }

  if (normalizedCode === "COOKIE_REQUIRED") {
    return "这个视频需要有效的 YouTube 登录态。请更新 cookies.txt；如果仍失败，建议改走本地音频上传。";
  }

  if (normalizedCode === "PO_TOKEN_REQUIRED") {
    return "这个视频需要 YouTube PO Token。请配置 PO Token 提供器，或切换到不需要 PO Token 的客户端；如果只是先完成处理，可改走本地音频上传。";
  }

  if (normalizedCode === "COOKIE_STALE") {
    return "当前 cookies 已失效。请重新导出并保存最新的 cookies.txt。";
  }

  if (normalizedCode === "YOUTUBE_BOT_CHECK") {
    return "YouTube 要求登录或人机验证。请更新 cookies.txt；如果仍失败，建议改走本地音频上传。";
  }

  if (normalizedCode === "YOUTUBE_429") {
    return "YouTube 当前限制了访问频率。请稍后重试，必要时切换网络。";
  }

  if (normalizedCode === "VIDEO_UNAVAILABLE") {
    return "该视频当前不可访问，可能被删除、受限或需要登录。";
  }

  if (normalizedCode === "VIDEO_PRIVATE") {
    return "该视频是私有内容，当前账号或 cookies 无法访问。";
  }

  if (normalizedCode === "VIDEO_REGION_BLOCKED") {
    return "该视频在当前地区不可访问。必要时改走本地音频上传。";
  }

  if (normalizedCode === "YTDLP_TIMEOUT") {
    return "YouTube 获取超时。请稍后重试；如果反复出现，优先检查 cookies 和网络状态。";
  }

  if (normalizedCode === "YTDLP_NOT_INSTALLED") {
    return "后端缺少 yt-dlp 运行依赖，请先安装后再试。";
  }

  if (normalizedCode === "BROWSER_COOKIE_LOCKED") {
    return "浏览器 cookies 数据库当前被占用。请先关闭浏览器，再重新导出 cookies.txt。";
  }

  if (normalizedCode === "COOKIE_DECRYPT_FAILED") {
    return "浏览器 cookies 无法解密。请改用导出的 cookies.txt。";
  }

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

  if (lowered.includes("po token") || lowered.includes("po_token") || lowered.includes("po-token")) {
    return (
      "该视频需要 YouTube PO Token。请配置 PO Token 提供器，或切换到不需要 PO Token 的客户端；如果只是先完成处理，可改走本地音频上传。"
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

export function buildTranslationText(segments: TranslationSegment[]): string {
  if (segments.length === 0) {
    return "";
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
  if (stage === "persist") {
    return "保存结果";
  }
  return stage;
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
