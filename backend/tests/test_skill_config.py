from app.services.skill_config_service import (
    LATEPOST_SKILL_DIR,
    SkillConfig,
    load_default_skill_config,
    load_skill_config,
    resolve_skill_config,
)


def test_load_default_skill_config():
    cfg = load_default_skill_config()
    assert cfg.style_name == "卡兹克"
    assert cfg.perspective == "first_person"
    assert cfg.output.min_chars == 3000
    assert cfg.output.target_chars == 5000
    assert cfg.output.max_chars == 8000


def test_load_latepost_config():
    cfg = load_skill_config(LATEPOST_SKILL_DIR / "config.yaml")
    assert cfg.style_name == "晚点"
    assert cfg.perspective == "third_person"
    assert cfg.output.min_chars == 0
    assert cfg.output.target_chars == 0
    assert cfg.output.max_chars == 0
    assert cfg.output.source_length_ratio_min == 0.4
    assert cfg.output.source_length_ratio_max == 0.6


def test_constraints_merged():
    cfg = load_default_skill_config()
    forbidden_words = [c for c in cfg.constraints if c.constraint_type == "forbidden_word"]
    assert len(forbidden_words) == 9
    patterns = {c.pattern for c in forbidden_words}
    assert "说白了" in patterns
    assert "本质上" in patterns

    forbidden_punct = [c for c in cfg.constraints if c.constraint_type == "forbidden_punctuation"]
    assert len(forbidden_punct) == 3


def test_perspective_markers():
    kz = load_default_skill_config()
    assert len(kz.perspective_markers) == 0

    lp = load_skill_config(LATEPOST_SKILL_DIR / "config.yaml")
    assert len(lp.perspective_markers) == 7
    marker_constraints = [c for c in lp.constraints if c.constraint_type == "perspective_marker"]
    assert len(marker_constraints) == 7


def test_resolve_skill_config_default():
    cfg = resolve_skill_config()
    assert cfg.style_name == "卡兹克"


def test_resolve_skill_config_by_name():
    cfg = resolve_skill_config(config_name="latepost")
    assert cfg.style_name == "晚点"
