"use client";

import { ContentRewritePanel } from "./content-rewrite-panel";
import { JobResult, TranslationSettings, buildTranslationText } from "../lib/job";

type JobResultPanelProps = {
  jobResult: JobResult | null;
  settings: TranslationSettings;
};

export function JobResultPanel({ jobResult, settings }: JobResultPanelProps) {
  const rewriteSourceText = jobResult
    ? buildTranslationText(jobResult.translation_zh.segments)
    : "";

  return (
    <section className="desk-card transcript-stage">
      <ContentRewritePanel
        settings={settings}
        initialSourceText={rewriteSourceText}
        sourceLocked
        resultOnly
      />
    </section>
  );
}
