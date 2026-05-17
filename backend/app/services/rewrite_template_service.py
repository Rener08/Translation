from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import re

from app.config import get_env_str

REFERENCE_FILE_CHAR_BUDGET = 8000
REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_LASTPOST_SKILL_DIR = REPO_ROOT / "writer-skill" / "latepost" / "references"
_LEGACY_LASTPOST_SKILL_DIR = Path.home() / ".hermes" / "skills" / "creative" / "lastpost-skill"


@dataclass(frozen=True)
class RewriteReferences:
    article_template: str
    content_methodology: str
    style_examples: str
    skill_guide: str
    quality_pipeline: str = ""
    reference_profile: str = "latepost-skill"
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
            "访谈", "播客", "字幕", "逐字稿", "采访", "主持人",
            "嘉宾", "提问", "回应", "speaker", "transcript", "host", "guest",
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
            "实测", "上手", "评测", "体验", "试用", "跑分", "提示词",
            "工作流", "任务", "功能", "可用性", "失败点", "纠错",
        ),
        strong_keywords=("测了", "测试", "使用过程", "真实任务", "复现"),
        priority=1,
    ),
    LastpostTemplateSpec(
        key="06_infra_cloud_model_platform",
        label="06 基础设施 / 云 / 模型 / 平台",
        filename="06_infra_cloud_model_platform.md",
        keywords=(
            "基础设施", "云", "模型", "平台", "推理", "训练", "算力",
            "gpu", "token", "api", "数据库", "中间件", "全栈", "benchmark",
        ),
        strong_keywords=("推理成本", "系统性", "平台化", "商业化关系"),
        priority=5,
    ),
    LastpostTemplateSpec(
        key="01_big_company_war",
        label="01 巨头战役 / 组织重排",
        filename="01_big_company_war.md",
        keywords=(
            "阿里", "腾讯", "字节", "百度", "美团", "京东", "华为",
            "小米", "谷歌", "微软", "苹果", "亚马逊", "meta", "openai",
            "anthropic", "xai", "入口", "战役", "竞争", "重排",
        ),
        strong_keywords=("大厂", "资源重排", "入口之争", "战略转向"),
        priority=8,
    ),
)

# 晚点默认表只保留三类主场景，其他题材不参与默认自动路由。
LASTPOST_CORE_TEMPLATE_KEYS: tuple[str, ...] = (
    "09_interview_transcript_sync",
    "03_product_review",
    "06_infra_cloud_model_platform",
)
LASTPOST_ROUTABLE_TEMPLATE_KEYS: tuple[str, ...] = LASTPOST_CORE_TEMPLATE_KEYS
LASTPOST_STRATEGIC_FALLBACK_TEMPLATE_KEY = "01_big_company_war"
# Backward-compatible alias: other modules and tests may still import the old name.
LASTPOST_DEFAULT_TEMPLATE_KEY = LASTPOST_STRATEGIC_FALLBACK_TEMPLATE_KEY

_EXPLICIT_TRANSCRIPT_SYNC_MARKERS: tuple[str, ...] = (
    "逐字稿",
    "同步稿",
    "字幕同步",
    "采访整理",
    "播客整理",
    "访谈整理",
    "时间轴",
)


