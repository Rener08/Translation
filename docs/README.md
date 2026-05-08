# Documentation Map

This project keeps docs in a few clear buckets so the active workflow is easy to find.

## 1. Source Of Truth

These files define the current product and should stay current with the code:

- [`README.md`](../README.md) - product overview, setup, workflow, and current scope
- [`TODO.md`](../TODO.md) - active backlog and prioritized follow-up work
- [`docs/writing_style_prompt_format.md`](writing_style_prompt_format.md) - format rules for imported writing prompts and styles

Current source-of-truth notes:

- Rewrite output is stored separately from the rendered Markdown so copy/export/history replay preserve the original structure.
- Session history writes are atomic per `content_context_id` so rewrite and chat updates do not overwrite each other.
- Imported writing prompts are validated before rewrite so empty bodies and broken placeholders fail fast.
- The desktop app now ships with a stable built-in default writing style and post-generation rewrite quality checks.
- The desktop app includes a runtime log viewer for backend and desktop logs.
- The app persists inspect metadata, source mode, transcript text, and translated text for local debugging.
- The desktop UI normalizes user-facing errors for cookie, auth, upstream disconnect, and Whisper failures.
- The web frontend is treated as a rewrite-aligned dev/debug surface, not the primary user-facing path.

## 2. Runtime Prompt And Style Assets

These files are not onboarding docs. They are assets the app can load or reference at runtime:

- [`references/content_methodology.md`](../references/content_methodology.md)
- [`references/style_examples.md`](../references/style_examples.md)
- [`references/article_template.md`](../references/article_template.md)
- [`references/SKILL.md`](../references/SKILL.md)
- [`skills/科技博主深度文.md`](../skills/%E7%A7%91%E6%8A%80%E5%8D%9A%E4%B8%BB%E6%B7%B1%E5%BA%A6%E6%96%87.md)
- [`skills/小红书短平快.md`](../skills/%E5%B0%8F%E7%BA%A2%E4%B9%A6%E7%9F%AD%E5%B9%B3%E5%BF%AB.md)

## 3. Design And Historical Notes

These documents capture design direction or historical specs. Keep them if they still explain an implementation choice:

- [`docs/superpowers/specs/2026-04-18-youtube-translator-gui-design.md`](superpowers/specs/2026-04-18-youtube-translator-gui-design.md)

## 4. Not Active Project Docs

These are not part of the active documentation set for this checkout:

- generated caches and tool folders such as `.pytest_cache/`, `.opencode/`, `.omx/`

## 5. Recommended Rule For New Docs

When adding a new document:

1. Put user-facing setup and product scope in the root `README.md`.
2. Put active work in `TODO.md`.
3. Put prompt-format or writing-style contracts under `docs/`.
4. Put reusable prompt assets under `references/` or `skills/`.
5. Put historical specs or one-off design notes under `docs/`.
6. Do not add a new document if an existing file can be updated instead.
