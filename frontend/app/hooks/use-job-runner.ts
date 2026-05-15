"use client";

import { useEffect, useRef, useState } from "react";

import {
  JobResult,
  TranslationConfigPayload,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  extractApiErrorMessage,
  loadYouTubeAccessStatus,
  mapJobStageLabel,
  normalizeApiErrorMessage,
  uploadAudioFile,
  waitForJobResult,
} from "../lib/job";


type UseJobRunnerParams = {
  settings: TranslationSettings;
  youtubeUrl: string;
  uploadedAudioFile: File | null;
  onJobResult: (result: JobResult) => void;
  onJobSuccess?: (result: JobResult) => void;
};

export function useJobRunner({
  settings,
  youtubeUrl,
  uploadedAudioFile,
  onJobResult,
  onJobSuccess,
}: UseJobRunnerParams) {
  const [isRunning, setIsRunning] = useState(false);
  const [activeJobId, setActiveJobId] = useState("");
  const [jobStatusMessage, setJobStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const currentRunSeqRef = useRef(0);
  const activeRunControllerRef = useRef<AbortController | null>(null);
  const activeJobIdRef = useRef("");

  useEffect(() => {
    return () => {
      activeRunControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    activeJobIdRef.current = activeJobId;
  }, [activeJobId]);

  function isCurrentRun(runSeq: number, controller: AbortController): boolean {
    return (
      runSeq === currentRunSeqRef.current && !controller.signal.aborted
    );
  }

  function invalidateActiveRun() {
    currentRunSeqRef.current += 1;
    activeRunControllerRef.current?.abort();
    activeRunControllerRef.current = null;
    activeJobIdRef.current = "";
    setIsRunning(false);
    setActiveJobId("");
    setJobStatusMessage("");
    setErrorMessage("");
  }

  function cancelBackendJob(jobId: string) {
    const normalizedJobId = jobId.trim();
    if (!normalizedJobId) {
      return;
    }
    void apiFetch(`/api/jobs/${encodeURIComponent(normalizedJobId)}/cancel`, {
      method: "POST",
    }).catch(() => {});
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

    const previousJobId = activeJobIdRef.current.trim();
    if (previousJobId) {
      cancelBackendJob(previousJobId);
    }

    activeRunControllerRef.current?.abort();
    const controller = new AbortController();
    activeRunControllerRef.current = controller;
    activeJobIdRef.current = "";
    setActiveJobId("");
    setIsRunning(true);
    setErrorMessage("");
    setJobStatusMessage(uploadedAudioFile ? "正在上传文件..." : "正在检查 YouTube 访问...");

    try {
      let response: Response;
      if (uploadedAudioFile) {
        const upload = await uploadAudioFile(uploadedAudioFile);
        if (!isCurrentRun(runSeq, controller)) {
          return;
        }
        setJobStatusMessage("上传完成，正在提交任务...");
        response = await apiFetch("/api/jobs/run-upload", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            audio_file_path: upload.audio_file_path,
            title: upload.title,
            translation_config: translationConfig,
          }),
          signal: controller.signal,
        });
      } else {
        const accessStatus = await loadYouTubeAccessStatus(youtubeUrl);
        if (!isCurrentRun(runSeq, controller)) {
          return;
        }
        if (!accessStatus.ok) {
          const guidance = [accessStatus.message, accessStatus.recommended_action]
            .map((value) => value.trim())
            .filter(Boolean)
            .join(" ");
          setErrorMessage(
            guidance || "当前 YouTube 访问状态异常，请检查 cookies、网络或视频可见性。",
          );
          setJobStatusMessage("");
          return;
        }

        setJobStatusMessage("正在提交任务...");
        response = await apiFetch("/api/jobs/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: youtubeUrl,
            source_mode: settings.sourceMode,
            translation_config: translationConfig,
          }),
          signal: controller.signal,
        });
      }

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
      activeJobIdRef.current = jobId;
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
          if (statusText && stageLabel) {
            setJobStatusMessage(statusText);
            return;
          }
          if (statusText) {
            setJobStatusMessage(statusText);
            return;
          }
          if (stageLabel) {
            setJobStatusMessage(`${stageLabel}处理中`);
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
        setErrorMessage("无法连接本地后端（http://localhost:8000）。请先运行 ./start-dev.sh 或 ./start-backend.sh。");
      } else {
        setErrorMessage(normalizeApiErrorMessage(rawMessage));
      }
      setJobStatusMessage("");
    } finally {
      if (isCurrentRun(runSeq, controller)) {
        if (activeRunControllerRef.current === controller) {
          activeRunControllerRef.current = null;
        }
        activeJobIdRef.current = "";
        setActiveJobId("");
        setIsRunning(false);
      }
    }
  }

  function clearJobError() {
    setErrorMessage("");
  }

  function invalidateCurrentRun(options?: { cancelBackend?: boolean }) {
    const jobId = activeJobIdRef.current.trim();
    if (options?.cancelBackend && jobId) {
      cancelBackendJob(jobId);
    }
    invalidateActiveRun();
  }

  async function cancelJob() {
    const jobId = activeJobIdRef.current.trim();
    if (!jobId) {
      return;
    }
    cancelBackendJob(jobId);
    invalidateActiveRun();
    setJobStatusMessage("任务已取消");
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
