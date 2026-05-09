from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import re
import time
from typing import Literal

import httpx

from app.config import get_env_str
from app.services.llm_provider_service import (
    build_endpoint_url,
    clean_model_output_text,
    discover_openai_compatible_model,
    extract_provider_error_message,
    normalize_ollama_base_url,
    provider_default_base_url,
    provider_default_model,
    provider_env_prefix,
)
from app.services.rewrite_quality_service import analyze_rewrite_quality
from app.services.translation_service import (
    RETRYABLE_STATUS_CODES,
)
from app.services.prompt_validation import validate_rewrite_prompt

SUPPORTED_REWRITE_PROVIDERS = {"openai", "deepseek", "lmstudio", "ollama"}
MAX_REWRITE_REQUEST_ATTEMPTS = 3
REFERENCE_FILE_CHAR_BUDGET = 8000
DEFAULT_LASTPOST_SKILL_DIR = Path.home() / ".hermes" / "skills" / "creative" / "lastpost-skill"

REWRITE_ASSISTANT_INSTRUCTIONS = """
你是一名中文内容改写助手。

任务：
1. 基于用户提供的原始内容进行“改写”，不是凭空重写。
2. 保留原文事实、观点顺序和关键信息，不编造新事实。
3. 语言更顺畅、更有节奏、更像公众号长文写作表达。
4. 默认输出简体中文。
5. 只输出改写后的正文，不要输出解释、标题前缀或分析过程。
""".strip()

DEFAULT_REWRITE_FOCUS = (
    "保留原意和事实，不删关键信息，改写为更有节奏和可读性的中文内容。"
)


class ContentRewriteError(Exception):
    """Base error for content rewrite failures."""


class ContentRewriteConfigurationError(ContentRewriteError):
    """Raised when rewrite configuration is missing or invalid."""


class ContentRewriteInputError(ContentRewriteError):
    """Raised when rewrite request input is invalid."""


class ContentRewriteProviderError(ContentRewriteError):
    """Raised when the upstream rewrite provider fails."""


class ContentRewriteEmptyOutputError(ContentRewriteProviderError):
    """Raised when the upstream provider returns an empty rewrite output."""


@dataclass(frozen=True)
class RewriteProviderConfig:
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    api_key: str
    base_url: str
    model: str
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentRewriteResult:
    rewritten_text: str
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str
    quality_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class RewriteReferences:
    article_template: str
    content_methodology: str
    style_examples: str
    skill_guide: str
    quality_pipeline: str = ""
    reference_profile: str = "lastpost-skill"
    category_templates: dict[str, str] = field(default_factory=dict)
    section_title_rules: str = ""


@dataclass(frozen=True)
class SelectedRewriteTemplate:
    key: str
    label: str
    body: str
    route_reason: str


@dataclass(frozen=True)
class LastpostTemplateSpec:
    key: str
    label: str
    filename: str
    keywords: tuple[str, ...]
    strong_keywords: tuple[str, ...] = ()
    regexes: tuple[str, ...] = ()
    priority: int = 50


