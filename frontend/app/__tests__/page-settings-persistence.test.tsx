import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "../page";
import type { TranslationSettings } from "../lib/job";

const SETTINGS_STORAGE_KEY = "translation-settings";

let latestSettings: TranslationSettings | null = null;
const localStorageData = new Map<string, string>();
const localStorageStub = {
  getItem: (key: string) => {
    const value = localStorageData.get(key);
    return value === undefined ? null : value;
  },
  setItem: (key: string, value: string) => {
    localStorageData.set(key, String(value));
  },
  removeItem: (key: string) => {
    localStorageData.delete(key);
  },
  clear: () => {
    localStorageData.clear();
  },
  key: (index: number) => Array.from(localStorageData.keys())[index] ?? null,
  get length() {
    return localStorageData.size;
  },
};

vi.stubGlobal("localStorage", localStorageStub);

vi.mock("../components/app-sidebar", () => ({
  AppSidebar: ({
    onOpenSettings,
    onNewConversation,
  }: {
    onOpenSettings: () => void;
    onNewConversation: () => void;
  }) => (
    <div>
      <button type="button" onClick={onOpenSettings}>
        open-settings
      </button>
      <button type="button" onClick={onNewConversation}>
        new-chat
      </button>
    </div>
  ),
}));

vi.mock("../components/entry-view", () => ({
  EntryView: () => <div data-testid="entry-view" />,
}));

vi.mock("../components/result-view", () => ({
  ResultView: () => <div data-testid="result-view" />,
}));

vi.mock("../components/translation-settings-panel", () => ({
  TranslationSettingsPanel: ({
    settings,
    onChange,
  }: {
    settings: TranslationSettings;
    onChange: (nextSettings: TranslationSettings) => void;
    onCloseSettings?: () => void;
    preflightRequestKey: number;
    onPreflightResult: (result: unknown) => void;
  }) => {
    latestSettings = settings;
    return (
      <div>
        <div data-testid="settings-summary">
          {settings.provider}|{settings.baseUrl}|{settings.model}|{settings.rewriteStyle}|{settings.skillConfigName}
        </div>
        <button
          type="button"
          onClick={() =>
            onChange({
              ...settings,
              baseUrl: "https://api.changed.example",
            })
          }
        >
          change-settings
        </button>
      </div>
    );
  },
}));

vi.mock("../hooks/use-job-runner", () => ({
  useJobRunner: () => ({
    isRunning: false,
    jobStatusMessage: "",
    errorMessage: "",
    failureDiagnostic: null,
    clearJobError: vi.fn(),
    invalidateCurrentRun: vi.fn(),
    runJob: vi.fn(),
    cancelJob: vi.fn(),
  }),
}));

vi.mock("../hooks/use-session-history", () => ({
  useSessionHistory: () => ({
    historyLoading: false,
    historyError: "",
    historyFailureDiagnostic: null,
    sidebarItems: [],
    loadHistory: vi.fn(),
    openHistorySession: vi.fn(),
    recordSearchHistory: vi.fn(),
  }),
}));

vi.mock("../hooks/use-rewrite-chat", () => ({
  useRewriteChat: () => ({
    translationText: "",
    rewriteText: "",
    rewriteProviderLabel: "",
    rewriteLoading: false,
    rewriteError: "",
    rewriteCopied: false,
    detailCoverageIssues: [],
    detailPatchLoading: false,
    rewriteFailureDiagnostic: null,
    requestDetailPatch: vi.fn(),
    retryRewrite: vi.fn(),
    messages: [],
    chatInput: "",
    chatSubmitting: false,
    chatError: "",
    setChatInput: vi.fn(),
    submitChatQuestion: vi.fn(),
    copyRewrite: vi.fn(),
    exportRewrite: vi.fn(),
  }),
}));

describe("HomePage settings persistence", () => {
  beforeEach(() => {
    localStorageStub.clear();
    latestSettings = null;
  });

  it("restores saved settings and writes back later changes", async () => {
    window.localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        provider: "openai",
        baseUrl: "https://api.initial.example",
        model: "gpt-4.1",
        rewriteStyle: "article_longform",
        skillConfigName: "latepost",
      }),
    );

    render(<HomePage />);

    fireEvent.click(screen.getByRole("button", { name: "open-settings" }));

    await waitFor(() => {
      expect(screen.getByTestId("settings-summary")).toHaveTextContent(
        "openai|https://api.initial.example|gpt-4.1|article_longform|latepost",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "change-settings" }));

    await waitFor(() => {
      expect(screen.getByTestId("settings-summary")).toHaveTextContent(
        "openai|https://api.changed.example|gpt-4.1|article_longform|latepost",
      );
    });

    expect(latestSettings).toEqual({
      provider: "openai",
      sourceMode: "subtitle_first",
      apiKey: "",
      baseUrl: "https://api.changed.example",
      model: "gpt-4.1",
      headersJson: "",
      rewriteStyle: "article_longform",
      skillConfigName: "latepost",
    });
    expect(window.localStorage.getItem(SETTINGS_STORAGE_KEY)).toBe(
      JSON.stringify({
        provider: "openai",
        baseUrl: "https://api.changed.example",
        model: "gpt-4.1",
        rewriteStyle: "article_longform",
        skillConfigName: "latepost",
      }),
    );
  });
});
