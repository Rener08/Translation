"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle, RefreshCw, Settings2 } from "lucide-react";

import { runSettingsPreflight } from "../lib/api";
import type {
  ApiErrorDetails,
  SettingsPreflightResult,
  TranslationSettings,
} from "../lib/types";

type PreflightPanelProps = {
  settings: TranslationSettings;
  requestKey: number;
  onResult: (result: SettingsPreflightResult | null) => void;
  onCloseSettings?: () => void;
};

export function PreflightPanel({
  settings,
  requestKey,
  onResult,
  onCloseSettings,
}: PreflightPanelProps) {
  const [result, setResult] = useState<SettingsPreflightResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [errorDetails, setErrorDetails] = useState<ApiErrorDetails | null>(null);

  function getApiErrorDetails(error: unknown): ApiErrorDetails | null {
    if (!error || typeof error !== "object") {
      return null;
    }
    const candidate = error as { apiError?: ApiErrorDetails };
    return candidate.apiError ?? null;
  }

  async function handleCheck() {
    setLoading(true);
    setError("");
    setErrorDetails(null);
    try {
      const data = await runSettingsPreflight(settings);
      setResult(data);
      onResult(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "检查失败";
      setResult(null);
      onResult(null);
      setError(message);
      setErrorDetails(getApiErrorDetails(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (requestKey > 0) {
      void handleCheck();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const failingChecks = useMemo(
    () => result?.runtime.checks.filter((check) => !check.ok) ?? [],
    [result],
  );
  const retryable = errorDetails?.retryable ?? null;

  return (
    <section className="settings-subsection">
      <div className="settings-subsection-header">
        <h4 className="settings-subsection-title">环境检查</h4>
      </div>

      <div className="settings-cookie-actions">
        <button
          className="settings-cookie-button settings-cookie-button-primary"
          type="button"
          onClick={() => void handleCheck()}
          disabled={loading}
        >
          <RefreshCw size={14} className={loading ? "is-spinning" : ""} />
          {loading ? "检查中..." : "检查环境"}
        </button>
        {onCloseSettings ? (
          <button
            className="settings-cookie-button"
            type="button"
            onClick={onCloseSettings}
          >
            <Settings2 size={14} />
            返回输入页
          </button>
        ) : null}
      </div>

      {error ? (
        <div className="diagnostic-shell">
          <div className="diagnostic-header">
            <div>
              <p className="diagnostic-kicker">预检请求失败</p>
              <h3>{errorDetails?.errorCode ? "预检返回错误" : "无法完成环境检查"}</h3>
            </div>
            {errorDetails?.errorCode ? (
              <span className="diagnostic-tag">{errorDetails.errorCode}</span>
            ) : null}
          </div>
          <p className="diagnostic-message">{error}</p>
          <ul className="diagnostic-list">
            <li>provider：{settings.provider}</li>
            <li>model：{settings.model.trim() || "自动探测"}</li>
            <li>base_url：{settings.baseUrl.trim() || "后端默认值"}</li>
            {retryable !== null ? (
              <li>retryable：{retryable ? "是" : "否"}</li>
            ) : null}
          </ul>
          <div className="diagnostic-actions">
            <button
              className="diagnostic-action"
              type="button"
              onClick={() => void handleCheck()}
              disabled={loading}
            >
              重新检查
            </button>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="preflight-diagnostics">
          <div className="preflight-summary">
            <span className={`preflight-summary-badge ${result.allOk ? "is-ok" : "is-fail"}`}>
              {result.allOk ? "环境正常" : "发现问题"}
            </span>
            <p className="preflight-summary-text">{result.summary}</p>
          </div>

          <div className="preflight-section">
            <h5>本地运行环境</h5>
            <ul className="preflight-check-list">
              {result.runtime.checks.map((check) => (
                <li
                  key={check.name}
                  className={`preflight-check-item ${check.ok ? "is-ok" : "is-fail"}`}
                >
                  <span className="preflight-check-status">
                    {check.ok ? <CheckCircle size={13} /> : "!"}
                  </span>
                  <div className="preflight-check-copy">
                    <strong>{check.label}</strong>
                    {check.detail ? <span>{check.detail}</span> : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="preflight-section">
            <h5>当前 provider / model</h5>
            <div
              className={`preflight-provider-card ${
                result.allOk && result.provider.reachable ? "is-ok" : "is-fail"
              }`}
            >
              <strong>
                {result.provider.provider}
                {result.provider.selected_model ? ` · ${result.provider.selected_model}` : ""}
              </strong>
              <span>{result.provider.message}</span>
              {result.provider.discovered_models.length > 0 ? (
                <span>可发现模型：{result.provider.discovered_models.slice(0, 4).join("、")}</span>
              ) : null}
            </div>
            {!result.allOk && failingChecks.length > 0 ? (
              <p className="preflight-summary-text">
                本地环境有 {failingChecks.length} 项未通过，先修复这些项再提交。
              </p>
            ) : null}
          </div>

          {result.details.length > 0 ? (
            <ul className="preflight-check-list">
              {result.details.map((detail) => (
                <li key={detail} className="preflight-check-item is-ok">
                  <span className="preflight-check-status">
                    <CheckCircle size={13} />
                  </span>
                  <div className="preflight-check-copy">
                    <strong>检查详情</strong>
                    <span>{detail}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
