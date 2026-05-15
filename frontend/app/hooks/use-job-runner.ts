"use client";

import { useEffect, useRef, useState } from "react";

import {
  JobResult,
  TranslationConfigPayload,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  extractApiErrorMessage,
  mapJobStageLabel,
  normalizeApiErrorMessage,
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
  const [activeJobId, setActiveJobId] = useState("");
  const [jobStatusMessage, setJobStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const currentRunSeqRef = useRef(0);
  const activeRunControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      activeRunControllerRef.current?.abort();
    };
  }, []);

  function isCurrentRun(runSeq: number, controller: AbortController): boolean {
    return (
      runSeq === currentRunSeqRef.current && !controller.signal.aborted
    );
  }

  function invalidateActiveRun() {
    currentRunSeqRef.current += 1;
    activeRunControllerRef.current?.abort();
    activeRunControllerRef.current = null;
    setIsRunning(false);
    setActiveJobId("");
    setJobStatusMessage("");
    setErrorMessage("");
  }

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

    const runSeq = currentRunSeqRef.current + 1;
    currentRunSeqRef.current = runSeq;
    activeRunControllerRef.current?.abort();
    const controller = new AbortController();
    activeRunControllerRef.current = controller;
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
        signal: controller.signal,
      });

      if (!isCurrentRun(runSeq, controller)) {
        return;
      }

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
      if (!isCurrentRun(runSeq, controller)) {
        return;
      }
      setActiveJobId(jobId);
      if (submission.progress_text) {
        setJobStatusMessage(submission.progress_text);
      }

      const result = await waitForJobResult(
        jobId,
        (status) => {
          if (!isCurrentRun(runSeq, controller)) {
            return;
          }
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
        },
        { signal: controller.signal },
      );

      if (!isCurrentRun(runSeq, controller)) {
        return;
      }

      onJobResult(result);
      onJobSuccess?.(result);
      setJobStatusMessage("");
    } catch (error) {
      if (!isCurrentRun(runSeq, controller)) {
        return;
      }
      const rawMessage = error instanceof Error ? error.message : "Unknown request error";
      if (controller.signal.aborted || rawMessage.includes("Request aborted.")) {
        return;
      }
      if (rawMessage.includes("任务已取消")) {
        setErrorMessage("");
        setJobStatusMessage("任务已取消");
        return;
      }
      if (/cannot connect to backend api|failed to fetch|network/i.test(rawMessage)) {
        setErrorMessage("无法连接本地后端（http://localhost:8000 或 8002）。请先启动 backend。");
      } else {
        setErrorMessage(normalizeApiErrorMessage(rawMessage));
      }
      setJobStatusMessage("");
    } finally {
      if (isCurrentRun(runSeq, controller)) {
        if (activeRunControllerRef.current === controller) {
          activeRunControllerRef.current = null;
        }
        setActiveJobId("");
        setIsRunning(false);
      }
    }
  }

  function clearJobError() {
    setErrorMessage("");
  }

  function invalidateCurrentRun() {
    invalidateActiveRun();
  }

  async function cancelJob() {
    const jobId = activeJobId.trim();
    if (!jobId) {
      return;
    }
    try {
      await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
      });
      setJobStatusMessage("任务已取消");
    } catch {
      setJobStatusMessage("取消请求已发送，请等待状态刷新。");
    }
  }

  return {
    isRunning,
    jobStatusMessage,
    errorMessage,
    setErrorMessage,
    clearJobError,
    invalidateCurrentRun,
    runJob,
    cancelJob,
  };
}
