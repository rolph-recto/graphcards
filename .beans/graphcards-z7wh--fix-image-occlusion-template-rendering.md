---
# graphcards-z7wh
title: Fix image occlusion template rendering
status: completed
type: bug
priority: normal
created_at: 2026-07-31T01:48:11Z
updated_at: 2026-07-31T02:03:31Z
---

Fix the image occlusion front image URL/rendering and make the back template display only the occluded answer text.

## Summary of Changes

Updated the image occlusion front styling and rebuilt the Tailwind stylesheet. Changed the default back template to display only the escaped occluded answer text. Verified with the full test suite and required checks.

The default front now uses a CSP-safe SVG overlay. The image remains a normal `<img>`, and normalized rectangle coordinates are SVG attributes so the mask stays anchored to the rendered image under the app's `style-src 'self'` policy. The back remains answer text only.
