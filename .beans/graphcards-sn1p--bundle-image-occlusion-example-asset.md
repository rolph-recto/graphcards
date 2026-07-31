---
# graphcards-sn1p
title: Bundle image occlusion example asset
status: completed
type: bug
priority: normal
created_at: 2026-07-31T01:53:17Z
updated_at: 2026-07-31T01:59:36Z
---

Include the referenced solar-system raster image in the image-occlusion template and copy binary template resources during workspace initialization.

## Summary of Changes

Added a NASA/Lunar and Planetary Institute solar-system JPEG to the bundled image-occlusion template and the existing demo. Updated workspace initialization to copy binary template resources. Added a regression test for raster copying. Full tests, Ruff checks, and build pass.

The example image shows the planets in correct order and relative sizes. Sample normalized rectangles hide the Sun and Earth regions in JSON, TOML, YAML, and the demo deck.
