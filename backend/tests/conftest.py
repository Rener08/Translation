import shutil

import pytest

from app.services.persistent_cache_service import CACHE_ROOT_DIR


ISOLATED_ENV_KEYS = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_TRANSLATION_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_TRANSLATION_MODEL",
    "LMSTUDIO_API_KEY",
    "LMSTUDIO_BASE_URL",
    "LMSTUDIO_TRANSLATION_MODEL",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_TRANSLATION_MODEL",
    "TRANSLATION_PROVIDER",
    "WHISPER_MODEL",
    "WHISPER_DEVICE",
    "WHISPER_COMPUTE_TYPE",
    "TMP_ARTIFACT_TTL_HOURS",
    "YTDLP_COOKIES_FROM_BROWSER",
    "YTDLP_COOKIES_FILE",
]


@pytest.fixture(autouse=True)
def isolate_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ISOLATED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    shutil.rmtree(CACHE_ROOT_DIR, ignore_errors=True)
