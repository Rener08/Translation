"use client";

import { useState } from "react";

import {
  JobResult,
  TranslationConfigPayload,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  extractApiErrorMessage,
  mapJobStageLabel,
  waitForJobResult,
} from "../lib/job";


type UseJobRunnerParams = {
  settings: TranslationSettings;
  youtubeUrl: string;
  onJobResult: (result: JobResult) => void;
  onJobSuccess?: (result: JobResult) => void;
};

export function useJobRunner({
  settings,
  youtubeUrl,
  onJobResult,
  onJobSuccess,
}: UseJobRunnerParams) {
  const [isRunning, setIsRunning] = useState(false);
  const [jobStatusMessage, setJobStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function runJob() {
    let translationConfig: TranslationConfigPayload;
    try {
      translationConfig = buildTranslationConfig(settings);
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Invalid translation settings.",
      );
      return;
    }

    setIsRunning(true);
    setErrorMessage("");
    setJobStatusMessage("正在提交任务...");

    try {
      const response = await apiFetch("/api/jobs/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: youtubeUrl,
          source_mode: settings.sourceMode,
          translation_config: translationConfig,
        }),
      });

      if (!response.ok) {
        throw new Error(await extractApiErrorMessage(response));
      }

      const submission = (await response.json()) as {
        job_id?: string;
        progress_text?: string | null;
      };
      const jobId = typeof submission.job_id === "string" ? submission.job_id.trim() : "";
      if (!jobId) {
        throw new Error("Job submission did not return a job id.");
      }
      if (submission.progress_text) {
        setJobStatusMessage(submission.progress_text);
      }

      const result = await waitForJobResult(jobId, (status) => {
        const statusText =
          typeof status.progress_text === "string" ? status.progress_text.trim() : "";
        const stageLabel =
          typeof status.stage === "string" && status.stage.trim()
            ? mapJobStageLabel(status.stage)
            : "";
        const timeoutLabel =
          typeof status.timeout_sec === "number" && status.timeout_sec > 0
            ? `（阶段超时 ${status.timeout_sec}s）`
            : "";
        if (statusText && stageLabel) {
          setJobStatusMessage(`${stageLabel}：${statusText}${timeoutLabel}`);
          return;
        }
        if (statusText) {
          setJobStatusMessage(`${statusText}${timeoutLabel}`);
          return;
        }
        if (stageLabel) {
          setJobStatusMessage(`${stageLabel}处理中${timeoutLabel}`);
        }
      });

      onJobResult(result);
      onJobSuccess?.(result);
      setJobStatusMessage("");
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "Unknown request error";
      if (/cannot connect to backend api|failed to fetch|network/i.test(rawMessage)) {
        setErrorMessage("无法连接本地后端（http://localhost:8000 或 8002）。请先启动 backend。");
      } else {
        setErrorMessage(rawMessage);
      }
      setJobStatusMessage("");
    } finally {
      setIsRunning(false);
    }
  }

  function clearJobError() {
    setErrorMessage("");
  }

  return {
    isRunning,
    jobStatusMessage,
    errorMessage,
    setErrorMessage,
    clearJobError,
    runJob,
  };
}
