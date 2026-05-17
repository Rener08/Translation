import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResultView } from "../result-view";
import type { FailureDiagnostic } from "../../lib/types";
import type { JobResult } from "../../lib/job";

const ShortcutIcon = () => null;

describe("ResultView", () => {
  it("shows the original transcript and wires recovery actions", () => {
    const jobResult: JobResult = {
      ok: true,
      video: {
        video_id: "abc123",
        title: "Sample video",
        thumbnail: null,
        duration_sec: 120,
        uploader: "Uploader",
      },
      source_type: "captions",
      content_context_id: "ctx-1",
      transcript_en: {
        text: "This is the original transcript.",
        segments: [],
      },
      translation_zh: {
        segments: [],
      },
    };
    const onRunPreflight = vi.fn();
    const failureDiagnostic: FailureDiagnostic = {
      source: "rewrite",
      title: "改写失败",
      message: "预检未通过。",
      details: ["provider：deepseek"],
      errorCode: "PREFLIGHT_FAILED",
      retryable: true,
      requestId: "",
      actions: [
        {
          kind: "run-preflight",
          label: "检查环境",
          description: "打开预检面板。",
        },
      ],
    };

    render(
      <ResultView
        jobResult={jobResult}
        rewriteProviderLabel="deepseek · deepseek-chat"
        rewriteLoading={false}
        rewriteError=""
        rewriteText="改写内容"
        rewriteCopied={false}
        rewriteFailureDiagnostic={failureDiagnostic}
        detailCoverageIssues={[]}
        detailPatchLoading={false}
        messages={[]}
        chatInput=""
        chatSubmitting={false}
        chatError=""
        shortcuts={[
          {
            key: "summary",
            label: "总结",
            icon: ShortcutIcon,
            prompt: "请总结。",
          },
        ]}
        restoredConversation={null}
        onCopyRewrite={vi.fn()}
        onExportRewrite={vi.fn()}
        onRequestDetailPatch={vi.fn()}
        onRetryRewrite={vi.fn()}
        onRunPreflight={onRunPreflight}
        onSubmitShortcut={vi.fn()}
        onSubmitChat={vi.fn()}
        onChangeChatInput={vi.fn()}
        onOpenSettings={vi.fn()}
        onResetConversation={vi.fn()}
      />,
    );

    expect(screen.getByText("原始素材")).toBeInTheDocument();
    expect(
      screen.getByText("This is the original transcript."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
    expect(onRunPreflight).toHaveBeenCalledTimes(1);
  });
});