LASTPOST_TEMPLATE_SPECS: tuple[LastpostTemplateSpec, ...] = (
    LastpostTemplateSpec(
        key="09_interview_transcript_sync",
        label="09 访谈 / 播客 / 字幕同步稿",
        filename="09_interview_transcript_sync.md",
        keywords=(
            "访谈",
            "播客",
            "字幕",
            "逐字稿",
            "采访",
            "主持人",
            "嘉宾",
            "提问",
            "回应",
            "speaker",
            "transcript",
            "host",
            "guest",
        ),
        strong_keywords=("问：", "答：", "q:", "a:", "00:", "01:", "02:", "03:"),
        regexes=(
            r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
            r"(^|\n)\s*(主持人|嘉宾|记者|speaker|host|guest)\s*[：:]",
            r"(^|\n)\s*(问|答|q|a)\s*[：:]",
        ),
        priority=0,
    ),
    LastpostTemplateSpec(
        key="03_product_review",
        label="03 产品 / 实测 / 评测",
        filename="03_product_review.md",
        keywords=(
            "实测",
            "上手",
            "评测",
            "体验",
            "试用",
            "跑分",
            "提示词",
            "工作流",
            "任务",
            "agent",
            "功能",
            "可用性",
            "失败点",
            "纠错",
        ),
        strong_keywords=("测了", "测试", "使用过程", "真实任务", "复现"),
        priority=1,
    ),
    LastpostTemplateSpec(
        key="02_person_organization_friction",
        label="02 人物 / 组织 / 风波",
        filename="02_person_organization_friction.md",
        keywords=(
            "离职",
            "加入",
            "任命",
            "高管",
            "创始人",
            "ceo",
            "裁员",
            "汇报线",
            "组织调整",
            "架构调整",
            "风波",
            "分歧",
            "权力",
            "组织问题",
        ),
        strong_keywords=("连夜开会", "提交离职", "组织重组", "权力结构"),
        priority=2,
    ),
    LastpostTemplateSpec(
        key="04_industry_adoption",
        label="04 行业落地 / 场景改造",
        filename="04_industry_adoption.md",
        keywords=(
            "落地",
            "场景",
            "流程",
            "客户",
            "企业",
            "医院",
            "教育",
            "金融",
            "工厂",
            "门店",
            "部署",
            "提效",
            "改造",
            "省了",
        ),
        strong_keywords=("旧流程", "新流程", "嵌入", "决策质量"),
        priority=3,
    ),
    LastpostTemplateSpec(
        key="05_hardware_robotics",
        label="05 硬件 / 机器人 / 制造 / 终端",
        filename="05_hardware_robotics.md",
        keywords=(
            "机器人",
            "硬件",
            "终端",
            "芯片",
            "眼镜",
            "汽车",
            "量产",
            "供应链",
            "传感器",
            "制造",
            "设备",
            "具身",
            "整机",
            "bom",
        ),
        strong_keywords=("量产", "供应链", "工程化", "可靠性"),
        priority=4,
    ),
    LastpostTemplateSpec(
        key="06_infra_cloud_model_platform",
        label="06 基础设施 / 云 / 模型 / 平台",
        filename="06_infra_cloud_model_platform.md",
        keywords=(
            "基础设施",
            "云",
            "模型",
            "平台",
            "推理",
            "训练",
            "算力",
            "gpu",
            "token",
            "api",
            "数据库",
            "中间件",
            "全栈",
            "benchmark",
        ),
        strong_keywords=("推理成本", "系统性", "平台化", "商业化关系"),
        priority=5,
    ),
    LastpostTemplateSpec(
        key="07_startup_funding_ipo",
        label="07 创业 / 融资 / 估值 / 路径对比",
        filename="07_startup_funding_ipo.md",
        keywords=(
            "融资",
            "估值",
            "ipo",
            "上市",
            "投资人",
            "基金",
            "轮融资",
            "a轮",
            "b轮",
            "c轮",
            "pre-ipo",
            "并购",
            "现金流",
            "营收",
        ),
        strong_keywords=("估值", "融资", "ipo", "投资机构"),
        priority=6,
    ),
    LastpostTemplateSpec(
        key="08_risk_bubble_safety_accident",
        label="08 风险 / 泡沫 / 对齐 / 事故",
        filename="08_risk_bubble_safety_accident.md",
        keywords=(
            "风险",
            "泡沫",
            "安全",
            "对齐",
            "事故",
            "泄露",
            "幻觉",
            "监管",
            "封禁",
            "违规",
            "灾难",
            "隐私",
            "误判",
            "攻击",
        ),
        strong_keywords=("安全事故", "数据泄露", "监管调查", "泡沫"),
        priority=7,
    ),
    LastpostTemplateSpec(
        key="01_big_company_war",
        label="01 巨头战役 / 组织重排",
        filename="01_big_company_war.md",
        keywords=(
            "阿里",
            "腾讯",
            "字节",
            "百度",
            "美团",
            "京东",
            "华为",
            "小米",
            "谷歌",
            "微软",
            "苹果",
            "亚马逊",
            "meta",
            "openai",
            "anthropic",
            "xai",
            "入口",
            "战役",
            "竞争",
            "重排",
        ),
        strong_keywords=("大厂", "资源重排", "入口之争", "战略转向"),
        priority=8,
    ),
)

