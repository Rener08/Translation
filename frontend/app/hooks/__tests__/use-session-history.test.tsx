import { describe, expect, it } from "vitest";

import { buildRestoredSessionState } from "../use-session-history";
import type { SessionHistoryDetail } from "../use-session-history";

describe("buildRestoredSessionState", () => {
  it("restores settings, history payload, and failure state from saved history", () => {
    const detail: SessionHistoryDetail = {
      content_context_id: "ctx-1",
      video_id: "abc123",
      video_url: "https://www.youtube.com/watch?v=abc123",
      video_title: "Recovered video",
      video_thumbnail: "https://img.example/thumb.jpg",
      video_duration_sec: 120,
      video_uploader: "Uploader",
      source_mode: "force_audio",
      source_type: "audio",
      translation_provider: "deepseek",
      translation_model: "deepseek-chat",
      translation_base_url: "https://api.deepseek.com",
      transcript_en_text: "Original transcript",
      transcript_en_segments: [
        {
          index: 0,
          start: 0,
          end: 3,
          text: "Original transcript",
          speaker: null,
        },
      ],
      translation_zh_text: "中文内容",
      translation_zh_segments: [
        {
          index: 0,
          start: 0,
          end: 3,
          source_text: "Original transcript",
          translated_text: "中文内容",
        },
      ],
      rewritten_text: "Recovered rewrite",
      rewrite_provider: "deepseek",
      rewrite_model: "deepseek-chat",
      rewrite_base_url: "https://api.deepseek.com",
      rewrite_style: "speech_verbatim",
      skill_config_name: "kazix",
      rewrite_focus: "请更口语化。",
      rewrite_source_text: "Original transcript",
      rewrite_quality_issues: ["too verbose"],
      rewrite_detail_coverage_issues: [],
      rewrite_failure_error_code: "UPSTREAM_ERROR",
      rewrite_failure_message: "上次改写失败。",
      rewrite_failure_retryable: true,
      rewrite_failure_details: ["provider：deepseek"],
      chat_turns: [
        {
          role: "user",
          content: "请解释这段内容。",
          created_at: "2026-05-17T10:00:00Z",
        },
        {
          role: "assistant",
          content: "当然可以。",
          created_at: "2026-05-17T10:00:01Z",
        },
      ],
    };

    const restored = buildRestoredSessionState(detail);

    expect(restored.youtubeUrl).toBe("https://www.youtube.com/watch?v=abc123");
    expect(restored.restoredSettings).toEqual({
      provider: "deepseek",
      sourceMode: "force_audio",
      baseUrl: "https://api.deepseek.com",
      model: "deepseek-v4-flash",
      rewriteStyle: "speech_verbatim",
      skillConfigName: "kazix",
    });
    expect(restored.jobResult).toEqual(
      expect.objectContaining({
        content_context_id: "ctx-1",
        source_type: "audio",
        transcript_en: {
          text: "Original transcript",
          segments: detail.transcript_en_segments,
        },
      }),
    );
    expect(restored.restoredConversation).toEqual(
      expect.objectContaining({
        rewrittenText: "Recovered rewrite",
        rewriteProviderLabel: "deepseek · deepseek-v4-flash",
        messages: [
          {
            role: "user",
            content: "请解释这段内容。",
          },
          {
            role: "assistant",
            content: "当然可以。",
          },
        ],
        detailCoverageIssues: [],
        failure: {
          source: "rewrite",
          message: "上次改写失败。",
          errorCode: "UPSTREAM_ERROR",
          retryable: true,
          details: ["provider：deepseek"],
        },
      }),
    );
  });
});
