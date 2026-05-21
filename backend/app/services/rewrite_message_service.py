from app.services.article_generation_service import measure_source_text_length
from app.services.rewrite_template_service import RewriteReferences, select_rewrite_template
from app.services.rewrite_stage_router import THIN_LONGFORM_PROMPT_PROFILE

SPEECH_VERBATIM_ASSISTANT_INSTRUCTIONS = """
你是一名中文口吻整理助手。

任务：
1. 基于用户提供的原始内容进行整理，不要凭空重写。
2. 保留原作者的说话节奏、语气、观点顺序和关键信息，不编造新事实。
3. 优先保留问答节奏、口头表达、停顿感和语气词，只做轻度润色和断句整理。
4. 输出必须是简体中文稿；如果原文是英文，也要整理成简体中文，不要整篇保留英文。
5. 不要总结化重写，不要改成公众号长文，不要加入标题前缀或分析过程。
6. 只输出整理后的正文。
""".strip()

ARTICLE_LONGFORM_ASSISTANT_INSTRUCTIONS = """
你是一名中文文章改写助手。

任务：
1. 基于用户提供的原始内容进行完整改写，不是总结或摘要。
2. 逐段翻译/改写所有内容，保留所有段落、细节、例子、数字、人名、地名、时间、引用。
3. 保留原文事实、观点顺序和关键信息，不编造新事实，不省略段落。
4. 如果原始内容是访谈、播客、问答或字幕稿，必须把它改写成第三视角的报道文章，不要保留逐字同步、时间块列表或问答壳。
5. 第三视角不是把人称换成他/她，而是把叙述重心放在事件、变化、机制、代价和边界上；不要让人物发言顺序主导段落顺序。
6. 如果原文里有安全、商业闭环、内部实践、合作、监管、算力部署等高价值信息，这些通常是文章骨架，不能压缩成背景。
7. 严格遵守用户给出的改写要求、约束和长度要求。
8. 默认输出简体中文。
9. 只输出改写后的正文，不要输出解释、标题前缀或分析过程。
""".strip()

DEFAULT_REWRITE_FOCUS = (
    "保留原作者的说话节奏和口吻，只做轻度整理，不要总结化重写。"
)

ARTICLE_LONGFORM_DEFAULT_FOCUS = (
    "改写成第三视角的中文文章，保留原意和事实，不删关键信息，不使用第一人称自述。"
)


def uses_full_skill_prompt(rewrite_focus: str) -> bool:
    return "{{transcript}}" in rewrite_focus


