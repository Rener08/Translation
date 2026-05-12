# Writing Skill Evaluation

This repo now includes a local evaluation harness for the writing layer.

## What it compares

- `speech_verbatim`
- `article_longform`
- `{{transcript}}` full-prompt baseline

## What it measures

- hard detail preservation
- third-person compliance
- order preservation
- compression ratio
- AI/disclaimer/self-reference markers
- backend-reported `quality_issues`
- backend-reported `detail_coverage_issues`

## Sample set

The fixed sample set lives at:

`backend/tests/fixtures/writer_skill_eval/samples.json`

Transcript snapshots are stored next to that manifest under:

`backend/tests/fixtures/writer_skill_eval/transcripts/`

The script can refresh missing snapshots from the listed YouTube URLs.

## Run it

```bash
python3 scripts/evaluate_writer_skill.py \
  --manifest backend/tests/fixtures/writer_skill_eval/samples.json
```

Optional overrides:

- `--provider deepseek`
- `--model deepseek-v4-flash`
- `--refresh-samples`
- `--sample-id <id>` to run a subset

The script writes:

- `report.json`
- `report.md`

into `tmp/writer_skill_eval/<timestamp>/` by default.

## How to read it

- If the report says `provider/model error`, treat the run as incomplete and do not use it to decide on the skill shape.
- If `article_longform` keeps leaking first person or compresses harder than the baseline, keep the current structure narrow and shrink `lastpost-skill`.
- If the skill-fed longform path is clearly stronger and more stable, keep it and fix the concrete failure samples rather than adding a new runner layer.

## 评测记录 (Eval log)

> 按时间倒序累积，最新在顶。每次评测追加一节；堆到 5 条以上考虑拆到 `docs/eval-log/`。

### 2026-05-12 — baseline #1（首次跑通后基线）

- baseline commit: `8031a96` (HEAD)
- provider/model: `deepseek` / `deepseek-chat` (实际路由到 `deepseek-v4-flash`)
- 样本：全部 6 个
- report 路径：`tmp/writer_skill_eval/20260512-075909/`（gitignored, 本地保留作对照）

#### 6-sample 平均

| mode | 硬细节覆盖率 | 第三视角通过率 | 顺序通过率 | 平均压缩比 | 第一人称失败 | AI/免责声明命中 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| speech_verbatim | 77.6% | 16.7% | 16.7% | 0.36 | 5 | 3* |
| article_longform | 66.6% | 66.7% | 0.0% | 0.22 | 2 | 1* |
| full_prompt_baseline | 51.8% | 83.3% | 0.0% | 0.16 | 1 | 0 |

\*：本次评测后发现 `_detect_ai_slop_hits` 存在"告警自我触发"bug（详见下方），AI/免责声明命中数据**仅本次有偏**，下次评测无此 bug。

#### 2-sample 演讲子集（steve_jobs_stanford + tim_cook_mit）

speech_verbatim 在密集数字/原话的演讲类素材上硬覆盖 95%，对比 article_longform 56% 形成 39 个百分点的代差。

#### `decision_hint`

> article_longform 仍有第一人称泄漏；article_longform 细节保真率偏低。建议先收缩 lastpost-skill，再决定是否抽通用 runner。

#### 结论

1. **保留 `speech_verbatim` 作为默认**：硬细节保留率三路最高，正是先前用户痛点（"AI 总结腔、内容压缩"）所指。
2. **`article_longform` 的"第三视角硬约束"实测仅 66.7% 命中**：codex 引入的 `ARTICLE_LONGFORM_FIRST_PERSON_MARKERS` + revise loop 在 deepseek-chat 上不足以让模型改写所有第一人称（如 Tim Cook "我们都喜欢难题"原样保留）。**暂时按下不修**——默认值已是 `speech_verbatim`，用户显式选 article 才会触发；要修需要加多轮 patch loop 或换路径。
3. **顺序通过率三路都很低**（0–16.7%）：当前 `_are_hard_items_in_source_order` 判定可能过严，下次有需要再调。

#### 本次评测后修的 bug（评测器自身）

- `AI_SLOP_MARKERS` 过宽：删除 5 个误报词（`我不知道` / `抱歉，` / `无法提供` / `仅供参考` / `不构成`），保留 9 个明确的 AI 自述/免责声明词。原因：演讲原文（Jobs "我不知道这辈子想做什么"）会被误判为模型自述。
- `_detect_ai_slop_hits` 自我触发：原实现将 `analyze_rewrite_quality(text)` 的告警消息文本喂回自身做关键词匹配，而 quality service 的告警消息本身含"模型/免责声明/自述"等触发词，相当于告警自己触发告警。已删除回喂逻辑，`ai_slop_hits` 现在只依赖 `AI_SLOP_MARKERS` 正向匹配。

修复未触发重跑评测——bug 只影响 `ai_slop_hits` 一个指标的统计，不改 LLM 输出。下次评测自然反映真实状态。
