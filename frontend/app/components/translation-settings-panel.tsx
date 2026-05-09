import { useEffect, useState } from "react";

import {
  apiFetch,
  extractApiErrorMessage,
  getProviderModelPlaceholder,
  normalizeTranslationModel,
  parseHeadersJson,
  type TranslationProvider,
  type TranslationSettings,
} from "../lib/job";

type TranslationSettingsPanelProps = {
  settings: TranslationSettings;
  rewriteFocus: string;
  onChange: (nextSettings: TranslationSettings) => void;
  onRewriteFocusChange: (nextValue: string) => void;
};

export function TranslationSettingsPanel({
  settings,
  rewriteFocus,
  onChange,
  onRewriteFocusChange,
}: TranslationSettingsPanelProps) {
  const modelPlaceholder = getProviderModelPlaceholder(settings.provider);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelOptionsLoading, setModelOptionsLoading] = useState(false);
  const [modelOptionsError, setModelOptionsError] = useState("");
  const apiKeyPlaceholder =
    settings.provider === "deepseek"
      ? "粘贴 DeepSeek API Key"
      : settings.provider === "openai"
        ? "粘贴 OpenAI API Key"
        : "本地模型通常不需要 API Key";
  const backendOffline =
    modelOptionsError.length > 0 &&
    /cannot connect to backend api|failed to fetch|network/i.test(
      modelOptionsError.toLowerCase(),
    );

  useEffect(() => {
    let cancelled = false;
    const debounceId = window.setTimeout(() => {
      async function loadModelOptions() {
        setModelOptionsLoading(true);
        setModelOptionsError("");

        try {
          const response = await apiFetch("/api/provider-models", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              provider: settings.provider,
              base_url: settings.baseUrl.trim() || undefined,
              api_key: settings.apiKey.trim() || undefined,
              extra_headers: parseHeadersJson(settings.headersJson),
            }),
          });

          if (!response.ok) {
            throw new Error(await extractApiErrorMessage(response));
          }

          const data = (await response.json()) as { models?: string[] };
          if (cancelled) {
            return;
          }

          const models = Array.isArray(data.models)
            ? data.models
                .map((value) => value.trim())
                .filter((value, index, array) => value && array.indexOf(value) === index)
            : [];
          setModelOptions(models);
        } catch (error) {
          if (!cancelled) {
            setModelOptions([]);
            setModelOptionsError(
              error instanceof Error ? error.message : "Failed to load model options.",
            );
          }
        } finally {
          if (!cancelled) {
            setModelOptionsLoading(false);
          }
        }
      }

      void loadModelOptions();
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(debounceId);
    };
  }, [settings.apiKey, settings.baseUrl, settings.headersJson, settings.provider]);

  return (
    <section className="settings-panel">
      <div className="settings-header">
        <h2 className="settings-heading">翻译设置</h2>
      </div>

      <div className="settings-grid compact-settings-grid">
        <label className="settings-field">
          <span>内容来源</span>
          <select
            value={settings.sourceMode}
            onChange={(event) =>
              onChange({
                ...settings,
                sourceMode: event.target.value as TranslationSettings["sourceMode"],
              })
            }
          >
            <option value="subtitle_first">字幕优先</option>
            <option value="force_audio">强制音频</option>
          </select>
        </label>

        <label className="settings-field">
          <span>翻译服务</span>
          <select
            value={settings.provider}
            onChange={(event) => {
              const nextProvider = event.target.value as TranslationProvider;
              const nextModel = normalizeTranslationModel(
                nextProvider,
                settings.model,
              );

              onChange({
                ...settings,
                provider: nextProvider,
                model: nextModel,
              });
            }}
          >
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
          </select>
        </label>

        <label className="settings-field">
          <span>API Key</span>
          <input
            type="password"
            placeholder={apiKeyPlaceholder}
            value={settings.apiKey}
            onChange={(event) =>
              onChange({
                ...settings,
                apiKey: event.target.value,
              })
            }
          />
        </label>

        <label className="settings-field">
          <span>模型</span>
          <input
            type="text"
            placeholder={modelPlaceholder}
            value={settings.model}
            onChange={(event) =>
              onChange({
                ...settings,
                model: event.target.value,
              })
            }
          />
          {modelOptionsLoading ? (
            <p className="settings-model-note">正在加载可选模型...</p>
          ) : null}
          {!modelOptionsLoading && modelOptions.length > 0 ? (
            <div className="settings-model-pills" aria-label="可选模型">
              {modelOptions.map((modelOption) => (
                <button
                  key={modelOption}
                  className={`settings-model-pill${
                    settings.model.trim() === modelOption ? " settings-model-pill-active" : ""
                  }`}
                  type="button"
                  onClick={() =>
                    onChange({
                      ...settings,
                      model: modelOption,
                    })
                  }
                >
                  {modelOption}
                </button>
              ))}
            </div>
          ) : null}
          {!modelOptionsLoading && modelOptionsError ? (
            <p
              className={`settings-model-note${
                backendOffline ? "" : " settings-model-error"
              }`}
            >
              {backendOffline
                ? "后端未连接，模型列表暂不可用，可手动填写模型。"
                : modelOptionsError}
            </p>
          ) : null}
        </label>

        <label className="settings-field">
          <span>写作风格</span>
          <select
            value={rewriteFocus}
            onChange={(event) => onRewriteFocusChange(event.target.value)}
          >
            <option value="保留原意和事实，不删关键信息，改写为更有节奏和可读性的中文内容。">
              默认内置风格（晚点通用）
            </option>
          </select>
        </label>
      </div>
    </section>
  );
}
