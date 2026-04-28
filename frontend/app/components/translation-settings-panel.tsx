import {
  SOURCE_MODE,
  type SourceMode,
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
  const apiKeyPlaceholder =
    settings.provider === "deepseek"
      ? "粘贴 DeepSeek API Key"
      : settings.provider === "openai"
        ? "粘贴 OpenAI API Key"
        : "本地模型通常不需要 API Key";

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
            onChange={(event) =>
              onChange({
                ...settings,
                provider: event.target.value as TranslationProvider,
              })
            }
          >
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
          </select>
        </label>

        <label className="settings-field">
          <span>内容来源</span>
          <select
            value={settings.sourceMode}
            onChange={(event) =>
              onChange({
                ...settings,
                sourceMode: event.target.value as SourceMode,
              })
            }
          >
            <option value={SOURCE_MODE.SUBTITLE_FIRST}>字幕优先</option>
            <option value={SOURCE_MODE.FORCE_AUDIO}>强制下载音频</option>
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
      </div>
    </section>
  );
}
