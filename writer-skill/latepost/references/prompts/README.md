# prompts 目录说明

这里放可直接复制的晚点风格 prompt 模板，按场景拆分。

晚点的主基调是第三视角、冷静客观、信息密度高的深度报道口吻。
正文篇幅只保留软提示：尽量控制在原文长度的 40% - 65% 区间，不作为硬失败条件。
段落标题长度另行约束，不要和正文篇幅混在一起理解。
第三视角不是把人称改成“他”，而是把叙述主语放到事件、变化、机制和边界上。

默认表只保留 3 类主场景：
- `09_interview_transcript_sync`：访谈 / 播客 / 字幕同步稿
- `03_product_review`：产品 / 实测 / 评测
- `06_infra_cloud_model_platform`：基础设施 / 云 / 模型 / 平台

`01_big_company_war` 只作为窄兜底，不放进默认主表；其余模板保留为扩展参考和显式模式素材。

建议优先使用：
- `latepost_prompt_templates_onepage.md`：3 类主表，一页直接复制
- `09_interview_transcript_sync.md`
- `03_product_review.md`
- `06_infra_cloud_model_platform.md`
- `01_big_company_war.md`：窄兜底
- `11_section_titles_and_reverse_prompt.md`：段落标题规则 + 反向提示词
- `../extended/README.md`：扩展参考索引

如果你想先快速用，先打开一页版；需要更细场景时再看扩展参考。
