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
- output language guess
- compression anomaly (`ratio > 1`)
- Chinese subset compression average
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
- `--model deepseek-v4-pro`（与当前 baseline #2 对齐；`deepseek-chat` 仍可用于本地冒烟）
- `--refresh-samples`
- `--sample-id <id>` to run a subset
- `--fail-on-error` to exit non-zero when any mode errors out

The script writes:

- `report.json`
- `report.md`

into `tmp/writer_skill_eval/<timestamp>/` by default.

## How to read it

- If the report says `provider/model error`, treat the run as incomplete and do not use it to decide on the skill shape.
- If `article_longform` keeps leaking first person or compresses harder than the baseline, keep the current structure narrow and shrink `lastpost-skill`.
- If the skill-fed longform path is clearly stronger and more stable, keep it and fix the concrete failure samples rather than adding a new runner layer.

## 写作 Agent 执行计划（可落地）

目标：在**不引入多 agent / 不新增通用 runner API** 的前提下，把默认主线 `speech_verbatim` 做成稳定中文整理稿，并用固定样本 + 回归门禁持续迭代。下文按**阶段顺序**执行；每一阶段结束后再开下一阶段。

### 0. 基线与门禁（先于一切代码改动定稿）

**唯一可比基线（当前）**

- 以 `tmp/writer_skill_eval/20260512-204154/` 为 **baseline #2**；对应代码起点 `5b0f659` 起（含 `max_tokens`、speech 长度提示、顺序判定解耦）。
- **任何** `report.md` 里 `错误数 > 0` 或 `decision_hint` 含「provider/model 错误」的 run：**不写进本文件「评测记录」**，只作排障。

**每次记录新 baseline 时必须写清**

- `report.json` / `report.md` 所在目录名、`provider`、`model`、commit、耗时量级。
- 若继续用 `deepseek-v4-pro`：全量 6×3 约 **60–90 分钟**量级，提前预留。

**合并门禁（写进 PR 自检，不写成「指标必须全线上升」）**

- `cd backend && python -m pytest` 全绿。
- `frontend/frontend` 下 `npx tsc --noEmit`（及需要时的 `npm run build`）不退化。
- 改动了写作路径时：**至少** `--sample-id steve_jobs_stanford --sample-id tim_cook_mit` 小集评测；合并前 **全量 6 样本** 一次。

---

### 1. SLA 分层（避免四条同时锁死导致无法迭代）

门禁分 **P0（必须先过）** 与 **P1（主线达标）**；`article_longform` 单独一条 **P2（长文模式）**。

| 代号 | 指标 | 目标 | 说明 |
| --- | --- | --- | --- |
| **P0-A** | `speech_verbatim` 输出语言 | 默认 **简体中文**；禁止整篇以英文为主交付 | 直接对齐产品「链接 → 中文稿」；先修 `sam_altman` / 英文漂移类失败 |
| **P0-B** | `speech_verbatim` 压缩比异常 | `output_chars <= source_chars`（允许极小浮动如 ≤1.02 若需兼容空白） | 先消灭 **ratio>1** 的「扩写」；再谈 0.45–0.6 |
| **P1-A** | `speech_verbatim` 中文子集压缩比 | 子集 `nasa_force_talent`, `steve_jobs_stanford`, `tim_cook_mit`, `vision_pro_review` 四条平均 **0.45–0.60** | baseline #2 该子集约 **0.30**，为后续主战场 |
| **P1-B** | `speech_verbatim` 硬细节覆盖率（6-sample 表） | **≥ 当前 baseline #2 的 66.7%**，再逐步冲 **≥80%** | 80% 与 P1-A 可能拉扯，**禁止**为追压缩比单独掉硬覆盖而不记录 |
| **P1-C** | `speech_verbatim` 顺序通过率 | **≥60%**（当前 baseline #2 为 83.3%） | 已解耦缺失 vs 乱序；回归时勿回退该逻辑 |
| **P2** | `article_longform` 第三视角通过率 | **North Star ≥90%**；**连续两轮**全量评测（同 provider/model）**均 <70%** → UI/文档标为 **「实验模式」**，不主推 | 不在此阶段加多轮自反思 agent；达标靠 revise 或专门人称 patch，另开任务 |

**决策规则**：合并以 **P0 全过 + P1-B 不低于 baseline #2** 为硬条件；P1-A、P1-B 同时大幅恶化则回滚。

---

### 2. 阶段 A — 评测 harness 收紧（「测准」）

**目的**：报告里能直接看出「中文稿 / 子集压缩 / ratio 异常」，减少手工从 `report.json` 里算。

