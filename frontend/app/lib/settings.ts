import type {
  TranslationProvider,
  TranslationSettings,
} from "./types";

export const REWRITE_STYLE = {
  SPEECH_VERBATIM: "speech_verbatim",
  ARTICLE_LONGFORM: "article_longform",
} as const;

export const SKILL_CONFIG_NAME = {
  KAZIX: "kazix",
  LATEPOST: "latepost",
} as const;

export const DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS =
  "保留原作者的说话节奏和口吻，只做轻度整理，不要总结化重写。";

export const DEFAULT_ARTICLE_LONGFORM_REWRITE_FOCUS =
  "改写成第三视角的中文文章，保留原意和事实，不删关键信息，不使用第一人称自述。";

export const DEFAULT_LATEPOST_REWRITE_FOCUS =
  "改写成晚点风格的第三视角中文报道文章，保留原意和事实，不删关键信息，不使用第一人称自述。";

export const LEGACY_ARTICLE_LONGFORM_REWRITE_FOCUS =
  "保留原意和事实，不删关键信息，改写为更有节奏和可读性的中文内容。";

export const DEEPSEEK_MODEL_OPTIONS = [
  "deepseek-v4-flash",
  "deepseek-v4-pro",
] as const;

export const OPENAI_MODEL_OPTIONS = [
  "gpt-4.1-mini",
  "gpt-4.1",
] as const;

export const SOURCE_MODE = {
  SUBTITLE_FIRST: "subtitle_first",
  FORCE_AUDIO: "force_audio",
} as const;

export const configuredApiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim();

export const defaultApiBaseUrl = configuredApiBaseUrl || "http://localhost:8000";

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

export const defaultTranslationProvider = resolveProvider(
  process.env.NEXT_PUBLIC_DEFAULT_TRANSLATION_PROVIDER,
  "deepseek",
);

const OPENAI_DEFAULT_MODEL = "gpt-4.1-mini";
const DEEPSEEK_DEFAULT_MODEL = DEEPSEEK_MODEL_OPTIONS[0];

export const LEGACY_DEEPSEEK_MODEL_MAP: Record<string, string> = {
  "deepseek-chat": DEEPSEEK_MODEL_OPTIONS[0],
  "deepseek-reasoner": DEEPSEEK_MODEL_OPTIONS[1],
};

export function getProviderDefaultModel(provider: TranslationProvider): string {
  if (provider === "openai") {
    return OPENAI_DEFAULT_MODEL;
  }
  if (provider === "deepseek") {
    return DEEPSEEK_DEFAULT_MODEL;
  }
  return "";
}

export const defaultSettings: TranslationSettings = {
  provider: defaultTranslationProvider,
  sourceMode: SOURCE_MODE.SUBTITLE_FIRST,
  apiKey: "",
  baseUrl: "",
  model: getProviderDefaultModel(defaultTranslationProvider),
  headersJson: "",
  rewriteStyle: REWRITE_STYLE.SPEECH_VERBATIM,
  skillConfigName: SKILL_CONFIG_NAME.KAZIX,
};