@lru_cache(maxsize=1)
def load_rewrite_references() -> RewriteReferences:
    from app.services.content_rewrite_service import ContentRewriteConfigurationError

    skill_root = resolve_lastpost_skill_root()
    if skill_root is None:
        raise ContentRewriteConfigurationError(
            "写作参考资料未找到。请确认 writer-skill/latepost/references 目录存在，或设置 LATEPOST_SKILL_DIR / LASTPOST_SKILL_DIR 环境变量。"
        )

    skill_guide = _read_skill_bundle_file(skill_root.parent, "SKILL.md")
    content_methodology = _read_skill_bundle_file(skill_root, "content_methodology.md")
    style_examples = _read_skill_bundle_file(skill_root, "style_examples.md")
    article_template = _read_skill_bundle_file(skill_root, "article_template.md")
    quality_pipeline = _read_skill_bundle_file(skill_root, "quality_pipeline.md")
    section_title_rules = _read_skill_bundle_file(
        skill_root, "prompts/11_section_titles_and_reverse_prompt.md"
    )
    category_templates = _load_lastpost_category_templates(skill_root)

    if article_template.startswith("[缺失参考文件"):
        article_template = _build_default_article_template(skill_guide=skill_guide)

    return RewriteReferences(
        article_template=article_template,
        content_methodology=content_methodology,
        style_examples=style_examples,
        skill_guide=skill_guide,
        quality_pipeline=quality_pipeline,
        reference_profile="latepost-skill",
        category_templates=category_templates,
        section_title_rules=section_title_rules,
    )


def select_rewrite_template(
    *,
    source_text: str,
    rewrite_focus: str,
    references: RewriteReferences,
) -> SelectedRewriteTemplate:
    if references.reference_profile != "latepost-skill" or not references.category_templates:
        return SelectedRewriteTemplate(
            key="generic",
            label="通用模板",
            body=references.article_template,
            route_reason="未加载晚点分类模板，回退到通用模板。",
        )

    combined_text = f"{rewrite_focus}\n{source_text}"
    normalized = combined_text.lower()

    if _explicit_transcript_sync_requested(rewrite_focus=rewrite_focus, source_text=source_text):
        transcript_spec = next(
            (
                spec
                for spec in LASTPOST_TEMPLATE_SPECS
                if spec.key == "09_interview_transcript_sync"
            ),
            None,
        )
        if transcript_spec is not None:
            body = references.category_templates.get(transcript_spec.key, references.article_template)
            return SelectedRewriteTemplate(
                key=transcript_spec.key,
                label=transcript_spec.label,
                body=body,
                route_reason="用户明确要求逐字稿/同步稿，按访谈同步模板处理。",
            )

    article_like_focus = _article_like_output_requested(rewrite_focus)
    routable_specs = tuple(
        spec for spec in LASTPOST_TEMPLATE_SPECS if spec.key in LASTPOST_ROUTABLE_TEMPLATE_KEYS
    )
    if article_like_focus:
        routable_specs = tuple(
            spec for spec in routable_specs
            if spec.key != "09_interview_transcript_sync"
        )
    scored = _score_template_specs(
        specs=routable_specs,
        normalized_text=normalized,
        combined_text=combined_text,
        allow_keyword_hits=True,
    )
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

    strategic_spec = next(
        (
            spec
            for spec in LASTPOST_TEMPLATE_SPECS
            if spec.key == LASTPOST_STRATEGIC_FALLBACK_TEMPLATE_KEY
        ),
        LASTPOST_TEMPLATE_SPECS[-1],
    )
    strategic_hits = _find_strategic_fallback_hits(strategic_spec, normalized)
    if strategic_hits:
        hit_text = "、".join(strategic_hits)
        body = references.category_templates.get(strategic_spec.key, references.article_template)
        return SelectedRewriteTemplate(
            key=strategic_spec.key,
            label=strategic_spec.label,
            body=body,
            route_reason=f"命中组织/战略信号，按\"{strategic_spec.label}\"处理。主要依据：{hit_text}。",
        )

    return SelectedRewriteTemplate(
        key="generic",
        label="通用素材报道稿",
        body=references.article_template,
        route_reason="未命中可自动路由的题材信号，回退到中性通用模板。",
    )


def _explicit_transcript_sync_requested(*, rewrite_focus: str, source_text: str) -> bool:
    normalized_focus = (rewrite_focus or "").lower()
    if any(marker in normalized_focus for marker in _EXPLICIT_TRANSCRIPT_SYNC_MARKERS):
        return True
    # Only treat an explicit request in the focus as a signal; source text often contains
    # interview markers even when the desired output is a rewritten article.
    _ = source_text
    return False


