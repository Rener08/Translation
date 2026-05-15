from app.services.detail_ledger import (
    build_detail_ledger,
    build_longform_topic_ledger,
    merge_detail_ledgers,
)


def test_build_longform_topic_ledger_extracts_expected_themes() -> None:
    source = (
        "Anthropic把可解释性和对齐研究当成核心使命。"
        "公司内部财务团队已经用Claude自动生成财务报表。"
        "他们还强调企业数据不会被拿去训练模型。"
        "在算力上，TPU、Trainium和GPU都在使用。"
        "团队也会主动和政府及监管部门沟通。"
    )

    ledger = build_longform_topic_ledger(source)
    prompt_text = ledger.to_prompt_text()

    assert "【主题脉络】" in prompt_text
    assert "AI安全与可解释性" in prompt_text
    assert "内部财务实践" in prompt_text
    assert "企业隐私承诺" in prompt_text
    assert "算力部署与合作" in prompt_text
    assert "政府与监管" in prompt_text


def test_merge_detail_ledgers_keeps_priority_order() -> None:
    detail = build_detail_ledger("NASA在2024年发射了3次火箭。")
    theme = build_longform_topic_ledger(
        "Anthropic把可解释性和对齐研究当成核心使命。"
    )
    merged = merge_detail_ledgers(detail, theme)

    prompt_text = merged.to_prompt_text()
    assert "【必须保留】" in prompt_text
    assert "【主题脉络】" in prompt_text
    assert "2024年" in prompt_text
    assert "AI安全与可解释性" in prompt_text
