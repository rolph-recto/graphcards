---
# graphcards-99s6
title: Use stock Tailwind utilities instead of arbitrary values
status: completed
type: task
priority: normal
created_at: 2026-07-29T01:36:30Z
updated_at: 2026-07-29T01:42:15Z
---

Replace arbitrary-value Tailwind classes (w-[min(...)], text-[0.78rem], max-[34rem]:, etc.) with natural stock utilities (max-w-4xl, text-xs, max-sm:, etc.). Small design shifts are acceptable.

- [x] Rewrite style.src.css layers with stock utilities
- [x] Rewrite all six templates with stock utilities
- [x] Rebuild style.css and verify no arbitrary values remain
- [x] Run tests, rebuild, restart demo server

## Summary of Changes

Swapped every arbitrary-value Tailwind class for stock utilities across `style.src.css` and all six templates; the compiled `style.css` was regenerated.

- Layout widths: `max-w-4xl` (deck hub), `max-w-7xl` (status pages, exact), `max-w-2xl` (study shell, exact), `max-w-sm` (card identity, exact), `min-w-3xl` (status table, exact).
- Custom breakpoints `max-[46rem]`/`max-[34rem]` became `max-md:`/`max-sm:`; clamp-based fluid sizes became stepped utilities (`py-8 md:py-16`, `p-6 md:p-10`, `text-3xl md:text-4xl`, `text-lg md:text-xl`).
- Fractional rem values moved to the nearest spacing/font-size scale steps (`px-3.5`, `py-2.5`, `gap-2.5`, `text-xs`, `text-sm`, `rounded-xl`, `rounded-lg`, `rounded-md`).
- Complex grid templates replaced with stock patterns: generator/history layouts use `md:grid-cols-3` with `md:col-span-2` (the pinned `.generator-list` hook carries its col-span via the component class), the filters form uses `grid-cols-1 sm:grid-cols-2 lg:grid-cols-6` with a `col-span-full` button, and history bars / rating legend entries use flex layouts.
- Focus outlines standardized to `outline-2`/`outline-offset-1`/`outline-offset-2`.

Verified: no `[...]` arbitrary values remain in templates or the source CSS, all 146 template class tokens exist in the compiled stylesheet, 253 tests pass with `-W error`, ruff clean, `uv build` succeeds, and the demo server was restarted on the new build.