def build_rewrite_messages(
    *,
    source_text: str,
    rewrite_focus: str,
    rewrite_style: str,
    references: RewriteReferences | None,
    detail_ledger: str | None,
    skill_config=None,
    prompt_profile: str = "default",
) -> list[dict[str, str]]:
    if uses_full_skill_prompt(rewrite_focus):
        wrapped_source = f"\n\n[转录内容开始]\n{source_text}\n[转录内容结束]\n\n"
        user_prompt = rewrite_focus.replace("{{transcript}}", wrapped_source)
        return [
            {"role": "system", "content": "你是一个智能写作助手。请严格遵守用户的格式要求。"},
            {"role": "user", "content": user_prompt},
        ]

    if rewrite_style == "speech_verbatim":
        return _build_speech_verbatim_messages(
            source_text=source_text,
            rewrite_focus=rewrite_focus,
            detail_ledger=detail_ledger,
        )

    if references is None:
        from app.services.content_rewrite_service import ContentRewriteConfigurationError

        raise ContentRewriteConfigurationError(
            "Rewrite references are required when no full skill prompt is provided."
        )

    selected_template = select_rewrite_template(
        source_text=source_text,
        rewrite_focus=rewrite_focus,
        references=references,
    )
    if prompt_profile == THIN_LONGFORM_PROMPT_PROFILE:
        reference_context = (
            f"【参考来源】\n{references.reference_profile}\n\n"
            "【晚点题材路由】\n"
            f"模板：{selected_template.label}\n"
            f"判定：{selected_template.route_reason}\n\n"
            "【场景模板】\n"
            f"{selected_template.body}"
        )
    else:
        reference_context = (
            f"【参考来源】\n{references.reference_profile}\n\n"
            "【晚点题材路由】\n"
            f"模板：{selected_template.label}\n"
            f"判定：{selected_template.route_reason}\n\n"
            "【场景模板】\n"
            f"{selected_template.body}\n\n"
            "【标题与反向提示】\n"
            f"{references.section_title_rules}\n\n"
            "【方法论参考】\n"
            f"{references.content_methodology}\n\n"
            "【风格示例】\n"
            f"{references.style_examples}\n\n"
            "【写作规则参考】\n"
            f"{references.skill_guide}\n\n"
            "【质量流程参考】\n"
            f"{references.quality_pipeline}"
        )

    constraint_lines = []
    length_guidance_line = ""
    if skill_config is not None:
        for c in skill_config.constraints:
            if c.constraint_type == "forbidden_word" and c.enabled:
                constraint_lines.append(f"- 禁用词：{c.pattern}")
        if skill_config.perspective == "third_person":
            constraint_lines.append(
                "- 使用第三视角成文，除原文直接引用外，不使用我/我们/咱们/本人作为叙述主语。"
            )
            constraint_lines.append(
                "- 第三视角要写成报道视角：正文主语优先是事件、变化、机制、平台和边界，不要让人物发言顺序主导段落顺序。"
            )
            constraint_lines.append(
                "- 如果原始内容是访谈、播客、问答或字幕稿，请改写成报道型文章，不要保留逐字同步、时间块列表或问答壳。"
            )
            constraint_lines.append(
                "- 如果原文包含安全、商业闭环、内部实践、合作、监管、算力部署等高价值信息，请把它们当成正文骨架，不要压缩成背景。"
            )
            constraint_lines.append(
                "- 主题脉络中的每一项都要在正文里得到呼应；如果某项不能展开，也要用一句话交代，不要完全遗漏。"
            )
        length_guidance_line = _build_length_guidance_line(
            source_text=source_text,
            skill_config=skill_config,
        )
    else:
        constraint_lines.append(
            "- 使用第三视角成文，除原文直接引用外，不使用我/我们/咱们/本人作为叙述主语。"
        )
        constraint_lines.append(
            "- 如果原始内容是访谈、播客、问答或字幕稿，请改写成报道型文章，不要保留逐字同步、时间块列表或问答壳。"
        )
        constraint_lines.append(
            "- 如果原文包含安全、商业闭环、内部实践、合作、监管、算力部署等高价值信息，请把它们当成正文骨架，不要压缩成背景。"
        )
        constraint_lines.append(
            "- 主题脉络中的每一项都要在正文里得到呼应；如果某项不能展开，也要用一句话交代，不要完全遗漏。"
        )
    constraint_block = "\n".join(constraint_lines)
    if length_guidance_line:
        constraint_block = f"{constraint_block}\n{length_guidance_line}" if constraint_block else length_guidance_line

    if prompt_profile == THIN_LONGFORM_PROMPT_PROFILE:
        user_prompt = (
            "请改写以下内容。\n\n"
            f"改写目标：{rewrite_focus}\n\n"
            "限制要求：\n"
            "- 不编造事实，不添加原文没有的关键结论。\n"
            "- 保持原始信息。\n"
            f"{constraint_block}\n"
            "- 优先遵守场景模板和长度要求。\n"
            "- 如果当前输出仍然像逐字稿或翻译稿，请重新组织段落，改成完整文章，而不是微调句子。\n"
            "- 如果原文包含明确的安全、财务、隐私、合作、监管或算力案例，请在文章中明确展开，不要只一句带过。\n"
            "- 如果参考资料里出现了【主题脉络】，不要只写其中一两个点；尽量把它们全部覆盖到正文中。\n"
            "- 输出只包含改写后的正文。\n\n"
            "原始内容：\n"
            f"{source_text}"
        )
    else:
        user_prompt = (
            "请改写以下内容。\n\n"
            f"改写目标：{rewrite_focus}\n\n"
            "限制要求：\n"
            "- 不编造事实，不添加原文没有的关键结论。\n"
            "- 保持原始信息。\n"
            f"{constraint_block}\n"
            "- 优先遵守场景模板、标题规则和质量流程。\n"
            "- 如果当前输出仍然像逐字稿或翻译稿，请重新组织段落，改成完整文章，而不是微调句子。\n"
            "- 如果原文包含明确的安全、财务、隐私、合作、监管或算力案例，请在文章中明确展开，不要只一句带过。\n"
            "- 如果参考资料里出现了【主题脉络】，不要只写其中一两个点；尽量把它们全部覆盖到正文中。\n"
            "- 输出只包含改写后的正文。\n\n"
            "原始内容：\n"
            f"{source_text}"
        )

    if skill_config and skill_config.content_filters:
        user_prompt += "\n\n内容过滤要求：\n"
        for f in skill_config.content_filters:
            user_prompt += f"- {f}\n"

    return [
        {
            "role": "system",
            "content": ARTICLE_LONGFORM_ASSISTANT_INSTRUCTIONS,
        },
        {"role": "system", "content": reference_context},
        {"role": "user", "content": user_prompt},
    ]


