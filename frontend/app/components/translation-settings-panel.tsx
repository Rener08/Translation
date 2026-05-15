import { useEffect, useState } from "react";

import {
  clearYtDlpCookies,
  DEEPSEEK_MODEL_OPTIONS,
  getProviderModelPlaceholder,
  getDefaultSkillConfigNameForRewriteStyle,
  REWRITE_STYLE,
  loadYtDlpCookies,
  normalizeTranslationModel,
  saveYtDlpCookies,
  type TranslationProvider,
  type TranslationSettings,
} from "../lib/job";

type TranslationSettingsPanelProps = {
  settings: TranslationSettings;
  onChange: (nextSettings: TranslationSettings) => void;
};

export function TranslationSettingsPanel({
  settings,
  onChange,
}: TranslationSettingsPanelProps) {
  const modelPlaceholder = getProviderModelPlaceholder(settings.provider);
  const [cookiesText, setCookiesText] = useState("");
  const [cookiesConfigured, setCookiesConfigured] = useState(false);
  const [cookiesEffectivePath, setCookiesEffectivePath] = useState("");
  const [cookiesLoading, setCookiesLoading] = useState(false);
  const [cookiesSaving, setCookiesSaving] = useState(false);
  const [cookiesError, setCookiesError] = useState("");
  const apiKeyPlaceholder =
    settings.provider === "deepseek"
      ? "粘贴 DeepSeek API Key"
      : settings.provider === "openai"
        ? "粘贴 OpenAI API Key"
        : "本地模型通常不需要 API Key";
  const cookiesCanEdit = cookiesConfigured && Boolean(cookiesEffectivePath);

  async function refreshCookies() {
    setCookiesLoading(true);
    setCookiesError("");

    try {
      const data = await loadYtDlpCookies();
      const effectivePath = String(data.cookies_file || "").trim();
      setCookiesText(data.exists ? data.cookies_text : "");
      setCookiesConfigured(Boolean(data.configured));
      setCookiesEffectivePath(effectivePath);
    } catch (error) {
      setCookiesError(error instanceof Error ? error.message : "Failed to load cookies.");
    } finally {
      setCookiesLoading(false);
    }
  }

  useEffect(() => {
    void refreshCookies();
  }, []);

  const modelValue = normalizeTranslationModel(settings.provider, settings.model);
  const isDeepseekProvider = settings.provider === "deepseek";
  const modelOptions = isDeepseekProvider ? DEEPSEEK_MODEL_OPTIONS : [];

  async function handleSaveCookies() {
    if (!cookiesCanEdit) {
      setCookiesError("请先在 .env 中设置 YTDLP_COOKIES_FILE 的绝对路径，再保存 cookies。");
      return;
    }
    setCookiesSaving(true);
    setCookiesError("");

    try {
      const data = await saveYtDlpCookies(cookiesText);
      setCookiesText(data.cookies_text);
      setCookiesEffectivePath(String(data.cookies_file || "").trim());
    } catch (error) {
      setCookiesError(error instanceof Error ? error.message : "Failed to save cookies.");
    } finally {
      setCookiesSaving(false);
    }
  }

  async function handleClearCookies() {
    if (!cookiesCanEdit) {
      setCookiesError("当前没有可编辑的 cookies 文件路径。");
      return;
    }
    if (
      !window.confirm(
        "确定要清空 cookies 文件吗？清空后，受限视频可能需要重新导出 cookies。",
      )
    ) {
      return;
    }

    setCookiesSaving(true);
    setCookiesError("");

    try {
      const data = await clearYtDlpCookies();
      setCookiesText("");
      setCookiesEffectivePath(String(data.cookies_file || "").trim());
    } catch (error) {
      setCookiesError(error instanceof Error ? error.message : "Failed to clear cookies.");
    } finally {
      setCookiesSaving(false);
    }
  }

  return (
    <section className="settings-panel">
      <div className="settings-header">
        <h2 className="settings-heading">翻译设置</h2>
      </div>

      <div className="settings-grid compact-settings-grid">
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
          <span>模型档位</span>
          {isDeepseekProvider ? (
            <select
              value={modelValue}
              onChange={(event) =>
                onChange({
                  ...settings,
                  model: event.target.value,
                })
              }
            >
              {modelOptions.map((modelOption) => (
                <option key={modelOption} value={modelOption}>
                  {modelOption}
                </option>
              ))}
            </select>
          ) : (
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
          )}
        </label>

        <label className="settings-field">
          <span>写作风格</span>
          <select
            value={settings.rewriteStyle}
            onChange={(event) => {
              const nextRewriteStyle = event.target.value as TranslationSettings["rewriteStyle"];
              const nextSkillConfigName = getDefaultSkillConfigNameForRewriteStyle(
                nextRewriteStyle,
              );

              onChange({
                ...settings,
                rewriteStyle: nextRewriteStyle,
                skillConfigName: nextSkillConfigName,
              });
            }}
          >
            <option value={REWRITE_STYLE.SPEECH_VERBATIM}>
              卡兹克（第一视角）
            </option>
            <option value={REWRITE_STYLE.ARTICLE_LONGFORM}>
              晚点（第三视角）
            </option>
          </select>
        </label>
      </div>

      <section className="settings-subsection">
        <div className="settings-subsection-header">
          <h4 className="settings-subsection-title">YouTube Cookies</h4>
        </div>

        <label className="settings-field settings-cookie-field settings-cookie-field-compact">
          <span>cookies.txt</span>
          <textarea
            className="settings-cookie-textarea"
            placeholder={
              cookiesCanEdit
                ? "粘贴 Netscape 格式的 cookies.txt 内容。"
                : "请先在 .env 中配置 YTDLP_COOKIES_FILE 绝对路径。"
            }
            value={cookiesText}
            onChange={(event) => setCookiesText(event.target.value)}
            spellCheck={false}
            disabled={cookiesLoading || cookiesSaving || !cookiesCanEdit}
          />
        </label>

        <div className="settings-cookie-actions">
          <button
            className="settings-cookie-button settings-cookie-button-primary"
            type="button"
            onClick={() => void handleSaveCookies()}
            disabled={cookiesLoading || cookiesSaving || !cookiesCanEdit}
          >
            {cookiesSaving ? "保存中..." : "保存 cookies"}
          </button>
          <button
            className="settings-cookie-button"
            type="button"
            onClick={() => void handleClearCookies()}
            disabled={cookiesLoading || cookiesSaving || !cookiesCanEdit}
          >
            清空文件
          </button>
        </div>

        {cookiesError ? (
          <p className="settings-cookie-error">{cookiesError}</p>
        ) : null}
      </section>
    </section>
  );
}
