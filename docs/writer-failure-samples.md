# Writer Failure Samples

This file records short, versioned examples of common writing failures so prompt or rule changes can be checked against real regressions before they are merged.

## How to use

- Read this list before changing `speech_verbatim`, `article_longform`, or the routing rules.
- Prefer fixing the smallest failing rule or ledger step, not widening the prompt.
- Keep each sample short and factual; do not paste full transcripts here.

## Known failure classes

### English drift

- `sam_altman_ted2025`
- Observed issue: output drifted into English main-body text instead of a Chinese article.
- Guardrail: `speech_verbatim` must stay in simplified Chinese; `ratio > 1` or English-dominant output is a failure.

### Compression overshoot

- `jensen_huang_gtc`
- Observed issue: output expanded beyond the source length, which is an article expansion rather than a rewrite.
- Guardrail: `speech_verbatim` should not expand; patch back when output length exceeds source length.

### First-person leakage

- `vision_pro_review`
- Observed issue: `article_longform` can still leak first-person phrasing when the model follows the legacy path too loosely.
- Guardrail: treat first-person markers as a hard style failure in longform mode.

### Hard-detail loss

- `steve_jobs_stanford`
- Observed issue: strong facts and named details can be dropped if the rewrite chases style too aggressively.
- Guardrail: must-preserve details such as numbers, dates, quotes, and strong entities should remain pinned in the ledger.

### Ordering regression

- `tim_cook_mit`
- Observed issue: the content can remain factually correct but lose source order, especially when patches rewrite too much.
- Guardrail: the hard-detail order check should stay separate from coverage so order regressions are visible.