def _build_length_guidance_line(*, source_text: str, skill_config) -> str:
    output = getattr(skill_config, "output", None)
    ratio_min = getattr(output, "source_length_ratio_min", None)
    ratio_max = getattr(output, "source_length_ratio_max", None)
    if ratio_min is None and ratio_max is None:
        return ""

    normalized_source = (source_text or "").strip()
    source_length = measure_source_text_length(normalized_source)
    if source_length <= 0:
        return ""

    min_ratio = ratio_min if ratio_min is not None else 0.0
    max_ratio = ratio_max if ratio_max is not None else 1.0
    if max_ratio < min_ratio:
        min_ratio, max_ratio = max_ratio, min_ratio

    min_chars = max(1, round(source_length * min_ratio))
    max_chars = max(min_chars, round(source_length * max_ratio))
    return (
        f"- 篇幅建议：总长度尽量控制在原文的 {int(min_ratio * 100)}%-{int(max_ratio * 100)}% "
        f"之间，当前原文约 {source_length} 字，建议输出约 {min_chars}-{max_chars} 字。"
    )


def _build_speech_verbatim_messages(
    *,
    source_text: str,
    rewrite_focus: str,
    detail_ledger: str | None,
) -> list[dict[str, str]]:
    prompt_parts = [
        "请将下面内容整理成自然、克制的中文稿件。",
        "",
        f"整理目标：{rewrite_focus}",
        "",
        "硬性要求：",
        "- 保留原作者的说话节奏、语气、观点顺序和信息密度。",
        "- 优先保留问答节奏、口头表达、停顿感和语气词，只做轻度断句与润色。",
        "- 不要总结化，不要改写成公众号长文，不要重排成更抽象的提纲。",
        "- 不要删掉有意义的重复、强调或转折，除非它们明显影响阅读。",
        "- 不要新增原文没有的新事实，不要补充背景判断。",
        "- 输出必须是简体中文稿；如果原文是英文，也要整理成简体中文，不要整篇保留英文。",
        "- 只输出正文，不要标题、解释、项目符号说明或分析过程。",
        "- 输出信息密度应与原文相当，不要大段省略，也不要无意义扩展。",
        "- 如果原文是英文，整理成中文后篇幅自然会缩短，这是正常的，不要强行补充。",
    ]
    if detail_ledger:
        prompt_parts.extend(
            [
                "",
                "【细节清单（优先保留）】",
                detail_ledger.strip(),
            ]
        )
    prompt_parts.extend(
        [
            "",
            "原始内容：",
            source_text,
        ]
    )
    user_prompt = "\n".join(prompt_parts)
    return [
        {"role": "system", "content": SPEECH_VERBATIM_ASSISTANT_INSTRUCTIONS},
        {"role": "user", "content": user_prompt},
    ]
