import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.config import get_env_str
from app.services.content_context_service import load_content_context
from app.services.llm_provider_service import (
    coerce_provider_headers,
    build_endpoint_url,
    clean_model_output_text,
    discover_openai_compatible_model,
    extract_provider_error_message,
    normalize_ollama_base_url,
    provider_default_base_url,
    provider_default_model,
    provider_env_prefix,
    resolve_provider_api_key,
    validate_provider_base_url,
)
from app.services.translation_service import (
    RETRYABLE_STATUS_CODES,
)

SUPPORTED_CHAT_PROVIDERS = {"openai", "deepseek", "lmstudio", "ollama"}
MAX_CHAT_REQUEST_ATTEMPTS = 3

CHAT_ASSISTANT_INSTRUCTIONS = """
You are a content research assistant for a single video.

Rules:
1. Base your answer on the provided English transcript and Chinese translation first.
2. Use the prior conversation turns to maintain continuity across follow-up questions.
3. If the answer is not supported by the provided video content, say so clearly.
4. You may summarize, explain, extract viewpoints, compare statements, and answer follow-up questions.
5. Prefer Simplified Chinese unless the user explicitly asks for another language.
6. Be concrete, accurate, and avoid fabricating facts outside the current video context.
""".strip()


class ContentChatError(Exception):
    """Base error for content chat failures."""


class ContentChatConfigurationError(ContentChatError):
    """Raised when chat configuration is missing or invalid."""


class ContentChatProviderError(ContentChatError):
    """Raised when the upstream provider fails while answering a chat request."""


@dataclass(frozen=True)
class ChatProviderConfig:
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    api_key: str
    base_url: str
    model: str
    custom_prompt: str
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentChatResult:
    answer: str
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str


def answer_content_question(
    *,
    video_title: str | None,
    transcript_en: str | None,
    translation_zh: str | None,
    question: str,
    messages: list[dict[str, object]] | None = None,
    chat_config: dict[str, object] | None = None,
    content_context_id: str | None = None,
) -> ContentChatResult:
    transcript_text = str(transcript_en or "").strip()
    translation_text = str(translation_zh or "").strip()
    question_text = question.strip()

    if content_context_id:
        cached_context = load_content_context(content_context_id)
        if cached_context is None:
            raise ContentChatConfigurationError(
                "content_context_id was not found. Run the job again or resend transcript content."
            )
        if not video_title:
            video_title = cached_context.video_title
        if not transcript_text:
            transcript_text = cached_context.transcript_en
        if not translation_text:
            translation_text = cached_context.translation_zh

    if not transcript_text:
        raise ContentChatConfigurationError(
            "transcript_en must not be empty for content chat."
        )
    if not question_text:
        raise ContentChatConfigurationError("question must not be empty.")

    config = _resolve_chat_config(chat_config)
    payload_messages = _build_chat_messages(
        video_title=video_title,
        transcript_en=transcript_text,
        translation_zh=translation_text,
        question=question_text,
        history=messages or [],
        custom_prompt=config.custom_prompt,
    )

    if config.provider == "ollama":
        answer = _chat_with_ollama(config, payload_messages)
    else:
        answer = _chat_with_openai_compatible(config, payload_messages)

    cleaned_answer = clean_model_output_text(answer).strip()
    if not cleaned_answer:
        raise ContentChatProviderError(
            f"{config.provider} returned an empty chat response."
        )

    return ContentChatResult(
        answer=cleaned_answer,
        provider=config.provider,
        model=config.model,
    )


