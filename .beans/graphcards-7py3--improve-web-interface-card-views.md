---
# graphcards-7py3
title: Improve web interface card views
status: completed
type: feature
priority: normal
created_at: 2026-08-01T17:16:24Z
updated_at: 2026-08-01T17:25:10Z
---

Update the web interface.

- [x] Make the exercise preview use 50% of the content width in the exercise generator tab.
- [x] Underline entity names in the card status tab.
- [x] Add review history and exercise generator tabs to the card detail page.
- [x] Show the card state above the card detail tabs.
- [x] Add behavior tests and verify the web assets.

## Summary of Changes

- Set the exercise generator preview to use half of the desktop content width.
- Underlined entity links in Card Status.
- Added Review History and Exercise Generators tabs to card detail pages.
- Added a card state summary above the detail tabs.
- Added per-card review rows, validation, behavior tests, and the rebuilt Tailwind stylesheet.
- Passed `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.
