import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PreflightPanel } from "../preflight-panel";
import { defaultSettings } from "../../lib/job";
import type { SettingsPreflightResult } from "../../lib/types";

vi.mock("../../lib/api", () => ({
  runSettingsPreflight: vi.fn(),
}));

import { runSettingsPreflight } from "../../lib/api";

const runSettingsPreflightMock = vi.mocked(runSettingsPreflight);

describe("PreflightPanel", () => {
  it("runs a combined preflight and renders the result", async () => {
    const result: SettingsPreflightResult = {
      runtime: {
        all_ok: true,
        checks: [
          {
            name: "yt-dlp",
            label: "yt-dlp",
            ok: true,
            detail: "可执行",
          },
        ],
      },
      provider: {
        ok: true,
        provider: "deepseek",
        reachable: true,
        selected_model: "deepseek-chat",
        discovered_models: ["deepseek-chat", "deepseek-reasoner"],
        message: "provider 连接正常。",
      },
      allOk: true,
      summary: "本地运行环境与当前 provider/model 都已通过预检。",
      details: ["本地环境通过", "provider 通过"],
    };

    runSettingsPreflightMock.mockResolvedValue(result);
    const onResult = vi.fn();

    render(
      <PreflightPanel
        settings={defaultSettings}
        requestKey={0}
        onResult={onResult}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "检查环境" }));

    await waitFor(() => {
      expect(runSettingsPreflightMock).toHaveBeenCalledTimes(1);
    });

    expect(onResult).toHaveBeenCalledWith(result);
    expect(await screen.findByText("环境正常")).toBeInTheDocument();
    expect(screen.getByText("provider 连接正常。")).toBeInTheDocument();
  });
});
