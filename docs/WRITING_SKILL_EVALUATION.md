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