| 步骤 | 操作 | 验收 |
| --- | --- | --- |
| A1 | 在 `[backend/app/services/writer_skill_eval_service.py](backend/app/services/writer_skill_eval_service.py)` 的 `WriterSkillEvalModeResult`（或汇总表）增加派生字段或 `report.md` 小节：如 `output_language_guess`（简中/英/混）、`compression_anomaly`（ratio>1）、`zh_subset_compression_avg`（固定四 sample_id） | 跑 `evaluate_writer_skill.py` 后 `report.md` 可读，无需手算 |
| A2 | 在 `[scripts/evaluate_writer_skill.py](scripts/evaluate_writer_skill.py)` 可选增加 `--fail-on-error`：任一 mode `error` 非空则 exit code 非 0，便于 CI | 本地 `pytest` 不受影响时可选用 |
| A3 | 在 `[backend/tests/test_writer_skill_eval_service.py](backend/tests/test_writer_skill_eval_service.py)` 为 A1 增加最小单测（固定短字符串） | `pytest` 通过 |

---

### 3. 阶段 B — 只改默认主线 `speech_verbatim`

**涉及文件（按顺序改）**

1. `[backend/app/services/content_rewrite_service.py](backend/app/services/content_rewrite_service.py)`：`SPEECH_VERBATIM_ASSISTANT_INSTRUCTIONS`、`_build_speech_verbatim_messages`（语言、不扩写、长度意图）。
2. `[backend/app/services/writer_agent_service.py](backend/app/services/writer_agent_service.py)`：`speech_verbatim` 分支内在 **初稿之后** 增加长度门控：
   - 若 `len(output) < 0.45 * len(source)`：调用已有 `rewrite_content` 能力做一次 **「补足」patch**（新 `rewrite_focus` 文案：只补缺、不重写全文、仍中文）。
   - 若 `len(output) > len(source)`（或超阈值）：一次 **「压回信息密度」** patch 或拒绝扩写类提示（具体实现二选一，优先与现有 patch 路径一致）。
3. 可选：在 `[backend/app/services/rewrite_quality_service.py](backend/app/services/rewrite_quality_service.py)` 增加 `language_mismatch` 类 **quality_issue**，供前端与评测统计（**不**在阶段 B 强改 API 响应形状时，可先只写在 `quality_issues` 文本前缀约定）。

**验收（阶段 B 结束）**

- P0-A、P0-B 在全量 6 样本 `speech_verbatim` 上成立。
- P1-A 在四条中文子集上达标或文档记录「剩余差距 + 下一迭代假设」。
- 全量 `report.md` 写入「评测记录」新一行，对照 baseline #2 表格。

---

### 4. 阶段 C — `article_longform` 收缩（不加新框架）

**原则**：不引入 LangChain / 多 agent / 新 runner API；保留 `outline -> draft -> validate -> revise once`。

| 步骤 | 操作 | 验收 |
| --- | --- | --- |
| C1 | 盘点 `lastpost-skill` 中实际被 `writer_skill_eval` 与路由命中的模板；在仓库内保留 **pinned 副本**（当前落在 `references/`），并继续保留 `LASTPOST_SKILL_DIR` override，避免仅依赖 `~/.hermes` | 新同事 clone 后能跑同构 article 评测 |
| C2 | 删除或弱化与 YouTube 场景无关的晚点模板引用（改 `[backend/app/services/content_rewrite_service.py](backend/app/services/content_rewrite_service.py)` 路由或模板列表，**小步**） | 全量评测 `article_longform` 硬覆盖不劣于阶段 C 前一轮 |
| C3 | 若需冲 P2：仅在 `article_longform` 增加 **第二轮**「人称 patch」（仍调用 `rewrite_content`，非新 agent），上限 1 次以控成本 | 记录 token/耗时；仍达不到 P2 则执行 **实验模式** 降级（前端 `[frontend/app/components/translation-settings-panel.tsx](frontend/app/components/translation-settings-panel.tsx)` 文案 + 本文件说明） |

**路由收窄约定**

- `article_longform` 的自动路由只优先考虑访谈 / 产品评测 / 基础设施-模型-平台三类。
- `01_big_company_war` 仅在明确出现组织/战略/竞争/入口/资源重排信号时作为窄兜底，不再作为未知素材的默认 fallback。
- 其余模板保留为参考资料和未来显式模式素材，不参与普通 YouTube 输入的默认路由。

---

### 5. 阶段 D — 外循环（版本化 + trace，最后做）

**原则**：不让模型在线自改 prompt；人审 + 固定样本回归。

| 步骤 | 操作 | 验收 |
| --- | --- | --- |
| D1 | 定义常量 `WRITER_POLICY_VERSION` / `SPEECH_VERBATIM_PROMPT_VERSION`（例如放在 `content_rewrite_service.py` 或单独 `writer_versions.py`），写入日志与（可选）响应头 | 日志可筛版本 |
| D2 | 在 `[backend/app/api/routers/content.py](backend/app/api/routers/content.py)` + `[backend/app/services/session_history_service.py](backend/app/services/session_history_service.py)` 增量持久化：至少 `rewrite_style`、`provider`、`model`、可选 `writer_policy_version`；**API 对外字段先与 Jack 确认再加**，避免破坏旧客户端 | 会话可回放 |
| D3 | 仓库内维护 [`docs/writer-failure-samples.md`](docs/writer-failure-samples.md) 或在 `tmp/` 外另设 `eval_failures/`（**小**、脱敏）：分类（英文、ratio>1、人称泄漏、硬缺）各 1–2 条摘录 + sample_id | 每次改 prompt 前过一遍该清单 |

