---
# graphcards-ie82
title: Use Tailwind CSS for the web interface instead of raw CSS
status: completed
type: feature
priority: normal
created_at: 2026-07-29T00:12:31Z
updated_at: 2026-07-29T01:15:54Z
---

Replace the hand-written CSS in the web interface with Tailwind utility classes.

- [x] Create a git worktree for the work
- [x] Survey current raw CSS usage in the web UI
- [x] Integrate Tailwind into the web server/static assets
- [x] Rewrite templates/styles to use Tailwind classes
- [x] Run tests and linters

## Summary of Changes

Replaced the hand-written stylesheet with a Tailwind CSS v4 build.

- Added `pytailwindcss` as a dev dependency (wraps the Tailwind v4 standalone CLI; no Node.js required).
- New source stylesheet `src/graphcards/web/style.src.css`: imports Tailwind with scanning scoped to the templates directory, defines the rating colors and Inter font stack in `@theme`, element defaults (buttons, inputs, labels, headings) in `@layer base`, and repeated/test-pinned patterns (`.stats`, `.prompt`, `.answer`, `.generator-card`, `.exercise-preview`, `.status-table`, `.history-stats`, `.rating-*`, progress-bar pseudo-elements) in `@layer components`.
- Rewrote all six web templates with Tailwind utility classes, preserving the exact class hooks the tests assert on (`status-card`, `generator-card`, `generator-list`, `exercise-preview exercise-preview-panel`, `prompt`, `answer`) and the Python-generated `rating-*` class names. Dropped dead CSS/classes (`.badges`, `.badge`, `.fsrs-metrics`, `.suspension-reason`, `.metric-note`, `.suspend-action`, `.rating-panel`, `.generator-status`).
- Rebuilt `src/graphcards/web/static/style.css` (1037 raw lines -> ~21 kB minified Tailwind build) with `uv run tailwindcss -i src/graphcards/web/style.src.css -o src/graphcards/web/static/style.css --minify`; the compiled file stays committed so wheels remain self-contained.
- Replaced the `main_class`/`wrapper_class` template variables with utility-class values (`main_width` for the 58rem/80rem layouts, `wrapper_class` for the 42rem study shell).
- Documented the rebuild command in AGENTS.md.

Verified: 253 tests pass with `-W error`, ruff check/format clean, `uv build` succeeds and the wheel contains the compiled stylesheet, plus a Flask test-client smoke check of every page (index, status tabs, history, generators, study, reveal/ratings) confirming rendered classes exist in the built CSS.