def _resolve_chat_config(raw_config: dict[str, object] | None) -> ChatProviderConfig:
    config = raw_config or {}
    provider = str(
        config.get("provider")
        or get_env_str("CHAT_PROVIDER")
        or get_env_str("TRANSLATION_PROVIDER")
        or "ollama"
    ).strip().lower()

    if provider not in SUPPORTED_CHAT_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_CHAT_PROVIDERS))
        raise ContentChatConfigurationError(
            f"Unsupported chat provider '{provider}'. Supported providers: {supported}."
        )

    env_prefix = provider_env_prefix(provider)
    try:
        api_key = resolve_provider_api_key(config, provider, env_prefix)
    except ValueError as error:
        raise ContentChatConfigurationError(str(error)) from error

    base_url = str(
        config.get("base_url")
        or get_env_str(f"{env_prefix}_BASE_URL")
        or provider_default_base_url(provider)
    ).strip()
    try:
        base_url = validate_provider_base_url(provider, base_url)
    except ValueError as error:
        raise ContentChatConfigurationError(str(error)) from error

    model = str(
        config.get("model")
        or get_env_str(f"{env_prefix}_CHAT_MODEL")
        or get_env_str(f"{env_prefix}_TRANSLATION_MODEL")
        or provider_default_model(provider)
    ).strip()

    extra_headers = coerce_provider_headers(config.get("extra_headers"))
    if not model and provider in {"lmstudio", "ollama"}:
        try:
            model = discover_openai_compatible_model(
                base_url=base_url,
                api_key=api_key,
                extra_headers=extra_headers,
                provider=provider,
            )
        except Exception as error:
            raise ContentChatConfigurationError(str(error)) from error

    if not model:
        raise ContentChatConfigurationError(
            f"{env_prefix}_CHAT_MODEL is not set and no model could be discovered for provider '{provider}'."
        )

    typed_provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    if provider == "openai":
        typed_provider = "openai"
    elif provider == "deepseek":
        typed_provider = "deepseek"
    elif provider == "lmstudio":
        typed_provider = "lmstudio"
    else:
        typed_provider = "ollama"

    return ChatProviderConfig(
        provider=typed_provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        custom_prompt=str(config.get("custom_prompt") or "").strip(),
        extra_headers=extra_headers,
    )


def _build_chat_messages(
    *,
    video_title: str | None,
    transcript_en: str,
    translation_zh: str,
    question: str,
    history: list[dict[str, object]],
    custom_prompt: str,
) -> list[dict[str, str]]:
    system_instructions = CHAT_ASSISTANT_INSTRUCTIONS
    if custom_prompt:
        system_instructions = f"{system_instructions}\n\nCustom prompt:\n{custom_prompt}"

    context_parts = []
    if video_title and video_title.strip():
        context_parts.append(f"Video title: {video_title.strip()}")
    context_parts.extend(["English transcript:", transcript_en])
    if translation_zh:
        context_parts.extend(["Chinese translation:", translation_zh])
    context_message = "\n\n".join(context_parts)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_instructions},
        {"role": "system", "content": context_message},
    ]

    for item in history:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})
    return messages


def _chat_with_openai_compatible(
    config: ChatProviderConfig,
    messages: list[dict[str, str]],
) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1200,
        "stream": False,
    }

    response = _post_json(
        url=build_endpoint_url(config.base_url, "/chat/completions"),
        headers=_build_headers(config),
        payload=payload,
        provider=config.provider,
    )

    try:
        body = response.json()
    except ValueError as error:
        raise ContentChatProviderError(
            f"{config.provider} returned invalid chat JSON."
        ) from error

    if not isinstance(body, dict):
        raise ContentChatProviderError(
            f"{config.provider} returned an unexpected chat payload."
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ContentChatProviderError(
            f"{config.provider} response did not include chat choices."
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ContentChatProviderError(
            f"{config.provider} response choice had an unexpected format."
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ContentChatProviderError(
            f"{config.provider} response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str):
        raise ContentChatProviderError(
            f"{config.provider} response did not include chat content."
        )

    return content


def _chat_with_ollama(
    config: ChatProviderConfig,
    messages: list[dict[str, str]],
) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2,
        },
    }

    response = _post_json(
        url=build_endpoint_url(normalize_ollama_base_url(config.base_url), "/api/chat"),
        headers=_build_headers(config),
        payload=payload,
        provider=config.provider,
    )

    try:
        body = response.json()
    except ValueError as error:
        raise ContentChatProviderError("ollama returned invalid chat JSON.") from error

    if not isinstance(body, dict):
        raise ContentChatProviderError("ollama returned an unexpected chat payload.")

    message = body.get("message")
    if not isinstance(message, dict):
        raise ContentChatProviderError("ollama response did not include a message payload.")

    content = message.get("content")
    if not isinstance(content, str):
        raise ContentChatProviderError("ollama response did not include chat content.")

    return content


def _post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    provider: str,
) -> httpx.Response:
    last_error_message = ""

    for attempt in range(1, MAX_CHAT_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=180.0,
            )
        except httpx.HTTPError as error:
            last_error_message = f"{provider} chat request failed: {error}"
            if attempt < MAX_CHAT_REQUEST_ATTEMPTS:
                time.sleep(0.75 * attempt)
                continue
            raise ContentChatProviderError(last_error_message) from error

        if response.status_code < 400:
            return response

        message = extract_provider_error_message(response)
        last_error_message = message
        if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_CHAT_REQUEST_ATTEMPTS:
            time.sleep(0.75 * attempt)
            continue

        raise ContentChatProviderError(message)

    raise ContentChatProviderError(last_error_message or "Chat request failed.")


def _build_headers(config: ChatProviderConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    headers.update(config.extra_headers)
    return headers
