"use client";

import { useEffect, useRef, useState } from "react";

import {
  JobResult,
  TranslationConfigPayload,
  TranslationSettings,
  apiFetch,
  buildTranslationConfig,
  mapJobStageLabel,
  normalizeApiErrorMessage,
  uploadAudioFile,
  waitForJobResult,
} from "../lib/job";

import {
  extractApiErrorDetails,
  loadYouTubeAccessStatus,
} from "../lib/api";

import type {
  ApiErrorDetails,
  FailureDiagnostic,
  RecoveryAction,
  SettingsPreflightResult,
} from "../lib/types";


type UseJobRunnerParams = {
  settings: TranslationSettings;
  settingsPreflight: SettingsPreflightResult | null;
  youtubeUrl: string;
  uploadedAudioFile: File | null;
  onJobResult: (result: JobResult) => void;
  onJobSuccess?: (result: JobResult) => void;
};

export function useJobRunner({
  settings,
  settingsPreflight,
  youtubeUrl,
  uploadedAudioFile,
  onJobResult,
  onJobSuccess,
}: UseJobRunnerParams) {
  const [isRunning, setIsRunning] = useState(false);
  const [activeJobId, setActiveJobId] = useState("");
  const [jobStatusMessage, setJobStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [failureDiagnostic, setFailureDiagnostic] =
    useState<FailureDiagnostic | null>(null);
  const currentRunSeqRef = useRef(0);
  const activeRunControllerRef = useRef<AbortController | null>(null);
  const activeJobIdRef = useRef("");

  function getApiErrorDetails(error: unknown): ApiErrorDetails | null {
    if (!error || typeof error !== "object") {
      return null;
    }
    const candidate = error as { apiError?: ApiErrorDetails };
    return candidate.apiError ?? null;
  }

  function buildRecoveryAction(
    kind: RecoveryAction["kind"],
    label: string,
    description: string,
    disabled = false,
  ): RecoveryAction {
    return {
      kind,
      label,
      description,
      ...(disabled ? { disabled: true } : {}),
    };
  }

  function buildJobFailureDiagnostic({
    title,
    message,
    errorCode,
    retryable,
    requestId,
    stageLabel,
    details,
  }: {
    title: string;
    message: string;
    errorCode: string | null;
    retryable: boolean | null;
    requestId: string;
    stageLabel?: string | null;
    details: string[];
  }): FailureDiagnostic {
    const actions: RecoveryAction[] = [
      buildRecoveryAction("retry-job", "重新提交任务", "用当前输入和设置再跑一次。"),
      buildRecoveryAction("fallback-audio", "改用本地音频", "如果 YouTube 链路不稳，切换到本地音频上传。"),
      buildRecoveryAction("run-preflight", "检查环境", "打开设置里的预检面板，复核 cookies 和后端连通性。"),
    ];

    if (retryable === false && errorCode && errorCode.startsWith("HTTP_")) {
      actions.unshift(
        buildRecoveryAction(
          "open-settings",
          "检查设置",
          "先核对模型、API Key 和后端 base_url。",
        ),
      );
    }

    return {
      source: "job",
      title,
      message,
      details,
      errorCode,
      retryable,
      requestId,
      stageLabel: stageLabel ?? null,
      actions,
    };
  }

  function setJobFailure(details: FailureDiagnostic) {
    setFailureDiagnostic(details);
    setErrorMessage(details.message);
  }

  function recordJobFailure(args: {
    title: string;
    message: string;
    errorCode: string | null;
    retryable: boolean | null;
    requestId: string;
    stageLabel?: string | null;
    details: string[];
  }) {
    setJobStatusMessage("");
    setJobFailure(buildJobFailureDiagnostic(args));
  }

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
    setFailureDiagnostic(null);
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
    if (settingsPreflight && !settingsPreflight.allOk) {
      recordJobFailure({
        title: "环境预检未通过",
        message: settingsPreflight.summary,
        errorCode: "PREFLIGHT_FAILED",
        retryable: true,
        requestId: "",
        details: settingsPreflight.details,
      });
      return;
    }

    let translationConfig: TranslationConfigPayload;
    try {
      translationConfig = buildTranslationConfig(settings);
    } catch (error) {
      setFailureDiagnostic(null);
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
    setFailureDiagnostic(null);
    setJobStatusMessage(uploadedAudioFile ? "正在上传文件..." : "正在检查 YouTube 访问...");

    try {
      let response: Response;
      if (uploadedAudioFile) {
        let upload;
        try {
          upload = await uploadAudioFile(uploadedAudioFile);
        } catch (error) {
          if (!isCurrentRun(runSeq, controller)) {
            return;
          }
          const apiError = getApiErrorDetails(error);
          recordJobFailure({
            title: "本地音频上传失败",
            message:
              apiError?.message ??
              (error instanceof Error ? error.message : "Failed to upload local media."),
            errorCode: apiError?.errorCode ?? "UPLOAD_FAILED",
            retryable: apiError?.retryable ?? null,
            requestId: apiError?.requestId ?? "",
            details: [
              `输入文件：${uploadedAudioFile.name || "未命名文件"}`,
              "可以重新选择一个更稳定的音频/视频文件，再尝试提交。",
            ],
          });
          return;
        }
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
        let accessStatus;
        try {
          accessStatus = await loadYouTubeAccessStatus(youtubeUrl);
        } catch (error) {
          if (!isCurrentRun(runSeq, controller)) {
            return;
          }
          const apiError = getApiErrorDetails(error);
          recordJobFailure({
            title: "YouTube 访问预检失败",
            message:
              apiError?.message ??
              (error instanceof Error ? error.message : "Failed to inspect YouTube access."),
            errorCode: apiError?.errorCode ?? "YOUTUBE_ACCESS_STATUS_FAILED",
            retryable: apiError?.retryable ?? null,
            requestId: apiError?.requestId ?? "",
            stageLabel: "解析视频",
            details: [
              `目标链接：${youtubeUrl.trim() || "未提供"}`,
              "可以重试检查、打开设置复核 cookies，或者改用本地音频上传。",
            ],
          });
          return;
        }
        if (!isCurrentRun(runSeq, controller)) {
          return;
        }
        if (!accessStatus.ok) {
          const guidance = [accessStatus.message, accessStatus.recommended_action]
            .map((value) => value.trim())
            .filter(Boolean)
            .join(" ");
          recordJobFailure({
            title: "YouTube 访问状态异常",
            message:
              guidance ||
              "当前 YouTube 访问状态异常，请检查 cookies、网络或视频可见性。",
            errorCode: accessStatus.error_code?.trim() || "YOUTUBE_ACCESS_BLOCKED",
            retryable: accessStatus.retryable ?? null,
            requestId: "",
            stageLabel: "解析视频",
            details: [
              `探测地址：${accessStatus.probe_url || youtubeUrl.trim() || "未提供"}`,
              accessStatus.video_id ? `视频 ID：${accessStatus.video_id}` : "视频 ID：未解析到",
              accessStatus.title ? `视频标题：${accessStatus.title}` : "视频标题：未解析到",
              ...Object.entries(accessStatus.checks || {}).map(([key, value]) => `${key}: ${value}`),
            ],
          });
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
        const apiError = await extractApiErrorDetails(response);
        recordJobFailure({
          title: "任务提交失败",
          message: apiError.message,
          errorCode: apiError.errorCode,
          retryable: apiError.retryable,
          requestId: apiError.requestId,
          details: [
            uploadedAudioFile
              ? `输入文件：${uploadedAudioFile.name || "未命名文件"}`
              : `目标链接：${youtubeUrl.trim() || "未提供"}`,
            "可以再次提交同一输入，或者先打开设置检查模型、API Key 和后端地址。",
          ],
        });
        return;
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
      const apiError = getApiErrorDetails(error);
      if (controller.signal.aborted || rawMessage.includes("Request aborted.")) {
        return;
      }
      if (rawMessage.includes("任务已取消")) {
        setErrorMessage("");
        setJobStatusMessage("任务已取消");
        setFailureDiagnostic(null);
        return;
      }
      if (/cannot connect to backend api|failed to fetch|network/i.test(rawMessage)) {
        recordJobFailure({
          title: "无法连接本地后端",
          message:
            "无法连接本地后端（http://localhost:8000）。请先运行 ./start-dev.sh 或 ./start-backend.sh。",
          errorCode: apiError?.errorCode || "BACKEND_UNREACHABLE",
          retryable: true,
          requestId: apiError?.requestId ?? "",
          details: [
            "如果后端已经启动，请检查 8000 端口是不是被另一个 Translation checkout 占用。",
            "也可以先改用本地音频上传，绕开 YouTube 网络链路。",
          ],
        });
      } else {
        recordJobFailure({
          title: "任务处理失败",
          message: apiError?.message ?? normalizeApiErrorMessage(rawMessage),
          errorCode: apiError?.errorCode || "JOB_FAILED",
          retryable: apiError?.retryable ?? null,
          requestId: apiError?.requestId ?? "",
          details: [
            uploadedAudioFile
              ? `输入文件：${uploadedAudioFile.name || "未命名文件"}`
              : `目标链接：${youtubeUrl.trim() || "未提供"}`,
            jobStatusMessage ? `最后进度：${jobStatusMessage}` : "没有可复用的阶段进度。",
          ],
        });
      }
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
    setFailureDiagnostic(null);
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
    failureDiagnostic,
    setErrorMessage,
    clearJobError,
    invalidateCurrentRun,
    runJob,
    cancelJob,
  };
}
