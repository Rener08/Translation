from app.services.content_rewrite_service import _select_rewrite_template
from app.services.rewrite_template_service import RewriteReferences


def test_select_rewrite_template_routes_infra_request_with_agent_language_to_infra_template() -> None:
    references = RewriteReferences(
        article_template="一页版模板",
        content_methodology="方法论",
        style_examples="示例",
        skill_guide="规则",
        category_templates={
            "03_product_review": "评测模板",
            "06_infra_cloud_model_platform": "平台模板",
            "01_big_company_war": "公司战役模板",
        },
        section_title_rules="标题规则",
    )

    selected = _select_rewrite_template(
        source_text=(
            "This Stanford interview discusses code design, compute, cloud, models, AI agents, "
            "chips, energy, and robotics."
        ),
        rewrite_focus="请改写成晚点式基础设施分析稿。",
        references=references,
    )

    assert selected.key == "06_infra_cloud_model_platform"
    assert selected.body == "平台模板"