LASTPOST_DEFAULT_TEMPLATE_KEY = "01_big_company_war"


def rewrite_content(
    *,
    source_text: str,
    rewrite_focus: str | None = None,
    rewrite_config: dict[str, object] | None = None,
) -> ContentRewriteResult:
    normalized_source = str(source_text or "").strip()
    if not normalized_source:
        raise ContentRewriteConfigurationError("source_text must not be empty.")

    if rewrite_focus is None:
        normalized_focus = DEFAULT_REWRITE_FOCUS
    else:
        normalized_focus = str(rewrite_focus).strip()
        if not normalized_focus:
            raise ContentRewriteInputError(
                "改写提示为空。请重新选择写作风格，或移除空白 rewrite_focus 后重试。"
            )

    prompt_validation = validate_rewrite_prompt(normalized_focus)
    if not prompt_validation.is_valid:
        raise ContentRewriteInputError("；".join(prompt_validation.errors))

    config = _resolve_rewrite_config(rewrite_config)
    references = None if prompt_validation.has_transcript_placeholder else load_rewrite_references()
    messages = _build_rewrite_messages(
        source_text=normalized_source,
        rewrite_focus=normalized_focus,
        references=references,
    )

    if config.provider == "ollama":
        rewritten_text = _rewrite_with_ollama(config, messages)
    else:
        rewritten_text = _rewrite_with_openai_compatible(config, messages)

    cleaned = clean_model_output_text(rewritten_text).strip()
    if not cleaned:
        raise ContentRewriteEmptyOutputError(
            f"内容改写失败：{config.provider} 返回了空内容。请重试，或更换模型/提示词。"
        )
    quality_issues = tuple(analyze_rewrite_quality(cleaned))

    return ContentRewriteResult(
        rewritten_text=cleaned,
        provider=config.provider,
        model=config.model,
        quality_issues=quality_issues,
    )


@lru_cache(maxsize=1)
def load_rewrite_references() -> RewriteReferences:
    skill_root = _resolve_lastpost_skill_root()
    if skill_root is None:
        raise ContentRewriteConfigurationError(
            "lastpost-skill not found. Set LASTPOST_SKILL_DIR or install ~/.hermes/skills/creative/lastpost-skill."
        )

    content_methodology = _read_reference_file(
        skill_root / "references" / "content_methodology.md"
    )
    style_examples = _read_reference_file(skill_root / "references" / "style_examples.md")
    skill_guide = _read_reference_file(skill_root / "SKILL.md")
    article_template = _read_reference_file(
        skill_root / "prompts" / "latepost_prompt_templates_onepage.md"
    )
    quality_pipeline = _read_reference_file(
        skill_root / "references" / "quality_pipeline.md"
    )
    section_title_rules = _read_reference_file(
        skill_root / "prompts" / "11_section_titles_and_reverse_prompt.md"
    )
    category_templates = _load_lastpost_category_templates(skill_root)

    if article_template.startswith("[缺失参考文件"):
        article_template = _build_default_article_template(
            content_methodology=content_methodology,
            style_examples=style_examples,
            skill_guide=skill_guide,
        )

    return RewriteReferences(
        article_template=article_template,
        content_methodology=content_methodology,
        style_examples=style_examples,
        skill_guide=skill_guide,
        quality_pipeline=quality_pipeline,
        reference_profile="lastpost-skill",
        category_templates=category_templates,
        section_title_rules=section_title_rules,
    )