---

### 6. 快速命令备忘

```bash
# 小集（改 prompt 后快速冒烟）
backend/.venv/bin/python scripts/evaluate_writer_skill.py \
  --provider deepseek --model deepseek-v4-pro \
  --sample-id steve_jobs_stanford --sample-id tim_cook_mit

# 全量基线（合并前）
backend/.venv/bin/python scripts/evaluate_writer_skill.py \
  --provider deepseek --model deepseek-v4-pro
```

---

### 与 baseline #2 小节的关系

- 「评测记录」里 **baseline #2** 表格保持历史快照。
- **本「执行计划」**为后续迭代的操作母版；每完成一阶段，在 baseline #2 小节下追加 **#2a / #3** 等新行并更新「计划内退出标准核对」表即可。

#### 建议的下一步迭代（仍未实现）

- 已并入上文 **阶段 A–D**；优先执行 **阶段 A → 阶段 B（P0）**。

## 评测记录 (Eval log)

> 按时间倒序累积，最新在顶。每次评测追加一节；堆到 5 条以上考虑拆到 `docs/eval-log/`。

### 2026-05-12 — baseline #2（`deepseek-v4-pro` + 更长 `max_tokens` + speech 长度提示 + 顺序判定解耦）

- code commit: `5b0f659`（`feat(writer): tune output length and decouple ordering metric`）
- provider/model: `deepseek` / `deepseek-v4-pro`
- 样本：6（**三路 18 格全部成功**，无 SSL / 鉴权失败）
- report 路径：`tmp/writer_skill_eval/20260512-204154/`（本地对照；gitignored）
- 备注：曾有一次 run 在 `084027` 出现单格 SSL 失败；使用**有效临时 key** 全量重跑约 **80 分钟** 得到本报告。请勿将 key 写入 `.env`（若需长期用请自行在本地更新）。

#### 6-sample 平均（摘自 `report.md`）

| mode | 硬细节覆盖率 | 第三视角通过率 | 顺序通过率 | 平均压缩比 | 错误数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| speech_verbatim | 66.7% | 33.3% | 83.3% | 0.54 | 0 |
| article_longform | 40.4% | 50.0% | 16.7% | 0.22 | 0 |
| full_prompt_baseline | 52.8% | 16.7% | 50.0% | 0.18 | 0 |

#### `decision_hint`（本次 run）

> article_longform 仍有第一人称泄漏；article_longform 细节保真率偏低；全量 prompt 基线在硬细节覆盖上明显更稳。建议先收缩 lastpost-skill，再决定是否抽通用 runner。

#### 相对 baseline #1（`deepseek-chat` / v4-flash）的注意点

- **顺序通过率（speech）**：16.7% → **83.3%**（评测器解耦 + 本次模型行为共同作用；#1 数字在解耦前已偏保守）。
- **硬细节（speech）**：77.6% → **66.7%**（仍 **未达 80%** 目标； article 与 baseline 路在 v4-pro 下也有波动，不宜单次 run 定生死）。
- **平均压缩比（speech）**：0.36 → **0.54** ——但该均值被 **两路异常样本拉高**：
  - `sam_altman_ted2025`：`compression_ratio ≈ 1.00`（输出略长于原文；speech 输出以**英文**为主，与「默认简体中文稿」产品预期不一致）。
  - `jensen_huang_gtc`：`compression_ratio ≈ 1.02`（输出长于原文，属「扩写」而非整理）。
- **中文向子集（4 条：nasa / steve / tim / vision，`speech_verbatim`）** 平均压缩比 **≈0.30**，目标区间 **0.45–0.6** → **仍未达标**。

#### 计划内退出标准核对（以中文子集 + 全表综合解读）

| 项 | 结果 |
| --- | --- |
| 中短 speech 压缩 0.45–0.6（中文子集） | **未** |
| 6-sample speech 表观均值 0.54 | **误导性偏高**（含 ratio>1 与英文路径） |
| 长素材 jensen：ratio>1 | **未**按「0.30–0.40 压缩」解释；需单独约定英文长稿 / 或强制中文化 + 上限 |
| speech 顺序通过率 ≥60% | **是**（83.3%） |
| speech 硬覆盖 ≥80% | **否**（66.7%） |

#### 与执行计划的对照

- 具体改法见上文 **「写作 Agent 执行计划」**；本表保留为 baseline #2 历史对照，不再重复列 bullet。

#### 历史：单次 SSL 失败 run（仅供参考）

- 报告 `tmp/writer_skill_eval/20260512-084027/`：`vision_pro_review` / `article_longform` 曾遇 `UNEXPECTED_EOF_WHILE_READING`；**勿再作正式基线**，以 `204154` 为准。

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
