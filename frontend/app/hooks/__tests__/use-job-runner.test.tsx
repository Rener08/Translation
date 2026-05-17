import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useJobRunner } from "../use-job-runner";
import { defaultSettings } from "../../lib/job";
import type { SettingsPreflightResult } from "../../lib/types";

describe("useJobRunner", () => {
  it("blocks submission when preflight fails", async () => {
    const preflight: SettingsPreflightResult = {
      runtime: {
        all_ok: false,
        checks: [
          {
            name: "ffmpeg",
            label: "ffmpeg",
            ok: false,
            detail: "未安装",
          },
        ],
      },
      provider: {
        ok: true,
        provider: "deepseek",
        reachable: false,
        selected_model: null,
        discovered_models: [],
        message: "provider 不可用。",
      },
      allOk: false,
      summary: "预检未通过，请先修复失败项后再提交。",
      details: ["ffmpeg 未安装"],
    };
    const onJobResult = vi.fn();

    const { result } = renderHook(() =>
      useJobRunner({
        settings: defaultSettings,
        settingsPreflight: preflight,
        youtubeUrl: "https://www.youtube.com/watch?v=abc123",
        uploadedAudioFile: null,
        onJobResult,
      }),
    );

    await act(async () => {
      await result.current.runJob();
    });

    expect(onJobResult).not.toHaveBeenCalled();
    expect(result.current.failureDiagnostic?.errorCode).toBe("PREFLIGHT_FAILED");
    expect(result.current.failureDiagnostic?.details).toContain("ffmpeg 未安装");
    expect(result.current.errorMessage).toBe(preflight.summary);
    expect(result.current.isRunning).toBe(false);
  });
});
