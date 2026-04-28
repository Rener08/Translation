# Writing Style Prompt Format

The desktop app loads writing styles from the local `skills/` directory.
Each file is treated as a plain text prompt and appears in the desktop "写作风格" dropdown.

## Supported files

- `*.md`
- `*.txt`

## Current contract

There are two supported prompt modes:

1. Full prompt mode
   - The file contains a complete writing prompt.
   - It must include `{{transcript}}` exactly where the source text should be injected.
   - When this placeholder is present, backend treats the prompt as the source of truth.

2. Style hint mode
   - The file does not contain `{{transcript}}`.
   - Backend uses the prompt as a rewrite target / style hint and falls back to its managed rewrite references and routing.

## Recommended structure

Use one file per style and keep the prompt self-contained.

Example full prompt:

```md
你是一个科技博主。
请根据以下内容写一篇中文文章。
要求：
1. 保留事实，不要编造。
2. 语言更自然，有节奏。
3. 输出只保留正文。

视频内容：
{{transcript}}
```

Example style hint:

```md
请改写为更短、更有节奏感的中文文章，保留关键事实，适合公众号阅读。
```

## Notes

- The file name becomes the label shown in the desktop dropdown.
- Keep the prompt in a single file; do not split one style across multiple files.
- If you need full prompt behavior, make sure the file contains the exact `{{transcript}}` placeholder.