def _article_like_output_requested(rewrite_focus: str) -> bool:
    normalized_focus = (rewrite_focus or "").lower()
    article_markers = (
        "文章",
        "报道",
        "分析稿",
        "深度",
        "长文",
        "基础设施",
        "平台",
        "模型",
        "云",
        "成稿",
    )
    return any(marker in normalized_focus for marker in article_markers)


def _score_template_specs(
    *,
    specs: tuple[LastpostTemplateSpec, ...],
    normalized_text: str,
    combined_text: str,
    allow_keyword_hits: bool,
) -> list[tuple[int, int, LastpostTemplateSpec, list[str]]]:
    scored: list[tuple[int, int, LastpostTemplateSpec, list[str]]] = []
    for spec in specs:
        if any(
            re.search(pattern, combined_text, flags=re.IGNORECASE | re.MULTILINE)
            for pattern in spec.regexes
        ):
            body_hits = [f"正则:{pattern}" for pattern in spec.regexes if re.search(
                pattern, combined_text, flags=re.IGNORECASE | re.MULTILINE
            )]
            scored.append((8, -spec.priority, spec, body_hits[:4]))
            continue

        score = 0
        hits: list[str] = []
        for keyword in spec.strong_keywords:
            if keyword.lower() in normalized_text:
                score += 4
                hits.append(keyword)
        if allow_keyword_hits:
            for keyword in spec.keywords:
                if keyword.lower() in normalized_text:
                    score += 1
                    hits.append(keyword)
        if score > 0:
            scored.append((score, -spec.priority, spec, hits[:4]))
    return scored


def _find_strategic_fallback_hits(
    spec: LastpostTemplateSpec,
    normalized_text: str,
) -> list[str]:
    hits: list[str] = []
    for keyword in spec.strong_keywords:
        if keyword.lower() in normalized_text:
            hits.append(keyword)
    return hits


def resolve_lastpost_skill_root() -> Path | None:
    configured_path = (
        get_env_str("LATEPOST_SKILL_DIR")
        or get_env_str("LASTPOST_SKILL_DIR")
        or get_env_str("REWRITE_SKILL_DIR")
    )
    if configured_path:
        configured_root = Path(configured_path).expanduser()
        if configured_root.exists():
            if (configured_root / "references").exists() and not (configured_root / "prompts").exists():
                return configured_root / "references"
            return configured_root

    if PINNED_LASTPOST_SKILL_DIR.exists():
        return PINNED_LASTPOST_SKILL_DIR

    # Legacy fallback: external lastpost-skill installation
    if _LEGACY_LASTPOST_SKILL_DIR.exists():
        return _LEGACY_LASTPOST_SKILL_DIR

    return None


def _read_skill_bundle_file(skill_root: Path, filename: str) -> str:
    candidates = (
        skill_root / filename,
        skill_root / "prompts" / filename,
    )
    for path in candidates:
        if path.exists():
            return _read_reference_file(path)
    return f"[缺失参考文件: {filename}]"


@lru_cache(maxsize=1)
def _load_lastpost_category_templates(skill_root: Path) -> dict[str, str]:
    templates: dict[str, str] = {}
    for spec in LASTPOST_TEMPLATE_SPECS:
        templates[spec.key] = _read_skill_bundle_file(skill_root, spec.filename)
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


def _build_default_article_template(*, skill_guide: str) -> str:
    _ = skill_guide
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
        "- 采用\"观点 -> 例子 -> 解释 -> 回扣主线\"节奏。\n"
        "- 保留原文事实，不新增未经提供的信息。\n\n"
        "## 4. 升维收束（1-2段）\n"
        "- 提炼更高层次结论或方法启发。\n"
        "- 语言保持克制，避免鸡汤式口号。\n\n"
        "## 5. 结尾（1段）\n"
        "- 回扣开头问题，给出可执行的下一步建议。\n"
    )