def _build_rewrite_messages(
    *,
    source_text: str,
    rewrite_focus: str,
    references: RewriteReferences | None,
) -> list[dict[str, str]]:
    if _uses_full_skill_prompt(rewrite_focus):
        # 如果前端传来了包含 {{transcript}} 占位符的完整 Skill Prompt，直接替换并使用
        user_prompt = rewrite_focus.replace("{{transcript}}", source_text)
        return [
            {"role": "system", "content": "你是一个智能写作助手。请严格遵守用户的格式要求。"},
            {"role": "user", "content": user_prompt},
        ]

    if references is None:
        raise ContentRewriteConfigurationError(
            "Rewrite references are required when no full skill prompt is provided."
        )

    selected_template = _select_rewrite_template(
        source_text=source_text,
        rewrite_focus=rewrite_focus,
        references=references,
    )
    reference_context = (
        f"【参考来源】\n{references.reference_profile}\n\n"
        "【晚点题材路由】\n"
        f"模板：{selected_template.label}\n"
        f"判定：{selected_template.route_reason}\n\n"
        "【场景模板】\n"
        f"{selected_template.body}\n\n"
        "【通用一页模板】\n"
        f"{references.article_template}\n\n"
        "【标题与反向提示】\n"
        f"{references.section_title_rules}\n\n"
        "【内容方法论参考】\n"
        f"{references.content_methodology}\n\n"
        "【风格示例参考】\n"
        f"{references.style_examples}\n\n"
        "【写作规则参考】\n"
        f"{references.skill_guide}\n\n"
        "【质量流程参考】\n"
        f"{references.quality_pipeline}"
    )

    # 没有完整 skill prompt 时，统一落到 backend 维护的参考材料和题材路由
    user_prompt = (
        "请改写以下内容。\n\n"
        f"改写目标：{rewrite_focus}\n\n"
        "限制要求：\n"
        "- 不编造事实，不添加原文没有的关键结论。\n"
        "- 保持原始信息。\n"
        "- 优先遵守场景模板、标题规则和质量流程。\n"
        "- 输出只包含改写后的正文。\n\n"
        "原始内容：\n"
        f"{source_text}"
    )

    return [
        {"role": "system", "content": REWRITE_ASSISTANT_INSTRUCTIONS},
        {"role": "system", "content": reference_context},
        {"role": "user", "content": user_prompt},
    ]


def _uses_full_skill_prompt(rewrite_focus: str) -> bool:
    return "{{transcript}}" in rewrite_focus


