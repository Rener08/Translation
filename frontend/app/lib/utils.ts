import type { JobResult, TranslationProvider, RewriteStyle, SkillConfigName } from "./types";
import {
  REWRITE_STYLE,
  SKILL_CONFIG_NAME,
  DEFAULT_LATEPOST_REWRITE_FOCUS,
  DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS,
} from "./settings";
import { getProviderModelOptions } from "./api";

/** Canonical watch URL for attribution footers and exports. */
export function youtubeWatchUrl(videoId: string): string {
  const id = String(videoId || "").trim();
  if (!id || id.startsWith("upload-")) {
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
  const safe = collapsed.replace(/[^a-zA-Z0-9一-鿿._-]+/g, "").slice(0, 80);
  return safe || "rewrite";
}

export function getProviderModelPlaceholder(provider: TranslationProvider): string {
  const options = getProviderModelOptions(provider);
  if (options.length > 0) {
    return options.join(" / ");
  }
  return "留空，后端自动探测";
}

export function getDefaultSkillConfigNameForRewriteStyle(
  rewriteStyle: RewriteStyle,
): SkillConfigName {
  if (rewriteStyle === REWRITE_STYLE.ARTICLE_LONGFORM) {
    return SKILL_CONFIG_NAME.LATEPOST;
  }
  return SKILL_CONFIG_NAME.KAZIX;
}

export function getDefaultRewriteFocusForSettings(
  rewriteStyle: RewriteStyle,
  skillConfigName?: SkillConfigName,
): string {
  if (
    skillConfigName === SKILL_CONFIG_NAME.LATEPOST ||
    rewriteStyle === REWRITE_STYLE.ARTICLE_LONGFORM
  ) {
    return DEFAULT_LATEPOST_REWRITE_FOCUS;
  }
  return DEFAULT_SPEECH_VERBATIM_REWRITE_FOCUS;
}
