"use client";

import { ContentRewritePanel } from "./content-rewrite-panel";
import { JobResult, TranslationSettings, buildTranslationText } from "../lib/job";

type JobResultPanelProps = {
  jobResult: JobResult | null;
  settings: TranslationSettings;
  rewriteFocus: string;
};

export function JobResultPanel({
  jobResult,
  settings,
  rewriteFocus,
}: JobResultPanelProps) {
  const rewriteSourceText = jobResult
    ? buildTranslationText(jobResult.translation_zh.segments)
    : "";

  return (
    <section className="desk-card transcript-stage">
      <ContentRewritePanel
        settings={settings}
        initialSourceText={rewriteSourceText}
        contentContextId={jobResult?.content_context_id ?? ""}
        rewriteFocus={rewriteFocus}
        title="中文改写"
        subtitle="改写内容会自动生成在这里，支持复制和导出。"
        sourceLocked
        resultOnly
      />
    </section>
  );
}
