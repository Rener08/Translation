import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRewriteChat } from "../use-rewrite-chat";
import * as jobModule from "../../lib/job";
import { defaultSettings } from "../../lib/job";
import type { JobResult } from "../../lib/job";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });
  return { promise, resolve, reject };
}

function createJobResult(contentContextId: string, transcriptText: string): JobResult {
  return {
    ok: true,
    video: {
      video_id: contentContextId,
      title: `Title ${contentContextId}`,
      thumbnail: null,
      duration_sec: 120,
      uploader: "Uploader",
    },
    source_type: "captions",
    content_context_id: contentContextId,
    transcript_en: {
      text: transcriptText,
      segments: [],
    },
    translation_zh: {
      segments: [],
    },
  };
}

function createRewriteResponse(rewrittenText: string) {
  return {
    ok: true,
    json: async () => ({
      ok: true,
      provider: "deepseek",
      model: "deepseek-v4-flash",
      rewritten_text: rewrittenText,
      detail_coverage_issues: [],
    }),
  } as Response;
}

function createChatResponse(answer: string) {
  return {
    ok: true,
    json: async () => ({
      ok: true,
      provider: "deepseek",
      model: "deepseek-v4-flash",
      answer,
    }),
  } as Response;
}

describe("useRewriteChat request races", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("ignores a stale rewrite response after the job context changes", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const apiFetchSpy = vi.spyOn(jobModule, "apiFetch");
    apiFetchSpy
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const { result, rerender } = renderHook(
      ({
        jobResult,
      }: {
        jobResult: JobResult;
      }) =>
        useRewriteChat({
          jobResult,
          settings: defaultSettings,
          rewriteFocus: "保留事实",
          restoredConversation: null,
        }),
      {
        initialProps: {
          jobResult: createJobResult("ctx-a", "First transcript"),
        },
      },
    );

    await waitFor(() => {
      expect(apiFetchSpy).toHaveBeenCalledTimes(1);
    });

    rerender({
      jobResult: createJobResult("ctx-b", "Second transcript"),
    });

    await waitFor(() => {
      expect(apiFetchSpy).toHaveBeenCalledTimes(2);
    });

    await act(async () => {
      second.resolve(createRewriteResponse("Second rewrite"));
    });

    await waitFor(() => {
      expect(result.current.rewriteText).toBe("Second rewrite");
      expect(result.current.rewriteLoading).toBe(false);
    });

    await act(async () => {
      first.resolve(createRewriteResponse("First rewrite"));
    });

    await waitFor(() => {
      expect(result.current.rewriteText).toBe("Second rewrite");
      expect(result.current.rewriteProviderLabel).toContain("deepseek");
    });
  });

  it("ignores a stale chat response after the job context changes", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const apiFetchSpy = vi.spyOn(jobModule, "apiFetch");
    apiFetchSpy
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const { result, rerender } = renderHook(
      ({
        jobResult,
      }: {
        jobResult: JobResult;
      }) =>
        useRewriteChat({
          jobResult,
          settings: defaultSettings,
          rewriteFocus: "保留事实",
          restoredConversation: null,
        }),
      {
        initialProps: {
          jobResult: createJobResult("ctx-a", ""),
        },
      },
    );

    await act(async () => {
      void result.current.submitChatQuestion("第一个问题");
    });

    await waitFor(() => {
      expect(apiFetchSpy).toHaveBeenCalledTimes(1);
      expect(result.current.chatSubmitting).toBe(true);
    });

    rerender({
      jobResult: createJobResult("ctx-b", ""),
    });

    await waitFor(() => {
      expect(result.current.chatSubmitting).toBe(false);
    });

    await act(async () => {
      void result.current.submitChatQuestion("第二个问题");
    });

    await waitFor(() => {
      expect(apiFetchSpy).toHaveBeenCalledTimes(2);
    });

    await act(async () => {
      second.resolve(createChatResponse("第二个回答"));
    });

    await waitFor(() => {
      expect(result.current.messages).toEqual([
        { role: "user", content: "第二个问题" },
        { role: "assistant", content: "第二个回答" },
      ]);
      expect(result.current.chatSubmitting).toBe(false);
    });

    await act(async () => {
      first.resolve(createChatResponse("第一个回答"));
    });

    await waitFor(() => {
      expect(result.current.messages).toEqual([
        { role: "user", content: "第二个问题" },
        { role: "assistant", content: "第二个回答" },
      ]);
    });
  });
});