def _resolve_rewrite_config(
    raw_config: dict[str, object] | None,
) -> RewriteProviderConfig:
    config = raw_config or {}
    provider = str(
        config.get("provider")
        or get_env_str("REWRITE_PROVIDER")
        or get_env_str("TRANSLATION_PROVIDER")
        or "ollama"
    ).strip().lower()

    if provider not in SUPPORTED_REWRITE_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_REWRITE_PROVIDERS))
        raise ContentRewriteConfigurationError(
            f"Unsupported rewrite provider '{provider}'. Supported providers: {supported}."
        )

    env_prefix = provider_env_prefix(provider)
    api_key = str(
        config.get("api_key")
        or get_env_str(f"{env_prefix}_API_KEY")
        or ""
    ).strip()
    requires_api_key = provider in {"openai", "deepseek"}
    if requires_api_key and not api_key:
        raise ContentRewriteConfigurationError(
            f"{env_prefix}_API_KEY is not set. Add it to your environment, .env file, or request settings."
        )

    base_url = str(
        config.get("base_url")
        or get_env_str(f"{env_prefix}_BASE_URL")
        or provider_default_base_url(provider)
    ).strip()

    model = str(
        config.get("model")
        or get_env_str(f"{env_prefix}_REWRITE_MODEL")
        or get_env_str(f"{env_prefix}_CHAT_MODEL")
        or get_env_str(f"{env_prefix}_TRANSLATION_MODEL")
        or provider_default_model(provider)
    ).strip()

    extra_headers = _coerce_headers(config.get("extra_headers"))
    if not model and provider in {"lmstudio", "ollama"}:
        try:
            model = discover_openai_compatible_model(
                base_url=base_url,
                api_key=api_key,
                extra_headers=extra_headers,
                provider=provider,
            )
        except Exception as error:
            raise ContentRewriteConfigurationError(str(error)) from error

    if not model:
        raise ContentRewriteConfigurationError(
            f"{env_prefix}_REWRITE_MODEL is not set and no model could be discovered for provider '{provider}'."
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

    return RewriteProviderConfig(
        provider=typed_provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        extra_headers=extra_headers,
    )


def _rewrite_with_openai_compatible(
    config: RewriteProviderConfig,
    messages: list[dict[str, str]],
) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 3000,
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
        raise ContentRewriteProviderError(
            f"{config.provider} returned invalid rewrite JSON."
        ) from error

    if not isinstance(body, dict):
        raise ContentRewriteProviderError(
            f"{config.provider} returned an unexpected rewrite payload."
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ContentRewriteProviderError(
            f"{config.provider} response did not include rewrite choices."
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ContentRewriteProviderError(
            f"{config.provider} response choice had an unexpected format."
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ContentRewriteProviderError(
            f"{config.provider} response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str):
        raise ContentRewriteProviderError(
            f"{config.provider} response did not include rewrite content."
        )

    return content


def _rewrite_with_ollama(
    config: RewriteProviderConfig,
    messages: list[dict[str, str]],
) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.4,
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
        raise ContentRewriteProviderError(
            "ollama returned invalid rewrite JSON."
        ) from error

    if not isinstance(body, dict):
        raise ContentRewriteProviderError(
            "ollama returned an unexpected rewrite payload."
        )

    message = body.get("message")
    if not isinstance(message, dict):
        raise ContentRewriteProviderError(
            "ollama response did not include a message payload."
        )

    content = message.get("content")
    if not isinstance(content, str):
        raise ContentRewriteProviderError(
            "ollama response did not include rewrite content."
        )

    return content


def _post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    provider: str,
) -> httpx.Response:
    last_error_message = ""
    for attempt in range(1, MAX_REWRITE_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=300.0,
            )
        except httpx.HTTPError as error:
            last_error_message = f"{provider} rewrite request failed: {error}"
            if attempt < MAX_REWRITE_REQUEST_ATTEMPTS:
                time.sleep(0.75 * attempt)
                continue
            raise ContentRewriteProviderError(last_error_message) from error

        if response.status_code < 400:
            return response

        message = extract_provider_error_message(response)
        last_error_message = message
        if (
            response.status_code in RETRYABLE_STATUS_CODES
            and attempt < MAX_REWRITE_REQUEST_ATTEMPTS
        ):
            time.sleep(0.75 * attempt)
            continue

        raise ContentRewriteProviderError(message)

    raise ContentRewriteProviderError(last_error_message or "Rewrite request failed.")


def _build_headers(config: RewriteProviderConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    headers.update(config.extra_headers)
    return headers


def _coerce_headers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    headers: dict[str, str] = {}
    for key, header_value in value.items():
        normalized_key = str(key).strip()
        normalized_value = str(header_value).strip()
        if not normalized_key or not normalized_value:
            continue
        headers[normalized_key] = normalized_value
    return headers


def _resolve_lastpost_skill_root() -> Path | None:
    configured_path = get_env_str("LASTPOST_SKILL_DIR") or get_env_str(
        "REWRITE_SKILL_DIR"
    )
    if configured_path:
        configured_root = Path(configured_path).expanduser()
        if configured_root.exists():
            return configured_root

    if DEFAULT_LASTPOST_SKILL_DIR.exists():
        return DEFAULT_LASTPOST_SKILL_DIR

    return None


def _select_rewrite_template(
    *,
    source_text: str,
    rewrite_focus: str,
    references: RewriteReferences,
) -> SelectedRewriteTemplate:
    if references.reference_profile != "lastpost-skill" or not references.category_templates:
        return SelectedRewriteTemplate(
            key="generic",
            label="通用模板",
            body=references.article_template,
            route_reason="未加载晚点分类模板，回退到通用模板。",
        )

    combined_text = f"{rewrite_focus}\n{source_text}"
    normalized = combined_text.lower()

    for spec in LASTPOST_TEMPLATE_SPECS:
        if any(re.search(pattern, combined_text, flags=re.IGNORECASE | re.MULTILINE) for pattern in spec.regexes):
            body = references.category_templates.get(spec.key, references.article_template)
            return SelectedRewriteTemplate(
                key=spec.key,
                label=spec.label,
                body=body,
                route_reason=f"命中强结构特征，按“{spec.label}”处理。",
            )

    scored: list[tuple[int, int, LastpostTemplateSpec, list[str]]] = []
    for spec in LASTPOST_TEMPLATE_SPECS:
        score = 0
        hits: list[str] = []

        for keyword in spec.strong_keywords:
            if keyword.lower() in normalized:
                score += 4
                hits.append(keyword)

        for keyword in spec.keywords:
            if keyword.lower() in normalized:
                score += 1
                hits.append(keyword)

        if score <= 0:
            continue

        scored.append((score, -spec.priority, spec, hits[:4]))

    if scored:
        score, _, spec, hits = max(scored, key=lambda item: (item[0], item[1]))
        hit_text = "、".join(hits) if hits else "题材关键词"
        body = references.category_templates.get(spec.key, references.article_template)
        return SelectedRewriteTemplate(
            key=spec.key,
            label=spec.label,
            body=body,
            route_reason=f"命中 {score} 个题材信号，主要依据：{hit_text}。",
        )

    default_spec = next(
        (
            spec
            for spec in LASTPOST_TEMPLATE_SPECS
            if spec.key == LASTPOST_DEFAULT_TEMPLATE_KEY
        ),
        LASTPOST_TEMPLATE_SPECS[-1],
    )
    return SelectedRewriteTemplate(
        key=default_spec.key,
        label=default_spec.label,
        body=references.category_templates.get(default_spec.key, references.article_template),
        route_reason="未命中特别强的题材信号，按晚点常见公司/战略稿主线处理。",
    )


@lru_cache(maxsize=1)
def _load_lastpost_category_templates(skill_root: Path) -> dict[str, str]:
    prompt_root = skill_root / "prompts"
    templates: dict[str, str] = {}
    for spec in LASTPOST_TEMPLATE_SPECS:
        templates[spec.key] = _read_reference_file(prompt_root / spec.filename)
    return templates


def _read_reference_file(path: Path) -> str:
    if not path.exists():
        return f"[缺失参考文件: {path.name}]"

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return f"[读取参考文件失败: {path.name}]"

    normalized = raw_text.strip()
    if len(normalized) <= REFERENCE_FILE_CHAR_BUDGET:
        return normalized

    return (
        normalized[:REFERENCE_FILE_CHAR_BUDGET]
        + "\n\n[内容过长，已截断。优先参考上面的方法与风格要点。]"
    )


def _build_default_article_template(
    *,
    content_methodology: str,
    style_examples: str,
    skill_guide: str,
) -> str:
    _ = (content_methodology, style_examples, skill_guide)
    return (
        "# 文章改写模板\n"
        "## 1. 开头（1-2段）\n"
        "- 从具体场景或事件切入，不讲空话。\n"
        "- 用口语化句子快速建立好奇心。\n\n"
        "## 2. 背景与问题（1-2段）\n"
        "- 交代问题背景和读者关切。\n"
        "- 明确本文要解决的核心问题。\n\n"
        "## 3. 核心展开（3-5段）\n"
        "- 每段围绕一个子观点展开。\n"
        "- 采用“观点 -> 例子 -> 解释 -> 回扣主线”节奏。\n"
        "- 保留原文事实，不新增未经提供的信息。\n\n"
        "## 4. 升维收束（1-2段）\n"
        "- 提炼更高层次结论或方法启发。\n"
        "- 语言保持克制，避免鸡汤式口号。\n\n"
        "## 5. 结尾（1段）\n"
        "- 回扣开头问题，给出可执行的下一步建议。\n"
    )
